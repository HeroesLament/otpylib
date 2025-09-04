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
from tests.test_supervisor.helpers import (
    sample_task_long_running,
    sample_task_error,
)


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


async def test_multiple_persistent_children(test_data, log_handler):
    """Test supervisor managing multiple persistent services."""
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with pytest.raises(ExceptionGroup) as exc_info:
        async with anyio.create_task_group() as tg:
            children = [
                supervisor.child_spec(
                    id=f"service-{i}",
                    task=sample_task_error,  # Will crash and restart
                    args=[test_data],
                    restart=Permanent(),
                )
                for i in range(3)
            ]
            
            opts = supervisor.options(max_restarts=2, max_seconds=5)
            
            # Use new supervisor start pattern
            handle = await tg.start(supervisor.start, children, opts)
            
            # Wait for restarts to exceed limits
            await anyio.sleep(0.5)

    # Check that RuntimeError is in the nested exception group
    assert _find_runtime_error(exc_info.value)
    
    # Services should have been restarted until one hits the limit
    assert test_data.exec_count >= 6  # At least 6 executions total
    assert test_data.error_count >= 6


async def test_mixed_restart_strategies(test_data, log_handler):
    """Test supervisor with persistent services having different restart strategies."""
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    async with anyio.create_task_group() as tg:
        children = [
            supervisor.child_spec(
                id="critical-service",
                task=sample_task_long_running,
                args=[test_data],
                restart=Permanent(),
            ),
            supervisor.child_spec(
                id="optional-service", 
                task=sample_task_long_running,
                args=[test_data],
                restart=Transient(),
            ),
        ]
        
        opts = supervisor.options(max_restarts=2)
        
        # Use new supervisor start pattern
        handle = await tg.start(supervisor.start, children, opts)
        
        # Let services run
        await anyio.sleep(0.2)
        
        # Use handle for graceful shutdown
        await handle.shutdown()

    # Both services should be running (long-running tasks increment periodically)
    assert test_data.exec_count >= 2
