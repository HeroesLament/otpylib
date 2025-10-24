"""
Runtime Protocols

Protocol definitions and base types for the runtime system.
Uses Protocol for type safety and clear interface contracts.
"""

from typing import Protocol, runtime_checkable, Any, Dict, List, Optional, Union, Set, Callable
from abc import ABC, abstractmethod
from dataclasses import dataclass

from otpylib.runtime.data import (
    ProcessInfo, RuntimeStatistics, ProcessCharacteristics
)
from otpylib import atom


# ============================================================================
# PID (Process Identifier)
# ============================================================================

@dataclass(frozen=True, eq=True)
class Pid:
    """
    Erlang Process Identifier
    
    A PID uniquely identifies a process in the distributed system.
    PIDs are immutable and hashable, suitable for use as dictionary keys.
    
    Backend-agnostic data structure - no async/await, no locks.
    
    Attributes:
        node: The node atom where the process lives
        id: Process number (0 to 2^32-1)
        serial: Reuse counter for ID wraparound (0 to 2^32-1)
        creation: Node incarnation number (0 to 2^32-1)
    
    Examples:
        >>> node = atom.ensure('otpylib@127.0.0.1')
        >>> pid = Pid(node, 101, 0, 1)
        >>> print(pid)
        #Pid<otpylib@127.0.0.1.101.0>
    """
    
    node: atom.Atom
    id: int
    serial: int
    creation: int
    
    def __post_init__(self):
        """Validate PID fields"""
        if not isinstance(self.node, atom.Atom):
            raise TypeError(f"node must be an Atom, got {type(self.node)}")
        
        if not (0 <= self.id <= 0xFFFFFFFF):
            raise ValueError(f"id must be 0-4294967295, got {self.id}")
        
        if not (0 <= self.serial <= 0xFFFFFFFF):
            raise ValueError(f"serial must be 0-4294967295, got {self.serial}")
        
        if not (0 <= self.creation <= 0xFFFFFFFF):
            raise ValueError(f"creation must be 0-4294967295, got {self.creation}")
    
    def __str__(self) -> str:
        """Display format similar to Erlang's #Pid<...>"""
        return f"#Pid<{self.node.name}.{self.id}.{self.serial}>"
    
    def __repr__(self) -> str:
        """Detailed representation for debugging"""
        return f"Pid({self.node.name!r}, {self.id}, {self.serial}, {self.creation})"
    
    def __hash__(self) -> int:
        """Hash for use in sets and as dict keys"""
        return hash((self.node, self.id, self.serial, self.creation))
    
    def is_local(self, local_node: atom.Atom) -> bool:
        """Check if this PID is on the local node"""
        return self.node == local_node
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'node': self.node.name,
            'id': self.id,
            'serial': self.serial,
            'creation': self.creation
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Pid':
        """Create PID from dictionary"""
        return cls(
            node=atom.ensure(data['node']),
            id=data['id'],
            serial=data['serial'],
            creation=data['creation']
        )


# ============================================================================
# Process Protocol
# ============================================================================

@runtime_checkable
class Process(Protocol):
    """Protocol for a runtime-managed process."""
    
    @property
    def pid(self) -> Pid:
        """Get the process identifier."""
        ...
    
    @property
    def info(self) -> ProcessInfo:
        """Get process information."""
        ...
    
    async def send(self, message: Any) -> None:
        """Send a message to this process."""
        ...
    
    async def call(self, message: Any, timeout: Optional[float] = None) -> Any:
        """Make a synchronous call to this process."""
        ...
    
    def is_alive(self) -> bool:
        """Check if the process is alive."""
        ...


# ============================================================================
# Runtime Backend Protocol
# ============================================================================

@runtime_checkable
class RuntimeBackend(Protocol):
    """
    Protocol for runtime backend implementations.
    
    A runtime backend manages process lifecycle, message passing, and
    fault tolerance primitives (monitors, links) for OTP patterns.
    """
    
    # =========================================================================
    # Core Process Management
    # =========================================================================
    
    async def spawn(
        self,
        func: Callable,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
        mailbox: bool = True,
        trap_exits: bool = False,
        characteristics: Optional[ProcessCharacteristics] = None
    ) -> Pid:
        """
        Spawn a new process.
        
        This is the unified spawn interface - whether it's a gen_server,
        supervisor, or simple worker is determined by what func does.
        
        :param func: The function to run as a process
        :param args: Positional arguments for the function
        :param kwargs: Keyword arguments for the function
        :param name: Optional registered name for the process
        :param mailbox: Whether to create a mailbox for this process
        :param trap_exits: Whether to trap exit signals as messages
        :param characteristics: Hints for backend optimization
        :returns: PID of the spawned process
        """
        ...
    
    async def spawn_link(
        self,
        func: Callable,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
        mailbox: bool = True,
        characteristics: Optional[ProcessCharacteristics] = None
    ) -> Pid:
        """
        Spawn a process and link it to the current process.
        
        Equivalent to spawn() followed by link(), but atomic.
        """
        ...
    
    async def spawn_monitor(
        self,
        func: Callable,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
        mailbox: bool = True,
        characteristics: Optional[ProcessCharacteristics] = None
    ) -> tuple[Pid, str]:
        """
        Spawn a process and monitor it from the current process.
        
        Equivalent to spawn() followed by monitor(), but atomic.
        
        :returns: Tuple of (PID, monitor_ref)
        """
        ...
    
    async def exit(
        self,
        pid: Union[Pid, str],  # Accept both Pid and registered name
        reason: Any
    ) -> None:
        """
        Send an exit signal to a process.
        
        :param pid: Process (Pid) or registered name (str) to send exit signal to
        :param reason: Exit reason (atom or exception)
        """
        ...
    
    def self(self) -> Optional[Pid]:  # Changed from str to Pid
        """
        Get the PID of the current process.
        
        :returns: Current process PID, or None if not in a process context
        """
        ...
    
    # =========================================================================
    # Process Relationships
    # =========================================================================
    
    async def link(self, pid: Union[Pid, str]) -> None:  # Accept both
        """
        Link the current process to another process.
        
        Creates bidirectional link - if either dies, the other is notified.
        
        :param pid: Process (Pid) or registered name (str) to link to
        """
        ...
    
    async def unlink(self, pid: Union[Pid, str]) -> None:  # Accept both
        """
        Remove link between current process and another process.
        
        :param pid: Process (Pid) or registered name (str) to unlink from
        """
        ...
    
    async def monitor(self, pid: Union[Pid, str]) -> str:  # Accept both
        """
        Monitor another process from the current process.
        
        When target dies, current process receives a DOWN message.
        
        :param pid: Process (Pid) or registered name (str) to monitor
        :returns: Monitor reference
        """
        ...
    
    async def demonitor(
        self,
        ref: str,
        flush: bool = False
    ) -> None:
        """
        Remove a monitor.
        
        :param ref: Monitor reference to remove
        :param flush: If True, remove any pending DOWN messages
        """
        ...
    
    # =========================================================================
    # Message Passing
    # =========================================================================
    
    async def send(
        self,
        target: Union[Pid, str, Process],  # Accept Pid, registered name, or Process
        message: Any
    ) -> None:
        """
        Send a message to a process.
        
        :param pid: Process ID (Pid), registered name (str), or Process object
        :param message: Message to send
        """
        ...
    
    async def receive(
        self,
        timeout: Optional[float] = None,
        match: Optional[Callable[[Any], bool]] = None
    ) -> Any:
        """
        Receive a message in the current process.
        
        :param timeout: Optional timeout in seconds
        :param match: Optional function to match specific messages
        :returns: The received message
        """
        ...
    
    # =========================================================================
    # Timing Operations
    # =========================================================================
    
    async def sleep(self, seconds: float) -> None:
        """
        Suspend the current process for the specified duration.
        
        Uses timing wheel internally for consistency with send_after().
        Backend implementations should use their native timing mechanism
        (e.g., asyncio.Event for AsyncIOBackend).
        
        BEAM equivalent: timer:sleep(Milliseconds)
        
        :param seconds: Duration to sleep in seconds
        """
        ...
    
    async def send_after(
        self,
        delay: float,
        target: Union[Pid, str],  # Accept both
        message: Any
    ) -> str:
        """
        Send a message to a process after a delay.
        
        BEAM equivalent: erlang:send_after(Time, Dest, Msg)
        
        :param delay: Delay in seconds before sending message
        :param target: Process PID or registered name
        :param message: Message to send
        :returns: Timer reference for cancellation
        """
        ...
    
    async def cancel_timer(self, ref: str) -> bool:
        """
        Cancel a timer by reference.
        
        BEAM equivalent: erlang:cancel_timer(TimerRef)
        
        :param ref: Timer reference returned by send_after()
        :returns: True if timer was cancelled, False if already fired or not found
        """
        ...
    
    async def read_timer(self, ref: str) -> Optional[float]:
        """
        Read remaining time on a timer in seconds.
        
        BEAM equivalent: erlang:read_timer(TimerRef)
        
        :param ref: Timer reference
        :returns: Remaining time in seconds, or None if timer not found
        """
        ...
    
    # =========================================================================
    # Process Registry
    # =========================================================================
    
    async def register(
        self,
        name: str,
        pid: Optional[Pid] = None
    ) -> None:
        """
        Register a name for a process.
        
        :param name: Name to register
        :param pid: Process ID (defaults to current process)
        """
        ...
    
    async def unregister(self, name: str) -> None:
        """
        Unregister a name.
        
        :param name: Name to unregister
        """
        ...
    
    def whereis(self, name: str) -> Optional[Pid]:
        """
        Look up a PID by registered name.
        
        :param name: Registered name
        :returns: PID if found, None otherwise
        """
        ...
    
    def whereis_name(self, pid: Pid) -> Optional[str]:
        """
        Look up a registered name by PID (reverse lookup).
    
        :param pid: Process ID
        :returns: Registered name if found, None otherwise
        """
        ...
    
    def registered(self) -> List[str]:
        """
        Get all registered names.
        
        :returns: List of all registered names
        """
        ...
    
    # =========================================================================
    # Process Inspection
    # =========================================================================
    
    def is_alive(self, pid: Union[Pid, str]) -> bool:  # Accept both
        """
        Check if a process is alive.
        
        :param pid: Process ID (Pid) or registered name (str)
        :returns: True if alive, False otherwise
        """
        ...
    
    def process_info(
        self,
        pid: Optional[Pid] = None
    ) -> Optional[ProcessInfo]:
        """
        Get information about a process.
        
        :param pid: Process ID (defaults to current process)
        :returns: ProcessInfo if found, None otherwise
        """
        ...
    
    def processes(self) -> List[Pid]:
        """
        Get all process IDs.
        
        :returns: List of all PIDs
        """
        ...
    
    # =========================================================================
    # Runtime Management
    # =========================================================================
    
    async def initialize(self) -> None:
        """Initialize the backend."""
        ...
    
    async def shutdown(self) -> None:
        """Shutdown the backend and clean up resources."""
        ...
    
    async def reset(self) -> None:
        """
        Reset the backend state (processes, registries, monitors, stats).
        Intended for test isolation, not production use.
        """
        ...
    
    def statistics(self) -> RuntimeStatistics:
        """Get runtime statistics and metrics."""
        ...


# ============================================================================
# Exceptions
# ============================================================================

class RuntimeError(Exception):
    """Base exception for runtime errors."""
    pass


class ProcessNotFoundError(RuntimeError):
    """Process does not exist."""
    pass


class NameAlreadyRegisteredError(RuntimeError):
    """Name is already registered to another process."""
    pass


class NotInProcessError(RuntimeError):
    """Operation requires being in a process context."""
    pass