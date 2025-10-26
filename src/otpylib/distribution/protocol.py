"""
Distribution protocol interfaces.

Defines contracts for distribution layer implementations.
Backend-agnostic - no asyncio or other runtime dependencies.
"""

from typing import Protocol, Any, Optional, Callable, Awaitable
from otpylib.distribution.etf import Reference

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from otpylib.runtime.backends.base import Pid
else:
    Pid = 'Pid'  # Use as string annotation because Python MRO


class ControlMessageProtocol(Protocol):
    """Protocol for control messages that can be sent over distribution."""
    
    ctrl_type: int
    
    def to_tuple(self) -> tuple:
        """Encode control message to ETF tuple format."""
        ...
    
    async def handle(self, backend: Any, payload: Optional[Any] = None) -> None:
        """Handle this control message with the given backend."""
        ...


class ConnectionProtocol(Protocol):
    """Protocol for a connection to a remote node."""
    
    local_node: str
    remote_node: str
    connected: bool
    
    async def connect(self, host: str, port: int) -> None:
        """Connect and perform handshake with remote node."""
        ...
    
    async def send_message(self, control_bytes: bytes, payload: bytes = b'') -> None:
        """
        Send raw ETF-encoded message over the connection.
        
        Args:
            control_bytes: ETF-encoded control tuple
            payload: Optional ETF-encoded payload (for SEND/REG_SEND)
        """
        ...
    
    async def send_reg_send(self, to_name: str, message: Any) -> None:
        """Send message to registered process on remote node."""
        ...
    
    async def send_to_pid(self, to_pid: Pid, message: Any) -> None:
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
    
    async def send_to_pid(self, remote_node: str, pid: Pid, message: Any) -> None:
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
    
    Supports both message passing and process control operations (links, monitors).
    """
    
    node_name: str
    port: Optional[int]
    
    # ========================================================================
    # Lifecycle Management
    # ========================================================================
    
    async def start(self, port: int = 0) -> None:
        """
        Start the distribution layer.
        
        Args:
            port: Port to listen on (0 for ephemeral)
        """
        ...
    
    async def shutdown(self) -> None:
        """Stop the distribution layer and close all connections."""
        ...
    
    # ========================================================================
    # Node Connection Management
    # ========================================================================
    
    async def connect(self, remote_node: str) -> None:
        """
        Connect to a remote node.
        
        Performs EPMD lookup and distribution protocol handshake.
        
        Args:
            remote_node: Full node name (e.g., "other@localhost")
        """
        ...
    
    def is_connected(self, remote_node: str) -> bool:
        """
        Check if connected to a remote node.
        
        Args:
            remote_node: Full node name
            
        Returns:
            True if connection exists and is active
        """
        ...
    
    # ========================================================================
    # Message Passing
    # ========================================================================
    
    async def send(self, remote_node: str, target: str, message: Any) -> None:
        """
        Send message to a registered process on a remote node.
        
        Uses CTRL_REG_SEND control message.
        
        Args:
            remote_node: Full node name
            target: Registered name of target process
            message: Message to send (will be ETF-encoded)
        """
        ...
    
    async def send_to_pid(self, remote_node: str, pid: Pid, message: Any) -> None:
        """
        Send message to a specific PID on a remote node.
        
        Uses CTRL_SEND control message.
        
        Args:
            remote_node: Full node name
            pid: Target process PID
            message: Message to send (will be ETF-encoded)
        """
        ...
    
    # ========================================================================
    # Process Control (Links, Monitors, Exits)
    # ========================================================================
    
    async def send_control_message(
        self,
        remote_node: str,
        control_msg: ControlMessageProtocol
    ) -> None:
        """
        Send a control message to a remote node.
        
        Used for links, monitors, exits, etc.
        
        Args:
            remote_node: Full node name
            control_msg: Control message object (LinkMessage, ExitMessage, etc.)
        
        Examples:
            # Send LINK
            await dist.send_control_message(
                "erlang@localhost",
                LinkMessage(local_pid, remote_pid)
            )
            
            # Send EXIT
            await dist.send_control_message(
                "erlang@localhost",
                ExitMessage(from_pid, to_pid, reason)
            )
        """
        ...
    
    async def link(self, local_pid: Pid, remote_pid: Pid) -> None:
        """
        Create a link between local and remote process.
        
        Convenience method that sends CTRL_LINK control message.
        
        Args:
            local_pid: Local process PID
            remote_pid: Remote process PID
        """
        ...
    
    async def unlink(self, local_pid: Pid, remote_pid: Pid) -> None:
        """
        Remove a link between local and remote process.
        
        Convenience method that sends CTRL_UNLINK control message.
        
        Args:
            local_pid: Local process PID
            remote_pid: Remote process PID
        """
        ...
    
    async def exit(self, from_pid: Pid, to_pid: Pid, reason: Any) -> None:
        """
        Send an exit signal to a remote process.
        
        Convenience method that sends CTRL_EXIT2 control message.
        
        Args:
            from_pid: PID of exiting process
            to_pid: PID of target process
            reason: Exit reason
        """
        ...
    
    async def monitor(self, local_pid: Pid, remote_pid: Pid, ref: Reference) -> None:
        """
        Monitor a remote process.
        
        Convenience method that sends CTRL_MONITOR_P control message.
        
        Args:
            local_pid: Local process doing the monitoring
            remote_pid: Remote process being monitored
            ref: Monitor reference
        """
        ...
    
    async def demonitor(self, local_pid: Pid, remote_pid: Pid, ref: Reference) -> None:
        """
        Stop monitoring a remote process.
        
        Convenience method that sends CTRL_DEMONITOR_P control message.
        
        Args:
            local_pid: Local process that was monitoring
            remote_pid: Remote process that was being monitored
            ref: Monitor reference to remove
        """
        ...
    
    async def monitor_exit(
        self,
        from_pid: Pid,
        to_pid: Pid,
        ref: Reference,
        reason: Any
    ) -> None:
        """
        Send DOWN message to monitoring process.
        
        Convenience method that sends CTRL_MONITOR_P_EXIT control message.
        Called when a monitored process exits.
        
        Args:
            from_pid: PID of process that exited
            to_pid: PID of process that was monitoring
            ref: Monitor reference
            reason: Exit reason
        """
        ...
    
    # ========================================================================
    # Message Reception and Routing
    # ========================================================================
    
    def set_control_handler(
        self,
        handler: Callable[[tuple, Optional[Any]], Awaitable[None]]
    ) -> None:
        """
        Set callback for handling incoming control messages.
        
        The handler receives decoded ETF control tuples and optional payloads.
        
        Args:
            handler: Async function (control_tuple, payload) -> None
        
        Example:
            async def handle_control(control_tuple, payload):
                msg = ControlMessage.parse(control_tuple)
                await msg.handle(backend, payload)
            
            dist.set_control_handler(handle_control)
        """
        ...
    
    def set_message_handler(
        self,
        handler: Callable[[str, Any], Awaitable[None]]
    ) -> None:
        """
        Set callback for delivering incoming messages to local processes.
        
        Args:
            handler: Async function (target_name, message) -> None
        """
        ...


class DistributionBackendIntegration(Protocol):
    """
    Protocol for backend integration with distribution layer.
    
    Runtime backends should implement these methods to handle
    incoming control messages from remote nodes.
    """
    
    # ========================================================================
    # Remote Link Handling
    # ========================================================================
    
    async def link_remote_incoming(self, from_pid: Pid, to_pid: Pid) -> None:
        """
        Handle incoming CTRL_LINK from remote node.
        
        Called when remote process wants to link to local process.
        
        Args:
            from_pid: Remote process PID
            to_pid: Local process PID
        """
        ...
    
    async def unlink_remote_incoming(self, from_pid: Pid, to_pid: Pid) -> None:
        """
        Handle incoming CTRL_UNLINK from remote node.
        
        Args:
            from_pid: Remote process PID
            to_pid: Local process PID
        """
        ...
    
    # ========================================================================
    # Remote Monitor Handling
    # ========================================================================
    
    async def monitor_remote_incoming(
        self,
        from_pid: Pid,
        to_pid: Pid,
        ref: Reference
    ) -> None:
        """
        Handle incoming CTRL_MONITOR_P from remote node.
        
        Called when remote process wants to monitor local process.
        
        Args:
            from_pid: Remote process PID (doing the monitoring)
            to_pid: Local process PID (being monitored)
            ref: Monitor reference
        """
        ...
    
    async def demonitor_remote_incoming(
        self,
        from_pid: Pid,
        to_pid: Pid,
        ref: Reference
    ) -> None:
        """
        Handle incoming CTRL_DEMONITOR_P from remote node.
        
        Args:
            from_pid: Remote process PID
            to_pid: Local process PID
            ref: Monitor reference
        """
        ...
    
    # ========================================================================
    # Remote Exit Handling
    # ========================================================================
    
    async def exit_remote_incoming(
        self,
        from_pid: Pid,
        to_pid: Pid,
        reason: Any
    ) -> None:
        """
        Handle incoming CTRL_EXIT/CTRL_EXIT2 from remote node.
        
        Called when remote process sends exit signal to local process.
        
        Args:
            from_pid: Remote process PID that exited or sent signal
            to_pid: Local process PID receiving the signal
            reason: Exit reason
        """
        ...
    
    async def monitor_exit_remote_incoming(
        self,
        from_pid: Pid,
        to_pid: Pid,
        ref: Reference,
        reason: Any
    ) -> None:
        """
        Handle incoming CTRL_MONITOR_P_EXIT from remote node.
        
        Called when a remote monitored process exits.
        Delivers DOWN message to local monitoring process.
        
        Args:
            from_pid: Remote process PID that exited
            to_pid: Local process PID that was monitoring
            ref: Monitor reference
            reason: Exit reason
        """
        ...
    
    # ========================================================================
    # PID Resolution
    # ========================================================================
    
    def is_local_pid(self, pid: Pid) -> bool:
        """
        Check if a PID belongs to this node.
        
        Args:
            pid: Process identifier
            
        Returns:
            True if PID is local, False if remote
        """
        ...


# ============================================================================
# Example Usage
# ============================================================================

"""
Example: Implementing a distribution backend

class AsyncIODistribution:
    def __init__(self, backend: AsyncIOBackend, node_name: str, cookie: str):
        self.backend = backend
        self.node_name = node_name
        self.cookie = cookie
        self._connections: Dict[str, Connection] = {}
        self._control_handler = None
    
    async def start(self, port: int = 0):
        # Register with EPMD
        creation = await EPMD.register(self.node_name, port)
        self.backend.pid_allocator.creation = creation
        
        # Set up control handler
        self.set_control_handler(self._handle_control)
        
        # Start listening for connections
        await self._start_listener(port)
    
    async def send_control_message(self, remote_node: str, control_msg):
        conn = self._connections[remote_node]
        control_bytes = encode(control_msg.to_tuple())
        await conn.send_message(control_bytes, payload=b'')
    
    async def _handle_control(self, control_tuple: tuple, payload: Optional[Any]):
        msg = ControlMessage.parse(control_tuple)
        
        # Route to backend
        if isinstance(msg, LinkMessage):
            await self.backend.link_remote_incoming(msg.from_pid, msg.to_pid)
        elif isinstance(msg, ExitMessage):
            await self.backend.exit_remote_incoming(msg.from_pid, msg.to_pid, msg.reason)
        # ... etc
"""