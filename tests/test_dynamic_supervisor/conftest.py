import pytest
import anyio


class TestData:
    """Shared test data for tracking task execution."""
    def __init__(self):
        self.exec_count = 0
        self.error_count = 0
        self.completed = anyio.Event()


@pytest.fixture
def test_data():
    """Provide test data instance for tracking execution."""
    return TestData()