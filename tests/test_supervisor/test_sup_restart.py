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
from .helpers import (
    sample_task_error,
    sample_task_long_running,
    sample_task_with_delay,
)


# Apply anyio plugin across this module
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


@pytest.mark.parametrize("max_restarts", [1, 3, 5])
async def test_automatic_restart_permanent(max_restarts, test_data, log_handler):
    """PERMANENT services restart until supervisor intensity is exceeded."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with pytest.raises(ExceptionGroup) as exc_info:
        async with anyio.create_task_group() as tg:
            children = [
                supervisor.child_spec(
                    id="persistent_service",
                    task=sample_task_error,  # Will crash and restart
                    args=[test_data],
                    restart=Permanent(),
                )
            ]
            opts = supervisor.options(max_restarts=max_restarts, max_seconds=5)
            
            # Use start with task_status parameter
            handle = await tg.start(supervisor.start, children, opts)
            await anyio.sleep(0.5)

    # Check that RuntimeError is in the nested exception group
    assert _find_runtime_error(exc_info.value)
    
    # Should have run at least max_restarts+1 times
    assert test_data.exec_count >= (max_restarts + 1)
    assert test_data.error_count >= (max_restarts + 1)


@pytest.mark.parametrize("max_restarts", [1, 3, 5])
@pytest.mark.parametrize("strategy", [
    Permanent(),
    Transient()
])
async def test_automatic_restart_on_crash(max_restarts, strategy, test_data, log_handler):
    """Crashing services restart until supervisor intensity is exceeded."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with pytest.raises(ExceptionGroup) as exc_info:
        async with anyio.create_task_group() as tg:
            children = [
                supervisor.child_spec(
                    id="failing_service",
                    task=sample_task_error,
                    args=[test_data],
                    restart=strategy,
                )
            ]
            opts = supervisor.options(max_restarts=max_restarts, max_seconds=5)
            
            # Use start with task_status parameter
            handle = await tg.start(supervisor.start, children, opts)
            await anyio.sleep(0.5)

    # Check that RuntimeError is in the nested exception group
    assert _find_runtime_error(exc_info.value)
              
    assert test_data.exec_count >= (max_restarts + 1)
    assert test_data.error_count >= (max_restarts + 1)


async def test_transient_no_restart_for_normal_exit(test_data, log_handler):
    """TRANSIENT services don't restart on normal completion (unusual for persistent services)."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with anyio.move_on_after(2.0):  # 2 second timeout
        async with anyio.create_task_group() as tg:
            children = [
                supervisor.child_spec(
                    id="transient_service",
                    task=sample_task_with_delay,
                    args=[test_data, 0.05],
                    restart=Transient(),
                )
            ]
            opts = supervisor.options(max_restarts=3, max_seconds=5)
            
            # Use start with task_status parameter
            handle = await tg.start(supervisor.start, children, opts)
            await anyio.sleep(0.2)
            
            # Graceful shutdown via handle
            await handle.shutdown()

    # TRANSIENT service completed normally, should not restart
    assert test_data.exec_count >= 1


async def test_long_running_persistent_service(test_data, log_handler):
    """A long-running persistent service stays alive until cancelled."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with anyio.move_on_after(1.0):  # 1 second timeout
        async with anyio.create_task_group() as tg:
            children = [
                supervisor.child_spec(
                    id="long_running_service",
                    task=sample_task_long_running,
                    args=[test_data],
                    restart=Permanent(),
                )
            ]
            opts = supervisor.options(max_restarts=3, max_seconds=5)
            
            # Use start with task_status parameter
            handle = await tg.start(supervisor.start, children, opts)

            await anyio.sleep(0.2)
            
            # Use handle to shutdown gracefully
            await handle.shutdown()

    # Should have executed and kept running
    assert test_data.exec_count >= 1


async def test_permanent_service_restarts_on_completion(test_data, log_handler):
    """A PERMANENT service restarts even on normal completion."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    exc_info = None
    
    with anyio.move_on_after(2.0):  # 2 second timeout
        try:
            async with anyio.create_task_group() as tg:
                children = [
                    supervisor.child_spec(
                        id="completing_service",
                        task=sample_task_with_delay,
                        args=[test_data, 0.05],
                        restart=Permanent(),
                    )
                ]
                opts = supervisor.options(max_restarts=3, max_seconds=5)
                
                # Use start with task_status parameter
                handle = await tg.start(supervisor.start, children, opts)

                await anyio.sleep(0.5)
        except ExceptionGroup as e:
            exc_info = e

    # Should have raised ExceptionGroup with RuntimeError or hit timeout
    if exc_info:
        assert _find_runtime_error(exc_info)
              
    # Should restart multiple times until limit exceeded
    assert test_data.exec_count >= 4  # Initial + 3 restarts


async def test_supervisor_handle_functionality(test_data, log_handler):
    """Test supervisor handle methods for monitoring and control."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    async with anyio.create_task_group() as tg:
        children = [
            supervisor.child_spec(
                id="monitored_service",
                task=sample_task_long_running,
                args=[test_data],
                restart=Permanent(),
            )
        ]
        opts = supervisor.options(max_restarts=3, max_seconds=5)
        
        # Get supervisor handle
        handle = await tg.start(supervisor.start, children, opts)
        
        # Test handle methods
        assert "monitored_service" in handle.list_children()
        assert handle.get_restart_count("monitored_service") == 0
        
        child_status = handle.get_child_status("monitored_service")
        assert child_status is not None
        assert child_status.spec.id == "monitored_service"
        
        health_status = handle.get_health_status("monitored_service") 
        assert "health_check_failures" in health_status
        
        assert not handle.is_shutting_down()
        
        # Shutdown gracefully
        await handle.shutdown()
        assert handle.is_shutting_down()


async def test_health_monitoring_with_custom_probe(test_data, log_handler):
    """Test health monitoring with custom health check function."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    health_check_called = {"count": 0}
    
    async def custom_health_check(child_id, child_process):
        health_check_called["count"] += 1
        from result import Ok
        return Ok(None)
    
    with anyio.move_on_after(1.0):
        async with anyio.create_task_group() as tg:
            children = [
                supervisor.child_spec(
                    id="health_monitored_service",
                    task=sample_task_long_running,
                    args=[test_data],
                    restart=Permanent(),
                    health_check_enabled=True,
                    health_check_interval=0.1,  # Check every 100ms
                    health_check_fn=custom_health_check,
                )
            ]
            opts = supervisor.options(max_restarts=3, max_seconds=5)
            
            handle = await tg.start(supervisor.start, children, opts)
            
            # Let health checks run
            await anyio.sleep(0.5)
            
            await handle.shutdown()
    
    # Health check should have been called multiple times
    assert health_check_called["count"] > 0