"""
Conftest for supervisor tests.
"""
import gc
import pytest
import anyio
from otpylib.runtime import set_runtime, reset_runtime
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend


class TestData:
    """Shared test data for tracking task execution."""
    def __init__(self):
        self.exec_count = 0
        self.error_count = 0
        self.completed = anyio.Event()


@pytest.fixture(scope="function", autouse=True)
def runtime_backend():
    """Ensure a runtime backend is configured for all tests."""
    backend = AsyncIOBackend()
    set_runtime(backend)
    yield backend
    reset_runtime()


@pytest.fixture
def test_data():
    """Provide test data instance for tracking execution."""
    return TestData()


@pytest.fixture(autouse=True)
def cleanup_gc():
    """Force garbage collection after each test to prevent coroutine leaks."""
    yield
    gc.collect()