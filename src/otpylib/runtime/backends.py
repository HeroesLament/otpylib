"""
Runtime Backend Implementations

Concrete implementations of the RuntimeBackend interface for different
execution environments.
"""

import asyncio
import time
import uuid
import logging
from typing import Any, Dict, List, Optional, Union
from types import ModuleType
import threading

import anyio

from otpylib import gen_server
from otpylib.runtime.core import BaseRuntimeBackend, validate_gen_server_module
from otpylib.runtime.data import (
    ProcessType, ProcessState, ProcessInfo, RuntimeStatistics, SimpleChildSpec,
    ProcessCharacteristics, ProcessNotFoundError, NameAlreadyRegisteredError, 
    ProcessSpawnError
)

logger = logging.getLogger(__name__)


class AnyIOBackend(BaseRuntimeBackend):
    """
    Runtime backend that uses pure AnyIO primitives.
    
    Provides OTP semantics using AnyIO task groups, memory streams, and
    coordination primitives. This is the fallback backend that works in
    any AnyIO application without requiring SPAM scheduling.
    """
    
    def __init__(self):
        super().__init__()
        
        # Process registry
        self._processes: Dict[str, ProcessInfo] = {}
        self._name_registry: Dict[str, str] = {}  # name -> pid
        self._process_tasks: Dict[str, anyio.abc.Task] = {}  # pid -> task
        
        # Statistics tracking
        self._stats = {
            'total_spawned': 0,
            'total_terminated': 0,
            'calls_processed': 0,
            'casts_processed': 0,
            'messages_processed': 0,
        }
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Task group for managing processes
        self._task_group: Optional[anyio.abc.TaskGroup] = None
        self._startup_time = time.time()
        
    async def initialize(self):
        """Initialize the backend - should be called before use."""
        # Backend is ready immediately for AnyIO
        logger.debug("AnyIOBackend initialized")
        
    async def shutdown(self):
        """Shutdown the backend and clean up resources."""
        with self._lock:
            # Cancel all running processes
            for pid in list(self._processes.keys()):
                try:
                    await self.terminate_process(pid, "backend_shutdown")
                except Exception as e:
                    logger.error(f"Error terminating process {pid} during shutdown: {e}")
                    
        logger.info("AnyIOBackend shutdown complete")
        
    async def spawn_gen_server(
        self,
        module: ModuleType,
        init_arg: Any = None,
        name: Optional[str] = None,
        supervisor_context: Optional[str] = None,
        recovered_state: Optional[Dict[str, Any]] = None,
        characteristics: Optional[ProcessCharacteristics] = None
    ) -> str:
        """Spawn a gen_server using the existing gen_server implementation."""
        
        validate_gen_server_module(module)
        
        if name:
            self._validate_process_name(name)
            with self._lock:
                if name in self._name_registry:
                    raise NameAlreadyRegisteredError(f"Name '{name}' is already registered")
        
        # Generate PID
        pid = f"gs_{uuid.uuid4().hex[:8]}"
        
        try:
            with self._lock:
                # Register process info
                process_info = self._create_process_info(
                    pid=pid,
                    process_type=ProcessType.GEN_SERVER,
                    name=name,
                    state=ProcessState.STARTING,
                    characteristics=characteristics,
                    supervisor_context=supervisor_context
                )
                self._processes[pid] = process_info
                
                if name:
                    self._name_registry[name] = pid
                    
                self._stats['total_spawned'] += 1
            
            # Import gen_server and start it
            # We use the existing gen_server.start implementation
            from otpylib import gen_server
            
            # Create a task to run the gen_server
            async def run_gen_server():
                try:
                    with self._lock:
                        self._processes[pid].state = ProcessState.RUNNING
                        self._processes[pid].last_active = time.time()
                    
                    # Use original gen_server._loop to avoid recursion
                    await gen_server._loop(
                        module, 
                        init_arg, 
                        name,
                        recovered_state, 
                        supervisor_context
                    )
                    
                except Exception as e:
                    logger.error(f"GenServer {pid} failed: {e}")
                    raise
                finally:
                    # Clean up on exit
                    with self._lock:
                        if pid in self._processes:
                            self._processes[pid].state = ProcessState.TERMINATED
                        self._cleanup_process(pid)
            
            # Start the task (need to use current task group or create one)
            try:
                # Try to use the current task group if available
                import anyio.lowlevel
                task_group = anyio.lowlevel.current_task_group()
                task = task_group.start_soon(run_gen_server)
                
            except (RuntimeError, LookupError):
                # No current task group - we'll need to manage this differently
                # For now, just start the task in the background
                import asyncio
                task = asyncio.create_task(run_gen_server())
            
            with self._lock:
                self._process_tasks[pid] = task
                
            logger.debug(f"Spawned gen_server {pid} (name: {name})")
            return pid
            
        except Exception as e:
            # Cleanup on failure
            with self._lock:
                self._cleanup_process(pid)
            raise ProcessSpawnError(f"Failed to spawn gen_server: {e}") from e
            
    async def spawn_supervisor(
        self,
        child_specs: List[SimpleChildSpec],
        supervisor_options: Dict[str, Any],
        name: Optional[str] = None,
        supervisor_context: Optional[str] = None,
        characteristics: Optional[ProcessCharacteristics] = None
    ) -> str:
        """Spawn a supervisor using the existing supervisor implementation."""
        
        if name:
            self._validate_process_name(name)
            with self._lock:
                if name in self._name_registry:
                    raise NameAlreadyRegisteredError(f"Name '{name}' is already registered")
        
        pid = f"sup_{uuid.uuid4().hex[:8]}"
        
        try:
            with self._lock:
                process_info = self._create_process_info(
                    pid=pid,
                    process_type=ProcessType.SUPERVISOR,
                    name=name,
                    state=ProcessState.STARTING,
                    characteristics=characteristics,
                    supervisor_context=supervisor_context
                )
                self._processes[pid] = process_info
                
                if name:
                    self._name_registry[name] = pid
                    
                self._stats['total_spawned'] += 1
            
            # Convert SimpleChildSpec to full supervisor child_spec
            from otpylib import supervisor
            
            full_child_specs = []
            for spec in child_specs:
                if spec.process_type == ProcessType.GEN_SERVER:
                    # Gen_server child spec
                    child_spec = supervisor.child_spec(
                        id=spec.id,
                        task=gen_server.start,  # Import will be available at runtime
                        args=[spec.module, spec.init_arg, spec.name]
                    )
                else:
                    # Worker or other task
                    child_spec = supervisor.child_spec(
                        id=spec.id,
                        task=spec.module,  # Assume it's a callable for workers
                        args=[spec.init_arg] if spec.init_arg else []
                    )
                full_child_specs.append(child_spec)
            
            # Create supervisor options from our dict
            sup_options = supervisor.options(
                max_restarts=supervisor_options.get('max_restarts', 3),
                max_seconds=supervisor_options.get('max_seconds', 5),
            )
            
            # Create task to run supervisor
            async def run_supervisor():
                try:
                    with self._lock:
                        self._processes[pid].state = ProcessState.RUNNING
                        self._processes[pid].last_active = time.time()
                    
                    await supervisor.start(full_child_specs, sup_options)
                    
                except Exception as e:
                    logger.error(f"Supervisor {pid} failed: {e}")
                    raise
                finally:
                    with self._lock:
                        if pid in self._processes:
                            self._processes[pid].state = ProcessState.TERMINATED
                        self._cleanup_process(pid)
            
            # Start supervisor task
            try:
                import anyio.lowlevel
                task_group = anyio.lowlevel.current_task_group()
                task = task_group.start_soon(run_supervisor)
            except (RuntimeError, LookupError):
                import asyncio
                task = asyncio.create_task(run_supervisor())
            
            with self._lock:
                self._process_tasks[pid] = task
                
            logger.debug(f"Spawned supervisor {pid} (name: {name})")
            return pid
            
        except Exception as e:
            with self._lock:
                self._cleanup_process(pid)
            raise ProcessSpawnError(f"Failed to spawn supervisor: {e}") from e
            
    async def spawn_worker(
        self,
        worker_func: Any,
        args: List[Any],
        name: Optional[str] = None,
        supervisor_context: Optional[str] = None,
        characteristics: Optional[ProcessCharacteristics] = None
    ) -> str:
        """Spawn a worker process."""
        
        if name:
            self._validate_process_name(name)
            with self._lock:
                if name in self._name_registry:
                    raise NameAlreadyRegisteredError(f"Name '{name}' is already registered")
        
        pid = f"worker_{uuid.uuid4().hex[:8]}"
        
        try:
            with self._lock:
                process_info = self._create_process_info(
                    pid=pid,
                    process_type=ProcessType.WORKER,
                    name=name,
                    state=ProcessState.STARTING,
                    characteristics=characteristics,
                    supervisor_context=supervisor_context
                )
                self._processes[pid] = process_info
                
                if name:
                    self._name_registry[name] = pid
                    
                self._stats['total_spawned'] += 1
            
            # Create task to run worker
            async def run_worker():
                try:
                    with self._lock:
                        self._processes[pid].state = ProcessState.RUNNING
                        self._processes[pid].last_active = time.time()
                    
                    if asyncio.iscoroutinefunction(worker_func):
                        await worker_func(*args)
                    else:
                        # Run sync function in thread pool
                        await anyio.to_thread.run_sync(worker_func, *args)
                    
                except Exception as e:
                    logger.error(f"Worker {pid} failed: {e}")
                    raise
                finally:
                    with self._lock:
                        if pid in self._processes:
                            self._processes[pid].state = ProcessState.TERMINATED
                        self._cleanup_process(pid)
            
            # Start worker task
            try:
                import anyio.lowlevel
                task_group = anyio.lowlevel.current_task_group()
                task = task_group.start_soon(run_worker)
            except (RuntimeError, LookupError):
                import asyncio
                task = asyncio.create_task(run_worker())
            
            with self._lock:
                self._process_tasks[pid] = task
                
            logger.debug(f"Spawned worker {pid} (name: {name})")
            return pid
            
        except Exception as e:
            with self._lock:
                self._cleanup_process(pid)
            raise ProcessSpawnError(f"Failed to spawn worker: {e}") from e
            
    async def call_process(
        self,
        target: Union[str, Any],
        message: Any,
        timeout: Optional[float] = None
    ) -> Any:
        """Make a call using the existing gen_server.call implementation."""
        
        target_str = self._normalize_target(target)
        
        # Increment stats
        with self._lock:
            self._stats['calls_processed'] += 1
        
        # Use existing gen_server.call - it handles mailbox lookup
        from otpylib import gen_server
        return await gen_server.call(target_str, message, timeout)
        
    async def cast_process(
        self,
        target: Union[str, Any],
        message: Any
    ) -> bool:
        """Send a cast using the existing gen_server.cast implementation."""
        
        target_str = self._normalize_target(target)
        
        # Increment stats  
        with self._lock:
            self._stats['casts_processed'] += 1
        
        try:
            from otpylib import gen_server
            await gen_server.cast(target_str, message)
            return True
        except Exception as e:
            logger.error(f"Cast to {target_str} failed: {e}")
            return False
            
    async def send_message(
        self,
        target: Union[str, Any],
        message: Any
    ) -> bool:
        """Send a message using the existing mailbox.send implementation."""
        
        target_str = self._normalize_target(target)
        
        with self._lock:
            self._stats['messages_processed'] += 1
        
        try:
            from otpylib import mailbox
            await mailbox.send(target_str, message)
            return True
        except Exception as e:
            logger.error(f"Message to {target_str} failed: {e}")
            return False
            
    async def terminate_process(
        self,
        pid: str,
        reason: str = "normal"
    ) -> bool:
        """Terminate a process by cancelling its task."""
        
        self._validate_pid(pid)
        
        with self._lock:
            if pid not in self._processes:
                raise ProcessNotFoundError(f"Process {pid} not found")
            
            task = self._process_tasks.get(pid)
            if task and not task.done():
                task.cancel()
                
            self._processes[pid].state = ProcessState.TERMINATING
            self._stats['total_terminated'] += 1
            
        logger.debug(f"Terminated process {pid}: {reason}")
        return True
        
    def is_process_alive(self, pid: str) -> bool:
        """Check if a process is alive by checking its task status."""
        
        with self._lock:
            if pid not in self._processes:
                return False
                
            task = self._process_tasks.get(pid)
            if task is None:
                return False
                
            return not task.done()
            
    async def register_name(self, name: str, pid: str) -> bool:
        """Register a name for a process."""
        
        self._validate_process_name(name)
        self._validate_pid(pid)
        
        with self._lock:
            if name in self._name_registry:
                raise NameAlreadyRegisteredError(f"Name '{name}' is already registered")
                
            if pid not in self._processes:
                raise ProcessNotFoundError(f"Process {pid} not found")
            
            self._name_registry[name] = pid
            self._processes[pid].name = name
            
        logger.debug(f"Registered name '{name}' for process {pid}")
        return True
        
    async def unregister_name(self, name: str) -> bool:
        """Unregister a name."""
        
        with self._lock:
            pid = self._name_registry.pop(name, None)
            if pid and pid in self._processes:
                self._processes[pid].name = None
                
        logger.debug(f"Unregistered name '{name}'")
        return pid is not None
        
    def whereis_name(self, name: str) -> Optional[str]:
        """Look up a PID by name."""
        
        with self._lock:
            return self._name_registry.get(name)
            
    def get_process_info(self, pid: str) -> Optional[ProcessInfo]:
        """Get process information."""
        
        with self._lock:
            process_info = self._processes.get(pid)
            if process_info:
                # Update queue length if we can
                # For AnyIO backend, we don't have direct access to queue lengths
                # This would need integration with mailbox system
                return process_info
            return None
            
    def list_processes(
        self,
        process_type: Optional[ProcessType] = None
    ) -> List[ProcessInfo]:
        """List processes, optionally filtered by type."""
        
        with self._lock:
            processes = list(self._processes.values())
            
        if process_type:
            processes = [p for p in processes if p.process_type == process_type]
            
        return processes
        
    def get_statistics(self) -> RuntimeStatistics:
        """Get runtime statistics."""
        
        with self._lock:
            active_processes = sum(1 for p in self._processes.values() 
                                 if p.state in [ProcessState.RUNNING, ProcessState.WAITING])
            
            return RuntimeStatistics(
                backend_type="AnyIOBackend",
                uptime_seconds=self.get_uptime(),
                total_processes=len(self._processes),
                active_processes=active_processes,
                total_spawned=self._stats['total_spawned'],
                total_terminated=self._stats['total_terminated'],
                messages_processed=self._stats['messages_processed'],
                calls_processed=self._stats['calls_processed'],
                casts_processed=self._stats['casts_processed'],
                registered_names=len(self._name_registry)
            )
            
    def _cleanup_process(self, pid: str) -> None:
        """Clean up process state."""
        
        # Remove from process registry
        process_info = self._processes.pop(pid, None)
        
        # Remove name registration if any
        if process_info and process_info.name:
            self._name_registry.pop(process_info.name, None)
            
        # Remove task reference
        self._process_tasks.pop(pid, None)
        
        logger.debug(f"Cleaned up process {pid}")
