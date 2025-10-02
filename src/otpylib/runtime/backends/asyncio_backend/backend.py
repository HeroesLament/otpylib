"""
AsyncIO Backend Implementation

Main backend class that implements the RuntimeBackend protocol.
"""

import asyncio
import time
import uuid
import logging
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
    RUNNING, WAITING, TERMINATED, NORMAL, KILLED, EXIT, DOWN, SHUTDOWN
)
from otpylib.runtime.atom_utils import (
    is_normal_exit, format_down_message, format_exit_message
)

from otpylib.runtime.backends.asyncio_backend.process import Process, ProcessMailbox

logger = logging.getLogger(__name__)

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
        logger.debug(f"[spawn] name={name}, pid={pid}")

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
            """
            Execute the process function and handle its complete lifecycle.

            This function implements BEAM-style process semantics in asyncio:

            1. Process execution: Run the user's function with proper context tracking
            2. Atomic termination: Mark process as dead immediately (is_alive() -> False)
            3. Exit propagation: Notify all linked processes and monitors asynchronously
            4. Cleanup: Remove process from registry after all async work completes

            The ordering is critical to avoid both deadlocks and memory leaks:
            - Setting TERMINATED before propagation makes the process appear instantly dead
              to external observers (matching BEAM semantics)
            - Keeping the process in _processes during propagation allows notification
              code to access it if needed (avoiding lookup failures)
            - Synchronous cleanup after propagation completes ensures immediate memory
              reclamation (no deferred cleanup, no leaked references)

            This differs from the BEAM where process cleanup is literally atomic (OS
            deallocates the heap instantly). In Python's shared-memory model, we must
            carefully sequence: mark dead -> propagate -> cleanup, all within the same
            async finally block to approximate atomic behavior.
            """
            token = _current_process.set(pid)
            reason = None  # Initialize so finally block always has a value
            try:
                proc.info.state = RUNNING
                proc.info.last_active = time.time()
                reason = await proc.run()
            except Exception as e:
                # Capture exception as the exit reason
                reason = e
                raise  # Re-raise so task shows the exception
            finally:
                _current_process.reset(token)

                # Step 1: Mark terminated FIRST so is_alive() immediately returns False
                # This makes the process appear instantly dead to external observers
                proc.info.state = TERMINATED

                # Step 2: Propagate exit to linked processes and monitors
                # This must happen while process is still in _processes dict
                # so notification code can access it if needed
                await self._handle_process_exit(pid, reason)

                # Step 3: Remove from registry immediately after propagation completes
                # All async work is done, safe to cleanup synchronously
                # This prevents memory leaks from deferred cleanup
                self._cleanup_process(pid)
                logger.debug(f"[cleanup] completed for pid={pid}, reason={reason}")

        proc.task = asyncio.create_task(run_process())
        logger.debug(f"[spawn] Spawned process {pid} (name={name})")
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

        logger.debug(f"[exit] target={pid} resolved={target_pid} reason={reason}")

        if not process:
            raise ProcessNotFoundError(f"Process {pid} not found")

        # Special case: KILLED is untrappable, immediate termination
        if reason == KILLED:
            if process.task and not process.task.done():
                process.task.cancel()
                logger.debug(f"[exit] Hard-killed process {target_pid}")

            # Mark immediately dead (so is_alive flips False right away)
            process.info.state = TERMINATED

            # Defer cleanup like in run_process.finally
            loop = asyncio.get_running_loop()
            loop.call_soon(self._cleanup_process, target_pid)
            logger.debug(f"[defer-cleanup] scheduled for pid={target_pid}, reason=killed")

            # Still propagate to links/monitors
            await self._notify_exit(target_pid, reason)
            return

        # If trapping exits, deliver EXIT as a message
        if process.trap_exits and process.mailbox:
            exit_msg = (EXIT, self.self() or "system", reason)
            await process.mailbox.send(exit_msg)
            logger.debug(f"[exit] Sent EXIT message to {target_pid}")
        else:
            # Default: cancel task
            if process.task and not process.task.done():
                process.task.cancel()
                logger.debug(f"[exit] Cancelled process {target_pid}")

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

        # Propagate to linked processes
        for linked_pid in list(process.links):
            linked = self._processes.get(linked_pid)
            if not linked:
                continue

            if linked.trap_exits and linked.mailbox:
                await linked.mailbox.send((EXIT, pid, reason))
                logger.debug(f"[link-exit] Delivered EXIT to {linked_pid}")
            else:
                if linked.task and not linked.task.done():
                    linked.task.cancel()
                    logger.debug(f"[link-exit] Cascade kill {linked_pid}")
                await self._notify_exit(linked_pid, reason, visited=visited)

        # Notify monitors
        for ref, watcher_pid in list(process.monitored_by.items()):
            if watcher_pid in self._processes:
                await self.send(watcher_pid, (DOWN, ref, pid, reason))
                logger.debug(f"[monitor-exit] Sent DOWN to {watcher_pid}")

        # Symmetric cleanup of links/monitors
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
            # BEAM: badarg -> here: ProcessNotFoundError
            logger.debug(f"[link] {self_pid} -> {target_pid} failed (not found)")
            raise ProcessNotFoundError(f"Process {target_pid} not found")

        # Add link symmetrically
        self._processes[self_pid].links.add(target_pid)
        self._processes[target_pid].links.add(self_pid)
        logger.debug(f"[link] {self_pid} <-> {target_pid}")

    async def unlink(self, target_pid: str) -> None:
        """Remove an existing link (symmetric, BEAM parity)."""
        self_pid = self.self()
        if not self_pid:
            raise NotInProcessError("unlink() must be called from within a process")

        target_pid = self._name_registry.get(target_pid, target_pid)

        # Symmetric removal, but no failure if one side is gone
        if self_pid in self._processes:
            self._processes[self_pid].links.discard(target_pid)
        if target_pid in self._processes:
            self._processes[target_pid].links.discard(self_pid)

        logger.debug(f"[unlink] {self_pid} -X- {target_pid}")

    async def monitor(self, target_pid: str) -> str:
        """Create a monitor (unidirectional). Returns the monitor ref."""
        self_pid = self.self()
        if not self_pid:
            raise NotInProcessError("monitor() must be called from within a process")

        ref = f"ref_{uuid.uuid4().hex}"

        # Check if target is alive *before* registering
        target_proc = self._processes.get(target_pid)
        if not target_proc or target_proc.info.state == TERMINATED:
            # Target already gone → deliver DOWN immediately (5-arity)
            msg = (DOWN, ref, atom.ensure("process"), target_pid, "noproc")
            await self.send(self_pid, msg)
            logger.debug(
                "[monitor] immediate DOWN to %s (ref=%s, target=%s, reason=noproc)",
                self_pid, ref, target_pid
            )
            return ref

        # Normal path: register both sides
        self._processes[self_pid].monitors[ref] = target_pid
        target_proc.monitored_by[ref] = self_pid

        logger.debug("[monitor] %s -> %s (ref=%s)", self_pid, target_pid, ref)
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

        # Remove from target's monitored_by
        target_proc = self._processes.get(target_pid)
        if target_proc:
            target_proc.monitored_by.pop(ref, None)

        if flush and proc.mailbox:
            # Access the internal message queue to filter out DOWN messages
            # ProcessMailbox stores messages in an asyncio.Queue accessed via _queue
            if hasattr(proc.mailbox, '_queue') and hasattr(proc.mailbox._queue, '_queue'):
                # Get the underlying deque from asyncio.Queue
                queue_items = list(proc.mailbox._queue._queue)
                filtered = [m for m in queue_items if not (isinstance(m, tuple) and len(m) >= 2 and m[0] == DOWN and m[1] == ref)]

                # Clear and repopulate the queue
                proc.mailbox._queue._queue.clear()
                for item in filtered:
                    proc.mailbox._queue._queue.append(item)

                logger.debug(f"[demonitor] flushed DOWN messages for ref={ref}")

    # =========================================================================
    # Message Passing
    # =========================================================================

    async def send(self, pid: Union[str, Process], message: Any) -> None:
        """Send a message to a process (by pid or registered name)."""
        target_pid = None
    
        if isinstance(pid, Process):
            target_pid = pid.pid
        else:
            # Handle both strings and atoms as names
            target_pid = self._name_registry.get(pid, pid)
    
        process = self._processes.get(target_pid)
        if not process:
            logger.debug(f"[send] Dropping to {pid} resolved={target_pid}: not alive")
            return
    
        if not process.mailbox:
            logger.debug(f"[send] Dropping to {target_pid}: no mailbox")
            return
    
        await process.mailbox.send(message)
        self._stats["messages_sent"] += 1
        logger.debug(f"[send] Delivered to {target_pid}: {message}")

    async def receive(self, timeout: Optional[float] = None, match: Optional[Callable[[Any], bool]] = None) -> Any:
        current = self.self()
        if not current:
            raise NotInProcessError("receive() must be called from within a process")

        process = self._processes.get(current)
        if not process or not process.mailbox:
            raise RuntimeError("Current process has no mailbox")

        return await process.mailbox.receive(timeout)

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
        logger.debug(f"[register] name={name} -> pid={target_pid}")

    async def unregister(self, name: str) -> None:
        """Remove a registered name (no error if not present)."""
        pid = self._name_registry.pop(name, None)
        if pid and pid in self._processes:
            self._processes[pid].name = None
        logger.debug(f"[unregister] name={name} removed (pid={pid})")

    def unregister_name(self, name: str) -> None:
        """Remove a registered name if present."""
        self._name_registry.pop(name, None)
        logger.debug(f"[unregister] name={name} removed")

    def whereis(self, name: str) -> Optional[str]:
        """Resolve a name to a pid (BEAM parity: stale names are dropped)."""
        pid = self._name_registry.get(name)
        if not pid:
            return None
        if not self.is_alive(pid):
            self._name_registry.pop(name, None)
            logger.debug(f"[whereis] cleaned stale name={name} pid={pid}")
            return None
        return pid

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
        # Consider TERMINATED as dead, even if still in table
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
        logger.debug("[initialize] AsyncIOBackend initialized")

    async def shutdown(self) -> None:
        """Gracefully shutdown the backend: kill all processes."""
        logger.info("[backend] shutting down runtime")
        for pid, proc in list(self._processes.items()):
            try:
                if proc.task and not proc.task.done():
                    proc.task.cancel()
                    logger.debug(f"[shutdown] cancelled process {pid}")
                await self._notify_exit(pid, SHUTDOWN)
            except Exception as e:
                logger.error(f"[shutdown] error stopping {pid}: {e}")

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

    async def _handle_process_exit(self, pid: str, reason: Any) -> None:
        proc = self._processes.get(pid)
        if not proc:
            return

        logger.debug("[exit] handling %s reason=%s", pid, reason)
        logger.debug("[exit/debug] proc.monitors=%s proc.monitored_by=%s",
                     dict(proc.monitors), dict(proc.monitored_by))

        # Special case: KILLED is untrappable
        if reason is KILLED:
            logger.debug("[exit] %s hard-killed (reason=KILLED)", pid)
            # cleanup will still happen later
            return

        # 🚨 Normal exits do not cascade
        if self._is_normal_exit(reason):
            logger.debug("[exit] %s exited normally, skipping link cascade", pid)
        else:
            # Abnormal exit: cascade to linked processes
            for linked_pid in list(proc.links):
                if not self.is_alive(linked_pid):
                    continue

                linked = self._processes.get(linked_pid)
                if linked and linked.trap_exits:
                    await self.send(linked_pid, (EXIT, pid, reason))
                    logger.debug("[exit/link] sent EXIT to %s from %s reason=%s",
                                 linked_pid, pid, reason)
                else:
                    logger.debug("[exit/link] cancelling linked %s (reason=%s)",
                                 linked_pid, reason)
                    await self.exit(linked_pid, reason)

        # Monitors always get DOWN (BEAM-style: use proc.monitored_by)
        if not proc.monitored_by:
            logger.debug("[exit/debug] no watchers in proc=%s.monitored_by", pid)

        for monitor_ref, mon_pid in list(proc.monitored_by.items()):
            if self.is_alive(mon_pid):
                msg = (DOWN, monitor_ref, atom.ensure("process"), pid, reason)
                await self.send(mon_pid, msg)
                logger.debug(
                    "[exit/monitor] sent DOWN to %s (ref=%s, target=%s, reason=%s)",
                    mon_pid, monitor_ref, pid, reason
                )

            # Cleanup both sides of the monitor relationship
            watcher_proc = self._processes.get(mon_pid)
            if watcher_proc and monitor_ref in watcher_proc.monitors:
                del watcher_proc.monitors[monitor_ref]
            del proc.monitored_by[monitor_ref]

    def _is_normal_exit(self, reason: Any) -> bool:
        """
        Return True if this reason counts as a 'normal' exit
        that should not cascade to linked processes.

        Mirrors BEAM semantics:
          - normal (regular completion)
          - shutdown (explicit orderly shutdown)
          - None (default Python coroutine return)
        """
        return reason in (NORMAL, SHUTDOWN, None)

    def _cleanup_process(self, pid: str) -> None:
        """Remove dead process from runtime state (after deferred cleanup)."""
        process = self._processes.pop(pid, None)
        logger.debug(
            f"[cleanup] start for pid={pid}, process={'yes' if process else 'no'}"
        )
        if not process:
            return

        # Remove from name registry
        if process.name and self._name_registry.get(process.name) == pid:
            self._name_registry.pop(process.name, None)
            logger.debug(f"[cleanup] removed name={process.name} for pid={pid}")
        # Null out fields (required for cleanup)
        process.func = None
        process.args = []
        process.kwargs = {}

        # Ensure links and monitors are dropped
        for linked_pid in list(process.links):
            if linked_pid in self._processes:
                self._processes[linked_pid].links.discard(pid)
        for ref, watcher_pid in list(process.monitored_by.items()):
            if watcher_pid in self._processes:
                self._processes[watcher_pid].monitors.pop(ref, None)

        logger.debug(f"[cleanup] process {pid} fully removed")

    async def reset(self) -> None:
        """
        Reset all backend state.
        Only for test isolation (pytest).
        """
        # Cancel all tasks immediately
        for process in list(self._processes.values()):
            if process.task and not process.task.done():
                process.task.cancel()

        # Clear registries
        self._processes.clear()
        self._name_registry.clear()
        self._monitors.clear()

        # Reset statistics counters
        self._stats.update({
            "total_spawned": 0,
            "total_terminated": 0,
            "messages_sent": 0,
            "down_messages_sent": 0,
            "exit_signals_sent": 0,
        })
        self._startup_time = time.time()

        logger.debug("[reset] AsyncIOBackend reset complete")
