import pytest
import anyio

from otpylib import supervisor, mailbox
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


def _find_runtime_error(exc_group):
    """Recursively find RuntimeError in nested ExceptionGroups."""
    for exc in exc_group.exceptions:
        if isinstance(exc, RuntimeError) and "Supervisor shutting down" in str(exc):
            return True
        elif isinstance(exc, ExceptionGroup):
            if _find_runtime_error(exc):
                return True
    return False


async def test_max_seconds_window(test_data, log_handler):
    """Test that restart count resets after max_seconds window for persistent services."""
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with pytest.raises(ExceptionGroup) as exc_info:
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
            
            # Use new supervisor start pattern
            handle = await tg.start(supervisor.start, children, opts)
            
            # Wait longer than the window for restart counts to reset
            await anyio.sleep(1.0)

    # Check that RuntimeError is in the nested exception group
    assert _find_runtime_error(exc_info.value)
    
    # Service should restart within limits, then hit the limit
    assert test_data.exec_count >= 3  # 1 initial + 2 restarts = limit reached
    assert test_data.error_count >= 3


async def test_shutdown_strategy(test_data):
    """Test different shutdown strategies with persistent services."""
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
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
        
        # Use new supervisor start pattern
        handle = await tg.start(supervisor.start, children, opts)
        
        # Let service run briefly
        await anyio.sleep(0.1)
        
        # Use handle for graceful shutdown
        await handle.shutdown()

    assert test_data.exec_count >= 1


async def test_zero_max_restarts(test_data, log_handler):
    """Test supervisor with max_restarts set to 0 - service crashes immediately."""
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
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
            
            # Use new supervisor start pattern
            handle = await tg.start(supervisor.start, children, opts)
            
            # Wait for crash
            await anyio.sleep(0.5)

    # Check that RuntimeError is in the nested exception group
    assert _find_runtime_error(exc_info.value)
    
    # Should only run once (no restarts allowed)
    assert test_data.exec_count == 1
    assert test_data.error_count == 1