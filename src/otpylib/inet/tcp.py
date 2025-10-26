#!/usr/bin/env python3
"""
TCP Socket Operations

TCP (Transmission Control Protocol) socket operations.
"""

from typing import Optional, Tuple
from otpylib.runtime import get_runtime

from otpylib.inet.data import Socket, ListenSocket, Address, SocketOptions
from otpylib.inet.atoms import TCP, CONNECTED, LISTENING


# =============================================================================
# TCP Operations
# =============================================================================

async def connect(host: str, port: int, options: Optional[SocketOptions] = None) -> Socket:
    """
    Connect to a TCP endpoint.
    
    Args:
        host: Hostname or IP address
        port: Port number
        options: Socket options
        
    Returns:
        Connected Socket
    """
    backend = get_runtime()
    
    if options is None:
        options = SocketOptions()
    
    return await backend.tcp_connect(host, port, options)


async def listen(port: int, options: Optional[SocketOptions] = None) -> ListenSocket:
    """
    Create a listening TCP socket.
    
    Args:
        port: Port to listen on (0 for OS-assigned)
        options: Socket options
        
    Returns:
        ListenSocket handle
    """
    backend = get_runtime()
    
    if options is None:
        options = SocketOptions()
    
    return await backend.tcp_listen(port, options)


async def accept(listen_socket: ListenSocket, timeout: Optional[float] = None) -> Socket:
    """
    Accept a connection from a listening socket.
    
    Args:
        listen_socket: Listening socket
        timeout: Accept timeout in seconds
        
    Returns:
        Connected Socket for the accepted connection
    """
    backend = get_runtime()
    return await backend.tcp_accept(listen_socket, timeout)


async def send(socket: Socket, data: bytes) -> None:
    """
    Send data on a TCP socket.
    
    Args:
        socket: Connected socket
        data: Data to send
    """
    backend = get_runtime()
    return await backend.tcp_send(socket, data)


async def recv(socket: Socket, length: int = 0, timeout: Optional[float] = None) -> bytes:
    """
    Receive data from a TCP socket.
    
    Args:
        socket: Connected socket
        length: Maximum bytes to receive (0 = no limit, read until EOF or buffer full)
        timeout: Receive timeout in seconds
        
    Returns:
        Received data
    """
    backend = get_runtime()
    return await backend.tcp_recv(socket, length, timeout)


async def close(socket: Socket) -> None:
    """
    Close a TCP socket.
    
    Args:
        socket: Socket to close
    """
    backend = get_runtime()
    return await backend.tcp_close(socket)


async def shutdown(socket: Socket, how: str = 'both') -> None:
    """
    Shutdown part of a TCP connection.
    
    Args:
        socket: Connected socket
        how: 'read', 'write', or 'both'
    """
    backend = get_runtime()
    return await backend.tcp_shutdown(socket, how)


async def peername(socket: Socket) -> Address:
    """
    Get remote address of a connected socket.
    
    Args:
        socket: Connected socket
        
    Returns:
        Remote address (host, port)
    """
    backend = get_runtime()
    return await backend.tcp_peername(socket)


async def sockname(socket: Socket) -> Address:
    """
    Get local address of a socket.
    
    Args:
        socket: Socket
        
    Returns:
        Local address (host, port)
    """
    backend = get_runtime()
    return await backend.tcp_sockname(socket)


async def setopts(socket: Socket, options: SocketOptions) -> None:
    """
    Set socket options on a TCP socket.
    
    Args:
        socket: Socket
        options: New socket options
    """
    backend = get_runtime()
    return await backend.tcp_setopts(socket, options)


async def getopts(socket: Socket) -> SocketOptions:
    """
    Get current socket options.
    
    Args:
        socket: Socket
        
    Returns:
        Current socket options
    """
    backend = get_runtime()
    return await backend.tcp_getopts(socket)


async def controlling_process(socket: Socket, pid: str) -> None:
    """
    Change the process that receives messages for this socket (active mode).
    
    Args:
        socket: Socket
        pid: PID of new controlling process
    """
    backend = get_runtime()
    return await backend.tcp_controlling_process(socket, pid)
