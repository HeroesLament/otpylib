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
    sample_task_with_delay,
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
    """Test supervisor with multiple failing children - should crash when first child exceeds restart limits."""
    print("DEBUG: Multiple children test starting")
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with pytest.raises(ExceptionGroup) as exc_info:
        async with anyio.create_task_group() as tg:
            print("DEBUG: Starting supervisor with 3 failing children")
            children = [
                supervisor.child_spec(
                    id=f"service-{i}",
                    task=sample_task_error,  # Will crash and restart
                    args=[test_data],
                    restart=Permanent(),
                )
                for i in range(3)
            ]
            
            # Use default restart limits
            opts = supervisor.options(
                max_restarts=3,
                max_seconds=5,
                strategy=OneForOne(),  # Only failing child should be restarted
            )
            
            handle = await tg.start(supervisor.start, children, opts)
            print(f"DEBUG: Supervisor started, exec_count={test_data.exec_count}, error_count={test_data.error_count}")
            
            print("DEBUG: Waiting for restart attempts...")
            # Wait for one of the children to exceed restart limits and crash the supervisor
            await anyio.sleep(1.0)

    # Verify the supervisor crashed due to restart intensity being exceeded
    print(f"DEBUG: Supervisor crashed as expected, error_count={test_data.error_count}")
    assert _find_runtime_error(exc_info.value)
    
    # Should have multiple failures before hitting restart limit
    assert test_data.error_count >= 4  # At least max_restarts + 1 failures


async def test_mixed_restart_strategies(test_data, log_handler):
    """Test supervisor with mixed restart strategies - PERMANENT and TRANSIENT."""
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
            supervisor.child_spec(
                id="transient-service", 
                task=sample_task_with_delay,
                args=[test_data, 0.1],  # Complete after 0.1 seconds
                restart=Transient(),
            ),
        ]
        
        opts = supervisor.options(
            max_restarts=3,
            max_seconds=5,
            strategy=OneForOne(),
        )
        
        handle = await tg.start(supervisor.start, children, opts)
        
        # Let services run briefly
        await anyio.sleep(0.2)
        
        # Transient service should have completed and not restarted
        # Persistent service should still be running
        
        # Clean shutdown
        await handle.shutdown()
    
    # Verify both services executed
    assert test_data.exec_count >= 2
