"""
Module-aware Generic State Machine (gen_statem)

Adapted from gen_statem to work with OTPModule metaclass-based modules.
Implements a state machine with explicit state names and data.

Key differences from gen_server:
- Has both state_name (str/atom) and state_data (Any)
- Callbacks are state-specific: handle_event(event_type, event, state_name, data)
- Supports state timeouts and event postponing
- Can use state_functions or handle_event_function callback mode

Usage:
    class MyStatem(metaclass=OTPModule, behavior=GEN_STATEM, version="1.0.0"):
        async def callback_mode(self):
            return CallbackMode.STATE_FUNCTIONS
        
        async def init(self, arg):
            return ("initial_state", {"data": arg})
        
        async def state_initial_state(self, event_type, event, data):
            # Handle events in this state
            return NextState("next_state", new_data, actions=[...])
"""

from typing import TypeVar, Union, Optional, Any, Dict, Literal
import time
import uuid
import asyncio
from dataclasses import dataclass
from enum import Enum

from otpylib import atom, process
from otpylib.gen_server.atoms import (
    STOP_ACTION,
    DOWN,
    TIMEOUT,
)
from otpylib.module import (
    OTPModule,
    is_otp_module,
    get_behavior,
    ModuleError
)

# Logger target atom
LOGGER = atom.ensure("logger")

# New behavior constant (would be defined in otpylib.module)
GEN_STATEM = atom.ensure("gen_statem")

StateData = TypeVar("StateData")
# State names are typically atoms, but can also be tuples like (atom, atom) or (str, str)
# Common patterns: atom.ensure("locked"), (atom.ensure("connected"), atom.ensure("auth"))
StateName = Any  # Atom preferred, but supports tuples for hierarchical states

# Event types
class EventType(str, Enum):
    CALL = "call"
    CAST = "cast"
    INFO = "info"
    TIMEOUT = "timeout"
    INTERNAL = "internal"
    STATE_TIMEOUT = "state_timeout"

# Callback modes
class CallbackMode(str, Enum):
    STATE_FUNCTIONS = "state_functions"  # Each state has its own callback
    HANDLE_EVENT_FUNCTION = "handle_event_function"  # Single handler for all states

# Only needed for bridging calls outside process context
_PENDING_CALLS: Dict[str, asyncio.Future] = {}
_CALL_COUNTER = 0


# ============================================================================
# Action/Transition Results
# ============================================================================

@dataclass
class NextState:
    """Transition to a new state."""
    state_name: StateName
    state_data: Any
    actions: list = None
    
    def __post_init__(self):
        if self.actions is None:
            self.actions = []


@dataclass
class KeepState:
    """Stay in current state."""
    state_data: Any
    actions: list = None
    
    def __post_init__(self):
        if self.actions is None:
            self.actions = []


@dataclass
class RepeatState:
    """Re-enter current state (runs entry actions)."""
    state_data: Any
    actions: list = None
    
    def __post_init__(self):
        if self.actions is None:
            self.actions = []


@dataclass
class StopState:
    """Stop the state machine."""
    reason: Any = None
    state_data: Any = None


# ============================================================================
# State Actions
# ============================================================================

@dataclass
class ReplyAction:
    """Reply to a call."""
    from_: tuple
    reply: Any


@dataclass
class StateTimeoutAction:
    """Set a timeout for this state."""
    timeout: float
    event_content: Any = None


@dataclass
class PostponeAction:
    """Postpone current event until next state change."""
    pass


@dataclass
class NextEventAction:
    """Insert an internal event to be processed next."""
    event_type: EventType
    event_content: Any


# ============================================================================
# Exceptions
# ============================================================================

class GenStatemContractError(Exception):
    """Base class for all GenStatem contract violations."""


class GenStatemBadReturn(GenStatemContractError):
    def __init__(self, value: Any):
        super().__init__(f"Invalid return from GenStatem handler: {value!r}")
        self.value = value


class GenStatemExited(Exception):
    """Raised when the state machine exited during a call."""
    def __init__(self, reason: Any = None):
        super().__init__(reason)
        self.reason = reason


class NotAGenStatemError(ModuleError):
    """Module is not a gen_statem behavior."""
    def __init__(self, module_class: type):
        behavior = get_behavior(module_class) if is_otp_module(module_class) else None
        super().__init__(
            f"Module {module_class.__name__} is not a gen_statem "
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


@dataclass
class _TimeoutMessage:
    timeout_type: str
    event_content: Any


# ============================================================================
# Module Validation
# ============================================================================

def _validate_gen_statem_module(module_class: type) -> None:
    """
    Validate that a class is an OTPModule with gen_statem behavior.
    Raises NotAGenStatemError if validation fails.
    """
    if not is_otp_module(module_class):
        raise NotAGenStatemError(module_class)
    
    behavior = get_behavior(module_class)
    if behavior != GEN_STATEM:
        raise NotAGenStatemError(module_class)


# ============================================================================
# Public API
# ============================================================================

async def start(
    module_class: type, 
    init_arg: Optional[Any] = None, 
    name: Optional[str] = None
) -> str:
    """
    Start a GenStatem process (unlinked).
    
    Args:
        module_class: Class created with OTPModule metaclass and GEN_STATEM behavior
        init_arg: Argument passed to init callback
        name: Optional registered name for the process
    
    Returns:
        Process PID
    """
    _validate_gen_statem_module(module_class)
    
    caller_pid = process.self()
    if not caller_pid:
        raise RuntimeError("gen_statem.start() must be called from within a process")

    pid = await process.spawn(
        _gen_statem_loop,
        args=[module_class, init_arg, caller_pid],
        name=name,
        mailbox=True,
    )

    buffered_messages = []
    
    try:
        while True:
            msg = await process.receive(timeout=5.0)
            match msg:
                case ("gen_statem_init_ok", init_pid) if init_pid == pid:
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    
                    modname = module_class.__mod_id__
                    await process.send(LOGGER, ("log", "DEBUG",
                        f"[gen_statem.start] module={modname}, name={name}, pid={pid} init ok",
                        {"module": modname, "pid": pid, "name": name}))
                    return pid
                case ("gen_statem_init_error", init_pid, reason) if init_pid == pid:
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    raise RuntimeError(f"[gen_statem.start] init failed: {reason}")
                case _:
                    buffered_messages.append(msg)
    except TimeoutError:
        for buffered_msg in buffered_messages:
            await process.send(caller_pid, buffered_msg)
        raise TimeoutError(f"[gen_statem.start] init timeout after 5.0s")


async def start_link(
    module_class: type, 
    init_arg: Optional[Any] = None, 
    name: Optional[str] = None
) -> str:
    """
    Start a GenStatem process linked to the caller.
    """
    _validate_gen_statem_module(module_class)
    
    caller_pid = process.self()
    if not caller_pid:
        raise RuntimeError("gen_statem.start_link() must be called from within a process")

    pid = await process.spawn_link(
        _gen_statem_loop,
        args=[module_class, init_arg, caller_pid],
        name=name,
        mailbox=True,
    )

    buffered_messages = []
    
    try:
        while True:
            msg = await process.receive(timeout=5.0)
            match msg:
                case ("gen_statem_init_ok", init_pid) if init_pid == pid:
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    
                    modname = module_class.__mod_id__
                    await process.send(LOGGER, ("log", "DEBUG",
                        f"[gen_statem.start_link] module={modname}, pid={pid} init ok",
                        {"module": modname, "pid": pid}))
                    return pid
                case ("gen_statem_init_error", init_pid, reason) if init_pid == pid:
                    for buffered_msg in buffered_messages:
                        await process.send(caller_pid, buffered_msg)
                    raise RuntimeError(f"[gen_statem.start_link] init failed: {reason}")
                case _:
                    buffered_messages.append(msg)
    except TimeoutError:
        for buffered_msg in buffered_messages:
            await process.send(caller_pid, buffered_msg)
        raise TimeoutError(f"[gen_statem.start_link] init timeout")


async def call(target: Union[str, str], payload: Any, timeout: Optional[float] = None) -> Any:
    """Synchronous call to a GenStatem (awaits reply)."""
    global _CALL_COUNTER
    _CALL_COUNTER += 1
    call_id = f"call_{_CALL_COUNTER}_{uuid.uuid4().hex[:8]}"

    caller_pid = process.self()
    if caller_pid:
        return await _call_from_process(target, payload, timeout, call_id, caller_pid)
    else:
        return await _call_from_outside_process(target, payload, timeout, call_id)


async def cast(target: Union[str, str], payload: Any) -> None:
    """Asynchronous cast to a GenStatem (no reply)."""
    message = _CastMessage(payload=payload)
    await process.send(LOGGER, ("log", "DEBUG",
        f"[gen_statem.cast] target={target}, payload={payload}",
        {"target": target, "payload": payload}))
    await process.send(target, message)


# ============================================================================
# Internal call helpers
# ============================================================================

async def _call_from_process(
    target: str, 
    payload: Any, 
    timeout: Optional[float], 
    call_id: str, 
    caller_pid: str
) -> Any:
    target_pid = process.whereis(target)
    if not target_pid or target_pid == target:
        raise ValueError(f"GenStatem '{target}' not found in registry")

    ref = await process.monitor(target_pid)
    try:
        message = _CallMessage(reply_to=caller_pid, payload=payload, call_id=call_id)
        await process.send(target, message)

        start_time = time.time()
        while True:
            remaining_timeout = None
            if timeout:
                elapsed = time.time() - start_time
                remaining_timeout = timeout - elapsed
                if remaining_timeout <= 0:
                    raise TimeoutError(f"gen_statem.call {call_id} timed out")

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
                raise GenStatemExited(reason)

    finally:
        await process.demonitor(ref, flush=True)


async def _call_from_outside_process(
    target: str, 
    payload: Any, 
    timeout: Optional[float], 
    call_id: str
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
        raise TimeoutError(f"gen_statem.call {call_id} timed out")


# ============================================================================
# GenStatem loop
# ============================================================================

async def _gen_statem_loop(module_class: type, init_arg: Any, caller_pid: str) -> None:
    """
    Main GenStatem loop - maintains state machine.
    
    Key difference from gen_server: module_class is created by OTPModule metaclass,
    so we instantiate it to get callback methods.
    """
    pid = process.self()
    modname = module_class.__mod_id__

    # --- Init handshake ---
    try:
        # Instantiate the module class (created by metaclass)
        module_instance = module_class()
        
        if not hasattr(module_instance, 'init'):
            await process.send(caller_pid, ("gen_statem_init_error", pid, "no init callback"))
            return
        
        if not hasattr(module_instance, 'callback_mode'):
            await process.send(caller_pid, ("gen_statem_init_error", pid, "no callback_mode defined"))
            return
        
        # Get callback mode
        callback_mode = await module_instance.callback_mode()
        if callback_mode not in [CallbackMode.STATE_FUNCTIONS, CallbackMode.HANDLE_EVENT_FUNCTION]:
            await process.send(caller_pid, ("gen_statem_init_error", pid, f"invalid callback_mode: {callback_mode}"))
            return
        
        # Init returns (state_name, state_data) or (state_name, state_data, actions)
        result = await module_instance.init(init_arg)
        
        if isinstance(result, tuple) and len(result) == 2:
            state_name, state_data = result
            actions = []
        elif isinstance(result, tuple) and len(result) == 3:
            state_name, state_data, actions = result
        else:
            await process.send(caller_pid, ("gen_statem_init_error", pid, f"invalid init return: {result}"))
            return

        await process.send(caller_pid, ("gen_statem_init_ok", pid))
        await process.send(LOGGER, ("log", "DEBUG",
            f"[gen_statem.init] module={modname}, pid={pid}, initial_state={state_name}",
            {"module": modname, "pid": pid, "state": state_name}))

    except Exception as e:
        await process.send(caller_pid, ("gen_statem_init_error", pid, repr(e)))
        return

    # --- Main loop state ---
    postponed_events = []
    state_timeout_ref = None

    # Process initial actions
    for action in actions:
        if isinstance(action, StateTimeoutAction):
            if state_timeout_ref:
                await process.cancel_timer(state_timeout_ref)
            state_timeout_ref = await _schedule_timeout(pid, action)

    # --- Main loop ---
    try:
        while True:
            msg = await process.receive()
            
            try:
                # Convert message to event
                event_type, event_content, from_ = _message_to_event(msg)
                
                # Handle the event
                result = await _handle_event(
                    module_instance,
                    callback_mode,
                    event_type,
                    event_content,
                    state_name,
                    state_data,
                    from_
                )
                
                # Process result
                state_changed = False
                
                match result:
                    case NextState() as ns:
                        state_name = ns.state_name
                        state_data = ns.state_data
                        actions = ns.actions
                        state_changed = True
                        
                        await process.send(LOGGER, ("log", "DEBUG",
                            f"[gen_statem] module={modname}, pid={pid} -> {state_name}",
                            {"module": modname, "pid": pid, "new_state": state_name}))
                    
                    case KeepState() as ks:
                        state_data = ks.state_data
                        actions = ks.actions
                    
                    case RepeatState() as rs:
                        state_data = rs.state_data
                        actions = rs.actions
                        state_changed = True
                    
                    case StopState() as stop:
                        await _terminate(module_instance, stop.reason, state_name, stop.state_data or state_data)
                        raise GenStatemExited(stop.reason)
                    
                    case _:
                        raise GenStatemBadReturn(result)
                
                # Handle state change cleanup BEFORE processing actions
                if state_changed:
                    # Cancel old state timeout
                    if state_timeout_ref:
                        await process.cancel_timer(state_timeout_ref)
                        state_timeout_ref = None
                
                # Process actions
                postpone_current = False
                
                for action in actions:
                    match action:
                        case ReplyAction(from_=from_, reply=reply):
                            reply_to, call_id = from_
                            await process.send(reply_to, (call_id, reply))
                        
                        case StateTimeoutAction() as timeout_action:
                            # Cancel any existing timeout before setting new one
                            if state_timeout_ref:
                                await process.cancel_timer(state_timeout_ref)
                            state_timeout_ref = await _schedule_timeout(pid, timeout_action)
                        
                        case PostponeAction():
                            postpone_current = True
                        
                        case NextEventAction(event_type=et, event_content=ec):
                            # Insert internal event (process next iteration)
                            await process.send(pid, ("_internal_event", et, ec))
                
                # Handle postponed events on state change
                if state_changed:
                    if postpone_current:
                        postponed_events.append((event_type, event_content, from_))
                    
                    # Replay postponed events
                    if postponed_events:
                        for evt_type, evt_content, evt_from in postponed_events:
                            await process.send(pid, ("_postponed_event", evt_type, evt_content, evt_from))
                        postponed_events = []
                elif postpone_current:
                    postponed_events.append((event_type, event_content, from_))

            except Exception as e:
                await process.send(LOGGER, ("log", "ERROR",
                    f"[gen_statem] module={modname}, pid={pid} crashed: {repr(e)}",
                    {"module": modname, "pid": pid, "exception": repr(e)}))
                raise

    except GenStatemExited as e:
        await process.send(LOGGER, ("log", "INFO",
            f"[gen_statem] module={modname}, pid={pid} stopped: {e}",
            {"module": modname, "pid": pid, "reason": str(e)}))
        raise
    except Exception as e:
        await process.send(LOGGER, ("log", "ERROR",
            f"[gen_statem] module={modname}, pid={pid} terminated abnormally: {repr(e)}",
            {"module": modname, "pid": pid, "exception": repr(e)}))
        raise


# ============================================================================
# Event handling
# ============================================================================

def _message_to_event(msg: Any) -> tuple[EventType, Any, Optional[tuple]]:
    """Convert process message to state machine event."""
    match msg:
        case _CallMessage(reply_to=reply_to, payload=payload, call_id=call_id):
            return EventType.CALL, payload, (reply_to, call_id)
        case _CastMessage(payload=payload):
            return EventType.CAST, payload, None
        case _TimeoutMessage(timeout_type=timeout_type, event_content=content):
            return EventType.STATE_TIMEOUT, content, None
        case ("_postponed_event", evt_type, evt_content, evt_from):
            return evt_type, evt_content, evt_from
        case ("_internal_event", evt_type, evt_content):
            return evt_type, evt_content, None
        case _:
            return EventType.INFO, msg, None


async def _handle_event(
    module_instance,
    callback_mode: CallbackMode,
    event_type: EventType,
    event_content: Any,
    state_name: StateName,
    state_data: Any,
    from_: Optional[tuple]
):
    """Route event to appropriate handler based on callback mode."""
    
    # For CALL events, package the from_ with the event content
    if event_type == EventType.CALL and from_ is not None:
        event_content = (event_content, from_)
    
    if callback_mode == CallbackMode.STATE_FUNCTIONS:
        # Look for state-specific handler method
        handler_name = f"state_{state_name.name}"
        if not hasattr(module_instance, handler_name):
            raise NotImplementedError(f"State handler {handler_name} not implemented")
        
        handler = getattr(module_instance, handler_name)
        return await handler(event_type, event_content, state_data)
    
    else:  # HANDLE_EVENT_FUNCTION
        if not hasattr(module_instance, 'handle_event'):
            raise NotImplementedError("handle_event not implemented")
        
        return await module_instance.handle_event(event_type, event_content, state_name, state_data)


async def _schedule_timeout(pid: str, action: StateTimeoutAction) -> str:
    """
    Schedule a state timeout using timing wheel.
    
    Returns timer reference for cancellation.
    """
    msg = _TimeoutMessage(timeout_type="state_timeout", event_content=action.event_content)
    ref = await process.send_after(action.timeout, pid, msg)
    return ref


async def _terminate(module_instance, reason, state_name, state_data):
    """Call terminate callback if defined."""
    if hasattr(module_instance, 'terminate'):
        try:
            await module_instance.terminate(reason, state_name, state_data)
        except Exception as e:
            await process.send(LOGGER, ("log", "ERROR",
                f"[gen_statem.terminate] error in terminate: {e}",
                {"pid": process.self(), "exception": repr(e)}))
