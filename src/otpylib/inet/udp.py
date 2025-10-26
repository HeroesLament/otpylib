#!/usr/bin/env python3
"""
UDP Socket Operations

UDP (User Datagram Protocol) socket operations.
"""

from typing import Optional, Tuple
from otpylib.runtime import get_runtime

from otpylib.inet.data import UdpSocket, Address, SocketOptions
from otpylib.inet.atoms import UDP


# =============================================================================
# UDP Operations
# =============================================================================

async def open(port: int = 0, options: Optional[SocketOptions] = None) -> UdpSocket:
    """
    Open a UDP socket.
    
    Args:
        port: Local port to bind (0 for OS-assigned)
        options: Socket options
        
    Returns:
        UdpSocket handle
    """
    backend = get_runtime()
    
    if options is None:
        options = SocketOptions()
    
    return await backend.udp_open(port, options)


async def send(socket: UdpSocket, address: Address, data: bytes) -> None:
    """
    Send data to remote address via UDP.
    
    Args:
        socket: UDP socket
        address: Destination address (host, port)
        data: Data to send
    """
    backend = get_runtime()
    return await backend.udp_send(socket, address, data)


async def recv(socket: UdpSocket, length: int = 0, timeout: Optional[float] = None) -> Tuple[bytes, Address]:
    """
    Receive data from UDP socket.
    
    Args:
        socket: UDP socket
        length: Maximum bytes to receive (0 = no limit)
        timeout: Receive timeout in seconds
        
    Returns:
        Tuple of (data, sender_address)
    """
    backend = get_runtime()
    return await backend.udp_recv(socket, length, timeout)


async def close(socket: UdpSocket) -> None:
    """
    Close UDP socket.
    
    Args:
        socket: UDP socket to close
    """
    backend = get_runtime()
    return await backend.udp_close(socket)


async def setopts(socket: UdpSocket, options: SocketOptions) -> None:
    """
    Set UDP socket options.
    
    Args:
        socket: UDP socket
        options: New socket options
    """
    backend = get_runtime()
    return await backend.udp_setopts(socket, options)


async def getopts(socket: UdpSocket) -> SocketOptions:
    """
    Get current UDP socket options.
    
    Args:
        socket: UDP socket
        
    Returns:
        Current socket options
    """
    backend = get_runtime()
    return await backend.udp_getopts(socket)


async def sockname(socket: UdpSocket) -> Address:
    """
    Get local address of UDP socket.
    
    Args:
        socket: UDP socket
        
    Returns:
        Local address (host, port)
    """
    backend = get_runtime()
    return await backend.udp_sockname(socket)
