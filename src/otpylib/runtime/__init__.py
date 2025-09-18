"""
OTPylib Runtime System

Runtime abstraction layer for otpylib process management.
Provides a pluggable backend system where different process runtimes
(AnyIO, SPAM, etc.) can be used transparently by gen_servers, supervisors,
and other OTP patterns.
"""

from .core import RuntimeBackend, RuntimeError
from .backends import AnyIOBackend
from .registry import get_runtime, set_runtime, reset_runtime

__all__ = [
    # Core abstractions
    'RuntimeBackend',
    'RuntimeError',
    
    # Backend implementations
    'AnyIOBackend',
    
    # Runtime registry
    'get_runtime',
    'set_runtime', 
    'reset_runtime',
]