import pytest
import anyio

from otpylib import application, supervisor
from otpylib.application.core import context_app_task_group, context_app_registry
from otpylib.types import (
    # Restart Strategies
    Permanent, Transient, RestartStrategy,
    # Supervisor Strategies  
    OneForOne, OneForAll, RestForOne, SupervisorStrategy,
    # Shutdown Strategies
    BrutalKill, GracefulShutdown, TimedShutdown, ShutdownStrategy,
    # Exit reasons
    NormalExit, ShutdownExit,
)

from .sample import app_a, app_b


pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("max_restarts", [1, 3, 5])
async def test_app_automatic_restart_permanent(test_data, max_restarts, log_handler):
    async with anyio.create_task_group() as tg:
        # Set up the context that application.start() expects
        context_app_task_group.set(tg)
        context_app_registry.set({})
        
        # Start the application
        await application.start(
            application.app_spec(
                module=app_a,
                start_arg=test_data,
                permanent=True,
                opts=supervisor.options(
                    max_restarts=max_restarts,
                ),
            )
        )
        
        # Wait a bit for restarts to happen
        await anyio.sleep(0.5)
        
        # Cancel everything to stop the test
        tg.cancel_scope.cancel()

    assert test_data.count == (max_restarts + 1)
    # Check if there are errors in the log buffer
    log_output = log_handler.getvalue()
    assert "ERROR" in log_output or "CRITICAL" in log_output


@pytest.mark.parametrize("max_restarts", [1, 3, 5])
async def test_app_automatic_restart_crash(test_data, max_restarts, log_handler):
    with pytest.raises(ExceptionGroup) as exc_info:
        async with anyio.create_task_group() as tg:
            # Set up the context that application.start() expects
            context_app_task_group.set(tg)
            context_app_registry.set({})
            
            # Start the application that will crash
            await application.start(
                application.app_spec(
                    module=app_b,
                    start_arg=test_data,
                    permanent=False,
                    opts=supervisor.options(
                        max_restarts=max_restarts,
                    ),
                )
            )
            
            # Wait for crashes to happen
            await anyio.sleep(0.5)
            
            # Cancel everything
            tg.cancel_scope.cancel()

    # Check that the ExceptionGroup contains RuntimeError
    assert any(isinstance(e, RuntimeError) for e in exc_info.value.exceptions)
    assert test_data.count == (max_restarts + 1)
    # Check if there are errors in the log buffer
    log_output = log_handler.getvalue()
    assert "ERROR" in log_output or "CRITICAL" in log_output


async def test_app_no_automatic_restart(test_data, log_handler):
    async with anyio.create_task_group() as tg:
        # Set up the context that application.start() expects
        context_app_task_group.set(tg)
        context_app_registry.set({})
        
        # Start the application
        await application.start(
            application.app_spec(
                module=app_a,
                start_arg=test_data,
                permanent=False,
            )
        )
        
        # Wait a bit
        await anyio.sleep(0.5)
        
        # Cancel everything
        tg.cancel_scope.cancel()

    assert test_data.count == 1
    # Check that there are no errors in the log buffer
    log_output = log_handler.getvalue()
    assert "ERROR" not in log_output and "CRITICAL" not in log_output