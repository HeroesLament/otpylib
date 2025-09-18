"""
Runtime Data Types

Common data structures and type definitions used across runtime backends.
Provides abstractions that work for both AnyIO and SPAM implementations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union, Callable, Awaitable
import time


class ProcessType(Enum):
    """Type of OTP process managed by the runtime."""
    GEN_SERVER = "gen_server"
    SUPERVISOR = "supervisor"
    WORKER = "worker"


class ProcessState(Enum):
    """Current state of a runtime-managed process."""
    STARTING = "starting"        # Process is being initialized
    RUNNING = "running"          # Process is active and processing messages
    WAITING = "waiting"          # Process is idle, waiting for messages
    TERMINATING = "terminating"  # Process is shutting down
    TERMINATED = "terminated"    # Process has ended


@dataclass
class ProcessInfo:
    """Information about a runtime-managed process."""
    pid: str
    process_type: ProcessType
    name: Optional[str]
    state: ProcessState
    created_at: float
    message_queue_length: int = 0
    restart_count: int = 0
    last_active: Optional[float] = None
    
    # Process characteristics (for SPAM optimization)
    characteristics: Optional[Dict[str, Any]] = None
    
    # Supervisor relationship
    supervisor_pid: Optional[str] = None
    supervisor_context: Optional[str] = None


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


# Type aliases for common callback patterns
ProcessCallback = Callable[[str, Any], Awaitable[None]]
HealthProbeCallback = Callable[[str, Any], Awaitable[bool]]

# Process characteristics for backend optimization hints
ProcessCharacteristics = Dict[str, Union[float, int, str]]

# Supervisor child specification (simplified from full supervisor module)
@dataclass 
class SimpleChildSpec:
    """Simplified child specification for runtime use."""
    id: str
    module: Any  # gen_server callbacks module or worker function
    init_arg: Any = None
    process_type: ProcessType = ProcessType.GEN_SERVER
    name: Optional[str] = None
    characteristics: Optional[ProcessCharacteristics] = None
