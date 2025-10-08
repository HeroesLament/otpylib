"""
Dynamic supervisor for managing OTPModule children with runtime add/remove capability.

Module-aware version that works with OTPModule classes using the 0.5.0 pattern.
"""

from typing import Any, Dict, List, Optional, Tuple
import time
from collections import deque
from dataclasses import dataclass, field

from otpylib import process
from otpylib.module import get_behavior, is_otp_module, ModuleError

from otpylib.dynamic_supervisor.atoms import (
    PERMANENT, TRANSIENT, TEMPORARY,
    ONE_FOR_ONE, ONE_FOR_ALL, REST_FOR_ONE,
    NORMAL, SHUTDOWN, KILLED, SUPERVISOR_SHUTDOWN,
    EXIT, DOWN,
)


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class child_spec:
    """Child specification for module-based dynamic supervisors."""
    id: str
    module: type  # OTPModule class
    args: Any = None
    restart: Any = PERMANENT
    name: Optional[str] = None


@dataclass
class options:
    """Supervisor options."""
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
    failure_times: deque = field(default_factory=lambda: deque())
    last_successful_start: Optional[float] = None
    is_dynamic: bool = False


@dataclass
class _SupervisorState:
    """Internal state for the dynamic supervisor."""
    module_class: Optional[type] = None
    module_instance: Optional[Any] = None
    children: Dict[str, _ChildState] = field(default_factory=dict)
    start_order: List[str] = field(default_factory=list)
    dynamic_children: List[str] = field(default_factory=list)
    pending_terminations: Dict[str, str] = field(default_factory=dict)
    opts: options = field(default_factory=options)


# ============================================================================
# Supervisor Control Messages (Atoms)
# ============================================================================

GET_CHILD_STATUS = "get_child_status"
LIST_CHILDREN = "list_children"
WHICH_CHILDREN = "which_children"
COUNT_CHILDREN = "count_children"
ADD_CHILD = "add_child"
TERMINATE_CHILD = "terminate_child"


# ============================================================================
# Public API (Module-Based - 0.5.0 Pattern)
# ============================================================================

async def start_link(
    module_class: type,
    init_arg: Any = None,
    name: Optional[str] = None
) -> str:
    """
    Start a dynamic supervisor from an OTPModule class (linked to caller).
    
    This is the 0.5.0 module-based pattern matching gen_server and supervisor.
    
    Args:
        module_class: OTPModule class with DYNAMIC_SUPERVISOR behavior
        init_arg: Argument passed to the module's init() callback
        name: Optional registered name
    
    Returns:
        Supervisor PID
    
    Example:
        class MyDynamicSup(metaclass=OTPModule, behavior=DYNAMIC_SUPERVISOR, version="1.0.0"):
            async def init(self, args):
                children = [...]
                opts = options(strategy=ONE_FOR_ONE)
                return (children, opts)
        
        pid = await dynamic_supervisor.start_link(MyDynamicSup, init_arg=config)
    """
    if not is_otp_module(module_class):
        raise ModuleError(f"{module_class} is not an OTPModule")
    
    parent = process.self()
    if not parent:
        raise RuntimeError("dynamic_supervisor.start_link() must be called from within a process")
    
    sup_pid = await process.spawn_link(
        _module_supervisor_loop,
        args=[module_class, init_arg, parent],
        name=name,
        mailbox=True,
        trap_exits=True,
    )
    
    # Wait for init handshake (matching gen_server/supervisor pattern)
    msg = await process.receive(timeout=5.0)
    
    match msg:
        case ("dynamic_supervisor_init_ok", pid, child_ids) if pid == sup_pid:
            return sup_pid
        case ("dynamic_supervisor_init_error", pid, reason) if pid == sup_pid:
            raise RuntimeError(f"[dynamic_supervisor] {module_class.__mod_id__} init failed: {reason}")
        case _:
            raise RuntimeError(f"[dynamic_supervisor] Unexpected init reply: {msg}")


async def start(
    module_class: type,
    init_arg: Any = None,
    name: Optional[str] = None
) -> str:
    """
    Start a dynamic supervisor from an OTPModule class (not linked).
    
    Args:
        module_class: OTPModule class with DYNAMIC_SUPERVISOR behavior
        init_arg: Argument passed to the module's init() callback
        name: Optional registered name
    
    Returns:
        Supervisor PID
    """
    if not is_otp_module(module_class):
        raise ModuleError(f"{module_class} is not an OTPModule")
    
    parent = process.self()
    if not parent:
        raise RuntimeError("dynamic_supervisor.start() must be called from within a process")
    
    sup_pid = await process.spawn(
        _module_supervisor_loop,
        args=[module_class, init_arg, parent],
        name=name,
        mailbox=True,
        trap_exits=True,
    )
    
    # Wait for init handshake
    msg = await process.receive(timeout=5.0)
    
    match msg:
        case ("dynamic_supervisor_init_ok", pid, child_ids) if pid == sup_pid:
            return sup_pid
        case ("dynamic_supervisor_init_error", pid, reason) if pid == sup_pid:
            raise RuntimeError(f"[dynamic_supervisor] {module_class.__mod_id__} init failed: {reason}")
        case _:
            raise RuntimeError(f"[dynamic_supervisor] Unexpected init reply: {msg}")


# ============================================================================
# Dynamic Child Management API
# ============================================================================

async def start_child(supervisor_pid: str, spec: child_spec) -> Tuple[bool, str]:
    """Dynamically add and start a child under the supervisor."""
    await process.send(supervisor_pid, (ADD_CHILD, spec, process.self()))
    return await process.receive(timeout=5.0)


async def terminate_child(supervisor_pid: str, child_id: str) -> Tuple[bool, str]:
    """Terminate a dynamic child (static children cannot be terminated)."""
    await process.send(supervisor_pid, (TERMINATE_CHILD, child_id, process.self()))
    return await process.receive(timeout=5.0)


async def list_children(supervisor_pid: str) -> List[str]:
    """Get a list of all child IDs."""
    await process.send(supervisor_pid, (LIST_CHILDREN, process.self()))
    return await process.receive(timeout=5.0)


async def which_children(supervisor_pid: str) -> List[Dict[str, Any]]:
    """Get detailed information about all children."""
    await process.send(supervisor_pid, (WHICH_CHILDREN, process.self()))
    return await process.receive(timeout=5.0)


async def count_children(supervisor_pid: str) -> Dict[str, int]:
    """Get counts of children by various categories."""
    await process.send(supervisor_pid, (COUNT_CHILDREN, process.self()))
    return await process.receive(timeout=5.0)


# ============================================================================
# Module-Based Supervisor Loop (0.5.0)
# ============================================================================

async def _module_supervisor_loop(module_class: type, init_arg: Any, parent_pid: str):
    """Main supervisor loop for module-based dynamic supervision."""
    pid = process.self()
    
    # Create module instance
    instance = module_class()
    
    # Call init() to get initial children and options
    try:
        result = await instance.init(init_arg)
        
        if not isinstance(result, tuple) or len(result) != 2:
            await process.send(parent_pid, ("dynamic_supervisor_init_error", pid, 
                f"{module_class.__name__}.init() must return (children, opts), got {type(result)}"))
            return
        
        child_specs, opts = result
        
    except Exception as e:
        # Call terminate with error reason if init fails
        if hasattr(instance, 'terminate'):
            try:
                await instance.terminate(e, None)
            except Exception:
                pass
        await process.send(parent_pid, ("dynamic_supervisor_init_error", pid, repr(e)))
        return
    
    # Build state
    state = _SupervisorState(
        module_class=module_class,
        module_instance=instance,
        opts=opts
    )
    
    # Validate and load static children
    for spec in child_specs:
        _validate_child_spec(spec)
        state.children[spec.id] = _ChildState(spec=spec, is_dynamic=False)
        state.start_order.append(spec.id)
    
    # Start all static children
    try:
        for child_id in state.start_order:
            await _start_child(state.children[child_id])
    except Exception as e:
        await process.send(parent_pid, ("dynamic_supervisor_init_error", pid, repr(e)))
        return
    
    # Send init success handshake
    child_ids = list(state.children.keys())
    await process.send(parent_pid, ("dynamic_supervisor_init_ok", pid, child_ids))
    
    # Main message loop
    shutting_down = False
    shutdown_reason = None
    
    while not shutting_down:
        try:
            msg = await process.receive()
            
            match msg:
                case (msg_type, from_pid, reason) if msg_type == EXIT:
                    pass  # Trapped exit - DOWN handles it
                
                case (msg_type, ref, _, pid, reason) if msg_type == DOWN:
                    result = await _handle_down(state, ref, pid, reason)
                    if result is not None:
                        shutting_down = True
                        shutdown_reason = result
                
                case (msg_type, spec, reply_to) if msg_type == ADD_CHILD:
                    await _handle_add_child(state, spec, reply_to)
                
                case (msg_type, child_id, reply_to) if msg_type == TERMINATE_CHILD:
                    await _handle_terminate_child(state, child_id, reply_to)
                
                case (msg_type, child_id, reply_to) if msg_type == GET_CHILD_STATUS:
                    await _handle_get_child_status(state, child_id, reply_to)
                
                case (msg_type, reply_to) if msg_type == LIST_CHILDREN:
                    await _handle_list_children(state, reply_to)
                
                case (msg_type, reply_to) if msg_type == WHICH_CHILDREN:
                    await _handle_which_children(state, reply_to)
                
                case (msg_type, reply_to) if msg_type == COUNT_CHILDREN:
                    await _handle_count_children(state, reply_to)
                
                case msg_type if msg_type == SHUTDOWN:
                    shutting_down = True
                    shutdown_reason = SHUTDOWN
                
                case _:
                    pass
        
        except Exception as e:
            import traceback
            print(f"[dynamic_supervisor] ERROR in main loop: {e}")
            traceback.print_exc()
    
    # Shutdown: terminate all children
    await _shutdown_children(state)
    
    # Call terminate callback
    if hasattr(instance, 'terminate'):
        try:
            await instance.terminate(shutdown_reason, state)
        except Exception as e:
            print(f"[dynamic_supervisor] Error in terminate: {e}")


# ============================================================================
# Child Management
# ============================================================================

def _validate_child_spec(spec: child_spec):
    """Validate that a child spec is correct."""
    if not isinstance(spec, child_spec):
        raise ModuleError(f"Expected child_spec, got {type(spec)}")
    
    if not is_otp_module(spec.module):
        raise ModuleError(f"Child module {spec.module.__name__} is not an OTPModule")


async def _start_child(child: _ChildState):
    """
    Start a child process from its child_spec.
    
    Uses the OTPModule's universal start_link which routes to the
    appropriate behavior implementation.
    """
    spec = child.spec
    module_class = spec.module
    
    # Call the module's start_link - OTPModule metaclass routes to correct behavior
    pid = await module_class.start_link(init_arg=spec.args, name=spec.name)
    
    # Monitor the child
    monitor_ref = await process.monitor(pid)
    
    child.pid = pid
    child.monitor_ref = monitor_ref
    child.last_successful_start = time.time()


async def _shutdown_children(state: _SupervisorState):
    """Shutdown all children on supervisor termination."""
    for child in state.children.values():
        if child.pid and process.is_alive(child.pid):
            try:
                await process.exit(child.pid, SUPERVISOR_SHUTDOWN)
            except Exception:
                pass


# ============================================================================
# Message Handlers
# ============================================================================

async def _handle_down(
    state: _SupervisorState,
    ref: str,
    pid: str,
    reason: Any
) -> Optional[Any]:
    """Handle DOWN message. Returns shutdown reason if should shutdown."""
    child_id = next((cid for cid, c in state.children.items() if c.monitor_ref == ref), None)
    
    if not child_id:
        return None
    
    # Check if pending termination
    if child_id in state.pending_terminations:
        reply_to = state.pending_terminations.pop(child_id)
        await process.send(reply_to, (True, f"Child {child_id} terminated"))
    
    # Handle child exit
    try:
        await _handle_child_exit(state, child_id, reason)
    except RuntimeError as e:
        print(f"[dynamic_supervisor] Restart intensity exceeded: {e}")
        return str(e)
    
    return None


async def _handle_child_exit(state: _SupervisorState, child_id: str, reason: Any):
    """Handle a child exit and apply restart strategy."""
    child = state.children[child_id]
    
    # Unregister name
    if child.spec.name:
        try:
            await process.unregister(child.spec.name)
        except Exception:
            pass
    
    # Check if normal shutdown
    if reason in [SHUTDOWN, SUPERVISOR_SHUTDOWN, KILLED]:
        if child.is_dynamic:
            state.children.pop(child_id, None)
            if child_id in state.dynamic_children:
                state.dynamic_children.remove(child_id)
        else:
            child.pid = None
            child.monitor_ref = None
        return
    
    # Determine if should restart
    failed = reason != NORMAL
    should_restart = True
    
    if child.spec.restart == TRANSIENT and not failed:
        should_restart = False
    elif child.spec.restart == TEMPORARY:
        should_restart = False
    
    if not should_restart:
        if child.is_dynamic:
            state.children.pop(child_id, None)
            if child_id in state.dynamic_children:
                state.dynamic_children.remove(child_id)
        else:
            child.pid = None
            child.monitor_ref = None
        return
    
    # Check restart intensity
    current_time = time.time()
    child.failure_times.append(current_time)
    cutoff = current_time - state.opts.max_seconds
    
    while child.failure_times and child.failure_times[0] < cutoff:
        child.failure_times.popleft()
    
    if len(child.failure_times) > state.opts.max_restarts:
        raise RuntimeError(f"Restart intensity exceeded for child {child_id}")
    
    # Apply restart strategy
    if state.opts.strategy == ONE_FOR_ONE:
        child.restart_count += 1
        await _start_child(child)
    
    elif state.opts.strategy == ONE_FOR_ALL:
        # Kill all other children
        for cid, other in state.children.items():
            if cid != child_id and other.pid and process.is_alive(other.pid):
                await process.exit(other.pid, KILLED)
        
        # Restart all children
        all_children = state.start_order + state.dynamic_children
        for cid in all_children:
            if cid in state.children:
                restart_child = state.children[cid]
                restart_child.restart_count += 1
                await _start_child(restart_child)
    
    elif state.opts.strategy == REST_FOR_ONE:
        # Kill and restart this child and all later ones
        all_children = state.start_order + state.dynamic_children
        try:
            idx = all_children.index(child_id)
            
            # Kill later children
            for cid in all_children[idx + 1:]:
                if cid in state.children:
                    other = state.children[cid]
                    if other.pid and process.is_alive(other.pid):
                        await process.exit(other.pid, KILLED)
            
            # Restart this and later children
            for cid in all_children[idx:]:
                if cid in state.children:
                    restart_child = state.children[cid]
                    restart_child.restart_count += 1
                    await _start_child(restart_child)
        except ValueError:
            # Child not in list, just restart it
            child.restart_count += 1
            await _start_child(child)


async def _handle_add_child(state: _SupervisorState, spec: child_spec, reply_to: str):
    """Handle request to add a dynamic child."""
    try:
        _validate_child_spec(spec)
        
        if spec.id in state.children:
            await process.send(reply_to, (False, f"Child {spec.id} already exists"))
            return
        
        # Create and start child
        child_state = _ChildState(spec=spec, is_dynamic=True)
        state.children[spec.id] = child_state
        state.dynamic_children.append(spec.id)
        
        await _start_child(child_state)
        await process.send(reply_to, (True, f"Child {spec.id} started successfully"))
    
    except Exception as e:
        # Cleanup on failure
        state.children.pop(spec.id, None)
        if spec.id in state.dynamic_children:
            state.dynamic_children.remove(spec.id)
        await process.send(reply_to, (False, f"Failed to start child: {e}"))


async def _handle_terminate_child(state: _SupervisorState, child_id: str, reply_to: str):
    """Handle request to terminate a dynamic child."""
    child = state.children.get(child_id)
    
    if not child:
        await process.send(reply_to, (False, f"Child {child_id} not found"))
        return
    
    if not child.is_dynamic:
        await process.send(reply_to, (False, f"Cannot terminate static child {child_id}"))
        return
    
    if child.pid and process.is_alive(child.pid):
        await process.exit(child.pid, SUPERVISOR_SHUTDOWN)
        state.pending_terminations[child_id] = reply_to
    else:
        await process.send(reply_to, (True, f"Child {child_id} already terminated"))


async def _handle_get_child_status(state: _SupervisorState, child_id: str, reply_to: str):
    """Handle request for child status."""
    child = state.children.get(child_id)
    
    if child:
        status = {
            "id": child_id,
            "pid": child.pid,
            "alive": process.is_alive(child.pid) if child.pid else False,
            "restart_count": child.restart_count,
            "is_dynamic": child.is_dynamic,
            "module": child.spec.module.__mod_id__,
        }
    else:
        status = None
    
    await process.send(reply_to, status)


async def _handle_list_children(state: _SupervisorState, reply_to: str):
    """Handle request to list all child IDs."""
    await process.send(reply_to, list(state.children.keys()))


async def _handle_which_children(state: _SupervisorState, reply_to: str):
    """Handle request for detailed child information."""
    infos = []
    for child_id, child in state.children.items():
        infos.append({
            "id": child_id,
            "pid": child.pid,
            "module": child.spec.module.__mod_id__,
            "restart_count": child.restart_count,
            "is_dynamic": child.is_dynamic,
            "restart_type": str(child.spec.restart),
        })
    
    await process.send(reply_to, infos)


async def _handle_count_children(state: _SupervisorState, reply_to: str):
    """Handle request for child counts."""
    counts = {
        "specs": len(state.children),
        "active": sum(1 for c in state.children.values() if c.pid and process.is_alive(c.pid)),
        "dynamic": sum(1 for c in state.children.values() if c.is_dynamic),
        "static": sum(1 for c in state.children.values() if not c.is_dynamic),
    }
    
    await process.send(reply_to, counts)
