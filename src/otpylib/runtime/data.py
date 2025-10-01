"""
Runtime Data Types

Common data structures and type definitions used across runtime backends.
Uses atoms from the centralized atoms module.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, Callable, Awaitable, Set
import time

# Import atom type
from otpylib import atom

# Import atoms from centralized definitions
from otpylib.runtime.atoms import (
    # Process types
    GEN_SERVER, SUPERVISOR, DYNAMIC_SUPERVISOR, WORKER,
    
    # Process states
    STARTING, RUNNING, WAITING, SUSPENDED, TERMINATING, TERMINATED,
    
    # Exit reasons
    NORMAL, SHUTDOWN, KILLED, ABNORMAL,
    
    # Messages
    DOWN, EXIT, PROCESS,
    
    # Restart strategies
    ONE_FOR_ONE, ONE_FOR_ALL, REST_FOR_ONE,
    
    # Restart types
    PERMANENT, TEMPORARY, TRANSIENT
)


@dataclass
class MonitorRef:
    """Reference to a monitor relationship."""
    ref_id: str  # Unique monitor reference
    watcher_pid: str  # Who's watching
    target_pid: str  # Who's being watched
    created_at: float = field(default_factory=time.time)


@dataclass
class ProcessLink:
    """Bidirectional link between processes."""
    pid1: str
    pid2: str
    created_at: float = field(default_factory=time.time)


@dataclass
class ProcessInfo:
    """Information about a runtime-managed process."""
    pid: str
    process_type: atom.Atom  # Using Atom type
    name: Optional[str]
    state: atom.Atom  # Using Atom type
    created_at: float
    message_queue_length: int = 0
    restart_count: int = 0
    last_active: Optional[float] = None
    
    # Monitor/Link tracking
    monitors: Set[str] = field(default_factory=set)  # Monitor refs we created
    monitored_by: Set[str] = field(default_factory=set)  # Monitor refs watching us
    links: Set[str] = field(default_factory=set)  # PIDs we're linked to
    trap_exits: bool = False  # Whether we convert exit signals to messages
    
    # Process characteristics (for SPAM optimization)
    characteristics: Optional[Dict[str, Any]] = None
    
    # Supervisor relationship
    supervisor_pid: Optional[str] = None
    supervisor_context: Optional[str] = None
    
    # Mailbox association (if any)
    mailbox_id: Optional[str] = None


@dataclass
class RuntimeStatistics:
    """Performance and operational statistics from a runtime backend."""
    backend_type: str
    uptime_seconds: float
    total_processes: int
    active_processes: int
    total_spawned: int
    total_terminated: int
    
    # Message throughput
    messages_processed: int = 0
    calls_processed: int = 0
    casts_processed: int = 0
    
    # Monitor/Link stats
    active_monitors: int = 0
    active_links: int = 0
    exit_signals_sent: int = 0
    down_messages_sent: int = 0
    
    # Registry stats
    registered_names: int = 0
    
    # Backend-specific metrics
    backend_metrics: Optional[Dict[str, Any]] = None


class RuntimeError(Exception):
    """Base exception for runtime-related errors."""
    pass


class ProcessNotFoundError(RuntimeError):
    """Raised when attempting to interact with a non-existent process."""
    pass


class NameAlreadyRegisteredError(RuntimeError):
    """Raised when attempting to register a name that's already taken."""
    pass


class ProcessSpawnError(RuntimeError):
    """Raised when process spawning fails."""
    pass


class RuntimeNotAvailableError(RuntimeError):
    """Raised when no runtime backend is available."""
    pass


class MonitorError(RuntimeError):
    """Raised when monitor operations fail."""
    pass


class LinkError(RuntimeError):
    """Raised when link operations fail."""
    pass


# Type aliases for common callback patterns
ProcessCallback = Callable[[str, Any], Awaitable[None]]
HealthProbeCallback = Callable[[str, Any], Awaitable[bool]]
ExitHandler = Callable[[str, atom.Atom], Awaitable[None]]

# Process characteristics for backend optimization hints
ProcessCharacteristics = Dict[str, Union[float, int, str]]


@dataclass
class SimpleChildSpec:
    """Simplified child specification for runtime use."""
    id: str
    module: Any  # gen_server callbacks module or worker function
    init_arg: Any = None
    process_type: atom.Atom = GEN_SERVER  # Using atom from atoms.py
    restart: atom.Atom = PERMANENT  # Using atom from atoms.py
    name: Optional[str] = None
    characteristics: Optional[ProcessCharacteristics] = None


@dataclass
class SupervisorOptions:
    """Supervisor configuration options."""
    strategy: atom.Atom = ONE_FOR_ONE  # Using atom from atoms.py
    max_restarts: int = 3
    max_seconds: int = 5
    auto_shutdown: bool = True


# Message types for process communication
@dataclass
class DownMessage:
    """Message sent when a monitored process dies."""
    ref: str  # Monitor reference
    pid: str  # Dead process PID
    reason: atom.Atom  # Exit reason (atom)
    
    def to_tuple(self):
        """Convert to Erlang-style tuple format."""
        return (DOWN, self.ref, PROCESS, self.pid, self.reason)


@dataclass
class ExitMessage:
    """Message sent through links when a process dies."""
    from_pid: str  # PID that died
    reason: atom.Atom  # Exit reason (atom)
    
    def to_tuple(self):
        """Convert to Erlang-style tuple format."""
        return (EXIT, self.from_pid, self.reason)
