"""
Module-aware Generic Server (gen_server)

Adapted from gen_server to work with OTPModule metaclass-based modules.
Uses module metadata and validates behavior contracts.

Differences from gen_server:
- Accepts OTPModule classes instead of ModuleType
- Uses __callbacks__ metadata instead of getattr
- Validates GEN_SERVER behavior before starting
- Creates module instances (not just module references)
"""

from typing import TypeVar, Union, Optional, Any, Dict
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
from otpylib.module import (
    OTPModule,
    GEN_SERVER,
    is_otp_module,
    get_behavior,
    ModuleError
)

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


class NotAGenServerError(ModuleError):
    """Module is not a gen_server behavior."""
    def __init__(self, module_class: type):
        behavior = get_behavior(module_class) if is_otp_module(module_class) else None
        super().__init__(
            f"Module {module_class.__name__} is not a gen_server "
            f"(behavior: {behavior.name if behavior else 'unknown'})"
        )


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
# Module Validation
# ============================================================================

def _validate_gen_server_module(module_class: type) -> None:
    """
    Validate that a class is an OTPModule with gen_server behavior.
    Raises NotAGenServerError if validation fails.
    """
    if not is_otp_module(module_class):
        raise NotAGenServerError(module_class)
    
    behavior = get_behavior(module_class)
    if behavior != GEN_SERVER:
        raise NotAGenServerError(module_class)


# ============================================================================
# Public API
# ============================================================================

async def start(module_class: type, init_arg: Optional[Any] = None, name: Optional[str] = None) -> str:
    """
    Start a GenServer process (unlinked).
    
    Args:
        module_class: OTPModule class with gen_server behavior
        init_arg: Argument passed to init callback
        name: Optional registered name for the process
    
    Returns:
        Process PID
    """
    _validate_gen_server_module(module_class)
    
    caller_pid = process.self()
    if not caller_pid:
        raise RuntimeError("gen_server.start() must be called from within a process")

    pid = await process.spawn(
        _gen_server_loop,
        args=[module_class, init_arg, caller_pid],
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
                    
                    modname = module_class.__mod_id__
                    await process.send(LOGGER, ("log", "DEBUG",
                        f"[gen_server.start] module={modname}, name={name}, pid={pid} init ok",
                        {"module": modname, "pid": pid, "name": name}))
                    return pid
                case ("gen_server_init_error", init_pid, reason) if init_pid == pid:
                    # Re-inject buffered messages even on error
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    raise RuntimeError(f"[gen_server.start] module={modname} pid={pid} init failed: {reason}")
                case ("gen_server_init_ok", init_pid) | ("gen_server_init_error", init_pid, _):
                    # Init message for a different pid - this is unexpected
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    raise RuntimeError(f"[gen_server.start] unexpected init reply: {msg}")
                case _:
                    # Not an init message - buffer it and keep waiting
                    buffered_messages.append(msg)
    except TimeoutError:
        # Re-inject buffered messages on timeout too
        for buffered_msg in buffered_messages:
            await process.send(caller_pid, buffered_msg)
        raise TimeoutError(f"[gen_server.start] module={module_class.__mod_id__} pid={pid} init timeout after 5.0s")


async def start_link(module_class: type, init_arg: Optional[Any] = None, name: Optional[str] = None) -> str:
    """
    Start a GenServer process linked to the caller.
    
    Args:
        module_class: OTPModule class with gen_server behavior
        init_arg: Argument passed to init callback
        name: Optional registered name for the process
    
    Returns:
        Process PID
    """
    _validate_gen_server_module(module_class)
    
    caller_pid = process.self()
    if not caller_pid:
        raise RuntimeError("gen_server.start_link() must be called from within a process")

    pid = await process.spawn_link(
        _gen_server_loop,
        args=[module_class, init_arg, caller_pid],
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
                    
                    modname = module_class.__mod_id__
                    await process.send(LOGGER, ("log", "DEBUG",
                        f"[gen_server.start_link] module={modname}, name={name}, pid={pid} init ok",
                        {"module": modname, "pid": pid, "name": name}))
                    return pid
                case ("gen_server_init_error", init_pid, reason) if init_pid == pid:
                    # Re-inject buffered messages even on error
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    raise RuntimeError(f"[gen_server.start_link] module={module_class.__mod_id__} pid={pid} init failed: {reason}")
                case ("gen_server_init_ok", init_pid) | ("gen_server_init_error", init_pid, _):
                    # Init message for a different pid - this is unexpected
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    raise RuntimeError(f"[gen_server.start_link] unexpected init reply: {msg}")
                case _:
                    # Not an init message - buffer it and keep waiting
                    buffered_messages.append(msg)
    except TimeoutError:
        # Re-inject buffered messages on timeout too
        for buffered_msg in buffered_messages:
            await process.send(caller_pid, buffered_msg)
        raise TimeoutError(f"[gen_server.start_link] module={module_class.__mod_id__} pid={pid} init timeout after 5.0s")


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

async def _gen_server_loop(module_class: type, init_arg: Any, caller_pid: str) -> None:
    """
    Main GenServer loop - creates module instance and processes messages.
    
    Key difference from gen_server: Creates an instance of the module class
    so callbacks are called as methods on that instance.
    """
    pid = process.self()
    modname = module_class.__mod_id__

    # --- Init handshake ---
    try:
        # Create module instance first
        module_instance = module_class()
        
        # Get init callback - it's stored as an unbound function in __callbacks__
        # We need to get the bound method from the instance instead
        if not hasattr(module_instance, 'init'):
            await process.send(caller_pid, ("gen_server_init_error", pid, "no init callback defined"))
            return
        
        # Call init as a bound method
        result = await module_instance.init(init_arg)
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
                        state = await _handle_call(module_instance, module_class, call, state)
                    case _CastMessage() as cast_msg:
                        state = await _handle_cast(module_instance, module_class, cast_msg, state)
                    case (action, reason) if action == STOP_ACTION:
                        await process.send(LOGGER, ("log", "DEBUG",
                            f"[gen_server.loop] module={modname}, pid={pid} stop requested: {reason}",
                            {"module": modname, "pid": pid, "reason": reason}))
                        raise GenServerExited(reason)
                    case _:
                        state = await _handle_info(module_instance, module_class, msg, state)

            except Exception as e:
                print(f"[gen_server] Process {pid} caught exception in message handler: {type(e).__name__}: {e}")
                await process.send(LOGGER, ("log", "ERROR",
                    f"[gen_server.loop] module={modname}, pid={pid} crashed with {repr(e)}",
                    {"module": modname, "pid": pid, "exception": repr(e)}))
                print(f"[gen_server] Process {pid} about to re-raise exception and die")
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

async def _handle_call(module_instance, module_class, message, state):
    """
    Handle call message using module's handle_call callback.
    """
    if not hasattr(module_instance, 'handle_call'):
        error = NotImplementedError("handle_call not implemented")
        await process.send(message.reply_to, (message.call_id, error))
        return state

    # Call handler as bound method
    result = await module_instance.handle_call(message.payload, (message.reply_to, message.call_id), state)

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


async def _handle_cast(module_instance, module_class, message: _CastMessage, state: Any) -> Any:
    """Handle cast message using module's handle_cast callback."""
    if not hasattr(module_instance, 'handle_cast'):
        return state

    result = await module_instance.handle_cast(message.payload, state)

    match result:
        case (NoReply(), new_state):
            return new_state
        case (Stop(reason=reason), new_state):
            raise GenServerExited(reason or STOP_ACTION)
        case _:
            raise GenServerBadReturn(result)


async def _handle_info(module_instance, module_class, message: Any, state: Any) -> Any:
    """Handle info message using module's handle_info callback."""
    if not hasattr(module_instance, 'handle_info'):
        return state

    result = await module_instance.handle_info(message, state)

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

async def _terminate(module_instance, module_class, reason, state):
    """Call terminate callback if defined."""
    handler = module_class.__callbacks__.get('terminate')
    modname = module_class.__mod_id__
    
    if handler is not None:
        try:
            await handler(module_instance, reason, state)
        except Exception as e:
            await process.send(LOGGER, ("log", "ERROR",
                f"[gen_server.terminate] module={modname}, pid={process.self()} error in terminate handler: {e}",
                {"module": modname, "pid": process.self(), "exception": repr(e)}))
    elif reason is not None:
        await process.send(LOGGER, ("log", "ERROR",
            f"[gen_server.terminate] module={modname}, pid={process.self()} terminated with reason={reason}",
            {"module": modname, "pid": process.self(), "reason": reason}))
