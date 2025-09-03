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
from tests.test_supervisor.helpers import (
    sample_task_long_running,
    sample_task_error,
)


pytestmark = pytest.mark.anyio


async def test_multiple_persistent_children(test_data, log_handler):
    """Test supervisor managing multiple persistent services."""
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
            tg.start_soon(supervisor.start, children, opts)
            
            # Wait for restarts to exceed limits
            await anyio.sleep(0.5)

    # Services should have been restarted until one hits the limit
    assert test_data.exec_count >= 6  # At least 6 executions total
    assert test_data.error_count >= 6


async def test_mixed_restart_strategies(test_data, log_handler):
    """Test supervisor with persistent services having different restart strategies."""
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
        tg.start_soon(supervisor.start, children, opts)
        
        # Let services run
        await anyio.sleep(0.2)
        
        # Cancel to stop test
        tg.cancel_scope.cancel()

    # Both services should be running (long-running tasks increment periodically)
    assert test_data.exec_count >= 2
