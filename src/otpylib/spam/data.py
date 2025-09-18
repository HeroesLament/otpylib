"""
SPAM Data Structures

Core data structures and types for Sypher's Abstract Python Machine.
Contains process definitions, configuration, and runtime state management.
"""

import os
import sys
import time
import uuid
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Dict, List, Set, Callable, Awaitable, Union
import anyio


class ProcessType(Enum):
    """Type of OTP process"""
    GEN_SERVER = "gen_server"
    SUPERVISOR = "supervisor"
    WORKER = "worker"
    APPLICATION = "application"


class ProcessState(Enum):
    """Current state of an OTP process"""
    READY = "ready"              # Ready to be scheduled
    RUNNING = "running"          # Currently executing
    WAITING = "waiting"          # Waiting for message/event
    MIGRATING = "migrating"      # Being moved between cores
    SUSPENDED = "suspended"      # Suspended for hot reload
    TERMINATED = "terminated"    # Process has ended


class RuntimeMode(Enum):
    """SPAM runtime execution mode"""
    COOPERATIVE = "cooperative"      # Single-threaded cooperative
    WORK_STEALING = "work_stealing"  # Multi-threaded work stealing
    MULTIPROCESS = "multiprocess"    # Multi-process distribution


class MigrationReason(Enum):
    """Reason for process migration"""
    WORK_STEALING = "work_stealing"  # Load balancing
    HOT_RELOAD = "hot_reload"        # Code update
    AFFINITY = "affinity"            # Core affinity optimization
    MANUAL = "manual"                # Explicit migration request


@dataclass
class ProcessMetrics:
    """Performance metrics for a process"""
    messages_processed: int = 0
    total_execution_time: float = 0.0
    last_execution_time: float = 0.0
    average_message_time: float = 0.0
    queue_high_water_mark: int = 0
    migration_count: int = 0
    restart_count: int = 0
    
    def update_execution_time(self, execution_time: float):
        """Update execution timing metrics"""
        self.total_execution_time += execution_time
        self.last_execution_time = execution_time
        
        if self.messages_processed > 0:
            self.average_message_time = self.total_execution_time / self.messages_processed


@dataclass 
class ProcessCharacteristics:
    """Process behavioral characteristics for scheduling optimization"""
    cpu_bound_score: float = 0.0        # 0.0 = I/O bound, 1.0 = CPU bound
    memory_usage_mb: float = 1.0        # Estimated memory usage
    message_throughput: float = 0.0     # Messages per second
    cache_affinity: float = 0.0         # Core cache affinity (0.0-1.0)
    migration_cost: float = 0.1         # Cost to migrate (0.0-1.0)
    priority: int = 0                   # Scheduling priority (-20 to 20)


@dataclass
class OTPProcess:
    """
    Core process abstraction in SPAM.
    
    Represents a single OTP process (gen_server, supervisor, worker)
    with all associated runtime state and metadata.
    """
    
    # Identity
    pid: str
    process_type: ProcessType
    module: Any
    init_arg: Any = None
    name: Optional[str] = None
    
    # Current runtime state
    state: ProcessState = ProcessState.READY
    internal_state: Any = None          # Process's business logic state
    message_queue: deque = field(default_factory=deque)
    
    # Execution context
    current_core: Optional[int] = None
    cancel_scope: Optional[anyio.CancelScope] = None
    task_handle: Optional[Any] = None
    
    # Timing and lifecycle
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    last_active: float = field(default_factory=time.time)
    last_scheduled: Optional[float] = None
    
    # Process characteristics and metrics
    characteristics: ProcessCharacteristics = field(default_factory=ProcessCharacteristics)
    metrics: ProcessMetrics = field(default_factory=ProcessMetrics)
    
    # Supervision and linking
    supervisor_pid: Optional[str] = None
    supervisor_context: Optional[str] = None
    linked_processes: Set[str] = field(default_factory=set)
    monitoring_processes: Set[str] = field(default_factory=set)
    
    # Hot reload support
    module_version: int = 1
    code_reload_count: int = 0
    last_hot_reload: Optional[float] = None
    
    # State recovery
    state_backup_enabled: bool = True
    last_state_backup: Optional[float] = None
    
    def __post_init__(self):
        """Initialize computed fields"""
        if not self.pid:
            self.pid = f"{self.process_type.value}_{uuid.uuid4().hex[:8]}"
    
    def can_be_stolen(self) -> bool:
        """Check if process is eligible for work stealing"""
        return (
            self.state in [ProcessState.READY, ProcessState.WAITING] and
            self.characteristics.migration_cost < 0.8 and
            (len(self.message_queue) > 0 or 
             (time.time() - self.last_active) < 5.0)
        )
    
    def update_queue_metrics(self):
        """Update message queue metrics"""
        current_length = len(self.message_queue)
        if current_length > self.metrics.queue_high_water_mark:
            self.metrics.queue_high_water_mark = current_length
    
    def record_migration(self, reason: MigrationReason):
        """Record process migration event"""
        self.metrics.migration_count += 1
        self.last_active = time.time()
        # Could extend to track migration reasons


@dataclass
class RuntimeConfig:
    """Configuration for SPAM runtime"""
    
    # Execution mode
    mode: RuntimeMode = RuntimeMode.WORK_STEALING
    
    # Process topology  
    core_count: Optional[int] = None          # None = auto-detect
    worker_processes: Optional[int] = None    # For multiprocess mode
    threads_per_process: Optional[int] = None # For hybrid mode
    
    # Scheduling parameters
    time_slice_ms: float = 10.0              # Process time slice duration
    work_stealing_enabled: bool = True        # Enable work stealing
    steal_threshold: int = 2                  # Min queue diff for stealing
    steal_attempts_per_cycle: int = 3         # Max steal attempts per cycle
    yield_check_interval: int = 10            # Check for yields every N messages
    
    # Process limits and quotas
    max_processes_per_core: int = 10000       # Process limit per core
    max_message_queue_size: int = 1000        # Message queue size limit  
    max_process_memory_mb: float = 100.0      # Memory limit per process
    
    # Performance tuning
    preemptive_scheduling: bool = True        # Use timeout-based preemption
    process_priorities: bool = True           # Honor process priorities
    numa_aware: bool = False                  # NUMA-aware scheduling
    
    # Hot reload and recovery
    hot_reload_enabled: bool = True           # Enable hot code reloading
    state_backup_enabled: bool = True         # Enable state preservation
    state_backup_interval: float = 30.0       # State backup frequency
    
    # Debugging and management
    management_socket: Optional[str] = None   # Unix socket path for management
    telemetry_enabled: bool = True            # OpenTelemetry metrics
    debugger_port: Optional[int] = None       # Web debugger port
    debug_mode: bool = False                  # Extended debugging info
    
    # System integration
    cpu_affinity: bool = False                # Set CPU affinity for cores
    process_isolation: bool = False           # Enhanced process isolation
    
    def __post_init__(self):
        """Validate and auto-detect configuration"""
        
        # Auto-detect core count
        if self.core_count is None:
            self.core_count = os.cpu_count() or 4
        
        # Auto-detect worker processes for multiprocess mode
        if self.mode == RuntimeMode.MULTIPROCESS and self.worker_processes is None:
            self.worker_processes = self.core_count
        
        # Set threads per process for work stealing mode
        if self.mode == RuntimeMode.WORK_STEALING and self.threads_per_process is None:
            self.threads_per_process = self.core_count
        
        # Generate default management socket path
        if self.management_socket is None:
            self.management_socket = f"/tmp/otpyx_{os.getpid()}.sock"
    
    @classmethod
    def auto_detect(cls) -> 'RuntimeConfig':
        """Auto-detect optimal configuration for current system"""
        
        # Check if free-threading is available
        gil_disabled = False
        try:
            gil_disabled = hasattr(sys, '_is_gil_enabled') and not sys._is_gil_enabled()
        except:
            pass
        
        cores = os.cpu_count() or 4
        
        if gil_disabled:
            # Free-threading available - use work stealing within single process
            return cls(
                mode=RuntimeMode.WORK_STEALING,
                core_count=cores,
                worker_processes=1,
                threads_per_process=cores,
                preemptive_scheduling=True,
                work_stealing_enabled=True
            )
        else:
            # GIL enabled - fall back to cooperative or multiprocess
            # Default to cooperative for simplicity
            return cls(
                mode=RuntimeMode.COOPERATIVE,
                core_count=1,
                preemptive_scheduling=False,
                work_stealing_enabled=False
            )


@dataclass
class CoreState:
    """State information for a single core scheduler"""
    
    core_id: int
    active_processes: Dict[str, OTPProcess] = field(default_factory=dict)
    ready_queue: deque = field(default_factory=deque) 
    current_process: Optional[str] = None
    
    # Performance metrics
    total_processes_run: int = 0
    total_execution_time: float = 0.0
    idle_time: float = 0.0
    last_activity: float = field(default_factory=time.time)
    
    # Work stealing metrics
    steal_attempts: int = 0
    successful_steals: int = 0
    processes_stolen: int = 0
    processes_given: int = 0
    
    # Resource usage
    cpu_utilization: float = 0.0
    memory_usage_mb: float = 0.0
    
    def get_load_factor(self) -> float:
        """Calculate current load factor for work stealing decisions"""
        queue_load = len(self.ready_queue) * 0.6
        active_load = len(self.active_processes) * 0.4  
        return queue_load + active_load
    
    def update_utilization(self, execution_time: float, total_time: float):
        """Update CPU utilization metrics"""
        if total_time > 0:
            self.cpu_utilization = execution_time / total_time
        self.total_execution_time += execution_time


@dataclass 
class GlobalSchedulerState:
    """Global state shared across all core schedulers"""
    
    process_table: Dict[str, OTPProcess] = field(default_factory=dict)
    name_registry: Dict[str, str] = field(default_factory=dict)  # name -> pid
    core_states: Dict[int, CoreState] = field(default_factory=dict)
    
    # Global metrics
    total_processes_created: int = 0
    total_processes_terminated: int = 0
    total_migrations: int = 0
    total_hot_reloads: int = 0
    
    # System state
    startup_time: float = field(default_factory=time.time)
    shutdown_requested: bool = False
    
    # Thread safety
    _lock: threading.RLock = field(default_factory=threading.RLock)
    
    def register_process(self, process: OTPProcess) -> bool:
        """Thread-safe process registration"""
        with self._lock:
            if process.pid in self.process_table:
                return False
            
            self.process_table[process.pid] = process
            if process.name:
                self.name_registry[process.name] = process.pid
            
            self.total_processes_created += 1
            return True
    
    def unregister_process(self, pid: str) -> bool:
        """Thread-safe process unregistration"""
        with self._lock:
            process = self.process_table.pop(pid, None)
            if not process:
                return False
            
            if process.name and process.name in self.name_registry:
                del self.name_registry[process.name]
            
            self.total_processes_terminated += 1
            return True
    
    def get_process_by_name(self, name: str) -> Optional[OTPProcess]:
        """Get process by registered name"""
        with self._lock:
            pid = self.name_registry.get(name)
            return self.process_table.get(pid) if pid else None


# Type aliases for common callback signatures
HealthCheckCallback = Callable[[str, OTPProcess], Awaitable[bool]]
StateRecoveryCallback = Callable[[Any, str, int], Awaitable[Any]]
ProcessCallback = Callable[[OTPProcess], Awaitable[None]]

# Exception types for SPAM
class SPAMError(Exception):
    """Base exception for SPAM-related errors"""
    pass

class ProcessMigrationError(SPAMError):
    """Error during process migration"""
    pass

class ProcessSpawnError(SPAMError):
    """Error spawning new process"""
    pass

class HotReloadError(SPAMError):
    """Error during hot code reload"""
    pass

class SchedulerError(SPAMError):
    """Error in scheduler operation"""
    pass