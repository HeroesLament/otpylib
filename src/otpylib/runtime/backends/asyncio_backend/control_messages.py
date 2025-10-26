# otpylib/distribution/control_messages.py
"""
Distribution Control Messages

Handlers for Erlang distribution protocol control messages.
These integrate with the runtime backend to provide cross-node:
- Links (bidirectional exit propagation)
- Monitors (unidirectional DOWN messages)
- Exit signals (process termination propagation)

Control message format (after handshake):
[4 bytes: Length][1 byte: PassThrough][Control Tuple][Optional Payload]

Control tuple format:
(ControlType, FromPid, ToPid/ToName, ...) encoded as ETF
"""

from typing import Any, Optional, Tuple
from dataclasses import dataclass
from otpylib import atom
from otpylib.runtime.backends.base import Pid
from otpylib.distribution.reference import Reference

# Control message types (from distribution protocol spec)
CTRL_LINK = 1
CTRL_SEND = 2
CTRL_EXIT = 3
CTRL_UNLINK = 4
CTRL_REG_SEND = 6
CTRL_GROUP_LEADER = 7
CTRL_EXIT2 = 8
CTRL_SEND_TT = 12
CTRL_EXIT_TT = 13
CTRL_REG_SEND_TT = 16
CTRL_MONITOR_P = 19
CTRL_DEMONITOR_P = 20
CTRL_MONITOR_P_EXIT = 21


@dataclass
class ControlMessage:
    """Base class for parsed control messages"""
    ctrl_type: int
    
    @classmethod
    def parse(cls, control_tuple: tuple) -> 'ControlMessage':
        """Parse ETF control tuple into typed message"""
        ctrl_type = control_tuple[0]
        
        if ctrl_type == CTRL_LINK:
            return LinkMessage.from_tuple(control_tuple)
        elif ctrl_type == CTRL_UNLINK:
            return UnlinkMessage.from_tuple(control_tuple)
        elif ctrl_type == CTRL_EXIT or ctrl_type == CTRL_EXIT2:
            return ExitMessage.from_tuple(control_tuple)
        elif ctrl_type == CTRL_MONITOR_P:
            return MonitorMessage.from_tuple(control_tuple)
        elif ctrl_type == CTRL_DEMONITOR_P:
            return DemonitorMessage.from_tuple(control_tuple)
        elif ctrl_type == CTRL_MONITOR_P_EXIT:
            return MonitorExitMessage.from_tuple(control_tuple)
        elif ctrl_type == CTRL_SEND:
            return SendMessage.from_tuple(control_tuple)
        elif ctrl_type == CTRL_REG_SEND:
            return RegSendMessage.from_tuple(control_tuple)
        else:
            raise NotImplementedError(f"Control message type {ctrl_type} not implemented")


@dataclass
class LinkMessage(ControlMessage):
    """CTRL_LINK: Create bidirectional link between processes"""
    from_pid: Pid
    to_pid: Pid
    
    def __init__(self, from_pid: Pid, to_pid: Pid):
        super().__init__(CTRL_LINK)
        self.from_pid = from_pid
        self.to_pid = to_pid
    
    @classmethod
    def from_tuple(cls, t: tuple) -> 'LinkMessage':
        """Parse (1, FromPid, ToPid)"""
        return cls(from_pid=t[1], to_pid=t[2])
    
    def to_tuple(self) -> tuple:
        """Encode to (1, FromPid, ToPid)"""
        return (CTRL_LINK, self.from_pid, self.to_pid)
    
    async def handle(self, backend) -> None:
        """
        Handle incoming LINK message.
        
        Creates a link between remote process (from_pid) and local process (to_pid).
        If to_pid doesn't exist, send EXIT back immediately.
        """
        if not backend.is_alive(self.to_pid):
            # Local process doesn't exist - send EXIT back
            exit_msg = ExitMessage(
                from_pid=self.to_pid,
                to_pid=self.from_pid,
                reason=atom.ensure('noproc')
            )
            # TODO: Send exit_msg back to remote node
            return
        
        # Create the link (backend should track remote links separately)
        await backend.link_remote(self.to_pid, self.from_pid)


@dataclass
class UnlinkMessage(ControlMessage):
    """CTRL_UNLINK: Remove link between processes"""
    from_pid: Pid
    to_pid: Pid
    
    def __init__(self, from_pid: Pid, to_pid: Pid):
        super().__init__(CTRL_UNLINK)
        self.from_pid = from_pid
        self.to_pid = to_pid
    
    @classmethod
    def from_tuple(cls, t: tuple) -> 'UnlinkMessage':
        """Parse (4, FromPid, ToPid)"""
        return cls(from_pid=t[1], to_pid=t[2])
    
    def to_tuple(self) -> tuple:
        """Encode to (4, FromPid, ToPid)"""
        return (CTRL_UNLINK, self.from_pid, self.to_pid)
    
    async def handle(self, backend) -> None:
        """Remove link between remote and local process"""
        await backend.unlink_remote(self.to_pid, self.from_pid)


@dataclass
class ExitMessage(ControlMessage):
    """CTRL_EXIT/CTRL_EXIT2: Propagate process exit"""
    from_pid: Pid
    to_pid: Pid
    reason: Any
    
    def __init__(self, from_pid: Pid, to_pid: Pid, reason: Any):
        super().__init__(CTRL_EXIT2)
        self.from_pid = from_pid
        self.to_pid = to_pid
        self.reason = reason
    
    @classmethod
    def from_tuple(cls, t: tuple) -> 'ExitMessage':
        """Parse (3, FromPid, ToPid, Reason) or (8, FromPid, ToPid, TraceToken, Reason)"""
        if len(t) == 4:
            return cls(from_pid=t[1], to_pid=t[2], reason=t[3])
        else:  # CTRL_EXIT2 with trace token
            return cls(from_pid=t[1], to_pid=t[2], reason=t[4])
    
    def to_tuple(self) -> tuple:
        """Encode to (8, FromPid, ToPid, TraceToken, Reason)"""
        trace_token = []  # Empty list = no tracing
        return (CTRL_EXIT2, self.from_pid, self.to_pid, trace_token, self.reason)
    
    async def handle(self, backend) -> None:
        """
        Handle incoming EXIT signal.
        
        If to_pid has trap_exit=True, delivers as message: {'EXIT', FromPid, Reason}
        Otherwise, terminates to_pid with the same reason.
        """
        if not backend.is_alive(self.to_pid):
            return  # Already dead, nothing to do
        
        # Check if process is trapping exits
        proc_info = backend.process_info(self.to_pid)
        if proc_info and proc_info.trap_exits:
            # Deliver as message
            exit_tuple = (atom.ensure('EXIT'), self.from_pid, self.reason)
            await backend.send(self.to_pid, exit_tuple)
        else:
            # Terminate the process
            await backend.exit(self.to_pid, self.reason)


@dataclass
class MonitorMessage(ControlMessage):
    """CTRL_MONITOR_P: Create unidirectional monitor"""
    from_pid: Pid
    to_pid: Pid
    ref: Reference
    
    def __init__(self, from_pid: Pid, to_pid: Pid, ref: Reference):
        super().__init__(CTRL_MONITOR_P)
        self.from_pid = from_pid
        self.to_pid = to_pid
        self.ref = ref
    
    @classmethod
    def from_tuple(cls, t: tuple) -> 'MonitorMessage':
        """Parse (19, FromPid, ToPid, Ref)"""
        return cls(from_pid=t[1], to_pid=t[2], ref=t[3])
    
    def to_tuple(self) -> tuple:
        """Encode to (19, FromPid, ToPid, Ref)"""
        return (CTRL_MONITOR_P, self.from_pid, self.to_pid, self.ref)
    
    async def handle(self, backend) -> None:
        """
        Handle incoming MONITOR request.
        
        If to_pid exists, track the monitor.
        If to_pid doesn't exist, send MONITOR_P_EXIT back immediately.
        """
        if not backend.is_alive(self.to_pid):
            # Send DOWN message immediately
            down_msg = MonitorExitMessage(
                from_pid=self.to_pid,
                to_pid=self.from_pid,
                ref=self.ref,
                reason=atom.ensure('noproc')
            )
            # TODO: Send down_msg back to remote node
            return
        
        # Track remote monitor
        await backend.monitor_remote(self.to_pid, self.from_pid, self.ref)


@dataclass
class DemonitorMessage(ControlMessage):
    """CTRL_DEMONITOR_P: Remove monitor"""
    from_pid: Pid
    to_pid: Pid
    ref: Reference
    
    def __init__(self, from_pid: Pid, to_pid: Pid, ref: Reference):
        super().__init__(CTRL_DEMONITOR_P)
        self.from_pid = from_pid
        self.to_pid = to_pid
        self.ref = ref
    
    @classmethod
    def from_tuple(cls, t: tuple) -> 'DemonitorMessage':
        """Parse (20, FromPid, ToPid, Ref)"""
        return cls(from_pid=t[1], to_pid=t[2], ref=t[3])
    
    def to_tuple(self) -> tuple:
        """Encode to (20, FromPid, ToPid, Ref)"""
        return (CTRL_DEMONITOR_P, self.from_pid, self.to_pid, self.ref)
    
    async def handle(self, backend) -> None:
        """Remove remote monitor"""
        await backend.demonitor_remote(self.to_pid, self.ref)


@dataclass
class MonitorExitMessage(ControlMessage):
    """CTRL_MONITOR_P_EXIT: Send DOWN message to monitoring process"""
    from_pid: Pid
    to_pid: Pid
    ref: Reference
    reason: Any
    
    def __init__(self, from_pid: Pid, to_pid: Pid, ref: Reference, reason: Any):
        super().__init__(CTRL_MONITOR_P_EXIT)
        self.from_pid = from_pid
        self.to_pid = to_pid
        self.ref = ref
        self.reason = reason
    
    @classmethod
    def from_tuple(cls, t: tuple) -> 'MonitorExitMessage':
        """Parse (21, FromPid, ToPid, Ref, Reason)"""
        return cls(from_pid=t[1], to_pid=t[2], ref=t[3], reason=t[4])
    
    def to_tuple(self) -> tuple:
        """Encode to (21, FromPid, ToPid, Ref, Reason)"""
        return (CTRL_MONITOR_P_EXIT, self.from_pid, self.to_pid, self.ref, self.reason)
    
    async def handle(self, backend) -> None:
        """
        Handle incoming DOWN message.
        
        Delivers DOWN message to monitoring process:
        {'DOWN', Ref, :process, Pid, Reason}
        """
        if not backend.is_alive(self.to_pid):
            return  # Monitoring process already dead
        
        # Build DOWN message (Erlang format)
        down_tuple = (
            atom.ensure('DOWN'),
            self.ref,
            atom.ensure('process'),
            self.from_pid,
            self.reason
        )
        await backend.send(self.to_pid, down_tuple)


@dataclass
class SendMessage(ControlMessage):
    """CTRL_SEND: Send message to PID"""
    unused: Any  # Cookie (unused in modern Erlang)
    to_pid: Pid
    
    def __init__(self, to_pid: Pid):
        super().__init__(CTRL_SEND)
        self.unused = atom.ensure('')  # Empty atom for unused field
        self.to_pid = to_pid
    
    @classmethod
    def from_tuple(cls, t: tuple) -> 'SendMessage':
        """Parse (2, Unused, ToPid)"""
        return cls(to_pid=t[2])
    
    def to_tuple(self) -> tuple:
        """Encode to (2, '', ToPid)"""
        return (CTRL_SEND, self.unused, self.to_pid)
    
    async def handle(self, backend, payload: Any) -> None:
        """Deliver message payload to local process"""
        if backend.is_alive(self.to_pid):
            await backend.send(self.to_pid, payload)


@dataclass
class RegSendMessage(ControlMessage):
    """CTRL_REG_SEND: Send message to registered name"""
    from_pid: Pid
    unused: Any  # Cookie (unused)
    to_name: atom.Atom
    
    def __init__(self, from_pid: Pid, to_name: atom.Atom):
        super().__init__(CTRL_REG_SEND)
        self.from_pid = from_pid
        self.unused = atom.ensure('')
        self.to_name = to_name
    
    @classmethod
    def from_tuple(cls, t: tuple) -> 'RegSendMessage':
        """Parse (6, FromPid, Unused, ToName)"""
        return cls(from_pid=t[1], to_name=t[3])
    
    def to_tuple(self) -> tuple:
        """Encode to (6, FromPid, '', ToName)"""
        return (CTRL_REG_SEND, self.from_pid, self.unused, self.to_name)
    
    async def handle(self, backend, payload: Any) -> None:
        """Deliver message payload to registered process"""
        print(f"[RegSendMessage.handle] Called!")
        print(f"[RegSendMessage.handle] to_name: {self.to_name} (type: {type(self.to_name)})")
        print(f"[RegSendMessage.handle] payload: {payload}")
        
        # Look up registered name
        name_str = self.to_name.name if hasattr(self.to_name, 'name') else str(self.to_name)
        print(f"[RegSendMessage.handle] Looking up: '{name_str}'")
        
        pid = backend.whereis(name_str)
        print(f"[RegSendMessage.handle] whereis returned: {pid}")
        
        if pid:
            print(f"[RegSendMessage.handle] is_alive check: {backend.is_alive(pid)}")
            if backend.is_alive(pid):
                print(f"[RegSendMessage.handle] Sending to {pid}")
                await backend.send(pid, payload)
                print(f"[RegSendMessage.handle] Send complete!")
            else:
                print(f"[RegSendMessage.handle] PID not alive!")
        else:
            print(f"[RegSendMessage.handle] whereis returned None!")
            print(f"[RegSendMessage.handle] Registry contents: {backend._name_registry}")


# ============================================================================
# Control Message Dispatcher
# ============================================================================

class ControlMessageHandler:
    """
    Handles incoming distribution control messages.
    
    Integrates with RuntimeBackend to provide cross-node process control.
    """
    
    def __init__(self, backend):
        """
        Initialize handler with runtime backend.
        
        Args:
            backend: RuntimeBackend instance (e.g., AsyncIOBackend)
        """
        self.backend = backend
    
    async def handle_control(self, control_tuple: tuple, payload: Optional[Any] = None):
        """
        Parse and handle a control message.
        
        Args:
            control_tuple: Decoded ETF control tuple
            payload: Optional message payload (for SEND/REG_SEND)
        """
        try:
            msg = ControlMessage.parse(control_tuple)
            
            # Messages with payload
            if isinstance(msg, (SendMessage, RegSendMessage)):
                await msg.handle(self.backend, payload)
            else:
                await msg.handle(self.backend)
                
        except Exception as e:
            # Log error but don't crash distribution
            print(f"[Distribution] Error handling control message: {e}")
            print(f"[Distribution] Control tuple: {control_tuple}")


# ============================================================================
# Backend Extensions (to be added to AsyncIOBackend)
# ============================================================================

"""
The following methods need to be added to AsyncIOBackend to support
cross-node process control:

class AsyncIOBackend:
    def __init__(self):
        # ... existing code ...
        
        # Remote process tracking
        self._remote_links: Dict[Pid, Set[Pid]] = {}  # local_pid -> {remote_pids}
        self._remote_monitors: Dict[Pid, Dict[Reference, Pid]] = {}  # monitored_pid -> {ref: monitoring_pid}
    
    async def link_remote(self, local_pid: Pid, remote_pid: Pid) -> None:
        '''Create link between local and remote process'''
        if local_pid not in self._remote_links:
            self._remote_links[local_pid] = set()
        self._remote_links[local_pid].add(remote_pid)
    
    async def unlink_remote(self, local_pid: Pid, remote_pid: Pid) -> None:
        '''Remove link between local and remote process'''
        if local_pid in self._remote_links:
            self._remote_links[local_pid].discard(remote_pid)
    
    async def monitor_remote(self, monitored_pid: Pid, monitoring_pid: Pid, ref: Reference) -> None:
        '''Track remote monitor'''
        if monitored_pid not in self._remote_monitors:
            self._remote_monitors[monitored_pid] = {}
        self._remote_monitors[monitored_pid][ref] = monitoring_pid
    
    async def demonitor_remote(self, monitored_pid: Pid, ref: Reference) -> None:
        '''Remove remote monitor'''
        if monitored_pid in self._remote_monitors:
            self._remote_monitors[monitored_pid].pop(ref, None)
    
    def get_remote_links(self, pid: Pid) -> Set[Pid]:
        '''Get all remote PIDs linked to this local PID'''
        return self._remote_links.get(pid, set())
    
    def get_remote_monitors(self, pid: Pid) -> Dict[Reference, Pid]:
        '''Get all remote monitors for this local PID'''
        return self._remote_monitors.get(pid, {})
"""