#!/usr/bin/env python3
"""
Networking Data Structures

Data types for socket operations and configuration.
"""

from dataclasses import dataclass
from typing import Optional, Any, Tuple
from enum import Enum


# =============================================================================
# Socket Types
# =============================================================================

@dataclass
class Socket:
    """
    Represents an active TCP socket connection.
    
    Attributes:
        handle: Backend-specific socket handle (e.g., asyncio StreamReader/Writer pair)
        peer: Remote address (host, port)
        local: Local address (host, port)
        options: Current socket options
    """
    handle: Any
    peer: Optional[Tuple[str, int]] = None
    local: Optional[Tuple[str, int]] = None
    options: Optional[dict] = None


@dataclass
class ListenSocket:
    """
    Represents a listening TCP socket.
    
    Attributes:
        handle: Backend-specific listen socket handle
        local: Local address (host, port) being listened on
        options: Current socket options
    """
    handle: Any
    local: Optional[Tuple[str, int]] = None
    options: Optional[dict] = None


@dataclass
class UdpSocket:
    """
    Represents a UDP socket.
    
    Attributes:
        handle: Backend-specific UDP socket handle
        local: Local address (host, port)
        options: Current socket options
    """
    handle: Any
    local: Optional[Tuple[str, int]] = None
    options: Optional[dict] = None


@dataclass
class Address:
    """
    Network address.
    
    Attributes:
        host: Hostname or IP address
        port: Port number
    """
    host: str
    port: int
    
    def __iter__(self):
        """Allow unpacking: host, port = address"""
        return iter((self.host, self.port))


# =============================================================================
# Socket Options
# =============================================================================

class ActiveMode(Enum):
    """Socket active mode"""
    ACTIVE = 'active'      # Messages delivered to process mailbox
    PASSIVE = 'passive'    # Must call recv() explicitly
    ONCE = 'once'          # One message then switch to passive


class PacketMode(Enum):
    """Packet framing mode"""
    RAW = 0               # No framing
    LINE = 1              # Line-delimited (\n)
    SIZE_1 = 1            # 1-byte length prefix
    SIZE_2 = 2            # 2-byte length prefix
    SIZE_4 = 4            # 4-byte length prefix


@dataclass
class SocketOptions:
    """
    Socket configuration options.
    
    Attributes:
        active: Active mode (active/passive/once)
        binary: Deliver data as bytes (True) or string (False)
        packet: Packet framing mode
        buffer_size: Receive buffer size
        send_timeout: Send timeout in milliseconds
        recv_timeout: Receive timeout in milliseconds
        nodelay: Disable Nagle's algorithm (TCP_NODELAY)
        keepalive: Enable TCP keepalive
        reuseaddr: Allow address reuse (SO_REUSEADDR)
        reuseport: Allow port reuse (SO_REUSEPORT)
    """
    active: ActiveMode = ActiveMode.PASSIVE
    binary: bool = True
    packet: PacketMode = PacketMode.RAW
    buffer_size: int = 8192
    send_timeout: Optional[int] = None
    recv_timeout: Optional[int] = None
    nodelay: bool = False
    keepalive: bool = False
    reuseaddr: bool = False
    reuseport: bool = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary for backend consumption"""
        return {
            'active': self.active.value,
            'binary': self.binary,
            'packet': self.packet.value,
            'buffer_size': self.buffer_size,
            'send_timeout': self.send_timeout,
            'recv_timeout': self.recv_timeout,
            'nodelay': self.nodelay,
            'keepalive': self.keepalive,
            'reuseaddr': self.reuseaddr,
            'reuseport': self.reuseport,
        }
    
    @classmethod
    def from_dict(cls, opts: dict) -> 'SocketOptions':
        """Create from dictionary"""
        return cls(
            active=ActiveMode(opts.get('active', 'passive')),
            binary=opts.get('binary', True),
            packet=PacketMode(opts.get('packet', 0)),
            buffer_size=opts.get('buffer_size', 8192),
            send_timeout=opts.get('send_timeout'),
            recv_timeout=opts.get('recv_timeout'),
            nodelay=opts.get('nodelay', False),
            keepalive=opts.get('keepalive', False),
            reuseaddr=opts.get('reuseaddr', False),
            reuseport=opts.get('reuseport', False),
        )


# =============================================================================
# Error Types
# =============================================================================

class InetError(Exception):
    """Base class for inet errors"""
    pass


class ConnectionError(InetError):
    """Connection failed or was refused"""
    pass


class TimeoutError(InetError):
    """Operation timed out"""
    pass


class ClosedError(InetError):
    """Socket is closed"""
    pass
