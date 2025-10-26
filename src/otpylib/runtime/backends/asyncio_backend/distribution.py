"""
AsyncIO-specific distribution layer integration.

Wires the AsyncIO-based Node transport to AsyncIOBackend's process scheduler.
"""

from typing import Any, Optional

from otpylib.distribution.etf import encode

from otpylib.runtime.backends.asyncio_backend.node import AsyncIONode
from otpylib.runtime.backends.asyncio_backend.pid import Pid
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend


class AsyncIODistribution:
    """
    Distribution layer for AsyncIOBackend.
    
    Integrates Erlang distribution with the AsyncIO runtime backend,
    routing incoming distributed messages to local processes via the
    backend's process registry.
    
    Example:
        from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend, AsyncIODistribution
        from otpylib import distribution
        
        backend = AsyncIOBackend()
        await backend.initialize()
        
        dist = AsyncIODistribution(backend, "myapp@localhost", cookie="secret")
        await dist.start()
        distribution.use_distribution(dist)
        
        # Now Erlang nodes can send messages to local processes
        await distribution.connect("erlang@localhost")
        await distribution.send("erlang@localhost", "gen_server", message)
    """
    
    def __init__(self, backend: AsyncIOBackend, node_name: str, cookie: str):
        """
        Initialize distribution layer.
        
        Args:
            backend: AsyncIOBackend instance to integrate with
            node_name: Full node name (e.g., "myapp@localhost")
            cookie: Shared secret for cluster authentication
        """
        self.backend = backend
        self.node_name = node_name
        self.cookie = cookie
        
        # Get creation from backend stats or default to 1
        creation = 1
        try:
            stats = backend.statistics()
            if hasattr(stats, 'uptime_seconds'):
                creation = int(stats.uptime_seconds) % 65536  # Keep it 16-bit
        except Exception:
            pass
        
        # Inform the backend of the node_name and set it
        backend.set_node_name(node_name, creation)
        
        # Create the AsyncIO-specific node
        self.node = AsyncIONode(node_name, cookie, creation=creation, backend=backend)
        
        # Wire up message delivery to backend's process registry
        async def deliver_to_local(target_name: str, message: Any):
            """Deliver incoming distributed message to local process."""
            try:
                # Use backend's send which looks up by registered name
                await self.backend.send(target_name, message)
            except Exception as e:
                pass
        
        self.node.set_local_delivery(deliver_to_local)
    
    async def start(self, port: int = 0) -> None:
        """
        Start distribution layer.
        
        Registers with EPMD and begins listening for connections.
        
        Args:
            port: Port to listen on (0 for ephemeral)
        """
        await self.node.start(port)
    
    async def connect(self, remote_node: str) -> None:
        """
        Connect to a remote node.
        
        Args:
            remote_node: Full node name (e.g., "erlang@localhost")
        """
        await self.node.connect(remote_node)
    
    async def send(self, remote_node: str, target: str, message: Any) -> None:
        """
        Send message to a process on a remote node.
        
        Args:
            remote_node: Full node name
            target: Registered name of target process
            message: Message to send (will be ETF-encoded)
        """
        await self.node.send(remote_node, target, message)
    
    async def send_to_pid(self, remote_node: str, pid: Pid, message: Any) -> None:
        """
        Send message to a specific PID on a remote node.
        
        Args:
            remote_node: Full node name
            pid: ETF Pid of target process
            message: Message to send
        """
        await self.node.send_to_pid(remote_node, pid, message)


    async def send_control_message(self, remote_node: str, control_msg):
        if remote_node not in self.node.connections:
            await self.connect(remote_node)
        
        conn = self.node.connections[remote_node]
        control_bytes = encode(control_msg.to_tuple())
        await conn.send_message(control_bytes, payload=b'')


    async def shutdown(self) -> None:
        """Stop distribution and close all connections."""
        self.node.close()
        # Close the server
        if self.node.server:
            self.node.server.close()
            await self.node.server.wait_closed()
    
    @property
    def port(self) -> Optional[int]:
        """Get the port this node is listening on."""
        return self.node.port