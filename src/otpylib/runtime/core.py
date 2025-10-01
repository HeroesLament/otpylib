"""
Runtime Backend Core

Abstract base class for runtime backends with full process management,
monitoring, and linking capabilities.
"""

from abc import ABC, abstractmethod
from types import ModuleType
from typing import Any, Dict, List, Optional, Union, Set
import time
import logging

# Import data structures
from otpylib.runtime.data import (
    ProcessInfo, RuntimeStatistics, SimpleChildSpec,
    SupervisorOptions, ProcessCharacteristics, MonitorRef,
    ProcessLink
)

# Import atoms from centralized definitions
from otpylib.runtime.atoms import (
    GEN_SERVER, SUPERVISOR, WORKER,
    RUNNING, TERMINATED,
    NORMAL
)

logger = logging.getLogger(__name__)


def validate_gen_server_module(module: ModuleType) -> None:
    """Validate that a module has required gen_server callbacks."""
    required_callbacks = ['init', 'handle_call']
    
    for callback in required_callbacks:
        if not hasattr(module, callback):
            raise ValueError(f"Module {module.__name__} missing required callback: {callback}")


class RuntimeBackend(ABC):
    """
    Abstract base class for runtime backend implementations.
    
    A runtime backend manages process lifecycle, message passing, and
    fault tolerance primitives (monitors, links) for OTP patterns.
    """
    
    def __init__(self):
        self._startup_time = time.time()
    
    # =========================================================================
    # Process Lifecycle Management
    # =========================================================================
    
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
        Spawn a new gen_server process.
        
        :param module: Module containing gen_server callbacks
        :param init_arg: Argument passed to init callback
        :param name: Optional registered name for the process
        :param supervisor_context: PID of supervisor if supervised
        :param recovered_state: State to restore after crash
        :param characteristics: Hints for backend optimization
        :returns: PID of the spawned process
        """
        pass
    
    @abstractmethod
    async def spawn_supervisor(
        self,
        child_specs: List[SimpleChildSpec],
        supervisor_options: SupervisorOptions,
        name: Optional[str] = None,
        supervisor_context: Optional[str] = None,
        characteristics: Optional[ProcessCharacteristics] = None
    ) -> str:
        """
        Spawn a new supervisor process.
        
        :param child_specs: List of child specifications
        :param supervisor_options: Supervisor configuration
        :param name: Optional registered name
        :param supervisor_context: Parent supervisor PID if nested
        :param characteristics: Backend optimization hints
        :returns: PID of the spawned supervisor
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
        Spawn a worker process (plain async or sync function).
        
        :param worker_func: Function to run as a process
        :param args: Arguments to pass to the function
        :param name: Optional registered name
        :param supervisor_context: Supervisor PID if supervised
        :param characteristics: Backend optimization hints
        :returns: PID of the spawned worker
        """
        pass
    
    @abstractmethod
    async def terminate_process(
        self,
        pid: str,
        reason: Any = NORMAL
    ) -> bool:
        """
        Terminate a process with the given reason.
        
        :param pid: Process ID to terminate
        :param reason: Exit reason (atom or exception)
        :returns: True if process was terminated, False if not found
        """
        pass
    
    # =========================================================================
    # Process Monitoring & Linking
    # =========================================================================
    
    @abstractmethod
    async def monitor_process(
        self,
        watcher_pid: str,
        target_pid: str
    ) -> str:
        """
        Create a monitor from watcher to target process.
        
        When target dies, watcher receives a DOWN message.
        
        :param watcher_pid: Process that will receive DOWN message
        :param target_pid: Process being monitored
        :returns: Monitor reference ID
        """
        pass
    
    @abstractmethod
    async def demonitor(
        self,
        monitor_ref: str,
        flush: bool = False
    ) -> bool:
        """
        Remove a monitor.
        
        :param monitor_ref: Monitor reference to remove
        :param flush: If True, remove any pending DOWN messages
        :returns: True if monitor was removed, False if not found
        """
        pass
    
    @abstractmethod
    async def link_processes(
        self,
        pid1: str,
        pid2: str
    ) -> bool:
        """
        Create bidirectional link between processes.
        
        If one dies, the other receives exit signal (or dies if not trapping).
        
        :param pid1: First process ID
        :param pid2: Second process ID
        :returns: True if link created, False if processes don't exist
        """
        pass
    
    @abstractmethod
    async def unlink_processes(
        self,
        pid1: str,
        pid2: str
    ) -> bool:
        """
        Remove link between processes.
        
        :param pid1: First process ID
        :param pid2: Second process ID
        :returns: True if link removed, False if not found
        """
        pass
    
    @abstractmethod
    async def trap_exits(
        self,
        pid: str,
        enabled: bool
    ) -> bool:
        """
        Enable/disable exit signal trapping for a process.
        
        When enabled, exit signals become EXIT messages instead of killing.
        
        :param pid: Process ID
        :param enabled: True to trap exits, False for normal behavior
        :returns: True if setting changed, False if process not found
        """
        pass
    
    @abstractmethod
    def get_process_links(self, pid: str) -> Set[str]:
        """
        Get all processes linked to the given process.
        
        :param pid: Process ID
        :returns: Set of linked process PIDs
        """
        pass
    
    @abstractmethod
    def get_process_monitors(self, pid: str) -> Dict[str, str]:
        """
        Get all monitors for a process.
        
        :param pid: Process ID
        :returns: Dict of monitor_ref -> target_pid
        """
        pass
    
    # =========================================================================
    # Message Passing
    # =========================================================================
    
    @abstractmethod
    async def call_process(
        self,
        target: Union[str, Any],
        message: Any,
        timeout: Optional[float] = None
    ) -> Any:
        """
        Make a synchronous call to a process (gen_server:call).
        
        :param target: Process PID or registered name
        :param message: Message to send
        :param timeout: Optional timeout in seconds
        :returns: Response from the process
        """
        pass
    
    @abstractmethod
    async def cast_process(
        self,
        target: Union[str, Any],
        message: Any
    ) -> bool:
        """
        Send an asynchronous cast to a process (gen_server:cast).
        
        :param target: Process PID or registered name
        :param message: Message to send
        :returns: True if sent successfully
        """
        pass
    
    @abstractmethod
    async def send_message(
        self,
        target: Union[str, Any],
        message: Any
    ) -> bool:
        """
        Send a raw message to a process mailbox.
        
        :param target: Process PID or registered name
        :param message: Message to send
        :returns: True if sent successfully
        """
        pass
    
    # =========================================================================
    # Process Registry
    # =========================================================================
    
    @abstractmethod
    async def register_name(
        self,
        name: str,
        pid: str
    ) -> bool:
        """
        Register a name for a process.
        
        :param name: Name to register
        :param pid: Process ID
        :returns: True if registered, False if name already taken
        """
        pass
    
    @abstractmethod
    async def unregister_name(
        self,
        name: str
    ) -> bool:
        """
        Unregister a name.
        
        :param name: Name to unregister
        :returns: True if unregistered, False if not found
        """
        pass
    
    @abstractmethod
    def whereis_name(
        self,
        name: str
    ) -> Optional[str]:
        """
        Look up a PID by registered name.
        
        :param name: Registered name
        :returns: PID if found, None otherwise
        """
        pass
    
    @abstractmethod
    def registered_names(self) -> List[str]:
        """
        Get all registered names.
        
        :returns: List of all registered names
        """
        pass
    
    # =========================================================================
    # Process Inspection
    # =========================================================================
    
    @abstractmethod
    def is_process_alive(
        self,
        pid: str
    ) -> bool:
        """
        Check if a process is alive.
        
        :param pid: Process ID
        :returns: True if alive, False otherwise
        """
        pass
    
    @abstractmethod
    def get_process_info(
        self,
        pid: str
    ) -> Optional[ProcessInfo]:
        """
        Get detailed information about a process.
        
        :param pid: Process ID
        :returns: ProcessInfo if found, None otherwise
        """
        pass
    
    @abstractmethod
    def list_processes(
        self,
        process_type: Optional[Any] = None
    ) -> List[ProcessInfo]:
        """
        List all processes, optionally filtered by type.
        
        :param process_type: Optional atom to filter by (e.g., PROCESS_GEN_SERVER)
        :returns: List of process information
        """
        pass
    
    @abstractmethod
    def get_statistics(self) -> RuntimeStatistics:
        """
        Get runtime statistics and metrics.
        
        :returns: RuntimeStatistics object with current metrics
        """
        pass
    
    # =========================================================================
    # Mailbox Integration
    # =========================================================================
    
    @abstractmethod
    async def associate_mailbox(
        self,
        pid: str,
        mailbox_id: str
    ) -> bool:
        """
        Associate a mailbox with a process for automatic cleanup.
        
        When the process dies, its mailbox will be automatically destroyed.
        
        :param pid: Process ID
        :param mailbox_id: Mailbox ID to associate
        :returns: True if associated, False if process not found
        """
        pass
    
    @abstractmethod
    async def dissociate_mailbox(
        self,
        pid: str
    ) -> Optional[str]:
        """
        Remove mailbox association from a process.
        
        :param pid: Process ID
        :returns: Mailbox ID that was dissociated, or None
        """
        pass
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def get_uptime(self) -> float:
        """Get backend uptime in seconds."""
        return time.time() - self._startup_time
    
    def _validate_process_name(self, name: str) -> None:
        """Validate a process name is valid."""
        if not name or not isinstance(name, str):
            raise ValueError("Process name must be a non-empty string")
        if len(name) > 255:
            raise ValueError("Process name too long (max 255 chars)")
    
    def _validate_pid(self, pid: str) -> None:
        """Validate a PID format."""
        if not pid or not isinstance(pid, str):
            raise ValueError("PID must be a non-empty string")
    
    def _normalize_target(self, target: Union[str, Any]) -> str:
        """Normalize a target to a string (PID or name)."""
        if hasattr(target, '__name__'):
            return target.__name__
        return str(target)


class BaseRuntimeBackend(RuntimeBackend):
    """
    Base implementation with common functionality.
    
    Concrete backends can inherit from this to get standard implementations
    of some methods while focusing on their unique aspects.
    """
    
    def __init__(self):
        super().__init__()
        self._monitors: Dict[str, MonitorRef] = {}  # ref -> MonitorRef
        self._links: Set[ProcessLink] = set()
    
    def _create_process_info(
        self,
        pid: str,
        process_type: Any,
        name: Optional[str] = None,
        state: Any = RUNNING,
        characteristics: Optional[ProcessCharacteristics] = None,
        supervisor_context: Optional[str] = None
    ) -> ProcessInfo:
        """Helper to create ProcessInfo with defaults."""
        return ProcessInfo(
            pid=pid,
            process_type=process_type,
            name=name,
            state=state,
            created_at=time.time(),
            characteristics=characteristics,
            supervisor_pid=supervisor_context
        )
