"""
Static supervisor for managing persistent, long-running processes.

The static supervisor is designed to manage services that should continuously
run and be restarted when they fail - things like web servers, database 
connections, message processors, etc.

Includes configurable health monitoring with custom probe functions.
"""

from collections.abc import Callable, Awaitable
from typing import Any, Dict, List, Optional
import logging
import time

from collections import deque
from dataclasses import dataclass, field

import anyio
import anyio.abc
from anyio import CancelScope
from result import Result, Ok, Err

from otpylib.types import (
    NormalExit, ShutdownExit, BrutalKill, GracefulShutdown, TimedShutdown, 
    ShutdownStrategy, RestartStrategy, SupervisorStrategy,
    Permanent, Transient, OneForOne, OneForAll, RestForOne
)


# Type alias for health probe functions
HealthProbeFunction = Callable[[str, Any], Awaitable[Result[None, str]]]


@dataclass
class child_spec:
    id: str
    task: Callable[..., Awaitable[None]]
    args: List[Any]
    restart: RestartStrategy = Permanent()
    shutdown: ShutdownStrategy = TimedShutdown(5000)
    health_check_enabled: bool = True  # Enable automatic health checking
    health_check_interval: float = 30.0  # Health check interval in seconds
    health_check_timeout: float = 5.0   # Health check timeout
    health_check_fn: Optional[HealthProbeFunction] = None  # Custom health probe function


@dataclass
class options:
    """Supervisor options."""
    max_restarts: int = 3
    max_seconds: int = 5
    strategy: SupervisorStrategy = OneForOne()
    shutdown_strategy: ShutdownStrategy = TimedShutdown(5000)


@dataclass
class _ChildProcess:
    """Runtime state of a child."""
    spec: child_spec
    cancel_scope: CancelScope
    task: Optional[anyio.abc.TaskGroup] = None
    restart_count: int = 0
    failure_times: deque = field(default_factory=lambda: deque())
    last_exception: Optional[Exception] = None
    health_check_failures: int = 0
    last_health_check: Optional[float] = None


class _SupervisorState:
    """Shared state for coordinating children."""
    
    def __init__(self, specs: List[child_spec], opts: options):
        self.opts = opts
        self.children: Dict[str, _ChildProcess] = {}
        self.start_order: List[str] = []
        self.task_group: Optional[anyio.abc.TaskGroup] = None
        self.failed_children: List[tuple[str, Exception]] = []
        self.shutting_down = False
        
        # Initialize children
        for spec in specs:
            self.children[spec.id] = _ChildProcess(
                spec=spec,
                cancel_scope=CancelScope()
            )
            self.start_order.append(spec.id)

    def should_restart_child(self, child_id: str, failed: bool, exception: Optional[Exception] = None) -> bool:
        """Check if a specific child should restart."""
        child = self.children[child_id]
        
        # If shutting down, don't restart
        if self.shutting_down:
            return False

        # For TRANSIENT: only restart on actual exceptions (not normal completion or NormalExit)
        if isinstance(child.spec.restart, Transient):
            if not failed or isinstance(exception, NormalExit):
                return False

        # Only count actual failures (exceptions that aren't NormalExit) for restart limits
        if failed and isinstance(exception, Exception) and not isinstance(exception, NormalExit):
            # Check if within time window
            current_time = time.time()
            child.failure_times.append(current_time)
            
            # Remove failures outside the time window
            cutoff_time = current_time - self.opts.max_seconds
            while child.failure_times and child.failure_times[0] < cutoff_time:
                child.failure_times.popleft()
            
            # Check if we've exceeded max_restarts within the time window
            if len(child.failure_times) > self.opts.max_restarts:
                return False

        return True

    def get_affected_children(self, failed_child_id: str, exceeded_limit: bool) -> List[str]:
        """Determine which children are affected by a failure."""
        if not exceeded_limit:
            return [failed_child_id]  # Just restart the one
            
        if isinstance(self.opts.strategy, OneForOne):
            # Even if limit exceeded, only this child is terminated
            return [failed_child_id]
        elif isinstance(self.opts.strategy, OneForAll):
            # All children must restart
            return list(self.children.keys())
        elif isinstance(self.opts.strategy, RestForOne):
            # This child and all started after it
            idx = self.start_order.index(failed_child_id)
            return self.start_order[idx:]
        else:
            # Default fallback
            return [failed_child_id]


class SupervisorHandle:
    """Handle for controlling and monitoring a running supervisor."""
    
    def __init__(self, state: _SupervisorState):
        self._state = state
    
    def get_child_status(self, child_id: str) -> Optional[_ChildProcess]:
        """Get status of a specific child."""
        return self._state.children.get(child_id)
    
    def list_children(self) -> List[str]:
        """Get list of all child IDs."""
        return list(self._state.children.keys())
    
    def get_restart_count(self, child_id: str) -> int:
        """Get restart count for a specific child."""
        child = self._state.children.get(child_id)
        return child.restart_count if child else 0
    
    def get_health_status(self, child_id: str) -> Dict[str, Any]:
        """Get health check status for a child."""
        child = self._state.children.get(child_id)
        if not child:
            return {"error": "Child not found"}
        
        return {
            "health_check_failures": child.health_check_failures,
            "last_health_check": child.last_health_check,
            "health_check_enabled": child.spec.health_check_enabled,
            "has_custom_probe": child.spec.health_check_fn is not None
        }
    
    def is_shutting_down(self) -> bool:
        """Check if supervisor is shutting down."""
        return self._state.shutting_down
    
    async def shutdown(self):
        """Initiate supervisor shutdown."""
        self._state.shutting_down = True
        if self._state.task_group:
            self._state.task_group.cancel_scope.cancel()


async def start(
    child_specs: List[child_spec],
    opts: options,
    *,
    task_status: anyio.abc.TaskStatus,
) -> None:
    """Start the supervisor with the given children and strategy."""
    
    state = _SupervisorState(child_specs, opts)
    logger = logging.getLogger("otpylib.supervisor")
    
    # Create handle for external control
    handle = SupervisorHandle(state)
    
    # Signal supervisor is ready and return the handle
    task_status.started(handle)
    
    try:
        async with anyio.create_task_group() as tg:
            state.task_group = tg
            
            # Start all children initially
            for child_id in state.start_order:
                tg.start_soon(_run_child, state, child_id, logger)
            
            # Start health monitoring for children that have probe functions
            for child_id in state.start_order:
                child = state.children[child_id]
                if child.spec.health_check_enabled and child.spec.health_check_fn is not None:
                    tg.start_soon(_health_monitor, state, child_id, logger)
            
            # Continue supervising indefinitely
            
    except* Exception as eg:
        # Re-raise the exception group, which will contain any child failures
        raise


async def _health_monitor(state: _SupervisorState, child_id: str, logger: logging.Logger):
    """Health monitoring using custom probe function."""
    child = state.children[child_id]
    
    if not child.spec.health_check_fn:
        logger.error(f"Health monitor started but no health_check_fn provided for {child_id}")
        return
    
    logger.debug(f"Starting health monitoring for child: {child_id}")
    
    while not state.shutting_down:
        try:
            # Call the custom health probe function with timeout
            with anyio.move_on_after(child.spec.health_check_timeout):
                probe_result = await child.spec.health_check_fn(child_id, child)
                
                if probe_result.is_ok():
                    # Health check succeeded
                    child.health_check_failures = 0
                    child.last_health_check = time.time()
                    logger.debug(f"Health check passed for {child_id}")
                else:
                    # Health check returned an error
                    child.health_check_failures += 1
                    error_msg = probe_result.unwrap_err()
                    logger.warning(f"Health check failed for {child_id} (failure #{child.health_check_failures}): {error_msg}")
            
            # If health check fails repeatedly, restart the child
            if child.health_check_failures >= 3:
                logger.error(f"Child {child_id} failed 3 health checks, triggering restart")
                child.cancel_scope.cancel()
                break
            
            # Wait before next check (longer on failure)
            if child.health_check_failures > 0:
                await anyio.sleep(5.0)  # Retry sooner on failure
            else:
                await anyio.sleep(child.spec.health_check_interval)
            
        except anyio.get_cancelled_exc_class():
            # Timeout occurred
            child.health_check_failures += 1
            child.last_health_check = time.time()
            
            logger.warning(f"Health check timed out for {child_id} (failure #{child.health_check_failures})")
            
        except Exception as e:
            child.health_check_failures += 1
            child.last_health_check = time.time()
            
            logger.warning(f"Health check exception for {child_id} (failure #{child.health_check_failures}): {e}")


async def _run_child(state: _SupervisorState, child_id: str, logger: logging.Logger) -> None:
    """Run and monitor a single child, coordinating with supervisor on failures."""

    child = state.children[child_id]

    while not state.shutting_down:
        failed = False
        exception = None
        
        try:
            with child.cancel_scope:
                await child.spec.task(*child.spec.args)
            
            # Task completed - this is unusual for persistent services
            logger.warning(f"Child {child_id} completed unexpectedly (persistent services should not exit)")

        except anyio.get_cancelled_exc_class():
            logger.info(f"Child {child_id} cancelled by supervisor")
            return

        except ShutdownExit:
            # ShutdownExit means never restart regardless of strategy
            logger.info(f"Child {child_id} requested shutdown")
            return

        except NormalExit as e:
            # NormalExit respects restart strategy
            logger.info(f"Child {child_id} exited normally")
            exception = e
            # This will be handled by restart logic below

        except Exception as e:
            failed = True
            exception = e
            child.last_exception = e
            logger.error(f"Child {child.spec.id} failed", exc_info=e)

        # Decide what to do next
        should_restart = state.should_restart_child(child_id, failed, exception)

        if not should_restart:
            if failed:
                # Check if this was due to restart limit being exceeded
                if len(child.failure_times) > state.opts.max_restarts:
                    # Restart intensity exceeded → crash the supervisor
                    logger.error(f"Child {child.spec.id} terminated (restart limit exceeded)")
                    state.shutting_down = True
                    # Raise the exception to crash the task group
                    raise RuntimeError(
                        f"Supervisor shutting down: restart limit exceeded for child {child_id}"
                    ) from exception
                else:
                    # TRANSIENT with normal exit
                    logger.info(f"Child {child_id} completed and will not be restarted")
                    return
            elif isinstance(exception, NormalExit):
                # NormalExit with non-restarting strategy is normal
                logger.info(f"Child {child_id} completed with NormalExit and will not be restarted")
                return
            else:
                # Normal completion (no exception): just stop child
                logger.info(f"Child {child_id} completed and will not be restarted")
                return

        # Otherwise restart the child after a small delay
        if not state.shutting_down:
            logger.info(f"Restarting child {child_id}")
            child.restart_count += 1
            child.health_check_failures = 0  # Reset health check failures on restart
            await anyio.sleep(0.01)  # Small delay before restart
