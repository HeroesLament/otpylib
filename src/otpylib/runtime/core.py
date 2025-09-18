"""
Runtime Core

Defines the abstract RuntimeBackend interface that all runtime implementations
must implement. Provides the contract for spawning, managing, and communicating
with OTP processes in a backend-agnostic way.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
from types import ModuleType

from .data import (
    ProcessType, ProcessInfo, RuntimeStatistics, SimpleChildSpec,
    ProcessCharacteristics, RuntimeError, ProcessNotFoundError,
    NameAlreadyRegisteredError, ProcessSpawnError
)


class RuntimeBackend(ABC):
    """
    Abstract base class for runtime backends.
    
    Defines the interface that all runtime implementations (AnyIO, SPAM, etc.)
    must provide. This allows transparent switching between different runtime
    backends while maintaining the same API for user code.
    """
    
    @abstractmethod
    async def spawn_gen_server(
        self,
        module: ModuleType,
        init_arg: Any = None,
        name: Optional[str] = None,
        supervisor_context: Optional[str] = None,
        recovered_state: Optional[Dict[str, Any]] = None,
        characteristics: Optional[ProcessCharacteristics] = None
    ) -> str:
        """
        Spawn a gen_server process.
        
        :param module: Module containing gen_server callbacks (init, handle_call, etc.)
        :param init_arg: Argument passed to the init callback
        :param name: Optional name to register the process under
        :param supervisor_context: Internal supervisor context for state recovery
        :param recovered_state: Pre-existing state for process recovery
        :param characteristics: Performance hints for backend optimization
        :returns: Process ID of the spawned gen_server
        :raises ProcessSpawnError: If spawning fails
        :raises NameAlreadyRegisteredError: If name is already taken
        """
        pass
    
    @abstractmethod
    async def spawn_supervisor(
        self,
        child_specs: List[SimpleChildSpec],
        supervisor_options: Dict[str, Any],
        name: Optional[str] = None,
        supervisor_context: Optional[str] = None,
        characteristics: Optional[ProcessCharacteristics] = None
    ) -> str:
        """
        Spawn a supervisor process.
        
        :param child_specs: List of child process specifications
        :param supervisor_options: Supervisor configuration (restart strategy, etc.)
        :param name: Optional name to register the supervisor under
        :param supervisor_context: Parent supervisor context
        :param characteristics: Performance hints for backend optimization
        :returns: Process ID of the spawned supervisor
        :raises ProcessSpawnError: If spawning fails
        :raises NameAlreadyRegisteredError: If name is already taken
        """
        pass
    
    @abstractmethod
    async def spawn_worker(
        self,
        worker_func: Any,
        args: List[Any],
        name: Optional[str] = None,
        supervisor_context: Optional[str] = None,
        characteristics: Optional[ProcessCharacteristics] = None
    ) -> str:
        """
        Spawn a worker process.
        
        :param worker_func: Function to execute as worker
        :param args: Arguments to pass to worker function
        :param name: Optional name to register the worker under
        :param supervisor_context: Supervisor context for restart management
        :param characteristics: Performance hints for backend optimization
        :returns: Process ID of the spawned worker
        :raises ProcessSpawnError: If spawning fails
        :raises NameAlreadyRegisteredError: If name is already taken
        """
        pass
    
    @abstractmethod
    async def call_process(
        self,
        target: Union[str, Any],
        message: Any,
        timeout: Optional[float] = None
    ) -> Any:
        """
        Make a synchronous call to a process.
        
        :param target: Process name, PID, or mailbox ID to call
        :param message: Message to send
        :param timeout: Optional timeout for the call
        :returns: Response from the target process
        :raises ProcessNotFoundError: If target process doesn't exist
        :raises TimeoutError: If call times out
        """
        pass
    
    @abstractmethod
    async def cast_process(
        self,
        target: Union[str, Any],
        message: Any
    ) -> bool:
        """
        Send an asynchronous message to a process.
        
        :param target: Process name, PID, or mailbox ID to send to
        :param message: Message to send
        :returns: True if message was sent successfully
        :raises ProcessNotFoundError: If target process doesn't exist
        """
        pass
    
    @abstractmethod
    async def send_message(
        self,
        target: Union[str, Any],
        message: Any
    ) -> bool:
        """
        Send a raw message directly to a process mailbox.
        
        :param target: Process name, PID, or mailbox ID to send to
        :param message: Message to send
        :returns: True if message was sent successfully
        :raises ProcessNotFoundError: If target process doesn't exist
        """
        pass
    
    @abstractmethod
    async def terminate_process(
        self,
        pid: str,
        reason: str = "normal"
    ) -> bool:
        """
        Terminate a specific process.
        
        :param pid: Process ID to terminate
        :param reason: Reason for termination
        :returns: True if process was terminated successfully
        :raises ProcessNotFoundError: If process doesn't exist
        """
        pass
    
    @abstractmethod
    def is_process_alive(self, pid: str) -> bool:
        """
        Check if a process is currently alive.
        
        :param pid: Process ID to check
        :returns: True if process is alive
        """
        pass
    
    @abstractmethod
    async def register_name(self, name: str, pid: str) -> bool:
        """
        Register a name for a process.
        
        :param name: Name to register
        :param pid: Process ID to associate with the name
        :returns: True if registration succeeded
        :raises NameAlreadyRegisteredError: If name is already registered
        :raises ProcessNotFoundError: If PID doesn't exist
        """
        pass
    
    @abstractmethod
    async def unregister_name(self, name: str) -> bool:
        """
        Unregister a name.
        
        :param name: Name to unregister
        :returns: True if unregistration succeeded
        """
        pass
    
    @abstractmethod
    def whereis_name(self, name: str) -> Optional[str]:
        """
        Look up a process ID by registered name.
        
        :param name: Name to look up
        :returns: Process ID if found, None otherwise
        """
        pass
    
    @abstractmethod
    def get_process_info(self, pid: str) -> Optional[ProcessInfo]:
        """
        Get detailed information about a process.
        
        :param pid: Process ID to get info for
        :returns: ProcessInfo if found, None otherwise
        """
        pass
    
    @abstractmethod
    def list_processes(
        self,
        process_type: Optional[ProcessType] = None
    ) -> List[ProcessInfo]:
        """
        List all processes, optionally filtered by type.
        
        :param process_type: Optional filter by process type
        :returns: List of ProcessInfo objects
        """
        pass
    
    @abstractmethod
    def get_statistics(self) -> RuntimeStatistics:
        """
        Get runtime performance statistics.
        
        :returns: RuntimeStatistics object with performance metrics
        """
        pass


class BaseRuntimeBackend(RuntimeBackend):
    """
    Base implementation providing common functionality for runtime backends.
    
    Provides shared utilities and validation that concrete backends can use.
    Concrete backends should inherit from this and implement the abstract methods.
    """
    
    def __init__(self):
        self._startup_time = 0.0
        
    def _validate_process_name(self, name: str) -> None:
        """Validate a process name."""
        if not name:
            raise ValueError("Process name cannot be empty")
        if not isinstance(name, str):
            raise TypeError("Process name must be a string")
        if len(name) > 255:
            raise ValueError("Process name too long (max 255 characters)")
        if name.startswith('_'):
            raise ValueError("Process name cannot start with underscore")
    
    def _validate_pid(self, pid: str) -> None:
        """Validate a process ID."""
        if not pid:
            raise ValueError("Process ID cannot be empty")
        if not isinstance(pid, str):
            raise TypeError("Process ID must be a string")
    
    def _normalize_target(self, target: Union[str, Any]) -> str:
        """
        Normalize a target (name, PID, or mailbox ID) to a consistent format.
        
        :param target: Target identifier
        :returns: Normalized target string
        """
        if isinstance(target, str):
            return target
        # Handle mailbox IDs or other target types - convert to string
        return str(target)
    
    def _create_process_info(
        self,
        pid: str,
        process_type: ProcessType,
        name: Optional[str] = None,
        **kwargs
    ) -> ProcessInfo:
        """Create a ProcessInfo object with common defaults."""
        import time
        return ProcessInfo(
            pid=pid,
            process_type=process_type,
            name=name,
            state=kwargs.get('state', None),
            created_at=time.time(),
            message_queue_length=kwargs.get('message_queue_length', 0),
            restart_count=kwargs.get('restart_count', 0),
            last_active=kwargs.get('last_active'),
            characteristics=kwargs.get('characteristics'),
            supervisor_pid=kwargs.get('supervisor_pid'),
            supervisor_context=kwargs.get('supervisor_context')
        )
    
    def get_uptime(self) -> float:
        """Get runtime uptime in seconds."""
        import time
        return time.time() - self._startup_time if self._startup_time else 0.0


# Utility functions for runtime backends

def validate_module_callbacks(module: ModuleType, required_callbacks: List[str]) -> None:
    """
    Validate that a module has required callback functions.
    
    :param module: Module to validate
    :param required_callbacks: List of required callback names
    :raises ValueError: If required callbacks are missing
    """
    missing = []
    for callback in required_callbacks:
        if not hasattr(module, callback):
            missing.append(callback)
    
    if missing:
        raise ValueError(f"Module missing required callbacks: {', '.join(missing)}")


def validate_gen_server_module(module: ModuleType) -> None:
    """
    Validate that a module is suitable for use as a gen_server.
    
    :param module: Module to validate
    :raises ValueError: If module is invalid
    """
    # Only 'init' is strictly required - others have defaults in gen_server
    validate_module_callbacks(module, ['init'])
    
    # Validate callback signatures if present
    if hasattr(module, 'handle_call'):
        # Could add signature validation here if needed
        pass


def validate_supervisor_options(options: Dict[str, Any]) -> None:
    """
    Validate supervisor options.
    
    :param options: Options dictionary to validate
    :raises ValueError: If options are invalid
    """
    # Add validation for supervisor options
    # For now, just ensure it's a dict
    if not isinstance(options, dict):
        raise TypeError("Supervisor options must be a dictionary")
