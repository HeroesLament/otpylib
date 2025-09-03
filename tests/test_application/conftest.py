import pytest
import anyio
from contextvars import ContextVar

from otpylib import application
from otpylib.application.core import context_app_task_group, context_app_registry


class SampleData:
    def __init__(self):
        self.count = 0
        self.stop = anyio.Event()


@pytest.fixture
def test_data():
    return SampleData()


@pytest.fixture
async def app_context():
    """
    Fixture that provides the application context needed for testing.
    Sets up the context variables that the application module expects.
    """
    async with anyio.create_task_group() as tg:
        # Set up the context variables that application.start() expects
        context_app_task_group.set(tg)
        context_app_registry.set({})
        
        # Use move_on_after to ensure tests don't hang
        with anyio.move_on_after(5.0) as cancel_scope:
            yield tg
        
        # Cancel all running tasks when test completes
        tg.cancel_scope.cancel()