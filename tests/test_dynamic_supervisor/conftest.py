import pytest
from otpylib.runtime import set_runtime, reset_runtime
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend


class DataHelper:
    """Shared test data for tracking task execution."""
    def __init__(self):
        self.exec_count = 0
        self.error_count = 0


@pytest.fixture(scope="session", autouse=True)
def runtime_backend():
    """Ensure a runtime backend is configured for all tests."""
    backend = AsyncIOBackend()
    set_runtime(backend)
    yield backend
    reset_runtime()


@pytest.fixture
def test_data():
    """Provide test data instance for tracking execution."""
    return DataHelper()
