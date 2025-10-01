"""
Runtime Module

Runtime system for otpylib process management.
"""

from otpylib.runtime.registry import (
    get_runtime,
    set_runtime,
    reset_runtime,
    is_runtime_active,
)

__all__ = [
    # Registry functions
    'get_runtime',
    'set_runtime',
    'reset_runtime',
    'is_runtime_active',
]