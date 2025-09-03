"""
otpylib logging system using loguru for modern, structured logging.

Provides a simple wrapper around loguru with enum-based log levels
for compatibility with the original triotp logging interface.
"""

import sys

from enum import Enum, auto
from typing import Dict

from loguru import logger


class LogLevel(Enum):
    """
    otpylib node's logging level
    """

    NONE = auto()     #: Logging is disabled
    DEBUG = auto()    
    INFO = auto()     
    WARNING = auto()  
    ERROR = auto()    
    CRITICAL = auto() 

    def to_loguru(self) -> str:
        """
        Convert this enum to a loguru log level.

        :returns: Loguru log level string
        """
        level_map: Dict[LogLevel, str] = {
            LogLevel.NONE: "CRITICAL",      # Effectively disable by setting to highest
            LogLevel.DEBUG: "DEBUG",
            LogLevel.INFO: "INFO", 
            LogLevel.WARNING: "WARNING",
            LogLevel.ERROR: "ERROR",
            LogLevel.CRITICAL: "CRITICAL",
        }
        return level_map[self]


def getLogger(name: str):
    """
    Get a logger by name.
    
    In loguru, there's a single global logger instance that can be contextualized
    with structured data. This function returns a bound logger with the name context.

    :param name: Name of the logger (typically module name)
    :returns: Contextualized loguru logger
    
    .. code-block:: python
       :caption: Example

       from otpylib import logging
       
       logger = logging.getLogger(__name__)
       logger.info("Server started", port=8080, pid=12345)
       logger.error("Connection failed", host="localhost", error_code=500)
    """
    
    # Return loguru logger bound with the module name context
    return logger.bind(module=name)


def configure_logging(level: LogLevel = LogLevel.INFO, format_string: str = None):
    """
    Configure the global loguru logger.
    
    :param level: Minimum log level to output
    :param format_string: Optional custom format string for log output
    
    .. code-block:: python
       :caption: Example
       
       from otpylib import logging
       
       # Basic configuration
       logging.configure_logging(logging.LogLevel.DEBUG)
       
       # Custom format
       logging.configure_logging(
           level=logging.LogLevel.INFO,
           format_string="{time:YYYY-MM-DD HH:mm:ss} | {level} | {extra[module]} | {message}"
       )
    """
    
    # Remove default handler
    logger.remove()
    
    # Skip logging entirely if NONE level
    if level == LogLevel.NONE:
        return
    
    # Default format includes module context
    default_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[module]}</cyan> | "
        "<level>{message}</level>"
    )
    
    # Add new handler with specified level and format
    logger.add(
        sink=sys.stdout,
        level=level.to_loguru(),
        format=format_string or default_format,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )


def add_file_logging(file_path: str, level: LogLevel = LogLevel.INFO, rotation: str = "10 MB"):
    """
    Add file-based logging in addition to console output.
    
    :param file_path: Path to log file
    :param level: Minimum log level for file output  
    :param rotation: When to rotate log files (e.g., "10 MB", "1 day")
    
    .. code-block:: python
       :caption: Example
       
       logging.add_file_logging(
           "/var/log/otpylib/app.log", 
           level=logging.LogLevel.DEBUG,
           rotation="100 MB"
       )
    """
    
    logger.add(
        sink=file_path,
        level=level.to_loguru(),
        rotation=rotation,
        retention="1 week", 
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {extra[module]} | {message}",
        backtrace=True,
        diagnose=True,
    )


# Initialize with sensible defaults on import
configure_logging()