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
    PERMANENT, TRANSIENT, TEMPORARY,
    ONE_FOR_ONE, ONE_FOR_ALL, REST_FOR_ONE,
    SUPERVISOR_SHUTDOWN,
    GET_CHILD_STATUS, LIST_CHILDREN, WHICH_CHILDREN, COUNT_CHILDREN,
    ADD_CHILD, TERMINATE_CHILD,
    DOWN, EXIT, NORMAL, SHUTDOWN, KILLED,
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
    from otpylib.atom import ensure
    DOWN_ATOM = ensure("DOWN")
    EXIT_ATOM = ensure("EXIT")
    ADD_CHILD_ATOM = ensure("add_child")
    TERMINATE_CHILD_ATOM = ensure("terminate_child")
    WHICH_CHILDREN_ATOM = ensure("which_children")
    COUNT_CHILDREN_ATOM = ensure("count_children")
    
    children: Dict[str, _ChildState] = {}
    start_order: List[str] = []
    dynamic_children: List[str] = []
    shutting_down = False
    
    for spec in child_specs:
        children[spec.id] = _ChildState(spec=spec, is_dynamic=False)
        start_order.append(spec.id)
    
    for child_id in start_order:
        await _start_child(children[child_id])
    
    while not shutting_down:
        try:
            msg = await process.receive()
            match msg:
                case (msg_type, from_pid, reason) if msg_type == EXIT_ATOM:
                    child_id = next((cid for cid, c in children.items() if c.pid == from_pid), None)
                    if child_id:
                        await _handle_child_exit(children, child_id, reason, opts, start_order, dynamic_children)
                
                case (msg_type, ref, _, pid, reason) if msg_type == DOWN_ATOM:
                    child_id = next((cid for cid, c in children.items() if c.monitor_ref == ref), None)
                    if child_id:
                        await _handle_child_exit(children, child_id, reason, opts, start_order, dynamic_children)
                
                case (msg_type, child_spec_obj, reply_to) if msg_type == ADD_CHILD_ATOM:
                    success, message = await _add_child(children, dynamic_children, child_spec_obj)
                    await process.send(reply_to, (success, message))
                
                case (msg_type, child_id, reply_to) if msg_type == TERMINATE_CHILD_ATOM:
                    success, message = await _terminate_child(children, dynamic_children, child_id)
                    await process.send(reply_to, (success, message))
                
                case (msg_type, child_id, reply_to) if msg_type == GET_CHILD_STATUS:
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
                    await process.send(reply_to, status)
                
                case (msg_type, reply_to) if msg_type == LIST_CHILDREN:
                    await process.send(reply_to, list(children.keys()))
                
                case (msg_type, reply_to) if msg_type == WHICH_CHILDREN_ATOM:
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
                    await process.send(reply_to, infos)
                
                case (msg_type, reply_to) if msg_type == COUNT_CHILDREN_ATOM:
                    counts = {
                        "specs": len(children),
                        "active": sum(1 for c in children.values() if c.pid and process.is_alive(c.pid)),
                        "supervisors": sum(1 for c in children.values() if c.spec.type == "supervisor"),
                        "workers": sum(1 for c in children.values() if c.spec.type == "worker"),
                        "dynamic": sum(1 for c in children.values() if c.is_dynamic),
                        "static": sum(1 for c in children.values() if not c.is_dynamic),
                    }
                    await process.send(reply_to, counts)
                
                case msg_type if msg_type == SHUTDOWN:
                    shutting_down = True
                    break
                
                case _:
                    pass
        except Exception:
            pass
    
    for child in children.values():
        if child.pid and process.is_alive(child.pid):
            await process.exit(child.pid, SUPERVISOR_SHUTDOWN)


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


async def _terminate_child(children: Dict[str, _ChildState], dynamic_children: List[str], child_id: str) -> Tuple[bool, str]:
    child = children.get(child_id)
    if not child:
        return False, f"Child {child_id} not found"
    if not child.is_dynamic:
        return False, f"Cannot terminate static child {child_id}"
    if child.pid and process.is_alive(child.pid):
        await process.exit(child.pid, SUPERVISOR_SHUTDOWN)
    children.pop(child_id, None)
    if child_id in dynamic_children:
        dynamic_children.remove(child_id)
    return True, f"Child {child_id} terminated successfully"


async def _start_child(child: _ChildState):
    pid, monitor_ref = await process.spawn_monitor(
        child.spec.func,
        args=child.spec.args,
        kwargs=child.spec.kwargs,
        name=child.spec.name,
        mailbox=True,
    )
    child.pid = pid
    child.monitor_ref = monitor_ref
    child.last_successful_start = time.time()


async def _handle_child_exit(children: Dict[str, _ChildState], child_id: str, reason: Any, opts: options, start_order: List[str], dynamic_children: List[str]):
    child = children[child_id]
    failed = reason not in [NORMAL, SUPERVISOR_SHUTDOWN] and reason != KILLED
    if reason in [SHUTDOWN, SUPERVISOR_SHUTDOWN]:
        if child.is_dynamic:
            children.pop(child_id, None)
            if child_id in dynamic_children:
                dynamic_children.remove(child_id)
        return
    
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
        
        if opts.strategy == ONE_FOR_ALL:
            for cid, other_child in children.items():
                if cid != child_id and other_child.pid and process.is_alive(other_child.pid):
                    await process.exit(other_child.pid, KILLED)
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
                for cid in all_children[idx + 1:]:
                    if cid in children:
                        other_child = children[cid]
                        if other_child.pid and process.is_alive(other_child.pid):
                            await process.exit(other_child.pid, KILLED)
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
        if child.is_dynamic:
            children.pop(child_id, None)
            if child_id in dynamic_children:
                dynamic_children.remove(child_id)
        else:
            child.pid = None
            child.monitor_ref = None


async def start_child(supervisor_pid: str, child_spec_obj: child_spec) -> Tuple[bool, str]:
    await process.send(supervisor_pid, (ADD_CHILD, child_spec_obj, process.self()))
    return await process.receive(timeout=5.0)


async def terminate_child(supervisor_pid: str, child_id: str) -> Tuple[bool, str]:
    await process.send(supervisor_pid, (TERMINATE_CHILD, child_id, process.self()))
    return await process.receive(timeout=5.0)


async def list_children(supervisor_pid: str) -> List[str]:
    await process.send(supervisor_pid, (LIST_CHILDREN, process.self()))
    return await process.receive(timeout=5.0)


async def which_children(supervisor_pid: str) -> List[Dict[str, Any]]:
    await process.send(supervisor_pid, (WHICH_CHILDREN, process.self()))
    return await process.receive(timeout=5.0)


async def count_children(supervisor_pid: str) -> Dict[str, int]:
    await process.send(supervisor_pid, (COUNT_CHILDREN, process.self()))
    return await process.receive(timeout=5.0)
