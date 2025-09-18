"""
SPAM Core Scheduling

Core scheduling primitives for individual cores.
Handles process execution, work stealing, and time slicing.
"""

import asyncio
import time
import random
import threading
from collections import deque
from typing import Optional, List, Dict, Any, Callable, Awaitable
import anyio
import logging

from .data import (
    OTPProcess, ProcessState, ProcessType, CoreState, GlobalSchedulerState,  
    MigrationReason, RuntimeConfig, SPAMError, ProcessMigrationError,
)

logger = logging.getLogger(__name__)


class ProcessExecutionContext:
    """Context for executing a process with cancellation and state tracking"""
    
    def __init__(self, process: OTPProcess, core_scheduler: 'CoreScheduler'):
        self.process = process
        self.core_scheduler = core_scheduler
        self.execution_start_time = 0.0
        self.messages_processed = 0
        self.should_yield = False
        
    async def __aenter__(self):
        """Enter execution context"""
        self.execution_start_time = time.time()
        self.process.state = ProcessState.RUNNING
        self.process.last_scheduled = self.execution_start_time
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit execution context and update metrics"""
        execution_time = time.time() - self.execution_start_time
        
        # Update process metrics
        self.process.metrics.update_execution_time(execution_time)
        self.process.metrics.messages_processed += self.messages_processed
        self.process.last_active = time.time()
        
        # Update core metrics
        self.core_scheduler.core_state.total_execution_time += execution_time
        
        # Reset process state
        if self.process.state == ProcessState.RUNNING:
            self.process.state = ProcessState.READY if self.process.message_queue else ProcessState.WAITING


class CoreScheduler:
    """
    Single-core process scheduler with work stealing capability.
    
    Manages process execution on one core, handles time slicing,
    and participates in work stealing with other cores.
    """
    
    def __init__(self, core_id: int, config: RuntimeConfig, global_state: GlobalSchedulerState):
        self.core_id = core_id
        self.config = config
        self.global_state = global_state
        self.core_state = CoreState(core_id)
        
        # Process execution state
        self.task_group: Optional[anyio.abc.TaskGroup] = None
        self.running = False
        self.shutdown_requested = False
        
        # Work stealing coordination
        self.steal_lock = threading.Lock()
        self.last_steal_attempt = 0.0
        
    async def initialize(self):
        """Initialize the core scheduler"""
        logger.debug(f"Initializing core scheduler {self.core_id}")
        
        # Register core state
        with self.global_state._lock:
            self.global_state.core_states[self.core_id] = self.core_state
            
    async def shutdown(self):
        """Shutdown the core scheduler"""
        logger.debug(f"Shutting down core scheduler {self.core_id}")
        self.shutdown_requested = True
        
        # Cancel all active processes
        for process in list(self.core_state.active_processes.values()):
            await self._cancel_process(process, "scheduler_shutdown")
            
    async def run_scheduler_loop(self):
        """Main scheduler loop for this core"""
        self.running = True
        logger.info(f"Starting scheduler loop for core {self.core_id}")
        
        try:
            async with anyio.create_task_group() as tg:
                self.task_group = tg
                
                while not self.shutdown_requested:
                    # Try to get work from local queue
                    process = await self._get_next_process()
                    
                    if process:
                        # Execute process for one time slice
                        tg.start_soon(self._execute_process_slice, process)
                    else:
                        # No local work - try work stealing
                        if await self._should_attempt_steal():
                            stolen_process = await self._attempt_work_steal()
                            if stolen_process:
                                tg.start_soon(self._execute_process_slice, stolen_process)
                            else:
                                # No work anywhere - brief idle
                                await anyio.sleep(0.001)
                        else:
                            await anyio.sleep(0.001)
                            
        except Exception as e:
            logger.error(f"Core scheduler {self.core_id} error: {e}")
            raise
        finally:
            self.running = False
            
    async def add_process(self, process: OTPProcess) -> bool:
        """Add a new process to this core"""
        if process.pid in self.core_state.active_processes:
            return False
            
        process.current_core = self.core_id
        process.state = ProcessState.READY
        
        self.core_state.active_processes[process.pid] = process
        self.core_state.ready_queue.append(process.pid)
        
        logger.debug(f"Added process {process.pid} to core {self.core_id}")
        return True
        
    async def remove_process(self, pid: str, reason: str = "terminated") -> bool:
        """Remove a process from this core"""
        process = self.core_state.active_processes.pop(pid, None)
        if not process:
            return False
            
        # Remove from ready queue if present
        try:
            self.core_state.ready_queue.remove(pid)
        except ValueError:
            pass
            
        # Cancel if running
        await self._cancel_process(process, reason)
        
        logger.debug(f"Removed process {pid} from core {self.core_id}: {reason}")
        return True
        
    async def _get_next_process(self) -> Optional[OTPProcess]:
        """Get next process to execute from local queue"""
        while self.core_state.ready_queue:
            pid = self.core_state.ready_queue.popleft()
            process = self.core_state.active_processes.get(pid)
            
            if process and process.state == ProcessState.READY:
                return process
                
        return None
        
    async def _execute_process_slice(self, process: OTPProcess):
        """Execute a process for one time slice with preemption"""
        
        async with ProcessExecutionContext(process, self) as ctx:
            try:
                # Set up cancellation scope for time slicing
                with anyio.move_on_after(self.config.time_slice_ms / 1000.0) as cancel_scope:
                    await self._run_process_messages(process, ctx)
                    
                if cancel_scope.cancelled_caught:
                    # Time slice expired - preempt process
                    logger.debug(f"Process {process.pid} preempted after time slice")
                    await self._handle_preemption(process, "time_slice_expired")
                else:
                    # Process yielded voluntarily or no more messages
                    await self._handle_voluntary_yield(process)
                    
            except Exception as e:
                logger.error(f"Error executing process {process.pid}: {e}")
                await self._handle_process_error(process, e)
                
    async def _run_process_messages(self, process: OTPProcess, ctx: ProcessExecutionContext):
        """Run process message handling loop"""
        
        message_count = 0
        
        while process.message_queue and message_count < self.config.yield_check_interval:
            # Check if we should yield for work stealing
            if ctx.should_yield or await self._should_yield_for_steal():
                break
                
            # Process one message
            try:
                message = process.message_queue.popleft()
                await self._handle_process_message(process, message)
                
                message_count += 1
                ctx.messages_processed += 1
                
            except Exception as e:
                logger.error(f"Error handling message in {process.pid}: {e}")
                break
                
        process.update_queue_metrics()
        
    async def _handle_process_message(self, process: OTPProcess, message: Any):
        """Handle a single message for a process"""
        
        match process.process_type:
            case ProcessType.GEN_SERVER:
                await self._handle_gen_server_message(process, message)
            case ProcessType.SUPERVISOR:
                await self._handle_supervisor_message(process, message)
            case ProcessType.WORKER:
                await self._handle_worker_message(process, message)
                
    async def _handle_gen_server_message(self, process: OTPProcess, message: Any):
        """Handle gen_server message with proper call/cast/info routing"""
        
        # Handle different message types from SPAMBackend
        if isinstance(message, dict):
            message_type = message.get('type')
            
            match message_type:
                case 'call':
                    await self._handle_gen_server_call(process, message)
                case 'cast':
                    await self._handle_gen_server_cast(process, message)
                case _:
                    # Handle as info message
                    await self._handle_gen_server_info(process, message)
        else:
            # Direct message - treat as info
            await self._handle_gen_server_info(process, message)
            
    async def _handle_gen_server_call(self, process: OTPProcess, call_message: Dict[str, Any]):
        """Handle synchronous gen_server call"""
        
        payload = call_message['payload']
        response_stream = call_message['response_stream']
        call_id = call_message['call_id']
        
        try:
            # Call the gen_server's handle_call function
            if hasattr(process.module, 'handle_call'):
                result = await process.module.handle_call(payload, response_stream, process.internal_state)
                
                # Expected result: (Reply(payload) | NoReply() | Stop(), new_state)
                if isinstance(result, tuple) and len(result) == 2:
                    continuation, new_state = result
                    process.internal_state = new_state
                    
                    # Handle different continuation types
                    if hasattr(continuation, 'payload'):  # Reply
                        await response_stream.send(continuation.payload)
                    elif hasattr(continuation, 'reason'):  # Stop
                        await response_stream.send(Exception("GenServer stopped"))
                        process.state = ProcessState.TERMINATED
                    # NoReply - don't send response yet
                else:
                    # Invalid return format
                    await response_stream.send(Exception("Invalid gen_server handle_call return"))
            else:
                await response_stream.send(Exception("handle_call not implemented"))
                
        except Exception as e:
            # Send exception back to caller
            await response_stream.send(e)
            
    async def _handle_gen_server_cast(self, process: OTPProcess, cast_message: Dict[str, Any]):
        """Handle asynchronous gen_server cast"""
        
        payload = cast_message['payload']
        
        try:
            # Call the gen_server's handle_cast function
            if hasattr(process.module, 'handle_cast'):
                result = await process.module.handle_cast(payload, process.internal_state)
                
                # Expected result: (NoReply() | Stop(), new_state)
                if isinstance(result, tuple) and len(result) == 2:
                    continuation, new_state = result
                    process.internal_state = new_state
                    
                    # Handle Stop continuation
                    if hasattr(continuation, 'reason'):  # Stop
                        process.state = ProcessState.TERMINATED
            else:
                logger.warning(f"handle_cast not implemented for process {process.pid}")
                
        except Exception as e:
            logger.error(f"Error in gen_server cast for {process.pid}: {e}")
            
    async def _handle_gen_server_info(self, process: OTPProcess, message: Any):
        """Handle gen_server info message"""
        
        try:
            # Call the gen_server's handle_info function if it exists
            if hasattr(process.module, 'handle_info'):
                result = await process.module.handle_info(message, process.internal_state)
                
                # Expected result: (NoReply() | Stop(), new_state)  
                if isinstance(result, tuple) and len(result) == 2:
                    continuation, new_state = result
                    process.internal_state = new_state
                    
                    # Handle Stop continuation
                    if hasattr(continuation, 'reason'):  # Stop
                        process.state = ProcessState.TERMINATED
            # If no handle_info, just ignore the message
                
        except Exception as e:
            logger.error(f"Error in gen_server info for {process.pid}: {e}")
        
    async def _handle_supervisor_message(self, process: OTPProcess, message: Any):
        """Handle supervisor message"""
        
        # Supervisor messages are typically child management requests
        if isinstance(message, dict):
            action = message.get('action')
            
            match action:
                case 'start_child':
                    await self._supervisor_start_child(process, message)
                case 'terminate_child':
                    await self._supervisor_terminate_child(process, message)
                case 'restart_child':
                    await self._supervisor_restart_child(process, message)
                case _:
                    # Delegate to supervisor module if it exists
                    if hasattr(process.module, 'handle_message'):
                        await process.module.handle_message(message, process.internal_state)
        else:
            # Direct message handling
            if hasattr(process.module, 'handle_message'):
                await process.module.handle_message(message, process.internal_state)
                
    async def _supervisor_start_child(self, process: OTPProcess, message: Dict[str, Any]):
        """Handle supervisor start_child request"""
        
        child_spec = message.get('child_spec')
        if child_spec:
            # This would integrate with the supervisor's child management
            logger.debug(f"Supervisor {process.pid} starting child: {child_spec}")
            # Implementation would spawn child process and track it
        
    async def _supervisor_terminate_child(self, process: OTPProcess, message: Dict[str, Any]):
        """Handle supervisor terminate_child request"""
        
        child_id = message.get('child_id')
        if child_id:
            logger.debug(f"Supervisor {process.pid} terminating child: {child_id}")
            # Implementation would terminate child process
        
    async def _supervisor_restart_child(self, process: OTPProcess, message: Dict[str, Any]):
        """Handle supervisor restart_child request"""
        
        child_id = message.get('child_id')
        if child_id:
            logger.debug(f"Supervisor {process.pid} restarting child: {child_id}")
            # Implementation would restart child process
        
    async def _handle_worker_message(self, process: OTPProcess, message: Any):
        """Handle worker process message"""
        
        # Workers can have custom message handling
        worker_spec = process.module
        
        if isinstance(worker_spec, dict) and 'function' in worker_spec:
            # Call the worker function with the message
            try:
                worker_func = worker_spec['function']
                args = worker_spec.get('args', [])
                
                # Call worker function with message and args
                if asyncio.iscoroutinefunction(worker_func):
                    await worker_func(message, *args)
                else:
                    # Run sync function in thread pool
                    await anyio.to_thread.run_sync(worker_func, message, *args)
                    
            except Exception as e:
                logger.error(f"Error in worker {process.pid}: {e}")
        else:
            # Custom worker message handling
            if hasattr(process.module, 'handle_message'):
                await process.module.handle_message(message, process.internal_state)
            else:
                # Default: just log the message
                logger.debug(f"Worker {process.pid} received message: {message}")
        
    async def _handle_preemption(self, process: OTPProcess, reason: str):
        """Handle process preemption"""
        logger.debug(f"Preempting process {process.pid}: {reason}")
        
        # Save process state if needed
        if self.config.state_backup_enabled:
            await self._save_process_state(process)
            
        # Return to ready queue for rescheduling
        if process.state == ProcessState.RUNNING:
            process.state = ProcessState.READY
            self.core_state.ready_queue.append(process.pid)
            
    async def _handle_voluntary_yield(self, process: OTPProcess):
        """Handle voluntary process yield"""
        
        if process.message_queue:
            # More work to do - return to queue
            process.state = ProcessState.READY
            self.core_state.ready_queue.append(process.pid)
        else:
            # No more work - wait for messages
            process.state = ProcessState.WAITING
            
    async def _handle_process_error(self, process: OTPProcess, error: Exception):
        """Handle process execution error"""
        logger.error(f"Process {process.pid} error: {error}")
        
        process.state = ProcessState.TERMINATED
        # This would integrate with supervisor restart logic
        
    async def _cancel_process(self, process: OTPProcess, reason: str):
        """Cancel a running process"""
        if process.cancel_scope:
            process.cancel_scope.cancel()
            
        process.state = ProcessState.TERMINATED
        logger.debug(f"Cancelled process {process.pid}: {reason}")
        
    async def _save_process_state(self, process: OTPProcess):
        """Save process state for recovery"""
        # This would integrate with the state backup system
        process.last_state_backup = time.time()
        
    async def _should_attempt_steal(self) -> bool:
        """Check if we should attempt work stealing"""
        if not self.config.work_stealing_enabled:
            return False
            
        # Rate limit steal attempts
        now = time.time()
        if now - self.last_steal_attempt < 0.1:  # Max 10 attempts per second
            return False
            
        # Only steal if we're significantly less loaded
        my_load = self.core_state.get_load_factor()
        
        return my_load < 1.0  # Only steal if relatively idle
        
    async def _attempt_work_steal(self) -> Optional[OTPProcess]:
        """Attempt to steal work from other cores"""
        self.last_steal_attempt = time.time()
        self.core_state.steal_attempts += 1
        
        # Find victim cores
        victim_cores = self._select_steal_victims()
        
        for victim_core_id in victim_cores:
            stolen_process = await self._steal_from_core(victim_core_id)
            if stolen_process:
                self.core_state.successful_steals += 1
                self.core_state.processes_stolen += 1
                logger.debug(f"Core {self.core_id} stole process {stolen_process.pid} from core {victim_core_id}")
                return stolen_process
                
        return None
        
    def _select_steal_victims(self) -> List[int]:
        """Select cores to attempt stealing from"""
        victims = []
        my_load = self.core_state.get_load_factor()
        
        with self.global_state._lock:
            for core_id, core_state in self.global_state.core_states.items():
                if core_id == self.core_id:
                    continue
                    
                victim_load = core_state.get_load_factor()
                
                # Only steal from significantly more loaded cores
                if victim_load > my_load + self.config.steal_threshold:
                    victims.append(core_id)
                    
        # Randomize victim order to avoid thundering herd
        random.shuffle(victims)
        return victims[:self.config.steal_attempts_per_cycle]
        
    async def _steal_from_core(self, victim_core_id: int) -> Optional[OTPProcess]:
        """Attempt to steal a process from specific victim core"""
        
        # Get victim core scheduler
        victim_scheduler = None
        for scheduler in self.global_state.core_schedulers.values():
            if scheduler.core_id == victim_core_id:
                victim_scheduler = scheduler
                break
                
        if not victim_scheduler:
            return None
            
        # Try to acquire victim's steal lock (non-blocking)
        if not victim_scheduler.steal_lock.acquire(blocking=False):
            return None
            
        try:
            return await self._perform_steal(victim_scheduler)
        finally:
            victim_scheduler.steal_lock.release()
            
    async def _perform_steal(self, victim_scheduler: 'CoreScheduler') -> Optional[OTPProcess]:
        """Perform the actual process theft"""
        
        victim_state = victim_scheduler.core_state
        
        # Find suitable process to steal
        stealable_processes = [
            pid for pid in victim_state.ready_queue
            if pid in victim_state.active_processes and
            victim_state.active_processes[pid].can_be_stolen()
        ]
        
        if not stealable_processes:
            return None
            
        # Steal from the back of the queue (LIFO for cache locality)
        stolen_pid = stealable_processes[-1]
        stolen_process = victim_state.active_processes.pop(stolen_pid)
        
        # Remove from victim's ready queue
        try:
            victim_state.ready_queue.remove(stolen_pid)
        except ValueError:
            pass
            
        # Update victim metrics
        victim_state.processes_given += 1
        
        # Migrate process to this core
        await self._migrate_process_to_core(stolen_process, victim_scheduler.core_id)
        
        return stolen_process
        
    async def _migrate_process_to_core(self, process: OTPProcess, from_core: int):
        """Migrate process to this core"""
        
        process.state = ProcessState.MIGRATING
        process.record_migration(MigrationReason.WORK_STEALING)
        
        # Update process core assignment
        process.current_core = self.core_id
        
        # Add to our core
        self.core_state.active_processes[process.pid] = process
        self.core_state.ready_queue.append(process.pid)
        
        process.state = ProcessState.READY
        
        # Update global metrics
        with self.global_state._lock:
            self.global_state.total_migrations += 1
            
        logger.debug(f"Migrated process {process.pid} from core {from_core} to core {self.core_id}")
        
    async def _should_yield_for_steal(self) -> bool:
        """Check if current process should yield for work stealing"""
        
        # Check if other cores are trying to steal our work
        # This is a simplified heuristic
        
        my_load = self.core_state.get_load_factor()
        
        # If we're heavily loaded and others are idle, be cooperative
        with self.global_state._lock:
            idle_cores = sum(
                1 for core_state in self.global_state.core_states.values()
                if core_state.get_load_factor() < 0.5
            )
            
        if idle_cores > 0 and my_load > 3.0:
            return True
            
        return False
        
    def get_core_statistics(self) -> Dict[str, Any]:
        """Get current core performance statistics"""
        return {
            'core_id': self.core_id,
            'active_processes': len(self.core_state.active_processes),
            'ready_queue_length': len(self.core_state.ready_queue),
            'total_processes_run': self.core_state.total_processes_run,
            'total_execution_time': self.core_state.total_execution_time,
            'cpu_utilization': self.core_state.cpu_utilization,
            'steal_attempts': self.core_state.steal_attempts,
            'successful_steals': self.core_state.successful_steals,
            'processes_stolen': self.core_state.processes_stolen,
            'processes_given': self.core_state.processes_given,
            'load_factor': self.core_state.get_load_factor()
        }
