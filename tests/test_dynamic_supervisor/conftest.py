import pytest
import pytest_asyncio
from otpylib.runtime import set_runtime, reset_runtime
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend


class DataHelper:
    """Shared test data for tracking task execution."""
    def __init__(self):
        self.exec_count = 0
        self.error_count = 0


@pytest_asyncio.fixture(autouse=True)
async def runtime_backend():
    """Ensure a runtime backend is configured for all tests."""
    backend = AsyncIOBackend()
    
    await backend.initialize()
    
    set_runtime(backend)
    yield backend
    
    # Cleanup
    await backend.shutdown()
    reset_runtime()


@pytest.fixture
def test_data():
    """Provide test data instance for tracking execution."""
    return DataHelper()
