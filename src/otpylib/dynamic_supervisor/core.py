"""
Dynamic supervisor for managing OTPModule children with runtime add/remove capability.

Module-aware version of dynamic_supervisor that works exclusively with OTPModule classes.
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


# ============================================================================
# Supervisor Control Messages
# ============================================================================

# Message atoms
_GET_CHILD_STATUS = "get_child_status"
_LIST_CHILDREN = "list_children"
_WHICH_CHILDREN = "which_children"
_COUNT_CHILDREN = "count_children"
_ADD_CHILD = "add_child"
_TERMINATE_CHILD = "terminate_child"


# ============================================================================
# Public API
# ============================================================================

async def start(
    child_specs: List[child_spec],
    opts: options = options(),
    name: Optional[str] = None
) -> str:
    """
    Start a dynamic supervisor (not linked to caller).
    
    Args:
        child_specs: List of initial static children
        opts: Supervisor options
        name: Optional registered name
    
    Returns:
        Supervisor PID
    """
    return await process.spawn(
        _dynamic_supervisor_loop,
        args=[child_specs, opts],
        name=name,
        mailbox=True,
        trap_exits=True,  # CRITICAL: Must trap exits to survive child crashes
    )


async def start_link(
    child_specs: List[child_spec],
    opts: options = options(),
    name: Optional[str] = None
) -> str:
    """
    Start a dynamic supervisor linked to the caller.
    
    Args:
        child_specs: List of initial static children
        opts: Supervisor options
        name: Optional registered name
    
    Returns:
        Supervisor PID
    """
    return await process.spawn_link(
        _dynamic_supervisor_loop,
        args=[child_specs, opts],
        name=name,
        mailbox=True,
        trap_exits=True,  # CRITICAL: Must trap exits to survive child crashes
    )


async def start_child(supervisor_pid: str, spec: child_spec) -> Tuple[bool, str]:
    """
    Dynamically add and start a child under the supervisor.
    
    Args:
        supervisor_pid: PID or name of the supervisor
        spec: Child specification
    
    Returns:
        Tuple of (success, message)
    """
    await process.send(supervisor_pid, (_ADD_CHILD, spec, process.self()))
    return await process.receive(timeout=5.0)


async def terminate_child(supervisor_pid: str, child_id: str) -> Tuple[bool, str]:
    """
    Terminate a dynamic child (static children cannot be terminated).
    
    Args:
        supervisor_pid: PID or name of the supervisor
        child_id: ID of the child to terminate
    
    Returns:
        Tuple of (success, message)
    """
    await process.send(supervisor_pid, (_TERMINATE_CHILD, child_id, process.self()))
    return await process.receive(timeout=5.0)


async def list_children(supervisor_pid: str) -> List[str]:
    """
    Get a list of all child IDs.
    
    Args:
        supervisor_pid: PID or name of the supervisor
    
    Returns:
        List of child IDs
    """
    await process.send(supervisor_pid, (_LIST_CHILDREN, process.self()))
    return await process.receive(timeout=5.0)


async def which_children(supervisor_pid: str) -> List[Dict[str, Any]]:
    """
    Get detailed information about all children.
    
    Args:
        supervisor_pid: PID or name of the supervisor
    
    Returns:
        List of child info dictionaries
    """
    await process.send(supervisor_pid, (_WHICH_CHILDREN, process.self()))
    return await process.receive(timeout=5.0)


async def count_children(supervisor_pid: str) -> Dict[str, int]:
    """
    Get counts of children by various categories.
    
    Args:
        supervisor_pid: PID or name of the supervisor
    
    Returns:
        Dictionary with counts (specs, active, dynamic, static)
    """
    await process.send(supervisor_pid, (_COUNT_CHILDREN, process.self()))
    return await process.receive(timeout=5.0)


# ============================================================================
# Supervisor Loop
# ============================================================================

async def _dynamic_supervisor_loop(child_specs: List[child_spec], opts: options):
    """Main supervisor loop for dynamic supervision."""
    children: Dict[str, _ChildState] = {}
    start_order: List[str] = []
    dynamic_children: List[str] = []
    pending_terminations: Dict[str, str] = {}  # child_id -> reply_to
    shutting_down = False
    
    # Validate and load static children
    for spec in child_specs:
        _validate_child_spec(spec)
        children[spec.id] = _ChildState(spec=spec, is_dynamic=False)
        start_order.append(spec.id)
    
    # Start all static children
    for child_id in start_order:
        await _start_child(children[child_id])
    
    # Main message loop
    while not shutting_down:
        try:
            msg = await process.receive()
            
            match msg:
                # Exit signal from linked child
                case (msg_type, from_pid, reason) if msg_type == EXIT:
                    # Supervisor traps exits, so we just ignore them
                    # The DOWN message from the monitor will handle restart
                    pass
                
                # Monitor DOWN - child exited
                case (msg_type, ref, _, pid, reason) if msg_type == DOWN:
                    shutting_down = await _handle_down(
                        children, ref, pid, reason, opts,
                        start_order, dynamic_children, pending_terminations
                    )
                
                # Add dynamic child
                case (msg_type, spec, reply_to) if msg_type == _ADD_CHILD:
                    await _handle_add_child(children, dynamic_children, spec, reply_to)
                
                # Terminate dynamic child
                case (msg_type, child_id, reply_to) if msg_type == _TERMINATE_CHILD:
                    await _handle_terminate_child(children, child_id, reply_to, pending_terminations)
                
                # Query operations
                case (msg_type, child_id, reply_to) if msg_type == _GET_CHILD_STATUS:
                    await _handle_get_child_status(children, child_id, reply_to)
                
                case (msg_type, reply_to) if msg_type == _LIST_CHILDREN:
                    await _handle_list_children(children, reply_to)
                
                case (msg_type, reply_to) if msg_type == _WHICH_CHILDREN:
                    await _handle_which_children(children, reply_to)
                
                case (msg_type, reply_to) if msg_type == _COUNT_CHILDREN:
                    await _handle_count_children(children, reply_to)
                
                # Shutdown
                case msg_type if msg_type == SHUTDOWN:
                    shutting_down = True
                
                case _:
                    # Ignore unknown messages
                    pass
        
        except Exception as e:
            import traceback
            print(f"[dynamic_supervisor] ERROR in main loop: {e}")
            traceback.print_exc()
    
    # Shutdown: terminate all children
    await _shutdown_children(children)


# ============================================================================
# Child Management
# ============================================================================

def _validate_child_spec(spec: child_spec):
    """Validate that a child spec is correct."""
    if not isinstance(spec, child_spec):
        raise ModuleError(f"Expected module_child_spec, got {type(spec)}")
    
    if not is_otp_module(spec.module):
        raise ModuleError(f"Child module {spec.module.__name__} is not an OTPModule")


async def _start_child(child: _ChildState):
    """Start a child process from its module_child_spec."""
    spec = child.spec
    module_class = spec.module
    behavior = get_behavior(module_class)
    
    # Import here to avoid circular dependency
    from otpylib import gen_server
    from otpylib import supervisor
    
    # Start based on behavior
    if behavior.name == 'gen_server':
        pid = await gen_server.start_link(
            module_class,
            init_arg=spec.args,
            name=spec.name
        )
    elif behavior.name == 'supervisor':
        pid = await supervisor.start_link(
            module_class,
            init_arg=spec.args,
            name=spec.name
        )
    else:
        raise RuntimeError(f"Unsupported child behavior: {behavior.name}")
    
    # Monitor the child
    monitor_ref = await process.monitor(pid)
    
    child.pid = pid
    child.monitor_ref = monitor_ref
    child.last_successful_start = time.time()


async def _shutdown_children(children: Dict[str, _ChildState]):
    """Shutdown all children on supervisor termination."""
    for child in children.values():
        if child.pid and process.is_alive(child.pid):
            try:
                await process.exit(child.pid, SUPERVISOR_SHUTDOWN)
            except Exception:
                pass


# ============================================================================
# Message Handlers
# ============================================================================

async def _handle_down(
    children: Dict[str, _ChildState],
    ref: str,
    pid: str,
    reason: Any,
    opts: options,
    start_order: List[str],
    dynamic_children: List[str],
    pending_terminations: Dict[str, str]
) -> bool:
    """Handle a DOWN message from a monitored child."""
    # Find the child
    child_id = next((cid for cid, c in children.items() if c.monitor_ref == ref), None)
    
    if not child_id:
        return False
    
    # Check if this was a pending termination FIRST (before handling exit)
    if child_id in pending_terminations:
        reply_to = pending_terminations.pop(child_id)
        await process.send(reply_to, (True, f"Child {child_id} terminated"))
    
    # Handle the child exit
    try:
        await _handle_child_exit(
            children, child_id, reason, opts,
            start_order, dynamic_children
        )
    except RuntimeError as e:
        # Restart intensity exceeded - shutdown supervisor
        print(f"[dynamic_supervisor] Restart intensity exceeded: {e}")
        return True
    
    return False


async def _handle_child_exit(
    children: Dict[str, _ChildState],
    child_id: str,
    reason: Any,
    opts: options,
    start_order: List[str],
    dynamic_children: List[str]
):
    """Handle a child exit and apply restart strategy."""
    child = children[child_id]
    
    # Unregister name if child had one
    if child.spec.name:
        try:
            await process.unregister(child.spec.name)
        except Exception:
            pass
    
    # Check if this is a normal shutdown
    if reason in [SHUTDOWN, SUPERVISOR_SHUTDOWN, KILLED]:
        if child.is_dynamic:
            # Remove dynamic children completely
            children.pop(child_id, None)
            if child_id in dynamic_children:
                dynamic_children.remove(child_id)
        else:
            # Mark static children as down
            child.pid = None
            child.monitor_ref = None
        return
    
    # Determine if we should restart
    failed = reason != NORMAL
    should_restart = True
    
    if child.spec.restart == TRANSIENT and not failed:
        should_restart = False
    elif child.spec.restart == TEMPORARY:
        should_restart = False
    
    if not should_restart:
        # No restart - remove if dynamic, mark down if static
        if child.is_dynamic:
            children.pop(child_id, None)
            if child_id in dynamic_children:
                dynamic_children.remove(child_id)
        else:
            child.pid = None
            child.monitor_ref = None
        return
    
    # Check restart intensity
    current_time = time.time()
    child.failure_times.append(current_time)
    cutoff = current_time - opts.max_seconds
    
    while child.failure_times and child.failure_times[0] < cutoff:
        child.failure_times.popleft()
    
    if len(child.failure_times) > opts.max_restarts:
        raise RuntimeError(f"Restart intensity exceeded for child {child_id}")
    
    # Apply restart strategy
    if opts.strategy == ONE_FOR_ONE:
        child.restart_count += 1
        await _start_child(child)
    
    elif opts.strategy == ONE_FOR_ALL:
        # Kill all other children
        for cid, other in children.items():
            if cid != child_id and other.pid and process.is_alive(other.pid):
                await process.exit(other.pid, KILLED)
        
        # Restart all children
        all_children = start_order + dynamic_children
        for cid in all_children:
            if cid in children:
                restart_child = children[cid]
                restart_child.restart_count += 1
                await _start_child(restart_child)
    
    elif opts.strategy == REST_FOR_ONE:
        # Find position and restart this child and all later ones
        all_children = start_order + dynamic_children
        try:
            idx = all_children.index(child_id)
            
            # Kill later children
            for cid in all_children[idx + 1:]:
                if cid in children:
                    other = children[cid]
                    if other.pid and process.is_alive(other.pid):
                        await process.exit(other.pid, KILLED)
            
            # Restart this and later children
            for cid in all_children[idx:]:
                if cid in children:
                    restart_child = children[cid]
                    restart_child.restart_count += 1
                    await _start_child(restart_child)
        except ValueError:
            # Child not in list, just restart it
            child.restart_count += 1
            await _start_child(child)


async def _handle_add_child(
    children: Dict[str, _ChildState],
    dynamic_children: List[str],
    spec: child_spec,
    reply_to: str
):
    """Handle request to add a dynamic child."""
    try:
        _validate_child_spec(spec)
        
        if spec.id in children:
            await process.send(reply_to, (False, f"Child {spec.id} already exists"))
            return
        
        # Create and start child
        child_state = _ChildState(spec=spec, is_dynamic=True)
        children[spec.id] = child_state
        dynamic_children.append(spec.id)
        
        await _start_child(child_state)
        await process.send(reply_to, (True, f"Child {spec.id} started successfully"))
    
    except Exception as e:
        # Cleanup on failure
        children.pop(spec.id, None)
        if spec.id in dynamic_children:
            dynamic_children.remove(spec.id)
        await process.send(reply_to, (False, f"Failed to start child: {e}"))


async def _handle_terminate_child(
    children: Dict[str, _ChildState],
    child_id: str,
    reply_to: str,
    pending_terminations: Dict[str, str]
):
    """Handle request to terminate a dynamic child."""
    child = children.get(child_id)
    
    if not child:
        await process.send(reply_to, (False, f"Child {child_id} not found"))
        return
    
    if not child.is_dynamic:
        await process.send(reply_to, (False, f"Cannot terminate static child {child_id}"))
        return
    
    if child.pid and process.is_alive(child.pid):
        # Send exit signal and wait for DOWN message
        await process.exit(child.pid, SUPERVISOR_SHUTDOWN)
        pending_terminations[child_id] = reply_to
    else:
        await process.send(reply_to, (True, f"Child {child_id} already terminated"))


async def _handle_get_child_status(
    children: Dict[str, _ChildState],
    child_id: str,
    reply_to: str
):
    """Handle request for child status."""
    child = children.get(child_id)
    
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


async def _handle_list_children(
    children: Dict[str, _ChildState],
    reply_to: str
):
    """Handle request to list all child IDs."""
    await process.send(reply_to, list(children.keys()))


async def _handle_which_children(
    children: Dict[str, _ChildState],
    reply_to: str
):
    """Handle request for detailed child information."""
    infos = []
    for child_id, child in children.items():
        infos.append({
            "id": child_id,
            "pid": child.pid,
            "module": child.spec.module.__mod_id__,
            "restart_count": child.restart_count,
            "is_dynamic": child.is_dynamic,
            "restart_type": str(child.spec.restart),
        })
    
    await process.send(reply_to, infos)


async def _handle_count_children(
    children: Dict[str, _ChildState],
    reply_to: str
):
    """Handle request for child counts."""
    counts = {
        "specs": len(children),
        "active": sum(1 for c in children.values() if c.pid and process.is_alive(c.pid)),
        "dynamic": sum(1 for c in children.values() if c.is_dynamic),
        "static": sum(1 for c in children.values() if not c.is_dynamic),
    }
    
    await process.send(reply_to, counts)
