"""Application module for managing supervised application lifecycles."""

from .core import (
    app_spec,
    start,
    stop,
)

__all__ = [
    "app_spec",
    "start", 
    "stop",
]