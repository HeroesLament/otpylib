import pytest

from otpylib import logging


def test_logenum():
    # Test conversion to loguru levels
    assert logging.LogLevel.DEBUG.to_loguru() == "DEBUG"
    assert logging.LogLevel.INFO.to_loguru() == "INFO"
    assert logging.LogLevel.WARNING.to_loguru() == "WARNING"
    assert logging.LogLevel.ERROR.to_loguru() == "ERROR"
    assert logging.LogLevel.CRITICAL.to_loguru() == "CRITICAL"
    
    # NONE level maps to CRITICAL (effectively disabling)
    assert logging.LogLevel.NONE.to_loguru() == "CRITICAL"


def test_logger(log_handler):
    logger = logging.getLogger("pytest")
    
    # Test debug level
    logger.debug("foo debug")
    output = log_handler.getvalue()
    assert "DEBUG" in output
    assert "pytest" in output
    assert "foo debug" in output
    
    # Clear buffer for next test
    log_handler.truncate(0)
    log_handler.seek(0)
    
    # Test info level
    logger.info("foo info")
    output = log_handler.getvalue()
    assert "INFO" in output
    assert "pytest" in output
    assert "foo info" in output
    
    # Clear buffer
    log_handler.truncate(0)
    log_handler.seek(0)
    
    # Test warning level
    logger.warning("foo warning")
    output = log_handler.getvalue()
    assert "WARNING" in output
    assert "pytest" in output
    assert "foo warning" in output
    
    # Clear buffer
    log_handler.truncate(0)
    log_handler.seek(0)
    
    # Test error level
    logger.error("foo error")
    output = log_handler.getvalue()
    assert "ERROR" in output
    assert "pytest" in output
    assert "foo error" in output
    
    # Clear buffer
    log_handler.truncate(0)
    log_handler.seek(0)
    
    # Test critical level
    logger.critical("foo critical")
    output = log_handler.getvalue()
    assert "CRITICAL" in output
    assert "pytest" in output
    assert "foo critical" in output


def test_structured_logging(log_handler):
    """Test loguru's structured logging capabilities"""
    logger = logging.getLogger("pytest")
    
    # Test with structured data
    logger.info("Server started", port=8080, host="localhost")
    output = log_handler.getvalue()
    assert "Server started" in output
    assert "pytest" in output