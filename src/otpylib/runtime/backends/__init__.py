"""
Runtime Backends Module
"""

from otpylib.runtime.backends.base import RuntimeBackend

# Lazy import to avoid circular dependency with etf.py
def __getattr__(name):
    if name == "AsyncIOBackend":
        from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend
        return AsyncIOBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'RuntimeBackend',
    'AsyncIOBackend',
]
