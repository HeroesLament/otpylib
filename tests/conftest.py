import pytest
import anyio
import sys
from io import StringIO

from otpylib import mailbox, application, logging
from loguru import logger


# Mark all async tests to use anyio
pytestmark = pytest.mark.anyio


# Configure to test with asyncio backend only
@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def log_handler():
    """
    Capture log output for testing using loguru.
    """
    # Create a StringIO buffer to capture logs
    log_buffer = StringIO()
    
    # Remove default handlers
    logger.remove()
    
    # Add test handler that writes to buffer
    handler_id = logger.add(
        sink=log_buffer,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {extra[module]} | {message}",
        colorize=False,  # No colors in test output
    )
    
    yield log_buffer
    
    # Cleanup: remove test handler and reset to defaults
    logger.remove(handler_id)
    logging.configure_logging()  # Reset to default configuration


@pytest.fixture
def mailbox_env():
    """Initialize mailbox system for tests."""
    mailbox.init_mailbox_registry()
    yield
    # Cleanup could go here if needed