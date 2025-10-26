"""
AsyncIO Backend Implementation

Main backend class that implements the RuntimeBackend protocol.
Now with full support for distributed process control (remote links, monitors, exits).
"""

import asyncio
import time
from typing import Any, Dict, List, Optional, Union, Callable, Tuple, Set
from contextvars import ContextVar

from otpylib import atom
from otpylib.runtime.backends.base import (
    RuntimeBackend, ProcessNotFoundError, NameAlreadyRegisteredError, NotInProcessError
)
from otpylib.runtime.data import (
    ProcessInfo, RuntimeStatistics, ProcessCharacteristics, MonitorRef
)
from otpylib.runtime.atoms import (
    RUNNING, WAITING, TERMINATED, NORMAL, KILLED, EXIT, DOWN, SHUTDOWN, SUPERVISOR_SHUTDOWN
)
from otpylib.runtime.atom_utils import (
    is_normal_exit, format_down_message, format_exit_message
)

from otpylib.runtime.backends.asyncio_backend.control_messages import (
    Reference,
    ExitMessage,
    LinkMessage,
    UnlinkMessage,
    MonitorMessage,
    DemonitorMessage,
    MonitorExitMessage, 
)
from otpylib.runtime.backends.asyncio_backend.timing_wheel import TimingWheel
from otpylib.runtime.backends.asyncio_backend.process import Process, ProcessMailbox
from otpylib.runtime.backends.asyncio_backend import tcp
from otpylib.runtime.backends.asyncio_backend.pid import Pid, PidAllocator

# Logger target
LOGGER = atom.ensure("logger")

# Context variable to track current process
_current_process: ContextVar[Optional[Pid]] = ContextVar("current_process", default=None)


class AsyncIOBackend(RuntimeBackend):
    """
    Runtime backend using pure asyncio.

    Simpler and more performant than anyio, closer to BEAM semantics.
    Now supports distributed process control across nodes.
    """

    def __init__(self):
        # Process registry
        self._processes: Dict[Pid, Process] = {}
        self._name_registry: Dict[str, Pid] = {}

        # Monitor tracking
        self._monitors: Dict[str, MonitorRef] = {}

        # Timer tracking
        self.timing_wheel = TimingWheel(tick_ms=10, num_slots=512)
        self._wheel_task: Optional[asyncio.Task] = None
        self._shutdown_flag = False

        # Pid allocator
        self.pid_allocator: Optional[PidAllocator] = None

        # Remote process control
        self._remote_links: Dict[Pid, Set[Pid]] = {}  # local_pid -> {remote_pids}
        self._remote_links_reverse: Dict[Pid, Set[Pid]] = {}  # remote_pid -> {local_pids}
        self._remote_monitors: Dict[Pid, Dict[str, Pid]] = {}  # local_pid -> {ref_str: remote_pid}
        self._remote_monitors_reverse: Dict[Pid, Dict[str, Pid]] = {}  # remote_pid -> {ref_str: local_pid}
        self._ref_counter = 0  # For creating unique references

        # Statistics
        self._stats = {
            "total_spawned": 0,
            "total_terminated": 0,
            "messages_sent": 0,
            "down_messages_sent": 0,
            "exit_signals_sent": 0,
        }
        self._startup_time = time.time()

    # =========================================================================
    # Core Process Management
    # =========================================================================

    async def spawn(
        self,
        func: Callable,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
        mailbox: bool = True,
        trap_exits: bool = False,
        characteristics: Optional[ProcessCharacteristics] = None,
    ) -> Pid:
        """Spawn a new process."""
        pid = await self.pid_allocator.allocate()

        await self.send(LOGGER, ("log", "DEBUG", f"[spawn] name={name}, pid={pid}", {"name": name, "pid": str(pid)}))

        proc = Process(
            pid=pid,
            func=func,
            args=args or [],
            kwargs=kwargs or {},
            name=name,
            characteristics=characteristics,
            trap_exits=trap_exits,
        )

        if mailbox:
            proc.mailbox = ProcessMailbox(maxsize=0)

        if name:
            self._name_registry[name] = pid

        self._processes[pid] = proc
        self._stats["total_spawned"] += 1

        async def run_process():
            token = _current_process.set(pid)
            reason = None
            try:
                proc.info.state = RUNNING
                proc.info.last_active = time.time()
                reason = await proc.run()
            except Exception as e:
                reason = e
                raise
            finally:
                _current_process.reset(token)
                proc.info.state = TERMINATED
                await self._handle_process_exit(pid, reason)
                self._cleanup_process(pid)
                await self.send(LOGGER, ("log", "DEBUG", f"[cleanup] completed for pid={pid}, reason={reason}", 
                                        {"pid": str(pid), "reason": str(reason)}))

        proc.task = asyncio.create_task(run_process())
        await self.send(LOGGER, ("log", "DEBUG", f"[spawn] Spawned process {pid} (name={name})", 
                                {"pid": str(pid), "name": name}))
        return pid

    async def spawn_link(self, *args, **kwargs) -> Pid:
        pid = await self.spawn(*args, **kwargs)
        await self.link(pid)
        return pid

    async def spawn_monitor(self, *args, **kwargs) -> Tuple[Pid, str]:
        pid = await self.spawn(*args, **kwargs)
        ref = await self.monitor(pid)
        return pid, ref

    async def exit(self, pid: Union[Pid, str], reason: Any) -> None:
        """Send an exit signal to a process (BEAM-style semantics)."""
        # Resolve name to PID
        if isinstance(pid, str):
            target_pid = self._name_registry.get(pid)
            if not target_pid:
                raise ProcessNotFoundError(f"Process {pid} not found")
        else:
            target_pid = pid
        
        process = self._processes.get(target_pid)

        await self.send(LOGGER, ("log", "DEBUG", f"[exit] target={pid} resolved={target_pid} reason={reason}",
                                {"target": str(pid), "resolved": str(target_pid), "reason": str(reason)}))

        if not process:
            raise ProcessNotFoundError(f"Process {pid} not found")

        if reason == KILLED:
            if process.task and not process.task.done():
                process.task.cancel()
                await self.send(LOGGER, ("log", "DEBUG", f"[exit] Hard-killed process {target_pid}",
                                        {"pid": str(target_pid)}))

            process.info.state = TERMINATED
            loop = asyncio.get_running_loop()
            loop.call_soon(self._cleanup_process, target_pid)
            await self.send(LOGGER, ("log", "DEBUG", f"[defer-cleanup] scheduled for pid={target_pid}, reason=killed",
                                    {"pid": str(target_pid), "reason": "killed"}))
            await self._notify_exit(target_pid, reason)
            return

        if process.trap_exits and process.mailbox:
            exit_msg = (EXIT, self.self() or "system", reason)
            await process.mailbox.send(exit_msg)
            await self.send(LOGGER, ("log", "DEBUG", f"[exit] Sent EXIT message to {target_pid}",
                                    {"pid": str(target_pid)}))
        else:
            if process.task and not process.task.done():
                process.task.cancel()
                await self.send(LOGGER, ("log", "DEBUG", f"[exit] Cancelled process {target_pid}",
                                        {"pid": str(target_pid)}))

        # Don't call _notify_exit for graceful shutdowns - let _handle_process_exit handle it
        # This ensures DOWN messages are sent with monitors still intact
        if reason not in [SHUTDOWN, SUPERVISOR_SHUTDOWN]:
            await self._notify_exit(target_pid, reason)

    async def _notify_exit(self, pid: Pid, reason: Any, visited: Optional[set] = None) -> None:
        """Propagate exit signals to links and monitors with cycle protection."""
        if visited is None:
            visited = set()
        if pid in visited:
            return
        visited.add(pid)

        process = self._processes.get(pid)
        if not process:
            return

        for linked_pid in list(process.links):
            linked = self._processes.get(linked_pid)
            if not linked:
                continue

            if linked.trap_exits and linked.mailbox:
                await linked.mailbox.send((EXIT, pid, reason))
                await self.send(LOGGER, ("log", "DEBUG", f"[link-exit] Delivered EXIT to {linked_pid}",
                                        {"pid": str(linked_pid)}))
            else:
                if linked.task and not linked.task.done():
                    linked.task.cancel()
                    await self.send(LOGGER, ("log", "DEBUG", f"[link-exit] Cascade kill {linked_pid}",
                                            {"pid": str(linked_pid)}))
                await self._notify_exit(linked_pid, reason, visited=visited)

        for ref, watcher_pid in list(process.monitored_by.items()):
            if watcher_pid in self._processes:
                await self.send(watcher_pid, (DOWN, ref, pid, reason))
                await self.send(LOGGER, ("log", "DEBUG", f"[monitor-exit] Sent DOWN to {watcher_pid}",
                                        {"watcher": str(watcher_pid)}))

        for linked_pid in list(process.links):
            if linked_pid in self._processes:
                self._processes[linked_pid].links.discard(pid)
        process.links.clear()

        for ref, watcher_pid in list(process.monitored_by.items()):
            if watcher_pid in self._processes:
                self._processes[watcher_pid].monitors.pop(ref, None)
        process.monitored_by.clear()

        if process.name:
            self._name_registry.pop(process.name, None)

    def self(self) -> Optional[Pid]:
        return _current_process.get()

    # =========================================================================
    # Process Relationships - Local and Remote
    # =========================================================================

    async def link(self, pid: Union[Pid, str]) -> None:
        """Link current process to another (local or remote)."""
        # Resolve name to PID if needed
        if isinstance(pid, str):
            resolved = self._name_registry.get(pid)
            if not resolved:
                raise ProcessNotFoundError(f"Process {pid} not found")
            target_pid = resolved
        else:
            target_pid = pid

        current_pid = self.self()
        if not current_pid:
            raise NotInProcessError("link() must be called from within a process")

        # Check if remote or local
        if self._is_local_pid(target_pid):
            await self._link_local(current_pid, target_pid)
        else:
            await self._link_remote(current_pid, target_pid)

    async def _link_local(self, from_pid: Pid, to_pid: Pid) -> None:
        """Create bidirectional link between two LOCAL processes."""
        from_proc = self._processes.get(from_pid)
        to_proc = self._processes.get(to_pid)
        
        if not from_proc or not to_proc:
            raise ProcessNotFoundError(f"Cannot link: process not found")
        
        # Create bidirectional link
        from_proc.links.add(to_pid)
        to_proc.links.add(from_pid)
        
        await self.send(LOGGER, ("log", "DEBUG", f"[link_local] {from_pid} <-> {to_pid}", {}))

    async def _link_remote(self, local_pid: Pid, remote_pid: Pid) -> None:
        """Create link to REMOTE process"""
        # Track locally
        if local_pid not in self._remote_links:
            self._remote_links[local_pid] = set()
        self._remote_links[local_pid].add(remote_pid)
        
        if remote_pid not in self._remote_links_reverse:
            self._remote_links_reverse[remote_pid] = set()
        self._remote_links_reverse[remote_pid].add(local_pid)
        
        # Send CTRL_LINK to remote node
        from otpylib.runtime.registry import get_distribution
        dist = get_distribution()
        if dist:
            await dist.send_control_message(
                remote_pid.node.name,
                LinkMessage(local_pid, remote_pid)
            )
        
        await self.send(LOGGER, ("log", "DEBUG", f"[link_remote] {local_pid} <-> {remote_pid}", {}))

    async def unlink(self, pid: Union[Pid, str]) -> None:
        """Remove link to another process (local or remote)."""
        # Resolve name to PID
        if isinstance(pid, str):
            resolved = self._name_registry.get(pid)
            if not resolved:
                return  # Already gone
            target_pid = resolved
        else:
            target_pid = pid
        
        current_pid = self.self()
        if not current_pid:
            raise NotInProcessError("unlink() must be called from within a process")
        
        # Check if remote or local
        if self._is_local_pid(target_pid):
            await self._unlink_local(current_pid, target_pid)
        else:
            await self._unlink_remote(current_pid, target_pid)

    async def _unlink_local(self, from_pid: Pid, to_pid: Pid) -> None:
        """Remove bidirectional link between two LOCAL processes"""
        from_proc = self._processes.get(from_pid)
        to_proc = self._processes.get(to_pid)
        
        if from_proc:
            from_proc.links.discard(to_pid)
        if to_proc:
            to_proc.links.discard(from_pid)
        
        await self.send(LOGGER, ("log", "DEBUG", f"[unlink_local] {from_pid} <-> {to_pid}", {}))

    async def _unlink_remote(self, local_pid: Pid, remote_pid: Pid) -> None:
        """Remove link to REMOTE process"""
        # Remove from tracking
        if local_pid in self._remote_links:
            self._remote_links[local_pid].discard(remote_pid)
            if not self._remote_links[local_pid]:
                del self._remote_links[local_pid]
        
        if remote_pid in self._remote_links_reverse:
            self._remote_links_reverse[remote_pid].discard(local_pid)
            if not self._remote_links_reverse[remote_pid]:
                del self._remote_links_reverse[remote_pid]
        
        # Send CTRL_UNLINK to remote node
        from otpylib.runtime.registry import get_distribution
        dist = get_distribution()
        if dist:
            await dist.send_control_message(
                remote_pid.node.name,
                UnlinkMessage(local_pid, remote_pid)
            )
        
        await self.send(LOGGER, ("log", "DEBUG", f"[unlink_remote] {local_pid} <-> {remote_pid}", {}))

    async def link_remote_incoming(self, from_pid: Pid, to_pid: Pid) -> None:
        """
        Handle incoming CTRL_LINK from remote node.
        
        Called by distribution layer when remote process wants to link to our process.
        """
        if not self.is_alive(to_pid):
            # Local process doesn't exist - send EXIT back
            from otpylib.runtime.registry import get_distribution
            dist = get_distribution()
            if dist:
                await dist.send_control_message(
                    from_pid.node.name,
                    ExitMessage(to_pid, from_pid, atom.ensure('noproc'))
                )
            return
        
        # Track the remote link (bidirectional)
        if to_pid not in self._remote_links:
            self._remote_links[to_pid] = set()
        self._remote_links[to_pid].add(from_pid)
        
        if from_pid not in self._remote_links_reverse:
            self._remote_links_reverse[from_pid] = set()
        self._remote_links_reverse[from_pid].add(to_pid)
        
        await self.send(LOGGER, ("log", "DEBUG", f"[link_remote_incoming] {from_pid} <-> {to_pid}", {}))

    async def unlink_remote_incoming(self, from_pid: Pid, to_pid: Pid) -> None:
        """Handle incoming CTRL_UNLINK from remote node"""
        # Remove from tracking
        if to_pid in self._remote_links:
            self._remote_links[to_pid].discard(from_pid)
            if not self._remote_links[to_pid]:
                del self._remote_links[to_pid]
        
        if from_pid in self._remote_links_reverse:
            self._remote_links_reverse[from_pid].discard(to_pid)
            if not self._remote_links_reverse[from_pid]:
                del self._remote_links_reverse[from_pid]
        
        await self.send(LOGGER, ("log", "DEBUG", f"[unlink_remote_incoming] {from_pid} <-> {to_pid}", {}))

    # =========================================================================
    # Monitor Management - Local and Remote
    # =========================================================================

    async def monitor(self, pid: Union[Pid, str]) -> str:
        """Monitor a process (local or remote)."""
        # Resolve name to PID
        if isinstance(pid, str):
            resolved = self._name_registry.get(pid)
            if not resolved:
                raise ProcessNotFoundError(f"Process {pid} not found")
            target_pid = resolved
        else:
            target_pid = pid
        
        current_pid = self.self()
        if not current_pid:
            raise NotInProcessError("monitor() must be called from within a process")
        
        # Check if remote or local
        if self._is_local_pid(target_pid):
            return await self._monitor_local(current_pid, target_pid)
        else:
            return await self._monitor_remote(current_pid, target_pid)

    async def _monitor_local(self, monitoring_pid: Pid, monitored_pid: Pid) -> str:
        """Create monitor for LOCAL process."""
        monitored_proc = self._processes.get(monitored_pid)
        if not monitored_proc:
            raise ProcessNotFoundError(f"Process {monitored_pid} not found")
        
        monitoring_proc = self._processes.get(monitoring_pid)
        if not monitoring_proc:
            raise ProcessNotFoundError(f"Process {monitoring_pid} not found")
        
        # Create unique reference
        ref = f"#Ref<{monitoring_pid}.{len(monitoring_proc.monitors)}>"
        
        # Track monitor bidirectionally
        monitoring_proc.monitors[ref] = monitored_pid
        monitored_proc.monitored_by[ref] = monitoring_pid
        
        await self.send(LOGGER, ("log", "DEBUG", 
            f"[monitor_local] {monitoring_pid} -> {monitored_pid} (ref={ref})", {}))
        
        return ref

    def _make_reference(self) -> Reference:
        """Create a unique ETF Reference for remote monitors"""
        self._ref_counter += 1
        
        return Reference(
            node=self.pid_allocator.node_atom,
            creation=self.pid_allocator.creation,
            ids=(self._ref_counter, 0, 0)
        )

    async def _monitor_remote(self, local_pid: Pid, remote_pid: Pid) -> str:
        """Create monitor for REMOTE process"""
        # Create reference
        ref = self._make_reference()
        ref_str = str(ref)
        
        # Track locally
        if local_pid not in self._remote_monitors:
            self._remote_monitors[local_pid] = {}
        self._remote_monitors[local_pid][ref_str] = remote_pid
        
        if remote_pid not in self._remote_monitors_reverse:
            self._remote_monitors_reverse[remote_pid] = {}
        self._remote_monitors_reverse[remote_pid][ref_str] = local_pid
        
        # Send CTRL_MONITOR_P to remote node
        from otpylib.runtime.registry import get_distribution
        dist = get_distribution()
        if dist:
            await dist.send_control_message(
                remote_pid.node.name,
                MonitorMessage(local_pid, remote_pid, ref)
            )
        
        await self.send(LOGGER, ("log", "DEBUG", 
            f"[monitor_remote] {local_pid} -> {remote_pid} (ref={ref_str})", {}))
        
        return ref_str

    async def demonitor(self, ref: str, flush: bool = False) -> None:
        """Remove a monitor (local or remote)."""
        current_pid = self.self()
        if not current_pid:
            raise NotInProcessError("demonitor() must be called from within a process")
        
        # Check if it's a remote monitor
        if current_pid in self._remote_monitors and ref in self._remote_monitors[current_pid]:
            await self._demonitor_remote(current_pid, ref)
        else:
            await self._demonitor_local(current_pid, ref, flush)

    async def _demonitor_local(self, monitoring_pid: Pid, ref: str, flush: bool) -> None:
        """Remove LOCAL monitor"""
        monitoring_proc = self._processes.get(monitoring_pid)
        if not monitoring_proc or ref not in monitoring_proc.monitors:
            return
        
        monitored_pid = monitoring_proc.monitors.pop(ref)
        monitored_proc = self._processes.get(monitored_pid)
        
        if monitored_proc and ref in monitored_proc.monitored_by:
            del monitored_proc.monitored_by[ref]
        
        if flush and monitoring_proc.mailbox:
            if hasattr(monitoring_proc.mailbox, '_queue') and hasattr(monitoring_proc.mailbox._queue, '_queue'):
                queue_items = list(monitoring_proc.mailbox._queue._queue)
                filtered = [m for m in queue_items if not (isinstance(m, tuple) and len(m) >= 2 and m[0] == DOWN and m[1] == ref)]
                
                monitoring_proc.mailbox._queue._queue.clear()
                for item in filtered:
                    monitoring_proc.mailbox._queue._queue.append(item)
        
        await self.send(LOGGER, ("log", "DEBUG", 
            f"[demonitor_local] {monitoring_pid} (ref={ref})", {}))

    async def _demonitor_remote(self, local_pid: Pid, ref_str: str) -> None:
        """Remove REMOTE monitor"""
        if local_pid not in self._remote_monitors:
            return
        
        remote_pid = self._remote_monitors[local_pid].pop(ref_str, None)
        if not remote_pid:
            return
        
        # Clean up forward mapping
        if not self._remote_monitors[local_pid]:
            del self._remote_monitors[local_pid]
        
        # Clean up reverse mapping
        if remote_pid in self._remote_monitors_reverse:
            self._remote_monitors_reverse[remote_pid].pop(ref_str, None)
            if not self._remote_monitors_reverse[remote_pid]:
                del self._remote_monitors_reverse[remote_pid]
        
        # Send CTRL_DEMONITOR_P to remote node
        from otpylib.runtime.registry import get_distribution
        dist = get_distribution()
        if dist:
            # Parse ref_str back to Reference
            ref = Reference(
                node=self.pid_allocator.node_atom,
                creation=self.pid_allocator.creation,
                ids=(hash(ref_str) & 0xFFFFFFFF, 0, 0)
            )
            await dist.send_control_message(
                remote_pid.node.name,
                DemonitorMessage(local_pid, remote_pid, ref)
            )
        
        await self.send(LOGGER, ("log", "DEBUG", 
            f"[demonitor_remote] {local_pid} (ref={ref_str})", {}))

    async def monitor_remote_incoming(self, from_pid: Pid, to_pid: Pid, ref: Reference) -> None:
        """
        Handle incoming CTRL_MONITOR_P from remote node.
        
        Called by distribution layer when remote process wants to monitor our process.
        """
        if not self.is_alive(to_pid):
            # Local process doesn't exist - send DOWN immediately
            from otpylib.runtime.registry import get_distribution
            dist = get_distribution()
            if dist:
                await dist.send_control_message(
                    from_pid.node.name,
                    MonitorExitMessage(to_pid, from_pid, ref, atom.ensure('noproc'))
                )
            return
        
        # Track the remote monitor
        ref_str = str(ref)
        if to_pid not in self._remote_monitors_reverse:
            self._remote_monitors_reverse[to_pid] = {}
        self._remote_monitors_reverse[to_pid][ref_str] = from_pid
        
        await self.send(LOGGER, ("log", "DEBUG", 
            f"[monitor_remote_incoming] {from_pid} -> {to_pid} (ref={ref_str})", {}))

    async def demonitor_remote_incoming(self, from_pid: Pid, to_pid: Pid, ref: Reference) -> None:
        """Handle incoming CTRL_DEMONITOR_P from remote node"""
        ref_str = str(ref)
        
        if to_pid in self._remote_monitors_reverse:
            self._remote_monitors_reverse[to_pid].pop(ref_str, None)
            if not self._remote_monitors_reverse[to_pid]:
                del self._remote_monitors_reverse[to_pid]
        
        await self.send(LOGGER, ("log", "DEBUG", 
            f"[demonitor_remote_incoming] {from_pid} -> {to_pid} (ref={ref_str})", {}))

    # =========================================================================
    # Remote Exit Handling
    # =========================================================================

    async def exit_remote_incoming(self, from_pid: Pid, to_pid: Pid, reason: Any) -> None:
        """
        Handle incoming CTRL_EXIT/CTRL_EXIT2 from remote node.
        
        Called when remote process sends exit signal to local process.
        """
        if not self.is_alive(to_pid):
            return  # Already dead
        
        # Check if process is trapping exits
        proc_info = self.process_info(to_pid)
        if proc_info and proc_info.trap_exits:
            # Deliver as message
            exit_tuple = (EXIT, from_pid, reason)
            await self.send(to_pid, exit_tuple)
            await self.send(LOGGER, ("log", "DEBUG", 
                f"[exit_remote_incoming] delivered EXIT to {to_pid} (trapping)", {}))
        else:
            # Terminate the process
            await self.exit(to_pid, reason)
            await self.send(LOGGER, ("log", "DEBUG", 
                f"[exit_remote_incoming] killed {to_pid} with reason={reason}", {}))

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
        """
        if not self.is_alive(to_pid):
            return  # Monitoring process already dead
        
        # Build DOWN message (Erlang format)
        down_tuple = (
            DOWN,
            ref,
            atom.ensure('process'),
            from_pid,
            reason
        )
        await self.send(to_pid, down_tuple)
        
        await self.send(LOGGER, ("log", "DEBUG",
            f"[monitor_exit_remote_incoming] sent DOWN to {to_pid} (ref={ref})", {}))

    # =========================================================================
    # Message Passing
    # =========================================================================

    async def send(
        self, 
        pid_or_name: Union[Pid, str, atom.Atom, Tuple[str, str]], 
        message: Any
    ) -> None:
        """
        Send a message to a process (fire-and-forget, silently drops if not found).
        
        Args:
            pid_or_name: Target process as:
                - Pid: Local or remote PID (transparent routing)
                - str/Atom: Local registered name only
                - Tuple[str, str]: Remote registered name as (name, node)
            message: Message to send
            
        Examples:
            # Send to PID (local or remote)
            await backend.send(pid, message)
            
            # Send to local registered name
            await backend.send("test_server", message)
            
            # Send to remote registered name
            await backend.send(("test_server", "node_b@127.0.0.1"), message)
        """
        
        # Handle PIDs (transparent local/remote routing)
        if isinstance(pid_or_name, Pid):
            target_pid = pid_or_name
            
            # Check if remote
            if not self._is_local_pid(target_pid):
                from otpylib.runtime.registry import get_distribution
                dist = get_distribution()
                if dist:
                    remote_node = target_pid.node.name if hasattr(target_pid.node, 'name') else str(target_pid.node)
                    await dist.send_to_pid(remote_node, target_pid, message)
                    self._stats["messages_sent"] += 1
                # else: no distribution layer - silently drop
                return
            
            # Local PID - fall through to local send below
        
        # Handle remote registered name: ("name", "node@host")
        elif isinstance(pid_or_name, tuple) and len(pid_or_name) == 2:
            name, node = pid_or_name
            from otpylib.runtime.registry import get_distribution
            dist = get_distribution()
            if dist:
                await dist.send(node, name, message)
                self._stats["messages_sent"] += 1
            # else: no distribution layer - silently drop
            return
        
        # Handle local registered name
        elif isinstance(pid_or_name, (str, atom.Atom)):
            target_pid = self.whereis(pid_or_name)
            if not target_pid:
                # Name not registered - silently drop (fire-and-forget)
                return
            
            # Fall through to local send below
        
        else:
            # Invalid type - silently drop
            return
        
        # Local send (for local PIDs and resolved local names)
        process = self._processes.get(target_pid)
        if process and process.mailbox:
            await process.mailbox.send(message)
            self._stats["messages_sent"] += 1
        # else: process not found or no mailbox - silently drop (fire-and-forget)

    async def receive(
        self,
        timeout: Optional[float] = None,
        match: Optional[Callable[[Any], bool]] = None
    ) -> Any:
        """Receive a message in the current process."""
        self_pid = self.self()
        if not self_pid:
            raise NotInProcessError("receive() must be called from within a process")

        process = self._processes.get(self_pid)
        if not process or not process.mailbox:
            raise RuntimeError("Process has no mailbox")

        try:
            if match:
                return await process.mailbox.receive_match(match, timeout)
            else:
                return await process.mailbox.receive(timeout)
        except asyncio.TimeoutError:
            raise TimeoutError("receive timeout")

    # =========================================================================
    # Timing Operations
    # =========================================================================

    async def sleep(self, seconds: float) -> None:
        """Suspend the current process for the specified duration."""
        event = asyncio.Event()
        ref = f"sleep_{id(event)}"
        self.timing_wheel.schedule_callback(seconds, ref, event.set)
        await event.wait()

    async def send_after(
        self,
        delay: float,
        target: Union[Pid, str],
        message: Any
    ) -> str:
        """Send a message after a delay."""
        # Resolve name to PID
        if isinstance(target, str):
            target_pid = self._name_registry.get(target)
            if not target_pid:
                raise ProcessNotFoundError(f"Process {target} not found")
        else:
            target_pid = target
        
        ref = f"timer_{self.timing_wheel._schedule_counter}"
        self.timing_wheel.schedule_message(delay, ref, target_pid, message)
        return ref

    async def cancel_timer(self, ref: str) -> bool:
        """Cancel a timer by reference."""
        return self.timing_wheel.cancel(ref)

    async def read_timer(self, ref: str) -> Optional[float]:
        """Read remaining time on a timer in seconds."""
        return self.timing_wheel.read(ref)

    # =========================================================================
    # Process Registry
    # =========================================================================

    async def register(
        self,
        name: str,
        pid: Optional[Pid] = None
    ) -> None:
        """Register a name for a process."""
        if name in self._name_registry:
            raise NameAlreadyRegisteredError(f"Name {name} is already registered")

        target_pid = pid if pid is not None else self.self()
        if not target_pid:
            raise NotInProcessError("register() requires a PID or must be called from within a process")

        self._name_registry[name] = target_pid

    async def unregister(self, name: str) -> None:
        """Unregister a name."""
        self._name_registry.pop(name, None)

    def whereis(self, name: Union[atom.Atom, str]) -> Optional[Pid]:
        """Look up a PID by registered name."""
        return self._name_registry.get(name)

    def whereis_name(self, pid: Pid) -> Optional[Union[atom.Atom, str]]:
        """Look up a registered name by PID (reverse lookup)."""
        for name, registered_pid in self._name_registry.items():
            if registered_pid == pid:
                return name
        return None

    def registered(self) -> List[str]:
        """Get all registered names."""
        return list(self._name_registry.keys())

    # =========================================================================
    # Process Inspection
    # =========================================================================

    def is_alive(self, pid: Union[Pid, str]) -> bool:
        """Check if a process is alive."""
        if isinstance(pid, str):
            pid = self._name_registry.get(pid)
            if not pid:
                return False
        
        return pid in self._processes

    def process_info(
        self,
        pid: Optional[Pid] = None
    ) -> Optional[ProcessInfo]:
        """Get information about a process."""
        target_pid = pid if pid is not None else self.self()
        if not target_pid:
            return None

        process = self._processes.get(target_pid)
        return process.info if process else None

    def processes(self) -> List[Pid]:
        """Get all process IDs."""
        return list(self._processes.keys())

    # =========================================================================
    # Runtime Management
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize the backend."""
        self._shutdown_flag = False
        self._wheel_task = asyncio.create_task(self._run_timing_wheel())

        # Start with a default local-only PID allocator
        # Will be replaced by distribution layer if used
        self.pid_allocator = PidAllocator("otpylib@localhost", creation=1)

        await self.send(LOGGER, ("log", "DEBUG", "[initialize] AsyncIOBackend initialized", {}))


    def set_node_name(self, node_name: str, creation: int):
        """Called by distribution layer to set proper node name for PIDs."""
        self.pid_allocator = PidAllocator(node_name, creation)


    async def shutdown(self) -> None:
        """Gracefully shutdown the backend: kill all processes."""
        # Stop timing wheel FIRST
        self._shutdown_flag = True
        if self._wheel_task:
            self._wheel_task.cancel()
            try:
                await self._wheel_task
            except asyncio.CancelledError:
                pass

        await self.send(LOGGER, ("log", "INFO", "[backend] shutting down runtime", {}))
        for pid, proc in list(self._processes.items()):
            try:
                if proc.task and not proc.task.done():
                    proc.task.cancel()
                    await self.send(LOGGER, ("log", "DEBUG", f"[shutdown] cancelled process {pid}", {"pid": str(pid)}))
                await self._notify_exit(pid, SHUTDOWN)
            except Exception as e:
                await self.send(LOGGER, ("log", "ERROR", f"[shutdown] error stopping {pid}: {e}",
                                        {"pid": str(pid), "error": str(e)}))

        self._processes.clear()
        self._name_registry.clear()

    def statistics(self) -> RuntimeStatistics:
        active = sum(1 for p in self._processes.values() if p.info.state in [RUNNING, WAITING])
        return RuntimeStatistics(
            backend_type="AsyncIOBackend",
            uptime_seconds=time.time() - self._startup_time,
            total_processes=len(self._processes),
            active_processes=active,
            total_spawned=self._stats["total_spawned"],
            total_terminated=self._stats["total_terminated"],
            messages_processed=self._stats["messages_sent"],
            down_messages_sent=self._stats["down_messages_sent"],
            exit_signals_sent=self._stats["exit_signals_sent"],
            active_monitors=len(self._monitors),
            active_links=sum(len(p.links) for p in self._processes.values()) // 2,
            registered_names=len(self._name_registry),
        )

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _is_local_pid(self, pid_or_name: Union[Pid, atom.Atom, str]) -> bool:
        """Check if a PID belongs to this node"""
        if isinstance(pid_or_name, Pid):
            return pid_or_name.node == self.pid_allocator.node_atom
        elif isinstance(pid_or_name, atom.Atom):
            return pid_or_name == self.pid_allocator.node_atom
        else:
            return atom.ensure(pid_or_name) == self.pid_allocator.node_atom

    async def _run_timing_wheel(self):
        """Background task - ticks the wheel every 10ms."""
        while not self._shutdown_flag:
            try:
                expired = self.timing_wheel.tick()
                for timer in expired:
                    if timer.callback:
                        # Callback-based timer (for sleep)
                        try:
                            timer.callback()
                        except Exception as e:
                            await self.send(LOGGER, ("log", "ERROR", 
                                f"[timing_wheel] callback error: {e}",
                                {"ref": timer.ref, "error": str(e)}))
                    else:
                        # Message-based timer (for send_after)
                        asyncio.create_task(self.send(timer.target, timer.message))

                await asyncio.sleep(0.01)  # 10ms tick
            except asyncio.CancelledError:
                break
            except Exception as e:
                await self.send(LOGGER, ("log", "ERROR",
                    f"[timing_wheel] tick error: {e}",
                    {"error": str(e)}))

    async def _handle_process_exit(self, pid: Pid, reason: Any) -> None:
        """Handle process exit: notify local AND remote links/monitors."""
        proc = self._processes.get(pid)
        if not proc:
            return
    
        await self.send(LOGGER, ("log", "DEBUG", f"[exit] handling {pid} reason={reason}",
                                {"pid": str(pid), "reason": str(reason)}))
        await self.send(LOGGER, ("log", "DEBUG", 
            f"[exit/debug] proc.monitors={dict(proc.monitors)} proc.monitored_by={dict(proc.monitored_by)}",
            {"monitors": dict(proc.monitors), "monitored_by": dict(proc.monitored_by)}))
    
        if reason is KILLED:
            await self.send(LOGGER, ("log", "DEBUG", f"[exit] {pid} hard-killed (reason=KILLED)", {"pid": str(pid)}))
            return
    
        is_normal = self._is_normal_exit(reason)
        
        # Handle LOCAL links for abnormal exits
        if not is_normal:
            for linked_pid in list(proc.links):
                if not self.is_alive(linked_pid):
                    continue
                
                linked = self._processes.get(linked_pid)
                if not linked:
                    continue
                
                if linked.trap_exits:
                    exit_msg = (EXIT, pid, reason)
                    await self.send(linked_pid, exit_msg)
                    await self.send(LOGGER, ("log", "DEBUG", 
                        f"[exit/link] sent EXIT to {linked_pid} from {pid} reason={reason}",
                        {"linked": str(linked_pid), "pid": str(pid), "reason": str(reason)}))
                else:
                    await self.send(LOGGER, ("log", "DEBUG", f"[exit/link] cancelling linked {linked_pid} (reason={reason})",
                                            {"linked": str(linked_pid), "reason": str(reason)}))
                    await self.exit(linked_pid, reason)
        
        # Handle REMOTE links for abnormal exits
        if pid in self._remote_links and not is_normal:
            from otpylib.runtime.registry import get_distribution
            dist = get_distribution()
            if dist:
                for remote_pid in list(self._remote_links[pid]):
                    await dist.send_control_message(
                        remote_pid.node.name,
                        ExitMessage(pid, remote_pid, reason)
                    )
                    await self.send(LOGGER, ("log", "DEBUG", 
                        f"[exit/remote_link] sent EXIT to {remote_pid}", {}))
            
            # Clean up remote link tracking
            del self._remote_links[pid]
    
        # Handle LOCAL monitors
        if not proc.monitored_by:
            await self.send(LOGGER, ("log", "DEBUG", f"[exit/debug] no watchers in proc={pid}.monitored_by",
                                    {"pid": str(pid)}))
    
        for monitor_ref, mon_pid in list(proc.monitored_by.items()):
            if self.is_alive(mon_pid):
                msg = (DOWN, monitor_ref, atom.ensure("process"), pid, reason)
                await self.send(mon_pid, msg)
                await self.send(LOGGER, ("log", "DEBUG",
                    f"[exit/monitor] sent DOWN to {mon_pid} (ref={monitor_ref}, target={pid}, reason={reason})",
                    {"watcher": str(mon_pid), "ref": monitor_ref, "target": str(pid), "reason": str(reason)}))
    
            watcher_proc = self._processes.get(mon_pid)
            if watcher_proc and monitor_ref in watcher_proc.monitors:
                del watcher_proc.monitors[monitor_ref]
            del proc.monitored_by[monitor_ref]
        
        # Handle REMOTE monitors
        if pid in self._remote_monitors_reverse:
            from otpylib.runtime.registry import get_distribution
            dist = get_distribution()
            if dist:
                for ref_str, monitoring_pid in list(self._remote_monitors_reverse[pid].items()):
                    # Parse ref_str back to Reference
                    ref = Reference(
                        node=pid.node,
                        creation=self.pid_allocator.creation,
                        ids=(hash(ref_str) & 0xFFFFFFFF, 0, 0)
                    )
                    await dist.send_control_message(
                        monitoring_pid.node.name,
                        MonitorExitMessage(pid, monitoring_pid, ref, reason)
                    )
                    await self.send(LOGGER, ("log", "DEBUG",
                        f"[exit/remote_monitor] sent DOWN to {monitoring_pid}", {}))
            
            # Clean up remote monitor tracking
            del self._remote_monitors_reverse[pid]

    def _is_normal_exit(self, reason: Any) -> bool:
        return reason in (NORMAL, SHUTDOWN, None)

    def _cleanup_process(self, pid: Pid) -> None:
        """Remove dead process from runtime state (after deferred cleanup)."""
        process = self._processes.pop(pid, None)
        if not process:
            return

        if process.name and self._name_registry.get(process.name) == pid:
            self._name_registry.pop(process.name, None)
        process.func = None
        process.args = []
        process.kwargs = {}

        for linked_pid in list(process.links):
            if linked_pid in self._processes:
                self._processes[linked_pid].links.discard(pid)
        for ref, watcher_pid in list(process.monitored_by.items()):
            if watcher_pid in self._processes:
                self._processes[watcher_pid].monitors.pop(ref, None)

    async def reset(self) -> None:
        """Reset all backend state. Only for test isolation (pytest)."""
        # Stop wheel
        self._shutdown_flag = True
        if self._wheel_task:
            self._wheel_task.cancel()
            try:
                await self._wheel_task
            except asyncio.CancelledError:
                pass

        for process in list(self._processes.values()):
            if process.task and not process.task.done():
                process.task.cancel()

        self._processes.clear()
        self._name_registry.clear()
        self._monitors.clear()
        
        # Clear remote tracking
        self._remote_links.clear()
        self._remote_links_reverse.clear()
        self._remote_monitors.clear()
        self._remote_monitors_reverse.clear()
        self._ref_counter = 0

        self.timing_wheel = TimingWheel(tick_ms=10, num_slots=512)
        self._shutdown_flag = False
        self._wheel_task = asyncio.create_task(self._run_timing_wheel())

        self._stats.update({
            "total_spawned": 0,
            "total_terminated": 0,
            "messages_sent": 0,
            "down_messages_sent": 0,
            "exit_signals_sent": 0,
        })
        self._startup_time = time.time()

        await self.send(LOGGER, ("log", "DEBUG", "[reset] AsyncIOBackend reset complete", {}))
