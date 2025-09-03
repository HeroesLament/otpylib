"""Dynamic supervisor module for runtime child management."""

from .core import (
    start,
    start_child,
    terminate_child,
)

__all__ = [
    "start",
    "start_child", 
    "terminate_child",
]