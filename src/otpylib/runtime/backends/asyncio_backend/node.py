"""
Distributed OTPYLIB node.

Manages connections to remote Erlang/OTP nodes and message routing.
"""

import asyncio
from typing import Optional, Dict, Any, Callable, Awaitable

from otpylib.runtime.backends.asyncio_backend.connection import AsyncIOConnection
from otpylib.runtime.backends.asyncio_backend.epmd import AsyncIOEPMD
from otpylib.distribution.etf import Pid


class AsyncIONode:
    """
    A distributed OTPYLIB node.
    
    Manages EPMD registration, incoming connections, and connections to remote nodes.
    
    Example:
        node = AsyncIONode("myapp@localhost", "secret")
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
        self.connections: Dict[str, AsyncIOConnection] = {}
        self.server: Optional[asyncio.Server] = None
        self.port: Optional[int] = None
        self._local_delivery: Optional[Callable[[str, Any], Awaitable[None]]] = None
        self._epmd_connection: Optional[tuple] = None  # Store (reader, writer) for EPMD
    
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
        
        # Register with EPMD and keep the connection alive
        self._epmd_connection, self.creation = await AsyncIOEPMD.register_and_keep_alive(
            self.short_name, self.port
        )
    
    async def _handle_incoming(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming connection (server-side handshake)"""
        try:
            # Get peer address for logging
            peer = writer.get_extra_info('peername')
            
            # Create connection and perform server-side handshake
            conn = AsyncIOConnection(self.name, None, self.cookie, self.creation)
            
            # Accept the handshake using the existing connection streams
            remote_node = await conn.accept_connection(reader, writer)
            
            if not remote_node:
                writer.close()
                await writer.wait_closed()
                return
            
            # Store the connection
            self.connections[remote_node] = conn
            
            # Set up message handler to deliver to local processes
            async def message_handler(message: Any):
                """Handle incoming distributed messages."""
                if self._local_delivery:
                    try:
                        # Messages are tuples: (control_msg, actual_msg)
                        # For REG_SEND: control is (6, from_pid, unused, to_name)
                        if isinstance(message, tuple) and len(message) >= 2:
                            control, payload = message[0], message[1]
                            
                            if isinstance(control, tuple) and len(control) >= 4:
                                msg_type = control[0]
                                if msg_type == 6:  # REG_SEND
                                    to_name_atom = control[3]
                                    # Extract string from Atom
                                    to_name = str(to_name_atom) if hasattr(to_name_atom, 'value') else str(to_name_atom)
                                    await self._local_delivery(to_name, payload)
                                elif msg_type == 2:  # SEND (to PID)
                                    to_pid = control[2]
                                else:
                                    pass
                            else:
                                pass
                        else:
                            pass
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
            
            conn.message_handler = message_handler
            
            # Start receive loop for this connection
            asyncio.create_task(self._receive_loop(conn, remote_node))
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            writer.close()
            await writer.wait_closed()
    
    async def _receive_loop(self, conn: AsyncIOConnection, remote_node: str):
        """
        Continuously receive messages from a connection.
        
        Args:
            conn: Connection object
            remote_node: Name of the remote node
        """
        try:
            while conn.connected:
                message = await conn.receive()
                
                if message is None:
                    # Connection closed
                    break
                
                if conn.message_handler:
                    await conn.message_handler(message)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            import traceback
            traceback.print_exc()
        finally:
            # Clean up connection
            if remote_node in self.connections:
                del self.connections[remote_node]
            conn.close()

    async def connect(self, remote_node: str):
        """Connect to remote node"""
        if remote_node in self.connections:
            return

        # Look up via EPMD
        remote_short = remote_node.split('@')[0]
        remote_host = remote_node.split('@')[1] if '@' in remote_node else '127.0.0.1'

        node_info = await AsyncIOEPMD.lookup(remote_short)
        if not node_info:
            raise ConnectionError(f"Node '{remote_node}' not found via EPMD")

        # Connect and handshake
        conn = AsyncIOConnection(self.name, remote_node, self.cookie, self.creation)
        await conn.connect(remote_host, node_info.port)

        self.connections[remote_node] = conn

        # Set up message handler for incoming messages on this connection
        async def message_handler(message: Any):
            """Handle incoming distributed messages."""
            if self._local_delivery:
                try:
                    # Messages are tuples: (control_msg, actual_msg)
                    if isinstance(message, tuple) and len(message) >= 2:
                        control, payload = message[0], message[1]
                        if isinstance(control, tuple) and len(control) >= 4:
                            msg_type = control[0]
                            if msg_type == 6:  # REG_SEND
                                to_name_atom = control[3]
                                to_name = str(to_name_atom) if hasattr(to_name_atom, 'value') else str(to_name_atom)
                                await self._local_delivery(to_name, payload)
                            elif msg_type == 2:  # SEND (to PID)
                                to_pid = control[2]
                            else:
                                pass
                        else:
                            pass
                    else:
                        pass
                except Exception as e:
                    import traceback
                    traceback.print_exc()

        conn.message_handler = message_handler

        # Start receive loop for this connection
        asyncio.create_task(self._receive_loop(conn, remote_node))

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
        
        # Close EPMD connection to unregister
        if self._epmd_connection:
            reader, writer = self._epmd_connection
            try:
                writer.close()
            except Exception:
                pass
            self._epmd_connection = None
