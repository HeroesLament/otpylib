import pytest
import anyio

from otpylib import supervisor
from otpylib.types import (
    # Restart Strategies - For persistent processes
    Permanent, Transient, RestartStrategy,
    # Supervisor Strategies  
    OneForOne, OneForAll, RestForOne, SupervisorStrategy,
    # Shutdown Strategies
    BrutalKill, GracefulShutdown, TimedShutdown, ShutdownStrategy,
    # Exit reasons
    NormalExit, ShutdownExit,
)
from tests.test_supervisor.helpers import sample_task_long_running, sample_task_error


pytestmark = pytest.mark.anyio


async def test_max_seconds_window(test_data, log_handler):
    """Test that restart count resets after max_seconds window for persistent services."""
    with pytest.raises(ExceptionGroup):
        async with anyio.create_task_group() as tg:
            children = [
                supervisor.child_spec(
                    id="persistent-service",
                    task=sample_task_error,  # Will crash and restart
                    args=[test_data],
                    restart=Permanent(),
                ),
            ]
            
            # Short window for testing
            opts = supervisor.options(
                max_restarts=2,
                max_seconds=0.5,  # Very short window
            )
            tg.start_soon(supervisor.start, children, opts)
            
            # Wait longer than the window for restart counts to reset
            await anyio.sleep(1.0)
            
            # Cancel the task group
            tg.cancel_scope.cancel()

    # Service should restart within limits, then hit the limit
    assert test_data.exec_count >= 3  # 1 initial + 2 restarts = limit reached
    assert test_data.error_count >= 3


async def test_shutdown_strategy(test_data):
    """Test different shutdown strategies with persistent services."""
    async with anyio.create_task_group() as tg:
        children = [
            supervisor.child_spec(
                id="persistent-service",
                task=sample_task_long_running,
                args=[test_data],
                restart=Permanent(),
            ),
        ]
        
        opts = supervisor.options(
            shutdown_strategy=TimedShutdown(5_000)
        )
        tg.start_soon(supervisor.start, children, opts)
        
        # Let service run briefly
        await anyio.sleep(0.1)
        
        # Cancel the task group
        tg.cancel_scope.cancel()

    assert test_data.exec_count >= 1


async def test_zero_max_restarts(test_data, log_handler):
    """Test supervisor with max_restarts set to 0 - service crashes immediately."""
    with pytest.raises(ExceptionGroup) as exc_info:
        async with anyio.create_task_group() as tg:
            children = [
                supervisor.child_spec(
                    id="failing-service",
                    task=sample_task_error,
                    args=[test_data],
                    restart=Permanent(),
                ),
            ]
            
            opts = supervisor.options(
                max_restarts=0,  # No restarts allowed
                max_seconds=5,
            )
            tg.start_soon(supervisor.start, children, opts)
            
            # Wait for crash
            await anyio.sleep(0.5)
            
            # Cancel the task group
            tg.cancel_scope.cancel()

    # Should only run once (no restarts allowed)
    assert test_data.exec_count == 1
    assert test_data.error_count == 1
