"""
otpylib.gen_statem - Generic State Machine Behavior

Public API for creating and interacting with state machines.
"""

from otpylib.gen_statem.core import (
    # Lifecycle functions
    start,
    start_link,
    call,
    cast,
    
    # Callback modes
    CallbackMode,
    EventType,
    
    # State transition results
    NextState,
    KeepState,
    RepeatState,
    StopState,
    
    # State actions
    ReplyAction,
    StateTimeoutAction,
    PostponeAction,
    NextEventAction,
    
    # Exceptions
    GenStatemExited,
    GenStatemContractError,
    GenStatemBadReturn,
    NotAGenStatemError,
)

__all__ = [
    # Lifecycle
    "start",
    "start_link",
    "call",
    "cast",
    
    # Enums
    "CallbackMode",
    "EventType",
    
    # Results
    "NextState",
    "KeepState",
    "RepeatState",
    "StopState",
    
    # Actions
    "ReplyAction",
    "StateTimeoutAction",
    "PostponeAction",
    "NextEventAction",
    
    # Exceptions
    "GenStatemExited",
    "GenStatemContractError",
    "GenStatemBadReturn",
    "NotAGenStatemError",
]
