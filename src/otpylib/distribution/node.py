"""
Distributed OTPYLIB node.

Manages connections to remote Erlang/OTP nodes and message routing.
"""

import asyncio
from typing import Optional, Dict, Any, Callable, Awaitable

from otpylib.distribution.connection import Connection
from otpylib.distribution.epmd import EPMD
from otpylib.distribution.etf import Pid


class Node:
    """
    A distributed OTPYLIB node.
    
    Manages EPMD registration, incoming connections, and connections to remote nodes.
    
    Example:
        node = Node("myapp@localhost", "secret")
        await node.start()
        await node.connect("other@localhost")
        await node.send("other@localhost", "registered_name", message)
    """
    
    def __init__(self, name: str, cookie: str, creation: int = 1):
        self.name = name
        self.short_name = name.split('@')[0]
        self.host = name.split('@')[1] if '@' in name else 'localhost'
        self.cookie = cookie
        self.creation = creation
        self.connections: Dict[str, Connection] = {}
        self.server: Optional[asyncio.Server] = None
        self.port: Optional[int] = None
        self._local_delivery: Optional[Callable[[str, Any], Awaitable[None]]] = None
    
    def set_local_delivery(self, handler: Callable[[str, Any], Awaitable[None]]):
        """
        Set callback for delivering incoming distributed messages to local processes.
        
        Args:
            handler: Async function that takes (target_name, message) and delivers
                    to the local process registry.
        """
        self._local_delivery = handler
    
    async def start(self, port: int = 0):
        """Start listening for connections and register with EPMD"""
        # Start TCP server
        self.server = await asyncio.start_server(
            self._handle_incoming,
            '0.0.0.0',
            port
        )
        
        self.port = self.server.sockets[0].getsockname()[1]
        
        # Register with EPMD
        self.creation = await EPMD.register(self.short_name, self.port)
    
    async def _handle_incoming(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming connection (server-side handshake)"""
        # TODO: Implement server-side handshake
        writer.close()
    
    async def connect(self, remote_node: str):
        """Connect to remote node"""
        if remote_node in self.connections:
            return
        
        # Look up via EPMD
        remote_short = remote_node.split('@')[0]
        remote_host = remote_node.split('@')[1] if '@' in remote_node else '127.0.0.1'
        
        node_info = await EPMD.lookup(remote_short)
        if not node_info:
            raise ConnectionError(f"Node '{remote_node}' not found via EPMD")
        
        # Connect and handshake
        conn = Connection(self.name, remote_node, self.cookie, self.creation)
        await conn.connect(remote_host, node_info.port)
        
        self.connections[remote_node] = conn
    
    async def send(self, remote_node: str, to_name: str, message: Any):
        """Send message to registered process on remote node"""
        if remote_node not in self.connections:
            await self.connect(remote_node)
        
        conn = self.connections[remote_node]
        await conn.send_reg_send(to_name, message)
    
    async def send_to_pid(self, remote_node: str, pid: Pid, message: Any):
        """Send message to specific PID on remote node"""
        if remote_node not in self.connections:
            await self.connect(remote_node)
        
        conn = self.connections[remote_node]
        await conn.send_to_pid(pid, message)
    
    def set_message_handler(self, remote_node: str, handler: Callable[[Any], Awaitable[None]]):
        """Set handler for messages from remote node"""
        if remote_node in self.connections:
            self.connections[remote_node].message_handler = handler
    
    def close(self):
        """Shutdown node"""
        if self.server:
            self.server.close()
        
        for conn in self.connections.values():
            conn.close()
