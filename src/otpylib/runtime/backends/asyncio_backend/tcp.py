#!/usr/bin/env python3
"""
TCP Socket Operations for AsyncIO Backend

Implements OTP-style TCP semantics using asyncio primitives.
Supports both passive mode (explicit recv) and active mode (messages to mailbox).
"""

import asyncio
import socket as socket_module
from typing import Optional, Dict

from otpylib.inet.data import (
    Socket, ListenSocket, Address, SocketOptions, ActiveMode,
    ClosedError, TimeoutError as InetTimeoutError,
    ConnectionError as InetConnectionError
)
from otpylib.inet.atoms import TCP_MSG, TCP_CLOSED, TCP_ERROR


# Global registry of active reader tasks
_active_readers: Dict[int, asyncio.Task] = {}


# =============================================================================
# Active Mode Implementation
# =============================================================================

async def _active_reader_loop(socket: Socket, controlling_pid: str, backend) -> None:
    """
    Background task that reads from socket and sends to process mailbox.
    
    Runs continuously in active mode, sending TCP messages to the controlling process.
    
    Args:
        socket: Socket to read from
        controlling_pid: PID of process to receive messages
        backend: Runtime backend (for process.send)
    """
    reader: asyncio.StreamReader = socket.handle['reader']
    socket_id = id(socket)
    
    try:
        while True:
            # Read data (up to buffer size)
            buffer_size = socket.options.buffer_size if socket.options else 8192
            data = await reader.read(buffer_size)
            
            if not data:
                # EOF - connection closed by peer
                await backend.send(controlling_pid, (TCP_CLOSED, socket))
                break
            
            # Send data to controlling process's mailbox
            await backend.send(controlling_pid, (TCP_MSG, socket, data))
            
    except asyncio.CancelledError:
        # Active mode disabled or controlling process changed
        raise
    except Exception as e:
        # Error reading - notify process
        await backend.send(controlling_pid, (TCP_ERROR, socket, str(e)))
    finally:
        # Clean up reader registry
        _active_readers.pop(socket_id, None)


async def set_active_mode(
    socket: Socket,
    active: bool,
    controlling_pid: str,
    backend
) -> None:
    """
    Enable or disable active mode for a socket.
    
    Active mode: Data automatically sent to process mailbox as messages
    Passive mode: Must call recv() explicitly to get data
    
    Args:
        socket: Socket to modify
        active: True for active mode, False for passive
        controlling_pid: PID of process to receive messages
        backend: Runtime backend (needed for process.send)
    """
    socket_id = id(socket)
    
    # Stop existing reader if any
    existing_task = _active_readers.get(socket_id)
    if existing_task and not existing_task.done():
        existing_task.cancel()
        try:
            await existing_task
        except asyncio.CancelledError:
            pass
    
    if active:
        # Start new reader task
        task = asyncio.create_task(
            _active_reader_loop(socket, controlling_pid, backend)
        )
        _active_readers[socket_id] = task
    else:
        # Passive mode - just clean up
        _active_readers.pop(socket_id, None)


async def controlling_process(socket: Socket, pid: str, backend) -> None:
    """
    Change controlling process for a socket.
    
    If socket is in active mode, restarts the reader task to send messages
    to the new controlling process.
    
    Args:
        socket: Socket to modify
        pid: PID of new controlling process
        backend: Runtime backend
    """
    socket_id = id(socket)
    
    # Check if there's an active reader
    existing_task = _active_readers.get(socket_id)
    if existing_task and not existing_task.done():
        # Socket is in active mode - restart with new PID
        existing_task.cancel()
        try:
            await existing_task
        except asyncio.CancelledError:
            pass
        
        # Start new reader for new controlling process
        task = asyncio.create_task(
            _active_reader_loop(socket, pid, backend)
        )
        _active_readers[socket_id] = task


# =============================================================================
# Connection Management
# =============================================================================

async def connect(host: str, port: int, options: SocketOptions) -> Socket:
    """
    Connect to TCP endpoint.
    
    Args:
        host: Hostname or IP address
        port: Port number
        options: Socket options
        
    Returns:
        Connected Socket
    """
    try:
        reader, writer = await asyncio.open_connection(host, port)
        
        # Apply socket options
        sock = writer.get_extra_info('socket')
        if sock is not None:
            if options.nodelay:
                sock.setsockopt(socket_module.IPPROTO_TCP, socket_module.TCP_NODELAY, 1)
            if options.keepalive:
                sock.setsockopt(socket_module.SOL_SOCKET, socket_module.SO_KEEPALIVE, 1)
        
        peer = writer.get_extra_info('peername')
        local = writer.get_extra_info('sockname')
        
        return Socket(
            handle={'reader': reader, 'writer': writer},
            peer=Address(*peer) if peer else None,
            local=Address(*local) if local else None,
            options=options
        )
    except Exception as e:
        raise InetConnectionError(f"Failed to connect to {host}:{port}: {e}")


async def listen(port: int, options: SocketOptions) -> ListenSocket:
    """
    Create listening TCP socket with OTP-style accept semantics.
    
    The server is created with a callback that pushes accepted connections
    into a queue. This allows accept() to have blocking semantics that map
    cleanly to OTP patterns.
    
    Args:
        port: Port to listen on
        options: Socket options
        
    Returns:
        ListenSocket with server and accept queue
    """
    # Create queue for accepted connections
    accept_queue: asyncio.Queue = asyncio.Queue()
    
    async def connection_callback(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> None:
        """Push accepted connections into queue"""
        await accept_queue.put((reader, writer))
    
    try:
        server = await asyncio.start_server(
            connection_callback,
            host='0.0.0.0',
            port=port,
            reuse_address=options.reuseaddr,
        )
        
        local = server.sockets[0].getsockname() if server.sockets else ('0.0.0.0', port)
        
        return ListenSocket(
            handle={'server': server, 'queue': accept_queue},
            local=Address(*local),
            options=options
        )
    except Exception as e:
        raise InetConnectionError(f"Failed to listen on port {port}: {e}")


async def accept(listen_socket: ListenSocket, timeout: Optional[float] = None) -> Socket:
    """
    Accept connection from listening socket (OTP-style blocking).
    
    This blocks until a client connects, then returns a Socket that can be
    passed to a spawned process for handling. This maps directly to Erlang's
    gen_tcp:accept/1 semantics.
    
    Args:
        listen_socket: Listening socket
        timeout: Accept timeout in seconds
        
    Returns:
        Socket for the accepted connection
    """
    accept_queue: asyncio.Queue = listen_socket.handle['queue']
    
    try:
        if timeout is not None:
            reader, writer = await asyncio.wait_for(accept_queue.get(), timeout)
        else:
            reader, writer = await accept_queue.get()
        
        peer = writer.get_extra_info('peername')
        local = writer.get_extra_info('sockname')
        
        return Socket(
            handle={'reader': reader, 'writer': writer},
            peer=Address(*peer) if peer else None,
            local=Address(*local) if local else None,
            options=listen_socket.options
        )
    except asyncio.TimeoutError:
        raise InetTimeoutError("Accept timeout")


# =============================================================================
# Data Transfer
# =============================================================================

async def send(socket: Socket, data: bytes) -> None:
    """
    Send data on TCP socket.
    
    Args:
        socket: Connected socket
        data: Data to send
    """
    writer: asyncio.StreamWriter = socket.handle['writer']
    
    if writer.is_closing():
        raise ClosedError("Socket is closed")
    
    writer.write(data)
    await writer.drain()


async def recv(socket: Socket, length: int, timeout: Optional[float]) -> bytes:
    """
    Receive data from TCP socket (passive mode only).
    
    In active mode, data is automatically sent to the process mailbox.
    This function is for passive mode where you explicitly request data.
    
    Args:
        socket: Connected socket
        length: Maximum bytes to receive (0 = read up to buffer size)
        timeout: Receive timeout in seconds
        
    Returns:
        Received data
    """
    reader: asyncio.StreamReader = socket.handle['reader']
    
    if reader.at_eof():
        raise ClosedError("Socket closed by peer")
    
    try:
        buffer_size = socket.options.buffer_size if socket.options else 8192
        read_size = length if length > 0 else buffer_size
        
        if timeout is not None:
            data = await asyncio.wait_for(reader.read(read_size), timeout)
        else:
            data = await reader.read(read_size)
        
        return data
    except asyncio.TimeoutError:
        raise InetTimeoutError("Receive timeout")


async def close(socket: Socket) -> None:
    """
    Close TCP socket.
    
    Also stops any active mode reader task.
    
    Args:
        socket: Socket to close
    """
    socket_id = id(socket)
    
    # Stop active reader if any
    existing_task = _active_readers.get(socket_id)
    if existing_task and not existing_task.done():
        existing_task.cancel()
        try:
            await existing_task
        except asyncio.CancelledError:
            pass
    
    # Close the socket
    writer: asyncio.StreamWriter = socket.handle['writer']
    
    if not writer.is_closing():
        writer.close()
        await writer.wait_closed()


async def shutdown(socket: Socket, how: str) -> None:
    """
    Shutdown part of TCP connection.
    
    Args:
        socket: Connected socket
        how: 'read', 'write', or 'both'
    """
    writer: asyncio.StreamWriter = socket.handle['writer']
    sock = writer.get_extra_info('socket')
    
    if sock is None:
        return
    
    shutdown_map = {
        'read': socket_module.SHUT_RD,
        'write': socket_module.SHUT_WR,
        'both': socket_module.SHUT_RDWR,
    }
    
    try:
        sock.shutdown(shutdown_map.get(how, socket_module.SHUT_RDWR))
    except OSError:
        pass  # Already closed


# =============================================================================
# Socket Information
# =============================================================================

async def peername(socket: Socket) -> Address:
    """
    Get remote address of connected socket.
    
    Args:
        socket: Connected socket
        
    Returns:
        Remote address (host, port)
    """
    if socket.peer:
        return socket.peer
    
    writer: asyncio.StreamWriter = socket.handle['writer']
    peer = writer.get_extra_info('peername')
    if peer:
        return Address(*peer)
    raise InetConnectionError("No peer address available")


async def sockname(socket: Socket) -> Address:
    """
    Get local address of socket.
    
    Args:
        socket: Socket
        
    Returns:
        Local address (host, port)
    """
    if socket.local:
        return socket.local
    
    writer: asyncio.StreamWriter = socket.handle['writer']
    local = writer.get_extra_info('sockname')
    if local:
        return Address(*local)
    raise InetConnectionError("No local address available")


# =============================================================================
# Socket Options
# =============================================================================

async def setopts(socket: Socket, options: SocketOptions) -> None:
    """
    Set socket options.
    
    Note: Changing active mode via setopts should be done through
    the backend's tcp_setopts which handles reader task management.
    
    Args:
        socket: Socket
        options: New socket options
    """
    writer: asyncio.StreamWriter = socket.handle['writer']
    sock = writer.get_extra_info('socket')
    
    if sock is not None:
        if options.nodelay:
            sock.setsockopt(socket_module.IPPROTO_TCP, socket_module.TCP_NODELAY, 1)
        if options.keepalive:
            sock.setsockopt(socket_module.SOL_SOCKET, socket_module.SO_KEEPALIVE, 1)
    
    socket.options = options


async def getopts(socket: Socket) -> SocketOptions:
    """
    Get current socket options.
    
    Args:
        socket: Socket
        
    Returns:
        Current socket options
    """
    return socket.options or SocketOptions()