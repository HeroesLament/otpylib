"""
Distribution protocol interfaces.

Defines contracts for distribution layer implementations.
Backend-agnostic - no asyncio or other runtime dependencies.
"""

from typing import Protocol, Any, Optional, Callable, Awaitable


class ConnectionProtocol(Protocol):
    """Protocol for a connection to a remote node."""
    
    local_node: str
    remote_node: str
    connected: bool
    
    async def connect(self, host: str, port: int) -> None:
        """Connect and perform handshake with remote node."""
        ...
    
    async def send_reg_send(self, to_name: str, message: Any) -> None:
        """Send message to registered process on remote node."""
        ...
    
    async def send_to_pid(self, to_pid: Any, message: Any) -> None:
        """Send message to specific PID on remote node."""
        ...
    
    def close(self) -> None:
        """Close the connection."""
        ...


class NodeProtocol(Protocol):
    """Protocol for a distributed node."""
    
    name: str
    cookie: str
    port: Optional[int]
    
    def set_local_delivery(self, handler: Callable[[str, Any], Awaitable[None]]) -> None:
        """
        Set callback for delivering incoming messages to local processes.
        
        Args:
            handler: Async function (target_name, message) -> None
        """
        ...
    
    async def start(self, port: int = 0) -> None:
        """Start listening and register with EPMD."""
        ...
    
    async def connect(self, remote_node: str) -> None:
        """Connect to a remote node."""
        ...
    
    async def send(self, remote_node: str, to_name: str, message: Any) -> None:
        """Send message to registered process on remote node."""
        ...
    
    async def send_to_pid(self, remote_node: str, pid: Any, message: Any) -> None:
        """Send message to specific PID on remote node."""
        ...
    
    def close(self) -> None:
        """Shutdown node and close all connections."""
        ...


class EPMDProtocol(Protocol):
    """Protocol for EPMD client operations."""
    
    @staticmethod
    async def register(node_name: str, port: int, node_type: int = 77) -> int:
        """Register node with EPMD, returns creation number."""
        ...
    
    @staticmethod
    async def lookup(node_name: str) -> Optional[Any]:
        """Look up node via EPMD, returns NodeInfo or None."""
        ...


class DistributionProtocol(Protocol):
    """
    Protocol for distribution layer implementations.
    
    Each runtime backend can provide its own distribution implementation
    that integrates the transport layer with the backend's process scheduler.
    """
    
    node_name: str
    port: Optional[int]
    
    async def start(self, port: int = 0) -> None:
        """
        Start the distribution layer.
        
        Args:
            port: Port to listen on (0 for ephemeral)
        """
        ...
    
    async def connect(self, remote_node: str) -> None:
        """
        Connect to a remote node.
        
        Args:
            remote_node: Full node name (e.g., "other@localhost")
        """
        ...
    
    async def send(self, remote_node: str, target: str, message: Any) -> None:
        """
        Send message to a process on a remote node.
        
        Args:
            remote_node: Full node name
            target: Registered name or PID of target process
            message: Message to send
        """
        ...
    
    async def shutdown(self) -> None:
        """Stop the distribution layer and close all connections."""
        ...
