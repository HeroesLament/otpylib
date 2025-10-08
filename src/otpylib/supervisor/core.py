"""
otpylib/supervisor/core.py

Module-aware static supervisor implementation.
Works with OTPModule classes that have SUPERVISOR behavior.
"""

from typing import Any, Dict, List, Optional, Tuple
import time
from collections import deque
from dataclasses import dataclass

from otpylib import atom, process
from otpylib.runtime.backends.base import ProcessNotFoundError
from otpylib.module import (
    SUPERVISOR,
    is_otp_module,
    get_behavior,
    ModuleError
)
from otpylib.supervisor.atoms import (
    PERMANENT, TRANSIENT, TEMPORARY,
    ONE_FOR_ONE, ONE_FOR_ALL, REST_FOR_ONE,
    SUPERVISOR_SHUTDOWN,
    SHUTDOWN, KILLED,
)

LOGGER = atom.ensure("logger")


# ============================================================================
# Exceptions
# ============================================================================

class NotASupervisorError(ModuleError):
    """Module is not a supervisor behavior."""
    def __init__(self, module_class: type):
        behavior = get_behavior(module_class) if is_otp_module(module_class) else None
        super().__init__(
            f"Module {module_class.__name__} is not a supervisor "
            f"(behavior: {behavior.name if behavior else 'unknown'})"
        )


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class child_spec:
    """Child specification for module-based supervisors."""
    id: str
    module: type  # OTPModule class
    args: Any = None
    restart: Any = PERMANENT
    name: Optional[str] = None


@dataclass
class options:
    max_restarts: int = 3
    max_seconds: int = 5
    strategy: Any = ONE_FOR_ONE


@dataclass
class _ChildState:
    """Internal state for tracking a child process."""
    spec: child_spec
    pid: Optional[str] = None
    monitor_ref: Optional[str] = None
    restart_count: int = 0


class _IntensityExceeded(Exception):
    """Raised when restart intensity limit is exceeded."""
    pass


# ============================================================================
# Validation
# ============================================================================

def _validate_supervisor_module(module_class: type) -> None:
    """Validate that a class is an OTPModule with supervisor behavior."""
    if not is_otp_module(module_class):
        raise NotASupervisorError(module_class)
    
    behavior = get_behavior(module_class)
    if behavior != SUPERVISOR:
        raise NotASupervisorError(module_class)


# ============================================================================
# Utilities
# ============================================================================

def _record_restart(intensity_times: deque, max_restarts: int, max_seconds: int) -> bool:
    """Record a restart attempt and check if intensity exceeded."""
    now = time.time()
    intensity_times.append(now)
    cutoff = now - max_seconds
    
    while intensity_times and intensity_times[0] < cutoff:
        intensity_times.popleft()
    
    restart_count = len(intensity_times)
    return restart_count > max_restarts


async def _mark_down(child: _ChildState):
    """Mark a child as down and unregister its name if any."""
    name = child.spec.name
    
    if child.pid and name:
        try:
            await process.unregister(name)
        except Exception:
            pass
    
    child.pid = None
    child.monitor_ref = None


def _safe_is_alive(pid: Optional[str]) -> bool:
    """Safely check if a PID is alive."""
    if not pid:
        return False
    try:
        return process.is_alive(pid)
    except ProcessNotFoundError:
        return False


async def _shutdown_children(children: Dict[str, _ChildState]):
    """Shutdown all children."""
    for child_id, c in children.items():
        if _safe_is_alive(c.pid):
            try:
                await process.exit(c.pid, SUPERVISOR_SHUTDOWN)
            except ProcessNotFoundError:
                pass


async def _start_child(child: _ChildState):
    """
    Start a child process from its child_spec.
    
    Uses the OTPModule's universal start_link which routes to the
    appropriate behavior implementation.
    """
    spec = child.spec
    child_id = spec.id
    module_class = spec.module
    args = spec.args
    name = spec.name
    
    try:
        # Call the module's start_link - OTPModule metaclass routes to correct behavior
        pid = await module_class.start_link(init_arg=args, name=name)
        
        monitor_ref = await process.monitor(pid)
        
        child.pid = pid
        child.monitor_ref = monitor_ref
        
    except Exception as e:
        raise


async def _restart_child(child: _ChildState, intensity_times: deque, 
                        max_restarts: int, max_seconds: int):
    """Restart a single child with intensity accounting."""
    if _record_restart(intensity_times, max_restarts, max_seconds):
        raise _IntensityExceeded()
    
    await _mark_down(child)
    child.restart_count += 1
    await _start_child(child)


# ============================================================================
# Public API
# ============================================================================

async def start_link(
    module_class: type,
    init_arg: Any = None,
    name: Optional[str] = None
) -> str:
    """
    Start a supervisor from an OTPModule supervisor class.
    
    Args:
        module_class: OTPModule class with SUPERVISOR behavior
        init_arg: Argument passed to init callback
        name: Optional registered name
    
    Returns:
        Supervisor PID
    """
    _validate_supervisor_module(module_class)
    
    if name:
        existing = process.whereis(name)
        if existing is not None:
            raise RuntimeError(f"Supervisor name '{name}' is already registered")
    
    parent = process.self()
    if not parent:
        raise RuntimeError("supervisor.start_link() must be called from within a process")
    
    sup_pid = await process.spawn_link(
        _supervisor_loop,
        args=[module_class, init_arg, parent],
        name=name,
        mailbox=True,
        trap_exits=True,
    )
    
    # Wait for init handshake
    msg = await process.receive(timeout=5.0)
    
    match msg:
        case ("supervisor_init_ok", pid, child_ids) if pid == sup_pid:
            return sup_pid
        case ("supervisor_init_error", pid, reason) if pid == sup_pid:
            raise RuntimeError(f"[supervisor] {module_class.__mod_id__} init failed: {reason}")
        case _:
            raise RuntimeError(f"[supervisor] Unexpected init reply: {msg}")


# ============================================================================
# Supervisor Loop
# ============================================================================

async def _supervisor_loop(module_class: type, init_arg: Any, parent_pid: str):
    """Main supervisor loop - creates supervisor instance and manages children."""
    DOWN_ATOM = atom.ensure("DOWN")
    
    pid = process.self()
    modname = module_class.__mod_id__
    
    try:
        # Create supervisor instance
        supervisor_instance = module_class()
        
        # Call init to get supervisor spec
        if not hasattr(supervisor_instance, 'init'):
            await process.send(parent_pid, ("supervisor_init_error", pid, "no init callback"))
            return
        
        result = await supervisor_instance.init(init_arg)
        
        # Parse supervisor spec - expect (child_specs, options) tuple
        if isinstance(result, tuple) and len(result) == 2:
            child_specs, opts = result
            
            # Extract options
            if isinstance(opts, dict):
                strategy = opts.get('strategy', 'one_for_one')
                max_restarts = opts.get('max_restarts', 3)
                max_seconds = opts.get('max_seconds', 5)
            else:
                # Assume it's an options dataclass
                strategy = getattr(opts, 'strategy', ONE_FOR_ONE)
                max_restarts = getattr(opts, 'max_restarts', 3)
                max_seconds = getattr(opts, 'max_seconds', 5)
        else:
            await process.send(parent_pid, ("supervisor_init_error", pid, f"init must return (child_specs, options), got {type(result)}"))
            return
        
        # Map strategy to atom if it's a string
        if isinstance(strategy, str):
            strategy_map = {
                'one_for_one': ONE_FOR_ONE,
                'one_for_all': ONE_FOR_ALL,
                'rest_for_one': REST_FOR_ONE
            }
            strategy_atom = strategy_map.get(strategy, ONE_FOR_ONE)
        else:
            strategy_atom = strategy
        
        # Validate child_specs are child_spec instances
        for i, spec in enumerate(child_specs):
            if not isinstance(spec, child_spec):
                await process.send(parent_pid, ("supervisor_init_error", pid, f"child_specs must be child_spec instances, got {type(spec)}"))
                return
        
        # Build child states
        children: Dict[str, _ChildState] = {}
        start_order: List[str] = []
        
        for spec in child_specs:
            children[spec.id] = _ChildState(spec=spec)
            start_order.append(spec.id)
        
        # Start all children
        for child_id in start_order:
            await _start_child(children[child_id])
        
        # Send init success
        child_ids = list(children.keys())
        await process.send(parent_pid, ("supervisor_init_ok", pid, child_ids))
        
    except Exception as e:
        await process.send(parent_pid, ("supervisor_init_error", pid, repr(e)))
        return
    
    # Main loop
    shutting_down = False
    intensity_times: deque = deque()
    
    while not shutting_down:
        try:
            msg = await process.receive()
            
            match msg:
                # Monitor DOWN
                case (msg_type, ref, _, child_pid, reason) if msg_type == DOWN_ATOM:
                    cid = None
                    for check_id, ch in children.items():
                        if ch.monitor_ref == ref:
                            cid = check_id
                            break
                    
                    if cid:
                        if reason != KILLED and reason != SHUTDOWN:
                            await _handle_child_exit(
                                children, cid, reason, strategy_atom,
                                start_order, intensity_times, 
                                max_restarts, max_seconds
                            )
                
                # Shutdown
                case msg_type if msg_type == SHUTDOWN:
                    shutting_down = True
                    break
                
                # Ignore unknown
                case _:
                    pass
        
        except _IntensityExceeded:
            shutting_down = True
            break
        except Exception:
            pass
    
    await _shutdown_children(children)


# ============================================================================
# Exit Handler
# ============================================================================

async def _handle_child_exit(
    children: Dict[str, _ChildState],
    dead_id: str,
    reason: Any,
    strategy: Any,
    start_order: List[str],
    intensity_times: deque,
    max_restarts: int,
    max_seconds: int
):
    """Handle a child exit based on supervisor strategy."""
    child = children[dead_id]
    
    if reason == SHUTDOWN or reason == SUPERVISOR_SHUTDOWN:
        await _mark_down(child)
        return
    
    if strategy == ONE_FOR_ONE:
        await _restart_child(child, intensity_times, max_restarts, max_seconds)
    
    elif strategy == ONE_FOR_ALL:
        for cid, other in children.items():
            if _safe_is_alive(other.pid):
                try:
                    await process.exit(other.pid, SUPERVISOR_SHUTDOWN)
                except ProcessNotFoundError:
                    pass
            await _mark_down(other)
        
        for cid in start_order:
            await _restart_child(children[cid], intensity_times, max_restarts, max_seconds)
    
    elif strategy == REST_FOR_ONE:
        idx = start_order.index(dead_id)
        victims = start_order[idx:]
        
        for cid in victims:
            c = children[cid]
            if _safe_is_alive(c.pid):
                try:
                    await process.exit(c.pid, SUPERVISOR_SHUTDOWN)
                except ProcessNotFoundError:
                    pass
            await _mark_down(c)
        
        for cid in victims:
            await _restart_child(children[cid], intensity_times, max_restarts, max_seconds)
