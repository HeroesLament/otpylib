"""
Shared types and classes for otpylib modules.

This module contains common types and utility classes used across
multiple otpylib modules to avoid circular imports.
"""
import asyncio
from dataclasses import dataclass
from typing import Any, Optional, Union



@dataclass(frozen=True)
class BrutalKill:
    """Unconditionally and immediately terminate the child."""
    pass


@dataclass(frozen=True)
class GracefulShutdown:
    """Wait indefinitely for the child to exit after cancel."""
    pass


@dataclass(frozen=True)
class TimedShutdown:
    """Wait up to `time_ms` milliseconds before forcing kill."""
    time_ms: int

ShutdownStrategy = Union[BrutalKill, GracefulShutdown, TimedShutdown]


# Restart Strategies (ADT) - For persistent, long-running processes
@dataclass(frozen=True)
class Permanent:
    """Always restart the process when it exits (normal or abnormal).
    
    Use for critical services that must always be running, like web servers,
    database connections, or message processors.
    """
    pass


@dataclass(frozen=True)
class Transient:
    """Only restart the process if it crashes (raises an exception).
    
    Use for processes where normal completion might be acceptable but crashes
    should be recovered from. Note: for persistent services, normal completion
    is often unexpected behavior.
    """
    pass

RestartStrategy = Union[Permanent, Transient]


# Supervisor Strategies (ADT)
@dataclass(frozen=True)
class OneForOne:
    """Only restart the failed child when it exceeds restart limits."""
    pass


@dataclass(frozen=True)
class OneForAll:
    """Restart all children when one child exceeds restart limits."""
    pass


@dataclass(frozen=True)
class RestForOne:
    """Restart the failed child and all children started after it when limits exceeded."""
    pass

SupervisorStrategy = Union[OneForOne, OneForAll, RestForOne]


class ExitReason(Exception):
    """Base class for explicit exit reasons used by supervised tasks.

    These allow child tasks to signal their termination reason to the
    supervisor without relying only on return vs. exception semantics.
    """

    def __init__(self, message: Optional[str] = None):
        super().__init__(message)
        self.message = message


class NormalExit(ExitReason):
    """Signal a normal, successful exit.

    - Transient children: do not restart
    - Permanent children: restart
    - Temporary children: never restart
    """


class ShutdownExit(ExitReason):
    """Signal an intentional shutdown.

    A child that raises this exit will not be restarted, regardless of
    its restart strategy. Equivalent to OTP's :shutdown reason.
    """



class StartupSync:
    """Helper for coordinating task startup across anyio backends."""
    
    def __init__(self):
        self._ready = asyncio.Event()
        self._result = None
        self._error = None
    
    def started(self, value: Any = None) -> None:
        """Signal that startup is complete."""
        self._result = value
        self._ready.set()
    
    async def wait(self) -> Any:
        """Wait for startup completion."""
        await self._ready.wait()
        if self._error:
            raise self._error
        return self._result
    
    def set_error(self, error: Exception) -> None:
        """Set an error that will be raised on wait()."""
        self._error = error
        self._ready.set()


def is_cancellation_exception(exception: BaseException) -> bool:
    """Check if exception is a cancellation from any backend."""
    # Check for asyncio cancellation
    try:
        import asyncio
        if isinstance(exception, asyncio.CancelledError):
            return True
    except ImportError:
        pass
        
    return False
