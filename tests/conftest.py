import pytest
import asyncio
import sys
from io import StringIO


# Mark all async tests to use anyio
pytestmark = pytest.mark.asyncio


# Configure to test with asyncio backend only
@pytest.fixture
def anyio_backend():
    return 'asyncio'
