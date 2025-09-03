import pytest
import anyio

from otpylib import application, supervisor
from otpylib.application.core import context_app_task_group, context_app_registry
from otpylib.types import (
    # Restart Strategies
    Permanent, Transient, Temporary, RestartStrategy,
    # Supervisor Strategies  
    OneForOne, OneForAll, RestForOne, SupervisorStrategy,
    # Shutdown Strategies
    BrutalKill, GracefulShutdown, TimedShutdown, ShutdownStrategy,
    # Exit reasons
    NormalExit, ShutdownExit,
)

from .sample import app_c


pytestmark = pytest.mark.anyio


async def test_app_stop(test_data, log_handler):
    async with anyio.create_task_group() as tg:
        # Set up the context that application.start() expects
        context_app_task_group.set(tg)
        context_app_registry.set({})
        
        # Start the application
        await application.start(
            application.app_spec(
                module=app_c,
                start_arg=test_data,
                permanent=True,
            )
        )

        await anyio.sleep(0.01)
        await application.stop(app_c.__name__)
        
        # Give it time to stop
        await anyio.sleep(0.01)
        
        # Cancel the task group to end the test
        tg.cancel_scope.cancel()

    assert test_data.count == 1
