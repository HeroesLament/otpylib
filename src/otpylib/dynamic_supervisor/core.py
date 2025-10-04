"""
Dynamic supervisor for managing both static and dynamically added children.

Uses the process API for BEAM-style supervision with the ability to add/remove
children at runtime via message passing.
"""

from collections.abc import Callable, Awaitable
from typing import Any, Dict, List, Optional, Tuple
import time
from collections import deque
from dataclasses import dataclass, field

from otpylib import process

from otpylib.dynamic_supervisor.atoms import (
    # Restart Strategy Atoms
    PERMANENT, TRANSIENT, TEMPORARY,

    # Supervisor Strategy Atoms
    ONE_FOR_ONE, ONE_FOR_ALL, REST_FOR_ONE,

    # Exit Reason Atoms
    NORMAL, SHUTDOWN, KILLED, SUPERVISOR_SHUTDOWN, SIBLING_RESTART_LIMIT,

    # Supervisor State Atoms
    STARTING, RUNNING, SHUTTING_DOWN, TERMINATED,

    # Dynamic Supervisor Message Atoms
    GET_CHILD_STATUS, LIST_CHILDREN, WHICH_CHILDREN, COUNT_CHILDREN,
    ADD_CHILD, TERMINATE_CHILD, RESTART_CHILD,

    # Process Message Atoms
    EXIT, DOWN, PROCESS,

    # Child Types
    WORKER, SUPERVISOR,

    # Dynamic Supervisor Specific
    DYNAMIC, STATIC,
)


@dataclass
class child_spec:
    id: str
    func: Callable[..., Awaitable[None]]
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    restart: Any = PERMANENT
    name: Optional[str] = None
    type: str = "worker"
    modules: List[str] = field(default_factory=list)


@dataclass
class options:
    max_restarts: int = 3
    max_seconds: int = 5
    strategy: Any = ONE_FOR_ONE


@dataclass
class _ChildState:
    spec: child_spec
    pid: Optional[str] = None
    monitor_ref: Optional[str] = None
    restart_count: int = 0
    failure_times: deque = field(default_factory=lambda: deque())
    last_successful_start: Optional[float] = None
    is_dynamic: bool = False


class DynamicSupervisorHandle:
    def __init__(self, supervisor_pid: str):
        self.supervisor_pid = supervisor_pid
    
    async def get_child_status(self, child_id: str) -> Optional[Dict[str, Any]]:
        await process.send(self.supervisor_pid, (GET_CHILD_STATUS, child_id, process.self()))
        return await process.receive(timeout=5.0)
    
    async def list_children(self) -> List[str]:
        await process.send(self.supervisor_pid, (LIST_CHILDREN, process.self()))
        return await process.receive(timeout=5.0)
    
    async def which_children(self) -> List[Dict[str, Any]]:
        await process.send(self.supervisor_pid, (WHICH_CHILDREN, process.self()))
        return await process.receive(timeout=5.0)
    
    async def count_children(self) -> Dict[str, int]:
        await process.send(self.supervisor_pid, (COUNT_CHILDREN, process.self()))
        return await process.receive(timeout=5.0)
    
    async def start_child(self, child_spec: child_spec) -> Tuple[bool, str]:
        await process.send(self.supervisor_pid, (ADD_CHILD, child_spec, process.self()))
        return await process.receive(timeout=5.0)
    
    async def terminate_child(self, child_id: str) -> Tuple[bool, str]:
        await process.send(self.supervisor_pid, (TERMINATE_CHILD, child_id, process.self()))
        return await process.receive(timeout=5.0)
    
    async def restart_child(self, child_id: str) -> Tuple[bool, str]:
        child_state = await self.get_child_status(child_id)
        if child_state and child_state.get("pid"):
            await process.exit(child_state["pid"], KILLED)
            return True, "restart_initiated"
        return False, "child_not_found"
    
    async def shutdown(self):
        await process.exit(self.supervisor_pid, SHUTDOWN)


async def start(child_specs: List[child_spec], opts: options = options(), name: Optional[str] = None) -> str:
    return await process.spawn(
        _dynamic_supervisor_loop,
        args=[child_specs, opts],
        name=name,
        mailbox=True,
    )


async def start_link(child_specs: List[child_spec], opts: options = options(), name: Optional[str] = None) -> str:
    return await process.spawn_link(
        _dynamic_supervisor_loop,
        args=[child_specs, opts],
        name=name,
        mailbox=True,
    )


async def _dynamic_supervisor_loop(child_specs: List[child_spec], opts: options):
    children: Dict[str, _ChildState] = {}
    start_order: List[str] = []
    dynamic_children: List[str] = []
    pending_terminations: Dict[str, str] = {}   # child_id -> reply_to
    shutting_down = False

    print("[SUP LOOP] initializing supervisor")

    # preload static children
    for spec in child_specs:
        print(f"[SUP LOOP] preload static child spec id={spec.id}")
        children[spec.id] = _ChildState(spec=spec, is_dynamic=False)
        start_order.append(spec.id)

    for child_id in start_order:
        print(f"[SUP LOOP] starting static child id={child_id}")
        await _start_child(children[child_id])
        print(f"[SUP LOOP] started static child id={child_id}, pid={children[child_id].pid}")

    while not shutting_down:
        try:
            msg = await process.receive()
            print(f"[SUP LOOP] received msg={msg}")

            match msg:
                # Exit signal
                case (msg_type, from_pid, reason) if msg_type == EXIT:
                    shutting_down = await _handle_exit(
                        children, from_pid, reason,
                        opts, start_order, dynamic_children,
                        pending_terminations
                    )

                # Monitor DOWN
                case (msg_type, ref, _, pid, reason) if msg_type == DOWN:
                    shutting_down = await _handle_down(
                        children, ref, pid, reason,
                        opts, start_order, dynamic_children,
                        pending_terminations
                    )

                # Add dynamic child
                case (msg_type, spec, reply_to) if msg_type == ADD_CHILD:
                    await _handle_add_child(children, dynamic_children, spec, reply_to)

                # Terminate dynamic child
                case (msg_type, child_id, reply_to) if msg_type == TERMINATE_CHILD:
                    await _handle_terminate_child(children, child_id, reply_to, pending_terminations)

                # Query child status
                case (msg_type, child_id, reply_to) if msg_type == GET_CHILD_STATUS:
                    await _handle_get_child_status(children, child_id, reply_to)

                # List children
                case (msg_type, reply_to) if msg_type == LIST_CHILDREN:
                    await _handle_list_children(children, reply_to)

                # Which children
                case (msg_type, reply_to) if msg_type == WHICH_CHILDREN:
                    await _handle_which_children(children, reply_to)

                # Count children
                case (msg_type, reply_to) if msg_type == COUNT_CHILDREN:
                    await _handle_count_children(children, reply_to)

                # Shutdown supervisor
                case msg_type if msg_type == SHUTDOWN:
                    print("[SUP LOOP] shutdown requested")
                    shutting_down = True

                # Fallback
                case _:
                    print(f"[SUP LOOP] unhandled msg={msg}")

        except Exception as e:
            import traceback
            print(f"[SUP LOOP] EXCEPTION: {e}")
            traceback.print_exc()

    # Supervisor shutdown: kill children
    print("[SUP LOOP] supervisor shutting down, killing children")
    for child in children.values():
        if child.pid and process.is_alive(child.pid):
            print(f"[SUP LOOP] killing child id={child.spec.id} pid={child.pid}")
            await process.exit(child.pid, SUPERVISOR_SHUTDOWN)


# ----------------------------------------------------------------------
# Handlers
# ----------------------------------------------------------------------

async def _handle_exit(children, from_pid, reason, opts, start_order, dynamic_children, pending_terminations):
    print(f"[SUP EXIT] pid={from_pid}, reason={reason}")
    child_id = next((cid for cid, c in children.items() if c.pid == from_pid), None)
    if child_id:
        print(f"[SUP EXIT] matched child_id={child_id}")
        await _handle_child_exit(children, child_id, reason, opts, start_order, dynamic_children)
        if child_id in pending_terminations:
            reply_to = pending_terminations.pop(child_id)
            print(f"[SUP EXIT] reply terminate ack for child={child_id}")
            await process.send(reply_to, (True, f"Child {child_id} terminated successfully"))
    return False


async def _handle_down(children, ref, pid, reason, opts, start_order, dynamic_children, pending_terminations):
    print(f"[SUP DOWN] ref={ref}, pid={pid}, reason={reason}")
    child_id = next((cid for cid, c in children.items() if c.monitor_ref == ref), None)
    if child_id:
        print(f"[SUP DOWN] matched child_id={child_id}")
        await _handle_child_exit(children, child_id, reason, opts, start_order, dynamic_children)
        if child_id in pending_terminations:
            reply_to = pending_terminations.pop(child_id)
            print(f"[SUP DOWN] reply terminate ack for child={child_id}")
            await process.send(reply_to, (True, f"Child {child_id} terminated successfully"))
    return False


async def _handle_add_child(children, dynamic_children, spec, reply_to):
    print(f"[SUP ADD_CHILD] request for child_id={spec.id}")
    success, message = await _add_child(children, dynamic_children, spec)
    print(f"[SUP ADD_CHILD] result for id={spec.id}: success={success}, message={message}")
    await process.send(reply_to, (success, message))


async def _handle_terminate_child(children, child_id, reply_to, pending_terminations):
    print(f"[SUP TERMINATE_CHILD] request id={child_id}")
    child = children.get(child_id)
    if not child:
        print(f"[SUP TERMINATE_CHILD] child {child_id} not found")
        await process.send(reply_to, (False, f"Child {child_id} not found"))
    elif not child.is_dynamic:
        print(f"[SUP TERMINATE_CHILD] cannot terminate static child {child_id}")
        await process.send(reply_to, (False, f"Cannot terminate static child {child_id}"))
    elif child.pid and process.is_alive(child.pid):
        print(f"[SUP TERMINATE_CHILD] sending exit to pid={child.pid}")
        await process.exit(child.pid, SUPERVISOR_SHUTDOWN)
        pending_terminations[child_id] = reply_to
    else:
        print(f"[SUP TERMINATE_CHILD] child {child_id} already dead")
        await process.send(reply_to, (True, f"Child {child_id} already dead"))


async def _handle_get_child_status(children, child_id, reply_to):
    print(f"[SUP GET_CHILD_STATUS] id={child_id}")
    child = children.get(child_id)
    if child:
        status = {
            "id": child_id,
            "pid": child.pid,
            "alive": process.is_alive(child.pid) if child.pid else False,
            "restart_count": child.restart_count,
            "type": child.spec.type,
            "is_dynamic": child.is_dynamic,
        }
    else:
        status = None
    print(f"[SUP GET_CHILD_STATUS] status={status}")
    await process.send(reply_to, status)


async def _handle_list_children(children, reply_to):
    print(f"[SUP LIST_CHILDREN] -> {list(children.keys())}")
    await process.send(reply_to, list(children.keys()))


async def _handle_which_children(children, reply_to):
    infos = []
    for cid, child in children.items():
        infos.append(
            {
                "id": cid,
                "pid": child.pid,
                "type": child.spec.type,
                "restart_count": child.restart_count,
                "is_dynamic": child.is_dynamic,
                "restart_type": str(child.spec.restart),
                "modules": child.spec.modules,
            }
        )
    print(f"[SUP WHICH_CHILDREN] infos={infos}")
    await process.send(reply_to, infos)


async def _handle_count_children(children, reply_to):
    counts = {
        "specs": len(children),
        "active": sum(1 for c in children.values() if c.pid and process.is_alive(c.pid)),
        "supervisors": sum(1 for c in children.values() if c.spec.type == "supervisor"),
        "workers": sum(1 for c in children.values() if c.spec.type == "worker"),
        "dynamic": sum(1 for c in children.values() if c.is_dynamic),
        "static": sum(1 for c in children.values() if not c.is_dynamic),
    }
    print(f"[SUP COUNT_CHILDREN] counts={counts}")
    await process.send(reply_to, counts)


async def _add_child(children: Dict[str, _ChildState], dynamic_children: List[str], child_spec_obj: child_spec) -> Tuple[bool, str]:
    if child_spec_obj.id in children:
        return False, f"Child {child_spec_obj.id} already exists"
    child_state = _ChildState(spec=child_spec_obj, is_dynamic=True)
    children[child_spec_obj.id] = child_state
    dynamic_children.append(child_spec_obj.id)
    try:
        await _start_child(child_state)
        return True, f"Child {child_spec_obj.id} started successfully"
    except Exception as e:
        children.pop(child_spec_obj.id, None)
        if child_spec_obj.id in dynamic_children:
            dynamic_children.remove(child_spec_obj.id)
        return False, f"Failed to start child: {e}"


async def _start_child(child: _ChildState):
    """
    Start a child process and monitor it.
    - If spec.name is given: supervisor registers it automatically.
    - If no name: expect the child function to return a PID string.
    """
    if child.spec.name:
        # Named child: supervisor owns registration
        pid, monitor_ref = await process.spawn_monitor(
            child.spec.func,
            args=child.spec.args,
            kwargs=child.spec.kwargs,
            name=child.spec.name,
            mailbox=True,
        )
    else:
        # Anonymous: run func, expect it to spawn and return a PID
        result_pid = await child.spec.func(*child.spec.args, **child.spec.kwargs)
        if not isinstance(result_pid, str):
            raise RuntimeError(
                f"Child function {child.spec.func.__name__} must return a PID string "
                f"when no name is given, got {type(result_pid).__name__}"
            )
        pid = result_pid
        monitor_ref = await process.monitor(pid)

    child.pid = pid
    child.monitor_ref = monitor_ref
    child.last_successful_start = time.time()


async def _handle_child_exit(
    children: Dict[str, _ChildState],
    child_id: str,
    reason: Any,
    opts: options,
    start_order: List[str],
    dynamic_children: List[str],
):
    child = children[child_id]
    failed = reason not in [NORMAL, SUPERVISOR_SHUTDOWN] and reason != KILLED

    # Clean up registry if child had a global name
    if child.spec.name:
        try:
            await process.unregister(child.spec.name)
        except Exception:
            pass

    if reason in [SHUTDOWN, SUPERVISOR_SHUTDOWN]:
        # Remove dynamic children fully
        if child.is_dynamic:
            children.pop(child_id, None)
            if child_id in dynamic_children:
                dynamic_children.remove(child_id)
        else:
            child.pid = None
            child.monitor_ref = None
        return

    # Decide restart policy
    should_restart = True
    if child.spec.restart == TRANSIENT and not failed:
        should_restart = False
    elif child.spec.restart == TEMPORARY:
        should_restart = False

    if should_restart:
        current_time = time.time()
        child.failure_times.append(current_time)
        cutoff = current_time - opts.max_seconds
        while child.failure_times and child.failure_times[0] < cutoff:
            child.failure_times.popleft()
        if len(child.failure_times) > opts.max_restarts:
            raise RuntimeError(f"Restart limit exceeded for child {child_id}")

        # Restart strategies
        if opts.strategy == ONE_FOR_ALL:
            for cid, other in children.items():
                if cid != child_id and other.pid and process.is_alive(other.pid):
                    await process.exit(other.pid, KILLED)
            all_children = start_order + dynamic_children
            for cid in all_children:
                if cid in children:
                    restart_child = children[cid]
                    restart_child.restart_count += 1
                    await _start_child(restart_child)

        elif opts.strategy == REST_FOR_ONE:
            all_children = start_order + dynamic_children
            try:
                idx = all_children.index(child_id)
                # Kill later siblings
                for cid in all_children[idx + 1:]:
                    if cid in children:
                        other_child = children[cid]
                        if other_child.pid and process.is_alive(other_child.pid):
                            await process.exit(other_child.pid, KILLED)
                # Restart this and later
                for cid in all_children[idx:]:
                    if cid in children:
                        restart_child = children[cid]
                        restart_child.restart_count += 1
                        await _start_child(restart_child)
            except ValueError:
                child.restart_count += 1
                await _start_child(child)
        else:
            child.restart_count += 1
            await _start_child(child)
    else:
        # No restart: purge if dynamic, clear if static
        if child.is_dynamic:
            children.pop(child_id, None)
            if child_id in dynamic_children:
                dynamic_children.remove(child_id)
        else:
            child.pid = None
            child.monitor_ref = None


async def start_child(sup_pid: str, spec: child_spec):
    print(f"[API start_child] sending add_child for {spec.id} to {sup_pid}")
    await process.send(sup_pid, (ADD_CHILD, spec, process.self()))
    result = await process.receive(timeout=5.0)
    print(f"[API start_child] got reply {result}")
    return result


async def terminate_child(sup_pid: str, child_id: str):
    print(f"[API terminate_child] sending terminate_child for {child_id} to {sup_pid}")
    await process.send(sup_pid, (TERMINATE_CHILD, child_id, process.self()))
    result = await process.receive(timeout=5.0)
    print(f"[API terminate_child] got reply {result}")
    return result


async def list_children(supervisor_pid: str) -> List[str]:
    """
    Get a list of child IDs under the supervisor.
    """
    await process.send(supervisor_pid, (LIST_CHILDREN, process.self()))
    return await process.receive(timeout=5.0)


async def which_children(supervisor_pid: str) -> List[Dict[str, Any]]:
    """
    Get detailed info for each child (id, pid, type, restart_count, etc.).
    """
    await process.send(supervisor_pid, (WHICH_CHILDREN, process.self()))
    return await process.receive(timeout=5.0)


async def count_children(supervisor_pid: str) -> Dict[str, int]:
    """
    Return counts of specs, active processes, supervisors, workers,
    dynamic vs static.
    """
    await process.send(supervisor_pid, (COUNT_CHILDREN, process.self()))
    return await process.receive(timeout=5.0)
