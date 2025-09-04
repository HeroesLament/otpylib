"""
Dynamic supervisor for managing both static and dynamically added children.

The dynamic supervisor extends the static supervisor's robust supervision logic
to handle children that can be added and removed at runtime via message passing.

It defines its own child_spec and options for flexibility while reusing the
proven supervision algorithms from the static supervisor.
"""

from collections.abc import Callable, Awaitable
from typing import Any, Dict, List, Optional, Union
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
    Permanent, Transient, OneForOne, OneForAll, RestForOne, StartupSync
)
from otpylib import mailbox

# Type alias for health probe functions
HealthProbeFunction = Callable[[str, Any], Awaitable[Result[None, str]]]


@dataclass
class child_spec:
    """Child specification for dynamic supervisor."""
    id: str
    task: Callable[..., Awaitable[None]]
    args: List[Any]
    restart: RestartStrategy = Permanent()
    shutdown: ShutdownStrategy = TimedShutdown(5000)
    health_check_enabled: bool = True
    health_check_interval: float = 30.0
    health_check_timeout: float = 5.0
    health_check_fn: Optional[HealthProbeFunction] = None


@dataclass
class options:
    """Dynamic supervisor options."""
    max_restarts: int = 3
    max_seconds: int = 5
    strategy: SupervisorStrategy = OneForOne()
    shutdown_strategy: ShutdownStrategy = TimedShutdown(5000)


@dataclass
class _ChildProcess:
    """Runtime state of a child in dynamic supervisor."""
    spec: child_spec
    cancel_scope: CancelScope
    task: Optional[anyio.abc.TaskGroup] = None
    restart_count: int = 0
    failure_times: deque = field(default_factory=lambda: deque())
    last_exception: Optional[Exception] = None
    health_check_failures: int = 0
    last_health_check: Optional[float] = None


class _DynamicSupervisorState:
    """Enhanced state management for dynamic supervisor."""
    
    def __init__(self, initial_specs: List[child_spec], opts: options):
        self.opts = opts
        self.children: Dict[str, _ChildProcess] = {}
        self.static_children: List[str] = []  # Track initial children
        self.dynamic_children: List[str] = []  # Track dynamically added children
        self.task_group: Optional[anyio.abc.TaskGroup] = None
        self.failed_children: List[tuple[str, Exception]] = []
        self.shutting_down = False
        self.mailbox_id: Optional[mailbox.MailboxID] = None
        
        # Initialize static children
        for spec in initial_specs:
            self.children[spec.id] = _ChildProcess(
                spec=spec,
                cancel_scope=CancelScope()
            )
            self.static_children.append(spec.id)

    def should_restart_child(self, child_id: str, failed: bool, exception: Optional[Exception] = None) -> bool:
        """Check if a specific child should restart (same logic as static supervisor)."""
        child = self.children.get(child_id)
        if not child:
            # Child no longer exists (was removed)
            return False
            
        if self.shutting_down:
            return False

        # For TRANSIENT: only restart on actual exceptions
        if isinstance(child.spec.restart, Transient):
            if not failed or isinstance(exception, NormalExit):
                return False

        # Rate limiting for actual failures
        if failed and isinstance(exception, Exception) and not isinstance(exception, NormalExit):
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
            return [failed_child_id]
            
        if isinstance(self.opts.strategy, OneForOne):
            return [failed_child_id]
        elif isinstance(self.opts.strategy, OneForAll):
            return list(self.children.keys())
        elif isinstance(self.opts.strategy, RestForOne):
            # For dynamic supervisor, RestForOne applies to start order
            # Static children first, then dynamic children in addition order
            all_children = self.static_children + self.dynamic_children
            try:
                idx = all_children.index(failed_child_id)
                return all_children[idx:]
            except ValueError:
                # Child not found in order, just restart itself
                return [failed_child_id]
        else:
            return [failed_child_id]

    async def add_child(self, child_spec: child_spec) -> bool:
        """Add a new dynamic child to the supervisor."""
        if self.task_group is None:
            return False
            
        # If child already exists, terminate it first
        if child_spec.id in self.children:
            await self.terminate_child(child_spec.id)
            
        # Create new child process
        self.children[child_spec.id] = _ChildProcess(
            spec=child_spec,
            cancel_scope=CancelScope()
        )
        
        # Track as dynamic child
        if child_spec.id not in self.dynamic_children:
            self.dynamic_children.append(child_spec.id)
        
        # Start child
        self.task_group.start_soon(self._run_child, child_spec.id)
        
        # Start health monitor if needed
        if child_spec.health_check_enabled and child_spec.health_check_fn is not None:
            self.task_group.start_soon(self._health_monitor, child_spec.id)
        
        return True

    async def terminate_child(self, child_id: str) -> bool:
        """Terminate a specific child."""
        if child_id not in self.children:
            return False
            
        child = self.children[child_id]
        child.cancel_scope.cancel()
        
        # Remove from tracking immediately to prevent health monitor from continuing
        self.children.pop(child_id, None)
        if child_id in self.dynamic_children:
            self.dynamic_children.remove(child_id)
            
        return True

    async def _run_child(self, child_id: str) -> None:
        """Run and monitor a single child (same logic as static supervisor)."""
        child = self.children[child_id]
        logger = logging.getLogger("otpylib.dynamic_supervisor")

        while not self.shutting_down and child_id in self.children:
            failed = False
            exception = None
            
            try:
                with child.cancel_scope:
                    await child.spec.task(*child.spec.args)
                
                # Check if this was due to cancellation (scope was cancelled but no exception was raised)
                if child.cancel_scope.cancelled_caught:
                    if child_id not in self.children:
                        logger.info(f"Child {child_id} was terminated")
                    else:
                        logger.info(f"Child {child_id} was cancelled")
                    return
                
                # Task completed - this may or may not be expected depending on restart strategy
                if isinstance(child.spec.restart, Permanent):
                    logger.warning(f"Child {child_id} completed unexpectedly (permanent children should not exit)")
                else:
                    logger.info(f"Child {child_id} completed normally")

            except anyio.get_cancelled_exc_class():
                # Check if this was an intentional termination vs supervisor cancellation
                if child_id not in self.children:
                    logger.info(f"Child {child_id} terminated")
                else:
                    logger.info(f"Child {child_id} cancelled")
                return

            except ShutdownExit:
                logger.info(f"Child {child_id} requested shutdown")
                return

            except NormalExit as e:
                logger.info(f"Child {child_id} exited normally")
                exception = e

            except Exception as e:
                failed = True
                exception = e
                child.last_exception = e
                logger.error(f"Child {child_id} failed", exc_info=e)

            # Decide what to do next
            should_restart = self.should_restart_child(child_id, failed, exception)

            if not should_restart:
                if failed and len(child.failure_times) > self.opts.max_restarts:
                    # Restart intensity exceeded → crash the supervisor
                    logger.error(f"Child {child_id} terminated (restart limit exceeded)")
                    self.shutting_down = True
                    raise RuntimeError(
                        f"Dynamic supervisor shutting down: restart limit exceeded for child {child_id}"
                    ) from exception
                else:
                    # Normal exit or TRANSIENT completion
                    logger.info(f"Child {child_id} will not be restarted")
                    # Remove from dynamic children if it was dynamic
                    if child_id in self.dynamic_children:
                        self.dynamic_children.remove(child_id)
                    self.children.pop(child_id, None)
                    return

            # Restart the child
            if not self.shutting_down and child_id in self.children:
                logger.info(f"Restarting child {child_id}")
                child.restart_count += 1
                child.health_check_failures = 0
                await anyio.sleep(0.01)

    async def _health_monitor(self, child_id: str):
        """Health monitoring (same logic as static supervisor)."""
        logger = logging.getLogger("otpylib.dynamic_supervisor")
        
        while not self.shutting_down and child_id in self.children:
            child = self.children.get(child_id)
            if not child or not child.spec.health_check_fn:
                break
                
            try:
                with anyio.move_on_after(child.spec.health_check_timeout):
                    probe_result = await child.spec.health_check_fn(child_id, child)
                    
                    if probe_result.is_ok():
                        child.health_check_failures = 0
                        child.last_health_check = time.time()
                        logger.debug(f"Health check passed for {child_id}")
                    else:
                        child.health_check_failures += 1
                        error_msg = probe_result.unwrap_err()
                        logger.warning(f"Health check failed for {child_id} (failure #{child.health_check_failures}): {error_msg}")
                
                # Restart on repeated failures
                if child.health_check_failures >= 3:
                    logger.error(f"Child {child_id} failed 3 health checks, triggering restart")
                    child.cancel_scope.cancel()
                    break
                
                # Adjust check frequency
                if child.health_check_failures > 0:
                    await anyio.sleep(5.0)
                else:
                    await anyio.sleep(child.spec.health_check_interval)
                
            except anyio.get_cancelled_exc_class():
                child.health_check_failures += 1
                child.last_health_check = time.time()
                logger.warning(f"Health check timed out for {child_id}")
                
            except Exception as e:
                child.health_check_failures += 1
                child.last_health_check = time.time()
                logger.warning(f"Health check exception for {child_id}: {e}")


class DynamicSupervisorHandle:
    """Handle for controlling and monitoring a running dynamic supervisor."""
    
    def __init__(self, state: _DynamicSupervisorState):
        self._state = state
    
    def get_child_status(self, child_id: str) -> Optional[_ChildProcess]:
        """Get status of a specific child."""
        return self._state.children.get(child_id)
    
    def list_children(self) -> List[str]:
        """Get list of all child IDs."""
        return list(self._state.children.keys())
    
    def list_static_children(self) -> List[str]:
        """Get list of static child IDs."""
        return self._state.static_children.copy()
    
    def list_dynamic_children(self) -> List[str]:
        """Get list of dynamic child IDs."""
        return self._state.dynamic_children.copy()
    
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

    async def add_child(self, child_spec: child_spec) -> bool:
        """Add a new dynamic child."""
        return await self._state.add_child(child_spec)
    
    async def terminate_child(self, child_id: str) -> bool:
        """Terminate a specific child."""
        return await self._state.terminate_child(child_id)


async def start(
    initial_children: List[child_spec],
    opts: options,
    mailbox_name: Optional[str] = None,
    *,
    task_status: anyio.abc.TaskStatus,
) -> DynamicSupervisorHandle:
    """Start the dynamic supervisor with initial children and mailbox for dynamic management."""
    
    state = _DynamicSupervisorState(initial_children, opts)
    logger = logging.getLogger("otpylib.dynamic_supervisor")
    
    # Create handle for external control
    handle = DynamicSupervisorHandle(state)
    
    # Signal supervisor is ready and return the handle
    task_status.started(handle)
    
    try:
        async with mailbox.open(mailbox_name) as mid:
            state.mailbox_id = mid
            
            async with anyio.create_task_group() as tg:
                state.task_group = tg
                
                # Start all initial (static) children
                for child_id in state.static_children:
                    tg.start_soon(state._run_child, child_id)
                
                # Start health monitoring for initial children with probe functions
                for child_id in state.static_children:
                    child = state.children[child_id]
                    if child.spec.health_check_enabled and child.spec.health_check_fn is not None:
                        tg.start_soon(state._health_monitor, child_id)
                
                # Start mailbox listener for dynamic child management
                tg.start_soon(_mailbox_listener, state, mid, logger)
                
                # Continue supervising indefinitely
                await anyio.sleep_forever()
                
    except* Exception as eg:
        raise


async def _mailbox_listener(
    state: _DynamicSupervisorState, 
    mailbox_id: mailbox.MailboxID,
    logger: logging.Logger
) -> None:
    """Listen for dynamic child management requests."""
    
    while not state.shutting_down:
        try:
            request = await mailbox.receive(mailbox_id)

            match request:
                case child_spec() as spec:
                    # Add new child
                    success = await state.add_child(spec)
                    if success:
                        logger.info(f"Added dynamic child: {spec.id}")
                    else:
                        logger.error(f"Failed to add dynamic child: {spec.id}")

                case {"action": "terminate", "child_id": child_id}:
                    # Terminate existing child
                    success = await state.terminate_child(child_id)
                    if success:
                        logger.info(f"Terminated child: {child_id}")
                    else:
                        logger.warning(f"Failed to terminate child (not found): {child_id}")

                case {"action": "list_children"}:
                    # Could extend to send response back via mailbox
                    children = list(state.children.keys())
                    logger.info(f"Current children: {children}")

                case _:
                    # Ignore unknown messages
                    logger.warning(f"Unknown mailbox message: {request}")
                    
        except Exception as e:
            logger.error(f"Error in mailbox listener: {e}")
            continue


# Convenience functions for external child management
async def start_child(
    name_or_mid: Union[str, mailbox.MailboxID],
    child_spec: child_spec,
) -> None:
    """Start a new task in the specified dynamic supervisor."""
    await mailbox.send(name_or_mid, child_spec)


async def terminate_child(
    name_or_mid: Union[str, mailbox.MailboxID], 
    child_id: str
) -> None:
    """Terminate a specific child in the dynamic supervisor."""
    await mailbox.send(name_or_mid, {"action": "terminate", "child_id": child_id})


async def list_children(
    name_or_mid: Union[str, mailbox.MailboxID]
) -> None:
    """Request list of children from dynamic supervisor."""
    await mailbox.send(name_or_mid, {"action": "list_children"})
