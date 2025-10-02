"""
Generic Server using Process API

Strict BEAM-aligned: no global state registry.  
Each GenServer owns its own state; other processes cannot reach in.
"""

from typing import Callable, TypeVar, Union, Optional, Any, Dict
from types import ModuleType
import logging
import time
import uuid
import asyncio
from dataclasses import dataclass

from otpylib import process
from otpylib.gen_server.atoms import (
    STOP_ACTION,
    CRASH,
)

State = TypeVar("State")

# Only needed for bridging calls outside process context
_PENDING_CALLS: Dict[str, asyncio.Future] = {}
_CALL_COUNTER = 0

logger = logging.getLogger(__name__)


class GenServerExited(Exception):
    """Raised when the generic server exited during a call."""
    def __init__(self, reason: Any = None):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Reply:
    payload: Any


@dataclass
class NoReply:
    pass


@dataclass
class Stop:
    reason: Any = STOP_ACTION


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

async def start(
    module: ModuleType,
    init_arg: Optional[Any] = None,
    name: Optional[str] = None,
) -> str:
    """
    Start a GenServer process (unlinked).
    
    BEAM semantics: Spawns a new process, waits for init to complete, returns PID.
    """
    if name is None:
        name = module.__name__
    
    caller_pid = process.self()
    if not caller_pid:
        raise RuntimeError("gen_server.start() must be called from within a process")
    
    # Spawn the GenServer loop
    pid = await process.spawn(
        _gen_server_loop,
        args=[module, init_arg, caller_pid],
        name=name,
        mailbox=True,
    )
    
    # Wait for init handshake
    msg = await process.receive(timeout=5.0)
    
    match msg:
        case ("gen_server_init_ok", init_pid) if init_pid == pid:
            logger.debug(f"[gen_server.start] module={module}, name={name}, pid={pid}")
            return pid
        case ("gen_server_init_error", init_pid, reason) if init_pid == pid:
            raise RuntimeError(f"GenServer init failed: {reason}")
        case _:
            raise RuntimeError(f"Unexpected init reply: {msg}")


async def start_link(
    module: ModuleType,
    init_arg: Optional[Any] = None,
    name: Optional[str] = None,
) -> str:
    """
    Start a GenServer process linked to the caller.
    
    BEAM semantics: Spawns a new linked process, waits for init to complete, returns PID.
    """
    if name is None:
        name = module.__name__
    
    caller_pid = process.self()
    if not caller_pid:
        raise RuntimeError("gen_server.start_link() must be called from within a process")
    
    # Spawn and link the GenServer loop
    pid = await process.spawn_link(
        _gen_server_loop,
        args=[module, init_arg, caller_pid],
        name=name,
        mailbox=True,
    )
    
    # Wait for init handshake
    msg = await process.receive(timeout=5.0)
    
    match msg:
        case ("gen_server_init_ok", init_pid) if init_pid == pid:
            logger.debug(f"[gen_server.start_link] module={module}, name={name}, pid={pid}")
            return pid
        case ("gen_server_init_error", init_pid, reason) if init_pid == pid:
            raise RuntimeError(f"GenServer init failed: {reason}")
        case _:
            raise RuntimeError(f"Unexpected init reply: {msg}")

async def call(
    target: Union[str, str],
    payload: Any,
    timeout: Optional[float] = None,
) -> Any:
    global _CALL_COUNTER
    _CALL_COUNTER += 1
    call_id = f"call_{_CALL_COUNTER}_{uuid.uuid4().hex[:8]}"

    caller_pid = process.self()
    
    if caller_pid:
        return await _call_from_process(target, payload, timeout, call_id, caller_pid)
    else:
        return await _call_from_outside_process(target, payload, timeout, call_id)

async def cast(target: Union[str, str], payload: Any) -> None:
    message = _CastMessage(payload=payload)
    logger.debug(f"[gen_server.cast] target={target}, payload={payload}")
    await process.send(target, message)


async def reply(caller: Union[str, Callable], response: Any) -> None:
    if callable(caller):
        await caller(response)
    else:
        await process.send(caller, response)


# ============================================================================
# Internal helpers
# ============================================================================

async def _call_from_process(
    target: str,
    payload: Any,
    timeout: Optional[float],
    call_id: str,
    caller_pid: str,
) -> Any:
    
    # Always try to resolve the name to PID
    target_pid = process.whereis(target)
    
    # If whereis returns None or returns the target itself (name not found), fail
    if not target_pid or target_pid == target:
        raise ValueError(f"GenServer '{target}' not found in registry")
    
    # Monitor the PID, not the name
    ref = await process.monitor(target_pid)
    
    try:
        message = _CallMessage(reply_to=caller_pid, payload=payload, call_id=call_id)
        
        # Send to the original target (could be name or PID)
        await process.send(target, message)
        logger.debug(f"[gen_server._call_from_process] sent call_id={call_id} to {target}")

        start_time = time.time()
        while True:
            remaining_timeout = None
            if timeout:
                elapsed = time.time() - start_time
                remaining_timeout = timeout - elapsed
                if remaining_timeout <= 0:
                    raise TimeoutError("GenServer call timed out")

            try:
                reply = await process.receive(timeout=remaining_timeout)
            except TimeoutError:
                raise TimeoutError("GenServer call timed out")

            if isinstance(reply, tuple) and len(reply) == 2 and reply[0] == call_id:
                _, result = reply
                logger.debug(f"[gen_server._call_from_process] got reply for call_id={call_id}: {result}")
                if isinstance(result, Exception):
                    if isinstance(result, GenServerExited):
                        raise result
                    else:
                        raise result
                return result

            if (
                isinstance(reply, tuple)
                and len(reply) == 4
                and reply[0] == "DOWN"
                and reply[1] == ref
                and reply[2] == target_pid
            ):
                reason = reply[3]
                logger.debug(f"[gen_server._call_from_process] target {target} died mid-call, reason={reason}")
                raise GenServerExited(reason)

    finally:
        await process.demonitor(ref, flush=True)

async def _call_from_outside_process(
    target: str,
    payload: Any,
    timeout: Optional[float],
    call_id: str,
) -> Any:
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
        raise TimeoutError("GenServer call timed out")

async def _gen_server_loop(module, init_arg, caller_pid=None):
    """Main GenServer loop, owns its state privately."""
    init_fn = getattr(module, "init", None)
    state = None
    
    if init_fn is not None:
        try:
            state = await init_fn(init_arg)
            
            # Send init success to caller
            if caller_pid:
                await process.send(caller_pid, ("gen_server_init_ok", process.self()))
        except Exception as e:
            # Send init failure to caller
            if caller_pid:
                await process.send(caller_pid, ("gen_server_init_error", process.self(), e))
            raise
    else:
        # No init function - still send success
        if caller_pid:
            await process.send(caller_pid, ("gen_server_init_ok", process.self()))

    try:
        while True:
            try:
                message = await process.receive()
            except Exception as e:
                import traceback
                traceback.print_exc()
                raise

            match message:
                case _CallMessage():
                    state = await _handle_call(module, message, state)
                case _CastMessage():
                    state = await _handle_cast(module, message, state)
                case _:
                    state = await _handle_info(module, message, state)

    except GenServerExited as e:
        try:
            await _terminate(module, e.reason, state)
        except Exception:
            logger.error("[gen_server.loop] terminate callback raised", exc_info=True)
        raise

    except Exception as e:
        try:
            await _terminate(module, CRASH, state)
        except Exception:
            logger.error("[gen_server.loop] terminate callback raised", exc_info=True)
        logger.error("[gen_server.loop] crashed with %s", e, exc_info=True)
        raise GenServerExited(CRASH)

# ============================================================================
# Message handlers
# ============================================================================

async def _handle_call(module: ModuleType, message: _CallMessage, state: Any) -> Any:
    handler = getattr(module, "handle_call", None)
    if handler is None:
        error = NotImplementedError("handle_call not implemented")
        await process.send(message.reply_to, (message.call_id, error))
        return state

    async def reply_fn(payload):
        await process.send(message.reply_to, (message.call_id, payload))

    result = await handler(message.payload, reply_fn, state)

    match result:
        case (Reply(payload), new_state):
            await process.send(message.reply_to, (message.call_id, payload))
            return new_state
        case (NoReply(), new_state):
            return new_state
        case (Stop(reason), new_state):
            await process.send(message.reply_to, (message.call_id, GenServerExited(reason)))
            raise GenServerExited(reason)
        case _:
            raise TypeError(f"Invalid handle_call return value: {result}")


async def _handle_cast(module: ModuleType, message: Any, state: Any) -> Any:
    handler = getattr(module, "handle_cast", None)
    if handler is None:
        raise NotImplementedError("handle_cast not implemented")

    result = await handler(message, state)

    match result:
        case (NoReply(), new_state):
            return new_state
        case (Stop(reason), new_state):
            reason_atom = reason or STOP_ACTION
            raise GenServerExited(reason_atom)
        case _:
            raise TypeError(f"Invalid handle_cast return value: {result}")


async def _handle_info(module: ModuleType, message: Any, state: Any) -> Any:
    handler = getattr(module, "handle_info", None)
    if handler is None:
        return state

    result = await handler(message, state)

    match result:
        case (NoReply(), new_state):
            return new_state
        case (Stop(reason), new_state):
            reason_atom = reason or STOP_ACTION
            raise GenServerExited(reason_atom)
        case _:
            raise TypeError(f"Invalid handle_info return value: {result}")


# ============================================================================
# Termination
# ============================================================================

async def _terminate(module, reason, state):
    handler = getattr(module, "terminate", None)

    if handler is not None:
        try:
            await handler(reason, state)
        except Exception as e:
            logger.error(f"Error in terminate handler: {e}", exc_info=True)
    elif reason is not None:
        logger.error(f"GenServer terminated with reason={reason}", exc_info=True)
