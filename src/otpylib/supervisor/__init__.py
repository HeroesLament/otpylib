"""
otpylib - OTP-style concurrency patterns for Python with AnyIO.

This library provides Erlang/OTP-inspired concurrency patterns for Python,
built on top of the AnyIO async framework.
"""

# Core supervisor functionality
from .core import (
    child_spec,
    options,
    start,
)

__all__ = [
    "child_spec",
    "options",
    "start",
]