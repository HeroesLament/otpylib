"""
Generic Server using Process API

Strict BEAM-aligned: no global state registry.
Each GenServer owns its own state; other processes cannot reach in.
"""

from typing import TypeVar, Union, Optional, Any, Dict
from types import ModuleType
import time
import uuid
import asyncio
from dataclasses import dataclass

from otpylib import atom, process
from otpylib.gen_server.atoms import (
    STOP_ACTION,
    CRASH,
    DOWN,
    EXIT,
    TIMEOUT,
)
from otpylib.gen_server.data import Reply, NoReply, Stop

# Logger target atom
LOGGER = atom.ensure("logger")

State = TypeVar("State")

# Only needed for bridging calls outside process context
_PENDING_CALLS: Dict[str, asyncio.Future] = {}
_CALL_COUNTER = 0


# ============================================================================
# Exceptions
# ============================================================================

class GenServerContractError(Exception):
    """Base class for all GenServer contract violations."""


class GenServerBadArity(GenServerContractError):
    def __init__(self, func_name: str, expected: int, got: int):
        super().__init__(f"{func_name} expected {expected} args, got {got}")
        self.func_name = func_name
        self.expected = expected
        self.got = got


class GenServerBadReturn(GenServerContractError):
    def __init__(self, value: Any):
        super().__init__(f"Invalid return from GenServer handler: {value!r}")
        self.value = value


class GenServerExited(Exception):
    """Raised when the generic server exited during a call."""
    def __init__(self, reason: Any = None):
        super().__init__(reason)
        self.reason = reason


# ============================================================================
# Internal Messages
# ============================================================================

@dataclass
class _CallMessage:
    reply_to: str
    payload: Any
    call_id: str


@dataclass
class _CastMessage:
    payload: Any


# ============================================================================
# Public API
# ============================================================================

async def start(module: ModuleType, init_arg: Optional[Any] = None, name: Optional[str] = None) -> str:
    """Start a GenServer process (unlinked)."""
    caller_pid = process.self()
    if not caller_pid:
        raise RuntimeError("gen_server.start() must be called from within a process")

    pid = await process.spawn(
        _gen_server_loop,
        args=[module, init_arg, caller_pid],
        name=name,
        mailbox=True,
    )

    # Buffer messages that aren't our init response
    buffered_messages = []
    
    try:
        while True:
            msg = await process.receive(timeout=5.0)
            match msg:
                case ("gen_server_init_ok", init_pid) if init_pid == pid:
                    # Re-inject buffered messages back into our mailbox
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    
                    modname = getattr(module, "name", getattr(module, "__name__", str(module)))
                    await process.send(LOGGER, ("log", "DEBUG",
                        f"[gen_server.start] module={modname}, name={name}, pid={pid} init ok",
                        {"module": modname, "pid": pid, "name": name}))
                    return pid
                case ("gen_server_init_error", init_pid, reason) if init_pid == pid:
                    # Re-inject buffered messages even on error
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    raise RuntimeError(f"[gen_server.start] module={module} pid={pid} init failed: {reason}")
                case ("gen_server_init_ok", init_pid) | ("gen_server_init_error", init_pid, _):
                    # Init message for a different pid - this is unexpected, preserve original error
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    raise RuntimeError(f"[gen_server.start] module={module} pid={pid} unexpected init reply: {msg}")
                case _:
                    # Not an init message - buffer it and keep waiting
                    buffered_messages.append(msg)
    except TimeoutError:
        # Re-inject buffered messages on timeout too
        for buffered_msg in buffered_messages:
            await process.send(caller_pid, buffered_msg)
        raise TimeoutError(f"[gen_server.start] module={module} pid={pid} init timeout after 5.0s")


async def start_link(module: ModuleType, init_arg: Optional[Any] = None, name: Optional[str] = None) -> str:
    """Start a GenServer process linked to the caller."""
    caller_pid = process.self()
    if not caller_pid:
        raise RuntimeError("gen_server.start_link() must be called from within a process")

    pid = await process.spawn_link(
        _gen_server_loop,
        args=[module, init_arg, caller_pid],
        name=name,
        mailbox=True,
    )

    # Buffer messages that aren't our init response
    buffered_messages = []
    
    try:
        while True:
            msg = await process.receive(timeout=5.0)
            match msg:
                case ("gen_server_init_ok", init_pid) if init_pid == pid:
                    # Re-inject buffered messages back into our mailbox
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    
                    modname = getattr(module, "name", getattr(module, "__name__", str(module)))
                    await process.send(LOGGER, ("log", "DEBUG",
                        f"[gen_server.start_link] module={modname}, name={name}, pid={pid} init ok",
                        {"module": modname, "pid": pid, "name": name}))
                    return pid
                case ("gen_server_init_error", init_pid, reason) if init_pid == pid:
                    # Re-inject buffered messages even on error
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    raise RuntimeError(f"[gen_server.start_link] module={module} pid={pid} init failed: {reason}")
                case ("gen_server_init_ok", init_pid) | ("gen_server_init_error", init_pid, _):
                    # Init message for a different pid - this is unexpected, preserve original error
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    raise RuntimeError(f"[gen_server.start_link] module={module} pid={pid} unexpected init reply: {msg}")
                case _:
                    # Not an init message - buffer it and keep waiting
                    buffered_messages.append(msg)
    except TimeoutError:
        # Re-inject buffered messages on timeout too
        for buffered_msg in buffered_messages:
            await process.send(caller_pid, buffered_msg)
        raise TimeoutError(f"[gen_server.start_link] module={module} pid={pid} init timeout after 5.0s")


async def call(target: Union[str, str], payload: Any, timeout: Optional[float] = None) -> Any:
    """Synchronous call to a GenServer (awaits reply)."""
    global _CALL_COUNTER
    _CALL_COUNTER += 1
    call_id = f"call_{_CALL_COUNTER}_{uuid.uuid4().hex[:8]}"

    caller_pid = process.self()
    if caller_pid:
        return await _call_from_process(target, payload, timeout, call_id, caller_pid)
    else:
        return await _call_from_outside_process(target, payload, timeout, call_id)


async def cast(target: Union[str, str], payload: Any) -> None:
    """Asynchronous cast to a GenServer (no reply)."""
    message = _CastMessage(payload=payload)
    await process.send(LOGGER, ("log", "DEBUG",
        f"[gen_server.cast] target={target}, payload={payload}",
        {"target": target, "payload": payload}))
    await process.send(target, message)


async def reply(from_: tuple[str, str], response: Any) -> None:
    """Reply to a GenServer call from inside handle_call."""
    reply_to, call_id = from_
    await process.send(reply_to, (call_id, response))


# ============================================================================
# Internal helpers
# ============================================================================

async def _call_from_process(target: str, payload: Any, timeout: Optional[float], call_id: str, caller_pid: str) -> Any:
    target_pid = process.whereis(target)
    if not target_pid or target_pid == target:
        raise ValueError(f"GenServer '{target}' not found in registry")

    ref = await process.monitor(target_pid)
    try:
        message = _CallMessage(reply_to=caller_pid, payload=payload, call_id=call_id)
        await process.send(target, message)
        await process.send(LOGGER, ("log", "DEBUG",
            f"[gen_server._call_from_process] call_id={call_id} target={target} from={caller_pid}",
            {"call_id": call_id, "target": target, "from": caller_pid}))

        start_time = time.time()
        while True:
            remaining_timeout = None
            if timeout:
                elapsed = time.time() - start_time
                remaining_timeout = timeout - elapsed
                if remaining_timeout <= 0:
                    raise TimeoutError(f"gen_server.call {call_id} timed out")

            reply = await process.receive(timeout=remaining_timeout)

            if isinstance(reply, tuple) and len(reply) == 2 and reply[0] == call_id:
                _, result = reply
                if isinstance(result, Exception):
                    raise result
                return result

            if (
                isinstance(reply, tuple)
                and len(reply) == 4
                and reply[0] == DOWN
                and reply[1] == ref
                and reply[2] == target_pid
            ):
                reason = reply[3]
                raise GenServerExited(reason)

    finally:
        await process.demonitor(ref, flush=True)


async def _call_from_outside_process(target: str, payload: Any, timeout: Optional[float], call_id: str) -> Any:
    future = asyncio.Future()
    _PENDING_CALLS[call_id] = future

    async def bridge_process():
        try:
            result = await _call_from_process(target, payload, timeout, call_id, process.self())
            if not future.done():
                future.set_result(result)
        except Exception as e:
            if not future.done():
                future.set_exception(e)
        finally:
            _PENDING_CALLS.pop(call_id, None)

    await process.spawn(bridge_process)

    try:
        if timeout:
            return await asyncio.wait_for(future, timeout)
        else:
            return await future
    except asyncio.TimeoutError:
        raise TimeoutError(f"gen_server.call {call_id} timed out")


# ============================================================================
# GenServer loop
# ============================================================================

async def _gen_server_loop(module: ModuleType, init_arg: Any, caller_pid: str) -> None:
    pid = process.self()
    modname = getattr(module, "name", getattr(module, "__name__", str(module)))

    # --- Init handshake ---
    try:
        init_fn = getattr(module, "init", None)
        if init_fn is None:
            await process.send(caller_pid, ("gen_server_init_error", pid, "no init/1 defined"))
            return

        result = await init_fn(init_arg)
        state = result  # allow simple `return state`

        await process.send(caller_pid, ("gen_server_init_ok", pid))
        await process.send(LOGGER, ("log", "DEBUG",
            f"[gen_server.init] module={modname}, pid={pid} initialized",
            {"module": modname, "pid": pid}))

    except Exception as e:
        await process.send(caller_pid, ("gen_server_init_error", pid, repr(e)))
        return

    # --- Main loop ---
    try:
        while True:
            msg = await process.receive()
            try:
                match msg:
                    case _CallMessage() as call:
                        state = await _handle_call(module, call, state)
                    case _CastMessage() as cast_msg:
                        state = await _handle_cast(module, cast_msg, state)
                    case (action, reason) if action == STOP_ACTION:
                        await process.send(LOGGER, ("log", "DEBUG",
                            f"[gen_server.loop] module={modname}, pid={pid} stop requested: {reason}",
                            {"module": modname, "pid": pid, "reason": reason}))
                        raise GenServerExited(reason)
                    case _:
                        state = await _handle_info(module, msg, state)

            except Exception as e:
                await process.send(LOGGER, ("log", "ERROR",
                    f"[gen_server.loop] module={modname}, pid={pid} crashed with {repr(e)}",
                    {"module": modname, "pid": pid, "exception": repr(e)}))
                raise

    except GenServerExited as e:
        await process.send(LOGGER, ("log", "INFO",
            f"[gen_server.loop] module={modname}, pid={pid} stopped: {e}",
            {"module": modname, "pid": pid, "reason": str(e)}))
        raise
    except Exception as e:
        await process.send(LOGGER, ("log", "ERROR",
            f"[gen_server.loop] module={modname}, pid={pid} terminated abnormally: {repr(e)}",
            {"module": modname, "pid": pid, "exception": repr(e)}))
        raise


# ============================================================================
# Message handlers
# ============================================================================

async def _handle_call(module, message, state):
    handler = getattr(module, "handle_call", None)
    if handler is None:
        error = NotImplementedError("handle_call not implemented")
        await process.send(message.reply_to, (message.call_id, error))
        return state

    result = await handler(message.payload, (message.reply_to, message.call_id), state)

    match result:
        case (Reply(payload=payload), new_state):
            await process.send(message.reply_to, (message.call_id, payload))
            return new_state
        case (NoReply(), new_state):
            return new_state
        case (Stop(reason=reason), new_state):
            await process.send(message.reply_to, (message.call_id, GenServerExited(reason)))
            raise GenServerExited(reason)
        case _:
            raise GenServerBadReturn(result)


async def _handle_cast(module, message: _CastMessage, state: Any) -> Any:
    handler = getattr(module, "handle_cast", None)
    if handler is None:
        return state

    result = await handler(message.payload, state)

    match result:
        case (NoReply(), new_state):
            return new_state
        case (Stop(reason=reason), new_state):
            raise GenServerExited(reason or STOP_ACTION)
        case _:
            raise GenServerBadReturn(result)


async def _handle_info(module: ModuleType, message: Any, state: Any) -> Any:
    handler = getattr(module, "handle_info", None)
    if handler is None:
        return state

    result = await handler(message, state)

    match result:
        case (NoReply(), new_state):
            return new_state
        case (Stop(reason=reason), new_state):
            raise GenServerExited(reason or STOP_ACTION)
        case _:
            raise GenServerBadReturn(result)


# ============================================================================
# Termination
# ============================================================================

async def _terminate(module, reason, state):
    handler = getattr(module, "terminate", None)
    modname = getattr(module, "name", getattr(module, "__name__", str(module)))
    if handler is not None:
        try:
            await handler(reason, state)
        except Exception as e:
            await process.send(LOGGER, ("log", "ERROR",
                f"[gen_server.terminate] module={modname}, pid={process.self()} error in terminate handler: {e}",
                {"module": modname, "pid": process.self(), "exception": repr(e)}))
    elif reason is not None:
        await process.send(LOGGER, ("log", "ERROR",
            f"[gen_server.terminate] module={modname}, pid={process.self()} terminated with reason={reason}",
            {"module": modname, "pid": process.self(), "reason": reason}))