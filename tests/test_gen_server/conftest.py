"""
Minimal conftest for gen_server tests.
"""
import pytest_asyncio
from otpylib.runtime import set_runtime, reset_runtime
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend


@pytest_asyncio.fixture(scope="session", autouse=True)
async def runtime_backend():
    """Set up runtime backend once per test session."""
    backend = AsyncIOBackend()
    await backend.initialize()
    set_runtime(backend)
    yield
    await backend.shutdown()
    reset_runtime()


class TestState:
    """Simple state container for gen_server tests."""
    def __init__(self):
        self.data = {}
        self.events = []
        self.messages = []
        self.counter = 0
        self.terminated = False
        self.terminate_reason = None


@pytest_asyncio.fixture
async def test_state():
    """Provide fresh test state for each test."""
    return TestState()