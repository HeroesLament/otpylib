"""
SPAM Scheduler

Multi-core scheduler coordination for Sypher's Abstract Python Machine.
Orchestrates multiple CoreScheduler instances and handles global process management.
"""

import asyncio
import time
import threading
from typing import Dict, List, Optional, Any, Union, Callable, Awaitable
import anyio
import logging

from .data import (
    OTPProcess, ProcessState, ProcessType, RuntimeConfig, 
    GlobalSchedulerState, SPAMError, ProcessSpawnError,
    SchedulerError
)
from .core import CoreScheduler

logger = logging.getLogger(__name__)


class WorkStealingScheduler:
    """
    Main scheduler that coordinates multiple CoreScheduler instances.
    
    Handles global process management, load balancing across cores,
    and provides the interface between SPAM and the otpylib runtime system.
    """
    
    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.global_state = GlobalSchedulerState()
        
        # Core schedulers (one per core)
        self.core_schedulers: Dict[int, CoreScheduler] = {}
        
        # Scheduler control
        self.running = False
        self.shutdown_requested = False
        self.main_task_group: Optional[anyio.abc.TaskGroup] = None
        
        # Process spawning
        self._next_core_assignment = 0
        self._spawn_lock = threading.Lock()
        
        # Statistics and monitoring
        self._stats_update_interval = 5.0
        self._last_stats_update = 0.0
        
    async def initialize(self):
        """Initialize the scheduler and all core schedulers"""
        logger.info(f"Initializing WorkStealingScheduler with {self.config.core_count} cores")
        
        # Create core schedulers
        for core_id in range(self.config.core_count):
            core_scheduler = CoreScheduler(core_id, self.config, self.global_state)
            self.core_schedulers[core_id] = core_scheduler
            await core_scheduler.initialize()
            
        # Store reference to core schedulers in global state for work stealing
        self.global_state.core_schedulers = self.core_schedulers
        
        logger.info("WorkStealingScheduler initialized successfully")
        
    async def shutdown(self):
        """Shutdown the scheduler and all core schedulers"""
        logger.info("Shutting down WorkStealingScheduler")
        
        self.shutdown_requested = True
        self.global_state.shutdown_requested = True
        
        # Shutdown all core schedulers
        shutdown_tasks = []
        for core_scheduler in self.core_schedulers.values():
            shutdown_tasks.append(core_scheduler.shutdown())
            
        if shutdown_tasks:
            await asyncio.gather(*shutdown_tasks, return_exceptions=True)
            
        logger.info("WorkStealingScheduler shutdown complete")
        
    async def run_forever(self):
        """Run the scheduler until shutdown is requested"""
        if self.running:
            raise SchedulerError("Scheduler is already running")
            
        self.running = True
        logger.info("Starting WorkStealingScheduler main loop")
        
        try:
            async with anyio.create_task_group() as tg:
                self.main_task_group = tg
                
                # Start all core scheduler loops
                for core_scheduler in self.core_schedulers.values():
                    tg.start_soon(core_scheduler.run_scheduler_loop)
                    
                # Start monitoring and statistics collection
                tg.start_soon(self._statistics_collector)
                tg.start_soon(self._health_monitor)
                
                # Keep running until shutdown
                while not self.shutdown_requested:
                    await anyio.sleep(1.0)
                    
        except Exception as e:
            logger.error(f"WorkStealingScheduler error: {e}")
            raise
        finally:
            self.running = False
            
    async def spawn_process(self, process: OTPProcess) -> str:
        """
        Spawn a new process on the scheduler.
        
        Selects the best core for the process and adds it to that core's queue.
        """
        if self.shutdown_requested:
            raise ProcessSpawnError("Cannot spawn process: scheduler is shutting down")
            
        # Ensure process has a PID
        if not process.pid:
            process.pid = f"{process.process_type.value}_{int(time.time() * 1000000)}"
            
        # Register process globally
        if not self.global_state.register_process(process):
            raise ProcessSpawnError(f"Process {process.pid} already exists")
            
        try:
            # Select target core for the process
            target_core = self._select_core_for_process(process)
            
            # Add process to the selected core
            success = await self.core_schedulers[target_core].add_process(process)
            if not success:
                raise ProcessSpawnError(f"Failed to add process {process.pid} to core {target_core}")
                
            logger.debug(f"Spawned process {process.pid} ({process.process_type.value}) on core {target_core}")
            return process.pid
            
        except Exception as e:
            # Cleanup on failure
            self.global_state.unregister_process(process.pid)
            raise ProcessSpawnError(f"Failed to spawn process {process.pid}: {e}") from e
            
    async def terminate_process(self, pid: str, reason: str = "manual_termination") -> bool:
        """Terminate a specific process"""
        
        with self.global_state._lock:
            process = self.global_state.process_table.get(pid)
            
        if not process:
            logger.warning(f"Attempt to terminate unknown process: {pid}")
            return False
            
        # Remove from appropriate core
        if process.current_core is not None:
            core_scheduler = self.core_schedulers.get(process.current_core)
            if core_scheduler:
                await core_scheduler.remove_process(pid, reason)
                
        # Unregister globally
        self.global_state.unregister_process(pid)
        
        logger.info(f"Terminated process {pid}: {reason}")
        return True
        
    async def send_message(self, target: Union[str, OTPProcess], message: Any) -> bool:
        """Send a message to a process"""
        
        # Resolve target process
        if isinstance(target, str):
            # Target is PID or registered name
            process = self._resolve_process_target(target)
        else:
            process = target
            
        if not process:
            logger.warning(f"Cannot send message: target process not found: {target}")
            return False
            
        # Add message to process queue
        process.message_queue.append(message)
        process.update_queue_metrics()
        
        # If process is waiting, make it ready
        if process.state == ProcessState.WAITING:
            process.state = ProcessState.READY
            
            # Add back to core's ready queue if needed
            if process.current_core is not None:
                core_scheduler = self.core_schedulers.get(process.current_core)
                if core_scheduler and process.pid not in core_scheduler.core_state.ready_queue:
                    core_scheduler.core_state.ready_queue.append(process.pid)
                    
        return True
        
    def _resolve_process_target(self, target: str) -> Optional[OTPProcess]:
        """Resolve a target string to an OTPProcess"""
        
        with self.global_state._lock:
            # Try as direct PID first
            process = self.global_state.process_table.get(target)
            if process:
                return process
                
            # Try as registered name
            return self.global_state.get_process_by_name(target)
            
    def _select_core_for_process(self, process: OTPProcess) -> int:
        """Select the best core for a new process"""
        
        # For now, use simple round-robin with load awareness
        with self._spawn_lock:
            
            # If work stealing is disabled, just use round-robin
            if not self.config.work_stealing_enabled:
                core = self._next_core_assignment % self.config.core_count
                self._next_core_assignment += 1
                return core
                
            # Select least loaded core
            best_core = 0
            best_load = float('inf')
            
            for core_id, core_scheduler in self.core_schedulers.items():
                load = core_scheduler.core_state.get_load_factor()
                
                # Add some randomness to prevent all processes going to same core
                adjusted_load = load + (hash(process.pid) % 100) / 1000.0
                
                if adjusted_load < best_load:
                    best_load = adjusted_load
                    best_core = core_id
                    
            return best_core
            
    async def _statistics_collector(self):
        """Collect and update global statistics"""
        
        while not self.shutdown_requested:
            try:
                await self._update_global_statistics()
                await anyio.sleep(self._stats_update_interval)
            except Exception as e:
                logger.error(f"Statistics collector error: {e}")
                await anyio.sleep(1.0)
                
    async def _update_global_statistics(self):
        """Update global performance statistics"""
        
        now = time.time()
        
        # Collect statistics from all cores
        total_processes = 0
        total_ready = 0
        total_cpu_time = 0.0
        total_steals = 0
        
        for core_scheduler in self.core_schedulers.values():
            core_state = core_scheduler.core_state
            
            total_processes += len(core_state.active_processes)
            total_ready += len(core_state.ready_queue)
            total_cpu_time += core_state.total_execution_time
            total_steals += core_state.successful_steals
            
            # Update core utilization
            elapsed = now - self._last_stats_update
            if elapsed > 0:
                core_state.update_utilization(
                    core_state.total_execution_time - getattr(core_state, '_last_execution_time', 0),
                    elapsed
                )
                core_state._last_execution_time = core_state.total_execution_time
                
        self._last_stats_update = now
        
        # Log periodic statistics
        if total_processes > 0:
            logger.debug(
                f"Scheduler stats: {total_processes} processes, "
                f"{total_ready} ready, {total_steals} steals, "
                f"{total_cpu_time:.2f}s total CPU"
            )
            
    async def _health_monitor(self):
        """Monitor scheduler and process health"""
        
        while not self.shutdown_requested:
            try:
                await self._check_scheduler_health()
                await anyio.sleep(30.0)  # Health check every 30 seconds
            except Exception as e:
                logger.error(f"Health monitor error: {e}")
                await anyio.sleep(5.0)
                
    async def _check_scheduler_health(self):
        """Check overall scheduler health"""
        
        # Check for stuck processes
        now = time.time()
        stuck_threshold = 300.0  # 5 minutes
        
        with self.global_state._lock:
            stuck_processes = [
                pid for pid, process in self.global_state.process_table.items()
                if now - process.last_active > stuck_threshold and 
                   process.state in [ProcessState.RUNNING, ProcessState.READY]
            ]
            
        if stuck_processes:
            logger.warning(f"Detected {len(stuck_processes)} potentially stuck processes")
            
        # Check for core imbalances
        loads = [cs.core_state.get_load_factor() for cs in self.core_schedulers.values()]
        if loads:
            max_load = max(loads)
            min_load = min(loads)
            if max_load - min_load > 5.0:  # Significant imbalance
                logger.warning(f"Core load imbalance detected: {min_load:.1f} - {max_load:.1f}")
                
    def get_scheduler_statistics(self) -> Dict[str, Any]:
        """Get comprehensive scheduler statistics"""
        
        with self.global_state._lock:
            global_stats = {
                'total_processes': len(self.global_state.process_table),
                'total_created': self.global_state.total_processes_created,
                'total_terminated': self.global_state.total_processes_terminated,
                'total_migrations': self.global_state.total_migrations,
                'uptime_seconds': time.time() - self.global_state.startup_time,
                'cores': {}
            }
            
        # Add per-core statistics
        for core_id, core_scheduler in self.core_schedulers.items():
            global_stats['cores'][core_id] = core_scheduler.get_core_statistics()
            
        return global_stats
        
    def list_processes(self, process_type: Optional[ProcessType] = None) -> List[Dict[str, Any]]:
        """List all processes with optional filtering"""
        
        processes = []
        
        with self.global_state._lock:
            for process in self.global_state.process_table.values():
                if process_type and process.process_type != process_type:
                    continue
                    
                process_info = {
                    'pid': process.pid,
                    'type': process.process_type.value,
                    'name': process.name,
                    'state': process.state.value,
                    'current_core': process.current_core,
                    'message_queue_length': len(process.message_queue),
                    'messages_processed': process.metrics.messages_processed,
                    'restart_count': process.metrics.restart_count,
                    'created_at': process.created_at,
                    'last_active': process.last_active
                }
                processes.append(process_info)
                
        return processes
        
    async def migrate_process(self, pid: str, target_core: int, reason: str = "manual") -> bool:
        """Manually migrate a process to a different core"""
        
        if target_core not in self.core_schedulers:
            raise ProcessSpawnError(f"Invalid target core: {target_core}")
            
        with self.global_state._lock:
            process = self.global_state.process_table.get(pid)
            
        if not process:
            return False
            
        current_core = process.current_core
        if current_core == target_core:
            return True  # Already on target core
            
        if current_core is not None:
            # Remove from current core
            await self.core_schedulers[current_core].remove_process(pid, f"migration_to_{target_core}")
            
        # Add to target core
        success = await self.core_schedulers[target_core].add_process(process)
        if success:
            logger.info(f"Migrated process {pid} from core {current_core} to core {target_core}: {reason}")
            
        return success
        
    def get_process_info(self, pid: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific process"""
        
        with self.global_state._lock:
            process = self.global_state.process_table.get(pid)
            
        if not process:
            return None
            
        return {
            'pid': process.pid,
            'type': process.process_type.value,
            'name': process.name,
            'state': process.state.value,
            'current_core': process.current_core,
            'created_at': process.created_at,
            'started_at': process.started_at,
            'last_active': process.last_active,
            'message_queue_length': len(process.message_queue),
            'characteristics': {
                'cpu_bound_score': process.characteristics.cpu_bound_score,
                'memory_usage_mb': process.characteristics.memory_usage_mb,
                'migration_cost': process.characteristics.migration_cost,
                'priority': process.characteristics.priority
            },
            'metrics': {
                'messages_processed': process.metrics.messages_processed,
                'total_execution_time': process.metrics.total_execution_time,
                'average_message_time': process.metrics.average_message_time,
                'migration_count': process.metrics.migration_count,
                'restart_count': process.metrics.restart_count
            },
            'supervisor_info': {
                'supervisor_pid': process.supervisor_pid,
                'supervisor_context': process.supervisor_context
            }
        }
