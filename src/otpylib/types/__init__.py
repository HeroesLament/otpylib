"""Shared types and classes for otpylib modules."""

from .core import (
    StartupSync,
    is_cancellation_exception,
    anyio_sleep,
    NormalExit,
    ShutdownExit,
    BrutalKill,
    TimedShutdown,
    GracefulShutdown,
    ShutdownStrategy,
    # Restart Strategies - For persistent processes only
    Permanent,
    Transient,
    RestartStrategy,
    # Supervisor Strategies
    OneForOne,
    OneForAll,
    RestForOne,
    SupervisorStrategy,
)

__all__ = [
    "StartupSync",
    "is_cancellation_exception", 
    "anyio_sleep",
    "NormalExit",
    "ShutdownExit",
    "BrutalKill",
    "TimedShutdown",
    "GracefulShutdown",
    "ShutdownStrategy",
    # Restart Strategies - For persistent processes only
    "Permanent",
    "Transient",
    "RestartStrategy",
    # Supervisor Strategies
    "OneForOne",
    "OneForAll",
    "RestForOne",
    "SupervisorStrategy",
]