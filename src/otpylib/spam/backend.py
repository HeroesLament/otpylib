"""
SPAM Backend

Runtime backend integration for connecting SPAM with the otpylib runtime abstraction.
Implements the RuntimeBackend interface to provide SPAM scheduling services 
transparently to gen_servers, supervisors, and other OTP patterns.
"""

import uuid
import time
import logging
from typing import Any, Optional, Union, List, Dict
import anyio

from .data import OTPProcess, ProcessType, ProcessState, ProcessCharacteristics, SPAMError
from .runtime import SPAMRuntime

logger = logging.getLogger(__name__)


class SPAMBackend:
    """
    Backend implementation that bridges otpylib runtime abstraction with SPAM.
    
    Provides the RuntimeBackend interface expected by gen_servers, supervisors,
    and other OTP components, routing their operations through the SPAM scheduler.
    """
    
    def __init__(self, spam_runtime: SPAMRuntime):
        self.spam_runtime = spam_runtime
        
        # Cache for process creation optimizations
        self._process_cache = {}
        
    async def spawn_gen_server(
        self, 
        module: Any, 
        init_arg: Any = None, 
        name: Optional[str] = None,
        supervisor_context: Optional[str] = None,
        characteristics: Optional[Dict[str, float]] = None
    ) -> str:
        """Spawn a gen_server process through SPAM"""
        
        # Create process characteristics
        process_chars = ProcessCharacteristics()
        if characteristics:
            process_chars.cpu_bound_score = characteristics.get('cpu_bound', 0.2)
            process_chars.memory_usage_mb = characteristics.get('memory_mb', 1.0)
            process_chars.migration_cost = characteristics.get('migration_cost', 0.1)
            process_chars.priority = characteristics.get('priority', 0)
            
        # Create OTPProcess for gen_server
        process = OTPProcess(
            pid=f"gs_{uuid.uuid4().hex[:8]}",
            process_type=ProcessType.GEN_SERVER,
            module=module,
            init_arg=init_arg,
            name=name,
            supervisor_context=supervisor_context,
            characteristics=process_chars
        )
        
        # Spawn through SPAM
        pid = await self.spam_runtime.spawn_process(process)
        
        logger.debug(f"Spawned gen_server {pid} (name: {name})")
        return pid
        
    async def spawn_supervisor(
        self,
        child_specs: List[Any],
        options: Any,
        name: Optional[str] = None,
        supervisor_context: Optional[str] = None
    ) -> str:
        """Spawn a supervisor process through SPAM"""
        
        # Supervisors are typically I/O bound with higher migration cost
        process_chars = ProcessCharacteristics(
            cpu_bound_score=0.1,  # Mostly reactive
            memory_usage_mb=2.0,  # Slightly more memory for child tracking
            migration_cost=0.3,   # Higher cost due to child coordination
            priority=1            # Slightly higher priority for supervisors
        )
        
        # Package supervisor specification
        supervisor_module = {
            'child_specs': child_specs,
            'options': options,
            'type': 'supervisor'
        }
        
        process = OTPProcess(
            pid=f"sup_{uuid.uuid4().hex[:8]}",
            process_type=ProcessType.SUPERVISOR,
            module=supervisor_module,
            init_arg=None,
            name=name,
            supervisor_context=supervisor_context,
            characteristics=process_chars
        )
        
        pid = await self.spam_runtime.spawn_process(process)
        
        logger.debug(f"Spawned supervisor {pid} (name: {name})")
        return pid
        
    async def spawn_worker(
        self,
        worker_func: Any,
        args: List[Any],
        name: Optional[str] = None,
        supervisor_context: Optional[str] = None,
        characteristics: Optional[Dict[str, float]] = None
    ) -> str:
        """Spawn a worker process through SPAM"""
        
        # Default worker characteristics - assume CPU bound
        process_chars = ProcessCharacteristics()
        if characteristics:
            process_chars.cpu_bound_score = characteristics.get('cpu_bound', 0.7)
            process_chars.memory_usage_mb = characteristics.get('memory_mb', 1.0)
            process_chars.migration_cost = characteristics.get('migration_cost', 0.05)
            process_chars.priority = characteristics.get('priority', 0)
        else:
            process_chars.cpu_bound_score = 0.7  # Default to CPU bound
            process_chars.migration_cost = 0.05  # Low migration cost
            
        # Package worker specification
        worker_module = {
            'function': worker_func,
            'args': args,
            'type': 'worker'
        }
        
        process = OTPProcess(
            pid=f"worker_{uuid.uuid4().hex[:8]}",
            process_type=ProcessType.WORKER,
            module=worker_module,
            init_arg=None,
            name=name,
            supervisor_context=supervisor_context,
            characteristics=process_chars
        )
        
        pid = await self.spam_runtime.spawn_process(process)
        
        logger.debug(f"Spawned worker {pid} (name: {name})")
        return pid
        
    async def send_message(self, target: Union[str, OTPProcess], message: Any) -> bool:
        """Send a message to a process"""
        return await self.spam_runtime.send_message(target, message)
        
    async def call_process(
        self, 
        target: Union[str, OTPProcess], 
        message: Any, 
        timeout: Optional[float] = None
    ) -> Any:
        """Make a synchronous call to a process"""
        
        # Create a response channel for the call
        send_stream, receive_stream = anyio.create_memory_object_stream(1)
        
        # Wrap message with response channel
        call_message = {
            'type': 'call',
            'payload': message,
            'response_stream': send_stream,
            'call_id': f"call_{uuid.uuid4().hex[:8]}"
        }
        
        try:
            # Send the call message
            success = await self.send_message(target, call_message)
            if not success:
                raise SPAMError(f"Failed to send call message to {target}")
                
            # Wait for response
            if timeout is not None:
                with anyio.move_on_after(timeout) as cancel_scope:
                    response = await receive_stream.receive()
                    
                if cancel_scope.cancelled_caught:
                    raise TimeoutError(f"Call to {target} timed out after {timeout}s")
            else:
                response = await receive_stream.receive()
                
            # Handle exception responses
            if isinstance(response, Exception):
                raise response
                
            return response
            
        finally:
            await send_stream.aclose()
            await receive_stream.aclose()
            
    async def cast_process(self, target: Union[str, OTPProcess], message: Any) -> bool:
        """Send an asynchronous message to a process"""
        
        cast_message = {
            'type': 'cast',
            'payload': message
        }
        
        return await self.send_message(target, cast_message)
        
    async def terminate_process(self, pid: str, reason: str = "normal") -> bool:
        """Terminate a specific process"""
        return await self.spam_runtime.terminate_process(pid, reason)
        
    def get_process_info(self, pid: str) -> Optional[Dict[str, Any]]:
        """Get information about a process"""
        return self.spam_runtime.get_process_info(pid)
        
    def list_processes(self, process_type: Optional[ProcessType] = None) -> List[Dict[str, Any]]:
        """List all processes"""
        return self.spam_runtime.list_processes(process_type)
        
    async def link_processes(self, pid1: str, pid2: str) -> bool:
        """Create a bidirectional link between two processes"""
        
        # Get both processes
        process1 = self.spam_runtime.scheduler.global_state.process_table.get(pid1)
        process2 = self.spam_runtime.scheduler.global_state.process_table.get(pid2)
        
        if not process1 or not process2:
            return False
            
        # Create bidirectional link
        process1.linked_processes.add(pid2)
        process2.linked_processes.add(pid1)
        
        logger.debug(f"Linked processes {pid1} <-> {pid2}")
        return True
        
    async def unlink_processes(self, pid1: str, pid2: str) -> bool:
        """Remove link between two processes"""
        
        process1 = self.spam_runtime.scheduler.global_state.process_table.get(pid1)
        process2 = self.spam_runtime.scheduler.global_state.process_table.get(pid2)
        
        if process1:
            process1.linked_processes.discard(pid2)
        if process2:
            process2.linked_processes.discard(pid1)
            
        logger.debug(f"Unlinked processes {pid1} <-> {pid2}")
        return True
        
    async def monitor_process(self, monitor_pid: str, target_pid: str) -> bool:
        """Monitor a process for termination"""
        
        target_process = self.spam_runtime.scheduler.global_state.process_table.get(target_pid)
        if not target_process:
            return False
            
        target_process.monitoring_processes.add(monitor_pid)
        logger.debug(f"Process {monitor_pid} now monitoring {target_pid}")
        return True
        
    async def demonitor_process(self, monitor_pid: str, target_pid: str) -> bool:
        """Stop monitoring a process"""
        
        target_process = self.spam_runtime.scheduler.global_state.process_table.get(target_pid)
        if target_process:
            target_process.monitoring_processes.discard(monitor_pid)
            logger.debug(f"Process {monitor_pid} stopped monitoring {target_pid}")
            return True
        return False
        
    # Registry operations
    
    async def register_name(self, name: str, pid: str) -> bool:
        """Register a name for a process"""
        
        with self.spam_runtime.scheduler.global_state._lock:
            if name in self.spam_runtime.scheduler.global_state.name_registry:
                return False  # Name already taken
                
            process = self.spam_runtime.scheduler.global_state.process_table.get(pid)
            if not process:
                return False  # Process doesn't exist
                
            # Update both registry and process
            self.spam_runtime.scheduler.global_state.name_registry[name] = pid
            process.name = name
            
        logger.debug(f"Registered name {name} for process {pid}")
        return True
        
    async def unregister_name(self, name: str) -> bool:
        """Unregister a name"""
        
        with self.spam_runtime.scheduler.global_state._lock:
            pid = self.spam_runtime.scheduler.global_state.name_registry.pop(name, None)
            if pid:
                process = self.spam_runtime.scheduler.global_state.process_table.get(pid)
                if process and process.name == name:
                    process.name = None
                    
        logger.debug(f"Unregistered name {name}")
        return pid is not None
        
    def whereis_name(self, name: str) -> Optional[str]:
        """Look up PID by registered name"""
        
        with self.spam_runtime.scheduler.global_state._lock:
            return self.spam_runtime.scheduler.global_state.name_registry.get(name)
            
    def registered_names(self) -> List[str]:
        """Get all registered names"""
        
        with self.spam_runtime.scheduler.global_state._lock:
            return list(self.spam_runtime.scheduler.global_state.name_registry.keys())
            
    # State and recovery operations
    
    async def save_process_state(self, pid: str, state_data: Any) -> bool:
        """Save process state for recovery"""
        
        process = self.spam_runtime.scheduler.global_state.process_table.get(pid)
        if not process:
            return False
            
        # This would integrate with the state backup system
        process.internal_state = state_data
        process.last_state_backup = time.time()
        
        return True
        
    async def recover_process_state(self, pid: str) -> Optional[Any]:
        """Recover saved process state"""
        
        process = self.spam_runtime.scheduler.global_state.process_table.get(pid)
        if not process:
            return None
            
        return process.internal_state
        
    # Statistics and monitoring
    
    def get_backend_statistics(self) -> Dict[str, Any]:
        """Get backend-specific statistics"""
        
        runtime_stats = self.spam_runtime.get_statistics()
        
        # Add backend-specific metrics
        backend_stats = {
            'backend_type': 'SPAM',
            'total_spawns': {
                'gen_servers': len([p for p in self.spam_runtime.list_processes() 
                                  if p['type'] == 'gen_server']),
                'supervisors': len([p for p in self.spam_runtime.list_processes() 
                                  if p['type'] == 'supervisor']),
                'workers': len([p for p in self.spam_runtime.list_processes() 
                              if p['type'] == 'worker'])
            },
            'registry_size': len(self.spam_runtime.scheduler.global_state.name_registry)
        }
        
        runtime_stats['backend_stats'] = backend_stats
        return runtime_stats
        
    # Utility methods for otpylib integration
    
    def is_process_alive(self, pid: str) -> bool:
        """Check if a process is alive"""
        
        process = self.spam_runtime.scheduler.global_state.process_table.get(pid)
        return process is not None and process.state != ProcessState.TERMINATED
        
    def get_process_type(self, pid: str) -> Optional[ProcessType]:
        """Get the type of a process"""
        
        process = self.spam_runtime.scheduler.global_state.process_table.get(pid)
        return process.process_type if process else None
        
    async def yield_process(self, pid: str) -> bool:
        """Request that a process yield control"""
        
        # This would signal the process to yield at the next opportunity
        # For now, this is handled automatically by the time slicing
        return True
        
    async def hibernate_process(self, pid: str) -> bool:
        """Put a process into hibernation (minimize memory)"""
        
        # This would be a memory optimization feature
        # For now, just mark the process as hibernating
        process = self.spam_runtime.scheduler.global_state.process_table.get(pid)
        if process:
            # Could add hibernation state to ProcessState enum
            logger.debug(f"Process {pid} hibernation requested (not implemented)")
            return True
        return False
        
    async def wake_process(self, pid: str) -> bool:
        """Wake a hibernating process"""
        
        process = self.spam_runtime.scheduler.global_state.process_table.get(pid)
        if process:
            logger.debug(f"Process {pid} wake requested (not implemented)")
            return True
        return False


# Convenience functions for common operations

async def get_current_process_pid() -> Optional[str]:
    """Get the PID of the currently executing process"""
    
    # This would require thread-local storage to track current process
    # For now, return None as placeholder
    return None
    
def is_spam_available() -> bool:
    """Check if SPAM runtime is available and active"""
    return SPAMRuntime.is_available()
    
def get_spam_backend() -> Optional[SPAMBackend]:
    """Get the current SPAM backend if available"""
    
    runtime = SPAMRuntime.get_global_instance()
    if runtime and runtime.initialized:
        # This assumes the backend is stored somewhere accessible
        # In practice, you'd need to track this in the runtime
        return SPAMBackend(runtime)
    return None
