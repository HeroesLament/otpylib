import pytest
import anyio

from otpylib import supervisor, dynamic_supervisor
from otpylib.types import (
    StartupSync,
    # Restart Strategies
    Permanent, Transient, Temporary, RestartStrategy,
    # Supervisor Strategies  
    OneForOne, OneForAll, RestForOne, SupervisorStrategy,
    # Shutdown Strategies
    BrutalKill, GracefulShutdown, TimedShutdown, ShutdownStrategy,
    # Exit reasons
    NormalExit, ShutdownExit,
)

from tests.test_dynamic_supervisor.helpers import sample_task, sample_task_error


pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("max_restarts", [1, 3, 5])
async def test_automatic_restart_permanent(max_restarts, test_data, log_handler, mailbox_env):
    """Test that PERMANENT children are restarted up to max_restarts."""
    async with anyio.create_task_group() as tg:
        # Start dynamic supervisor
        opts = supervisor.options(
            max_restarts=max_restarts,
            max_seconds=5,
        )
        
        sync = StartupSync()
        tg.start_soon(dynamic_supervisor.start, opts, 'test-restart-permanent', sync)
        mid = await sync.wait()

        # Add child with PERMANENT restart strategy
        child_spec = supervisor.child_spec(
            id="sample_task",
            task=sample_task,
            args=[test_data],
            restart=Permanent(),
        )
        
        await dynamic_supervisor.start_child(mid, child_spec)

        # Wait for restarts to happen
        await anyio.sleep(0.5)
        
        # Cancel everything
        tg.cancel_scope.cancel()

    assert test_data.exec_count == (max_restarts + 1)
    # Check for errors in log output
    log_output = log_handler.getvalue()
    assert "ERROR" in log_output or "CRITICAL" in log_output


@pytest.mark.parametrize("max_restarts", [1, 3, 5])
@pytest.mark.parametrize(
    "strategy",
    [
        Permanent(),
        Transient(),
    ],
)
async def test_automatic_restart_on_crash(
    max_restarts,
    strategy,
    test_data,
    log_handler,
    mailbox_env,
):
    """Test that crashing children are restarted according to strategy."""
    with pytest.raises(ExceptionGroup) as exc_info:
        async with anyio.create_task_group() as tg:
            # Start dynamic supervisor
            opts = supervisor.options(
                max_restarts=max_restarts,
                max_seconds=5,
            )
            
            sync = StartupSync()
            tg.start_soon(dynamic_supervisor.start, opts, f'test-restart-crash-{strategy}', sync)
            mid = await sync.wait()

            # Add child that will crash
            child_spec = supervisor.child_spec(
                id="sample_task_error",
                task=sample_task_error,
                args=[test_data],
                restart=strategy,
            )
            
            await dynamic_supervisor.start_child(mid, child_spec)

            # Wait for crashes to happen
            await anyio.sleep(0.5)
            
            # Cancel everything
            tg.cancel_scope.cancel()

    # Check that RuntimeError is in the exception group
    assert any(isinstance(e, RuntimeError) for e in exc_info.value.exceptions)
    assert test_data.exec_count == (max_restarts + 1)
    assert test_data.error_count == (max_restarts + 1)
    
    # Check for errors in log output
    log_output = log_handler.getvalue()
    assert "ERROR" in log_output or "CRITICAL" in log_output


@pytest.mark.parametrize(
    "strategy",
    [
        Temporary(),
        Transient(),
    ],
)
async def test_no_restart_for_normal_exit(strategy, test_data, log_handler, mailbox_env):
    """Test that TEMPORARY and TRANSIENT children aren't restarted on normal exit."""
    async with anyio.create_task_group() as tg:
        # Start dynamic supervisor
        opts = supervisor.options(
            max_restarts=3,
            max_seconds=5,
        )
        
        sync = StartupSync()
        tg.start_soon(dynamic_supervisor.start, opts, f'test-no-restart-{strategy}', sync)
        mid = await sync.wait()

        # Add child with TEMPORARY/TRANSIENT strategy
        child_spec = supervisor.child_spec(
            id="sample_task",
            task=sample_task,
            args=[test_data],
            restart=strategy,
        )
        
        await dynamic_supervisor.start_child(mid, child_spec)

        # Wait for task to complete
        await anyio.sleep(0.5)
        
        # Cancel everything
        tg.cancel_scope.cancel()

    assert test_data.exec_count == 1  # Should only run once
    
    # Check that there are no errors in log output
    log_output = log_handler.getvalue()
    assert "ERROR" not in log_output and "CRITICAL" not in log_output