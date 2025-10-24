"""
AsyncIO Backend Implementation

Main backend class that implements the RuntimeBackend protocol.
"""

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional, Union, Callable, Tuple
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

from otpylib.runtime.backends.asyncio_backend.timing_wheel import TimingWheel
from otpylib.runtime.backends.asyncio_backend.process import Process, ProcessMailbox
from otpylib.runtime.backends.asyncio_backend import tcp

# Logger target
LOGGER = atom.ensure("logger")

# Context variable to track current process
_current_process: ContextVar[Optional[str]] = ContextVar("current_process", default=None)


class AsyncIOBackend(RuntimeBackend):
    """
    Runtime backend using pure asyncio.

    Simpler and more performant than anyio, closer to BEAM semantics.
    """

    def __init__(self):
        # Process registry
        self._processes: Dict[str, Process] = {}
        self._name_registry: Dict[str, str] = {}  # name -> pid

        # Monitor tracking
        self._monitors: Dict[str, MonitorRef] = {}  # ref -> MonitorRef

        # Timer tracking
        self.timing_wheel = TimingWheel(tick_ms=10, num_slots=512)
        self._wheel_task: Optional[asyncio.Task] = None
        self._shutdown_flag = False

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
    ) -> str:
        """Spawn a new process."""
        pid = f"pid_{uuid.uuid4().hex[:12]}"

        await self.send(LOGGER, ("log", "DEBUG", f"[spawn] name={name}, pid={pid}", {"name": name, "pid": pid}))

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
                                        {"pid": pid, "reason": str(reason)}))

        proc.task = asyncio.create_task(run_process())
        await self.send(LOGGER, ("log", "DEBUG", f"[spawn] Spawned process {pid} (name={name})", 
                                {"pid": pid, "name": name}))
        return pid

    async def spawn_link(self, *args, **kwargs) -> str:
        pid = await self.spawn(*args, **kwargs)
        await self.link(pid)
        return pid

    async def spawn_monitor(self, *args, **kwargs) -> Tuple[str, str]:
        pid = await self.spawn(*args, **kwargs)
        ref = await self.monitor(pid)
        return pid, ref

    async def exit(self, pid: str, reason: Any) -> None:
        """Send an exit signal to a process (BEAM-style semantics)."""
        target_pid = self._name_registry.get(pid, pid)
        process = self._processes.get(target_pid)

        await self.send(LOGGER, ("log", "DEBUG", f"[exit] target={pid} resolved={target_pid} reason={reason}",
                                {"target": pid, "resolved": target_pid, "reason": str(reason)}))

        if not process:
            raise ProcessNotFoundError(f"Process {pid} not found")

        if reason == KILLED:
            if process.task and not process.task.done():
                process.task.cancel()
                await self.send(LOGGER, ("log", "DEBUG", f"[exit] Hard-killed process {target_pid}",
                                        {"pid": target_pid}))

            process.info.state = TERMINATED
            loop = asyncio.get_running_loop()
            loop.call_soon(self._cleanup_process, target_pid)
            await self.send(LOGGER, ("log", "DEBUG", f"[defer-cleanup] scheduled for pid={target_pid}, reason=killed",
                                    {"pid": target_pid, "reason": "killed"}))
            await self._notify_exit(target_pid, reason)
            return

        if process.trap_exits and process.mailbox:
            exit_msg = (EXIT, self.self() or "system", reason)
            await process.mailbox.send(exit_msg)
            await self.send(LOGGER, ("log", "DEBUG", f"[exit] Sent EXIT message to {target_pid}",
                                    {"pid": target_pid}))
        else:
            if process.task and not process.task.done():
                process.task.cancel()
                await self.send(LOGGER, ("log", "DEBUG", f"[exit] Cancelled process {target_pid}",
                                        {"pid": target_pid}))

        # Don't call _notify_exit for graceful shutdowns - let _handle_process_exit handle it
        # This ensures DOWN messages are sent with monitors still intact
        if reason not in [SHUTDOWN, SUPERVISOR_SHUTDOWN]:
            await self._notify_exit(target_pid, reason)

    async def _notify_exit(self, pid: str, reason: Any, visited: Optional[set] = None) -> None:
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
                                        {"pid": linked_pid}))
            else:
                if linked.task and not linked.task.done():
                    linked.task.cancel()
                    await self.send(LOGGER, ("log", "DEBUG", f"[link-exit] Cascade kill {linked_pid}",
                                            {"pid": linked_pid}))
                await self._notify_exit(linked_pid, reason, visited=visited)

        for ref, watcher_pid in list(process.monitored_by.items()):
            if watcher_pid in self._processes:
                await self.send(watcher_pid, (DOWN, ref, pid, reason))
                await self.send(LOGGER, ("log", "DEBUG", f"[monitor-exit] Sent DOWN to {watcher_pid}",
                                        {"watcher": watcher_pid}))

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

    def self(self) -> Optional[str]:
        return _current_process.get()

    # =========================================================================
    # Process Relationships
    # =========================================================================

    async def link(self, target_pid: str) -> None:
        """Create a bidirectional link (BEAM-style parity)."""
        self_pid = self.self()

        if not self_pid:
            raise NotInProcessError("link() must be called from within a process")

        target_pid = self._name_registry.get(target_pid, target_pid)

        if target_pid not in self._processes:
            await self.send(LOGGER, ("log", "DEBUG", f"[link] {self_pid} -> {target_pid} failed (not found)",
                                    {"self": self_pid, "target": target_pid}))
            raise ProcessNotFoundError(f"Process {target_pid} not found")

        self._processes[self_pid].links.add(target_pid)
        self._processes[target_pid].links.add(self_pid)

        await self.send(LOGGER, ("log", "DEBUG", f"[link] {self_pid} <-> {target_pid}",
                                {"self": self_pid, "target": target_pid}))

    async def unlink(self, target_pid: str) -> None:
        """Remove an existing link (symmetric, BEAM parity)."""
        self_pid = self.self()
        if not self_pid:
            raise NotInProcessError("unlink() must be called from within a process")

        target_pid = self._name_registry.get(target_pid, target_pid)

        if self_pid in self._processes:
            self._processes[self_pid].links.discard(target_pid)
        if target_pid in self._processes:
            self._processes[target_pid].links.discard(self_pid)

        await self.send(LOGGER, ("log", "DEBUG", f"[unlink] {self_pid} -X- {target_pid}",
                                {"self": self_pid, "target": target_pid}))


    async def monitor(self, target_pid: str) -> str:
        """Create a monitor (unidirectional). Returns the monitor ref."""
        self_pid = self.self()
        if not self_pid:
            raise NotInProcessError("monitor() must be called from within a process")

        ref = f"ref_{uuid.uuid4().hex}"

        target_proc = self._processes.get(target_pid)
        if not target_proc or target_proc.info.state == TERMINATED:
            msg = (DOWN, ref, atom.ensure("process"), target_pid, "noproc")
            await self.send(self_pid, msg)
            await self.send(LOGGER, ("log", "DEBUG", 
                f"[monitor] immediate DOWN to {self_pid} (ref={ref}, target={target_pid}, reason=noproc)",
                {"watcher": self_pid, "ref": ref, "target": target_pid, "reason": "noproc"}))
            return ref

        self._processes[self_pid].monitors[ref] = target_pid
        target_proc.monitored_by[ref] = self_pid

        await self.send(LOGGER, ("log", "DEBUG", f"[monitor] {self_pid} -> {target_pid} (ref={ref})",
                                {"watcher": self_pid, "target": target_pid, "ref": ref}))
        return ref

    async def demonitor(self, ref: str, flush: bool = False) -> None:
        """Remove a monitor reference. If flush=True, drop any pending DOWN."""
        self_pid = self.self()
        if not self_pid:
            raise NotInProcessError("demonitor() must be called from within a process")

        proc = self._processes.get(self_pid)
        if not proc:
            raise NotInProcessError("demonitor() must be called from within a process")

        target_pid = proc.monitors.pop(ref, None)
        if not target_pid:
            return

        target_proc = self._processes.get(target_pid)
        if target_proc:
            target_proc.monitored_by.pop(ref, None)

        if flush and proc.mailbox:
            if hasattr(proc.mailbox, '_queue') and hasattr(proc.mailbox._queue, '_queue'):
                queue_items = list(proc.mailbox._queue._queue)
                filtered = [m for m in queue_items if not (isinstance(m, tuple) and len(m) >= 2 and m[0] == DOWN and m[1] == ref)]

                proc.mailbox._queue._queue.clear()
                for item in filtered:
                    proc.mailbox._queue._queue.append(item)

                await self.send(LOGGER, ("log", "DEBUG", f"[demonitor] flushed DOWN messages for ref={ref}",
                                        {"ref": ref}))

    # =========================================================================
    # Message Passing
    # =========================================================================

    async def send(self, pid_or_name: Union[str, Process], message: Any) -> None:
        """Send a message to a process (by pid or registered name)."""
        target_pid = None
        if isinstance(pid_or_name, Process):
            target_pid = pid_or_name.pid
        else:
            target_pid = self._name_registry.get(pid_or_name, pid_or_name)

        process = self._processes.get(target_pid)
        if not process:
            return

        if not process.mailbox:
            return

        await process.mailbox.send(message)
        self._stats["messages_sent"] += 1

    async def sleep(self, seconds: float) -> None:
        """
        Suspend the current coroutine for the specified duration.

        Uses timing wheel internally for consistency with send_after().

        :param seconds: Duration to sleep in seconds
        """
        # Create event to wait on
        done = asyncio.Event()

        # Generate unique reference
        ref = f"sleep_{id(done)}_{time.monotonic()}"

        # Insert callback-based timer into wheel
        self.timing_wheel.insert(
            ref=ref,
            delay_ms=int(seconds * 1000),
            target="",  # Unused for callbacks
            message=None,  # Unused for callbacks
            callback=lambda: done.set()  # Wake up sleeper
        )

        # Wait for timer to fire
        try:
            await done.wait()
        except asyncio.CancelledError:
            # If cancelled, cancel the timer too
            self.timing_wheel.cancel(ref)
            raise

    async def send_after(self, delay: float, target: str, message: Any) -> str:
        """
        Send message after delay using timing wheel.

        :param delay: Delay in seconds before sending message
        :param target: Target process PID or registered name
        :param message: Message to send when timer fires
        :returns: Timer reference for cancellation
        """
        ref = f"timer_{uuid.uuid4().hex[:12]}"

        # Insert into timing wheel
        self.timing_wheel.insert(
            ref=ref,
            delay_ms=int(delay * 1000),
            target=target,
            message=message,
            callback=None  # Message-based timer
        )

        await self.send(LOGGER, ("log", "DEBUG",
            f"[send_after] ref={ref} delay={delay}s target={target}",
            {"ref": ref, "delay": delay, "target": target}))

        return ref


    async def cancel_timer(self, ref: str) -> bool:
        """
        Cancel a timer by reference.

        :param ref: Timer reference returned by send_after()
        :returns: True if timer was cancelled, False if not found
        """
        cancelled = self.timing_wheel.cancel(ref)

        if cancelled:
            await self.send(LOGGER, ("log", "DEBUG",
                f"[cancel_timer] ref={ref} cancelled",
                {"ref": ref}))

        return cancelled


    async def read_timer(self, ref: str) -> Optional[float]:
        """
        Read remaining time on a timer in seconds.

        :param ref: Timer reference
        :returns: Remaining time in seconds, or None if timer not found
        """
        remaining_ms = self.timing_wheel.read_timer(ref)
        return remaining_ms / 1000.0 if remaining_ms is not None else None


    async def receive(self, timeout: Optional[float] = None,
                      match: Optional[Callable[[Any], bool]] = None) -> Any:
        """Receive a message from the current process's mailbox."""
        current = self.self()
        if not current:
            raise NotInProcessError("receive() must be called from within a process")

        process = self._processes.get(current)
        if not process or not process.mailbox:
            raise RuntimeError("Current process has no mailbox")

        msg = await process.mailbox.receive(timeout)
        return msg

    # =========================================================================
    # Process Registry
    # =========================================================================

    async def register(self, name: str, pid: Optional[str] = None) -> None:
        """Register a process under a global name (BEAM parity)."""
        target_pid = pid or self.self()
        if not target_pid:
            raise NotInProcessError("register() must be called from within a process or with pid")

        if name in self._name_registry:
            raise NameAlreadyRegisteredError(f"Name '{name}' is already registered")

        if target_pid not in self._processes:
            raise ProcessNotFoundError(f"Process {target_pid} not found")

        self._name_registry[name] = target_pid
        self._processes[target_pid].name = name

    async def unregister(self, name: str) -> None:
        """Remove a registered name (no error if not present)."""
        pid = self._name_registry.pop(name, None)
        if pid and pid in self._processes:
            self._processes[pid].name = None
        await self.send(LOGGER, ("log", "DEBUG", f"[unregister] name={name} removed (pid={pid})",
                                {"name": name, "pid": pid}))

    def unregister_name(self, name: str) -> None:
        """Remove a registered name if present."""
        self._name_registry.pop(name, None)

    def whereis(self, name: str) -> Optional[str]:
        """Resolve a name to a pid (BEAM parity: stale names are dropped)."""
        pid = self._name_registry.get(name)
        if not pid:
            return None
        if not self.is_alive(pid):
            self._name_registry.pop(name, None)
            return None
        return pid

    def whereis_name(self, pid: str) -> Optional[str]:
        """Get the registered name for a PID (reverse lookup)."""
        process = self._processes.get(pid)
        if process:
            return process.name
        return None

    def registered(self) -> List[str]:
        """Return all registered process names."""
        return list(self._name_registry.keys())

    # =========================================================================
    # Process Inspection
    # =========================================================================

    def is_alive(self, pid: str) -> bool:
        process = self._processes.get(pid)
        if not process:
            return False
        return process.info.state not in (TERMINATED,)

    def process_info(self, pid: Optional[str] = None) -> Optional[ProcessInfo]:
        target_pid = pid or self.self()
        if not target_pid:
            return None
        process = self._processes.get(target_pid)
        return process.info if process else None

    def processes(self) -> List[str]:
        return list(self._processes.keys())

    # =========================================================================
    # Runtime Management
    # =========================================================================

    async def initialize(self) -> None:
        # Start timing wheel here
        self._shutdown_flag = False
        self._wheel_task = asyncio.create_task(self._run_timing_wheel())
        await self.send(LOGGER, ("log", "DEBUG", "[initialize] AsyncIOBackend initialized", {}))

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
                    await self.send(LOGGER, ("log", "DEBUG", f"[shutdown] cancelled process {pid}", {"pid": pid}))
                await self._notify_exit(pid, SHUTDOWN)
            except Exception as e:
                await self.send(LOGGER, ("log", "ERROR", f"[shutdown] error stopping {pid}: {e}",
                                        {"pid": pid, "error": str(e)}))

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

    async def _handle_process_exit(self, pid: str, reason: Any) -> None:
        """Handle process exit: notify links and monitors."""
        proc = self._processes.get(pid)
        if not proc:
            return
    
        await self.send(LOGGER, ("log", "DEBUG", f"[exit] handling {pid} reason={reason}",
                                {"pid": pid, "reason": str(reason)}))
        await self.send(LOGGER, ("log", "DEBUG", 
            f"[exit/debug] proc.monitors={dict(proc.monitors)} proc.monitored_by={dict(proc.monitored_by)}",
            {"monitors": dict(proc.monitors), "monitored_by": dict(proc.monitored_by)}))
    
        if reason is KILLED:
            await self.send(LOGGER, ("log", "DEBUG", f"[exit] {pid} hard-killed (reason=KILLED)", {"pid": pid}))
            return
    
        is_normal = self._is_normal_exit(reason)
        
        if is_normal:
            await self.send(LOGGER, ("log", "DEBUG", f"[exit] {pid} exited normally, skipping link cascade",
                                    {"pid": pid}))
        else:
            # Process links for abnormal exits
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
                        {"linked": linked_pid, "pid": pid, "reason": str(reason)}))
                else:
                    await self.send(LOGGER, ("log", "DEBUG", f"[exit/link] cancelling linked {linked_pid} (reason={reason})",
                                            {"linked": linked_pid, "reason": str(reason)}))
                    await self.exit(linked_pid, reason)
    
        # Process monitors
        if not proc.monitored_by:
            await self.send(LOGGER, ("log", "DEBUG", f"[exit/debug] no watchers in proc={pid}.monitored_by",
                                    {"pid": pid}))
    
        for monitor_ref, mon_pid in list(proc.monitored_by.items()):
            if self.is_alive(mon_pid):
                msg = (DOWN, monitor_ref, atom.ensure("process"), pid, reason)
                await self.send(mon_pid, msg)
                await self.send(LOGGER, ("log", "DEBUG",
                    f"[exit/monitor] sent DOWN to {mon_pid} (ref={monitor_ref}, target={pid}, reason={reason})",
                    {"watcher": mon_pid, "ref": monitor_ref, "target": pid, "reason": str(reason)}))
    
            watcher_proc = self._processes.get(mon_pid)
            if watcher_proc and monitor_ref in watcher_proc.monitors:
                del watcher_proc.monitors[monitor_ref]
            del proc.monitored_by[monitor_ref]

    def _is_normal_exit(self, reason: Any) -> bool:
        return reason in (NORMAL, SHUTDOWN, None)

    def _cleanup_process(self, pid: str) -> None:
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
