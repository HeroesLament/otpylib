"""
Static supervisor for managing persistent, long-running processes.

Provides BEAM-style supervision strategies with OTP-like restart limits:
- No normal exits: any child exit not initiated by the supervisor is a fault.
- Global restart intensity window: every restarted child increments the counter.
"""

from collections.abc import Callable, Awaitable
from typing import Any, Dict, List, Optional
import time
from collections import deque
from dataclasses import dataclass, field

from otpylib import atom, process
from otpylib.runtime.backends.base import ProcessNotFoundError

from otpylib.supervisor.atoms import (
    PERMANENT, TRANSIENT, TEMPORARY,
    ONE_FOR_ONE, ONE_FOR_ALL, REST_FOR_ONE,
    SUPERVISOR_SHUTDOWN,
    GET_CHILD_STATUS, LIST_CHILDREN,
    SHUTDOWN, KILLED,
)

# --------------------------------------------------------------------------------------
# Specs & Options
# --------------------------------------------------------------------------------------

@dataclass
class child_spec:
    id: str
    func: Callable[..., Awaitable[None]]
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    restart: Any = PERMANENT
    name: Optional[str] = None


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


class _IntensityExceeded(Exception):
    pass


# --------------------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------------------

def _record_restart(intensity_times: deque, opts: options) -> bool:
    """Record a restart attempt and check if intensity exceeded."""
    now = time.time()
    intensity_times.append(now)
    cutoff = now - opts.max_seconds
    while intensity_times and intensity_times[0] < cutoff:
        intensity_times.popleft()
    return len(intensity_times) > opts.max_restarts


async def _mark_down(child: _ChildState):
    if child.pid and child.spec.name:
        try:
            await process.unregister(child.spec.name)
        except Exception:
            pass
    child.pid = None
    child.monitor_ref = None


def _safe_is_alive(pid: Optional[str]) -> bool:
    if not pid:
        return False
    try:
        return process.is_alive(pid)
    except ProcessNotFoundError:
        return False


async def _shutdown_children(children: Dict[str, _ChildState]):
    for c in children.values():
        if _safe_is_alive(c.pid):
            try:
                await process.exit(c.pid, SUPERVISOR_SHUTDOWN)
            except ProcessNotFoundError:
                pass


async def _start_child(child: _ChildState):
    """
    Start a child and monitor it. 
    
    Calls the child function which should return a PID of the spawned process.
    The supervisor then monitors that returned PID.
    """
    # Call the child function - it should return a PID
    result_pid = await child.spec.func(*child.spec.args, **child.spec.kwargs)
    
    if not isinstance(result_pid, str):
        raise RuntimeError(
            f"Child function {child.spec.func.__name__} must return a PID string, "
            f"got {type(result_pid).__name__}"
        )
    
    # Monitor the returned PID
    monitor_ref = await process.monitor(result_pid)
    child.pid = result_pid
    child.monitor_ref = monitor_ref


async def _restart_child(child: _ChildState, intensity_times: deque, opts: options):
    """Restart a single child with intensity accounting."""
    if _record_restart(intensity_times, opts):
        raise _IntensityExceeded()

    await _mark_down(child)
    child.restart_count += 1
    await _start_child(child)


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------

class SupervisorHandle:
    def __init__(self, supervisor_pid: str, state_getter: Callable):
        self.supervisor_pid = supervisor_pid
        self._get_state = state_getter

    async def get_child_status(self, child_id: str) -> Optional[Dict[str, Any]]:
        await process.send(self.supervisor_pid, (GET_CHILD_STATUS, child_id, process.self()))
        return await process.receive(timeout=5.0)

    async def list_children(self) -> List[str]:
        await process.send(self.supervisor_pid, (LIST_CHILDREN, process.self()))
        return await process.receive(timeout=5.0)

    async def shutdown(self):
        await process.exit(self.supervisor_pid, SHUTDOWN)


async def get_child_status(sup_pid: str, child_id: str):
    """Query a supervisor for the status of one child."""
    me = process.self()
    await process.send(sup_pid, (GET_CHILD_STATUS, child_id, me))
    return await process.receive()

async def list_children(sup_pid: str):
    """Query a supervisor for the list of all child IDs."""
    me = process.self()
    await process.send(sup_pid, (LIST_CHILDREN, me))
    return await process.receive()

async def start(
    child_specs: List[child_spec],
    opts: options = options(),
    name: Optional[str] = None,
) -> str:
    """Start supervisor and wait for init handshake (OTP style)."""
    if name and process.whereis(name) is not None:
        raise RuntimeError(f"Supervisor name '{name}' is already registered")

    parent = process.self()
    sup_pid = await process.spawn(
        _supervisor_loop,
        args=[child_specs, opts],
        name=name,
        mailbox=True,
    )

    # Handshake: request init, wait for ack
    await process.send(sup_pid, ("INIT", parent))
    msg = await process.receive(timeout=5.0)

    match msg:
        case ("ok", pid, child_ids) if pid == sup_pid:
            return sup_pid
        case ("error", reason):
            raise RuntimeError(f"Supervisor init failed: {reason}")
        case other:
            raise RuntimeError(f"Unexpected init reply: {other!r}")


async def start_link(
    child_specs: List[child_spec],
    opts: options = options(),
    name: Optional[str] = None,
) -> str:
    """Start supervisor linked to caller, OTP-style handshake."""
    if name and process.whereis(name) is not None:
        raise RuntimeError(f"Supervisor name '{name}' is already registered")
    parent = process.self()
    sup_pid = await process.spawn_link(
        _supervisor_loop,
        args=[child_specs, opts],
        name=name,
        mailbox=True,
    )
    await process.send(sup_pid, ("INIT", parent))
    msg = await process.receive(timeout=5.0)
    match msg:
        case ("ok", pid, child_ids) if pid == sup_pid:
            return sup_pid
        case ("error", reason):
            raise RuntimeError(f"Supervisor init failed: {reason}")
        case other:
            raise RuntimeError(f"Unexpected init reply: {other!r}")


# --------------------------------------------------------------------------------------
# Supervisor loop
# --------------------------------------------------------------------------------------

async def _supervisor_loop(child_specs: List[child_spec], opts: options):
    DOWN_ATOM = atom.ensure("DOWN")
    EXIT_ATOM = atom.ensure("EXIT")

    children: Dict[str, _ChildState] = {}
    start_order: List[str] = []
    shutting_down = False
    intensity_times: deque = deque()

    # ------------------------------------------------------------------
    # Handshake phase: wait for INIT from parent
    # ------------------------------------------------------------------
    while True:
        msg = await process.receive()
        match msg:
            case ("INIT", reply_to):
                try:
                    # Build child states
                    for spec in child_specs:
                        children[spec.id] = _ChildState(spec=spec)
                        start_order.append(spec.id)

                    # Start children
                    for child_id in start_order:
                        await _start_child(children[child_id])

                    # Ack parent with children list
                    child_ids = list(children.keys())
                    await process.send(reply_to, ("ok", process.self(), child_ids))
                except Exception as e:
                    await process.send(reply_to, ("error", e))
                    return  # supervisor dies on init error
                break  # done with handshake
            case _:
                # Ignore anything else until INIT arrives
                continue

    # ------------------------------------------------------------------
    # Main supervisor loop
    # ------------------------------------------------------------------
    while not shutting_down:
        try:
            msg = await process.receive()

            match msg:
                # Exit from linked child
                case (msg_type, from_pid, reason) if msg_type == EXIT_ATOM:
                    cid = next((cid for cid, ch in children.items() if ch.pid == from_pid), None)
                    if cid:
                        await _handle_child_exit(children, cid, reason, opts, start_order, intensity_times)

                # Monitor DOWN
                case (msg_type, ref, _, _pid, reason) if msg_type == DOWN_ATOM:
                    cid = next((cid for cid, ch in children.items() if ch.monitor_ref == ref), None)
                    if cid and reason != KILLED:
                        await _handle_child_exit(children, cid, reason, opts, start_order, intensity_times)

                # Query status
                case (msg_type, cid, reply_to) if msg_type == GET_CHILD_STATUS:
                    ch = children.get(cid)
                    if ch:
                        alive = _safe_is_alive(ch.pid)
                        status = {
                            "pid": ch.pid,
                            "alive": alive,
                            "restart_count": ch.restart_count,
                        }
                    else:
                        status = None
                    await process.send(reply_to, status)

                # List children
                case (msg_type, reply_to) if msg_type == LIST_CHILDREN:
                    await process.send(reply_to, list(children.keys()))

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
            # keep supervisor alive on unexpected error
            pass

    await _shutdown_children(children)

# --------------------------------------------------------------------------------------
# Exit handler
# --------------------------------------------------------------------------------------

async def _handle_child_exit(
    children: Dict[str, _ChildState],
    dead_id: str,
    reason: Any,
    opts: options,
    start_order: List[str],
    intensity_times: deque,
):
    child = children[dead_id]

    # Static sup → no NORMAL exits. Anything not SHUTDOWN is abnormal.
    if reason == SHUTDOWN or reason == SUPERVISOR_SHUTDOWN:
        await _mark_down(child)
        return

    # Determine restart based on strategy
    if opts.strategy == ONE_FOR_ONE:
        if child.spec.name:
            try:
                await process.unregister(child.spec.name)
            except Exception:
                pass
        await _restart_child(child, intensity_times, opts)

    elif opts.strategy == ONE_FOR_ALL:
        # Kill everyone
        for cid, other in children.items():
            if _safe_is_alive(other.pid):
                try:
                    await process.exit(other.pid, SUPERVISOR_SHUTDOWN)
                except ProcessNotFoundError:
                    pass
            await _mark_down(other)

        # Restart in order
        for cid in start_order:
            await _restart_child(children[cid], intensity_times, opts)

    elif opts.strategy == REST_FOR_ONE:
        idx = start_order.index(dead_id)
        victims = start_order[idx:]  # crashed child + later ones
        # Kill victims
        for cid in victims:
            c = children[cid]
            if _safe_is_alive(c.pid):
                try:
                    await process.exit(c.pid, SUPERVISOR_SHUTDOWN)
                except ProcessNotFoundError:
                    pass
            await _mark_down(c)
        # Restart victims
        for cid in victims:
            await _restart_child(children[cid], intensity_times, opts)

    else:
        # Unknown strategy → do nothing
        pass
