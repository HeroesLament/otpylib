#!/usr/bin/env python3
"""
otpylib.inet - Networking Primitives

Backend-agnostic networking layer providing OTP-style socket operations.
"""

from typing import TYPE_CHECKING

# Always safe to import - no circular deps
from otpylib.inet.data import (
    Socket,
    ListenSocket,
    Address,
    SocketOptions,
)

from otpylib.inet.atoms import (
    TCP,
    UDP,
    INET,
    INET6,
    ACTIVE,
    PASSIVE,
    BINARY,
    LIST,
    PACKET,
    REUSEADDR,
)

# Only import for type checking, not at runtime
if TYPE_CHECKING:
    from otpylib.inet.tcp import (
        connect,
        listen,
        accept,
        send,
        recv,
        close,
        peername,
        sockname,
        setopts,
        getopts,
    )

# Lazy load API functions to avoid circular import
def __getattr__(name):
    if name in ['connect', 'listen', 'accept', 'send', 'recv', 'close', 
                'peername', 'sockname', 'setopts', 'getopts']:
        from otpylib.inet import tcp as _tcp
        return getattr(_tcp, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = [
    "connect", "listen", "accept", "send", "recv", "close",
    "peername", "sockname", "setopts", "getopts",
    "Socket", "ListenSocket", "Address", "SocketOptions",
    "TCP", "UDP", "INET", "INET6", "ACTIVE", "PASSIVE",
    "BINARY", "LIST", "PACKET", "REUSEADDR",
]
