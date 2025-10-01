"""
Process Management

Process data structures and lifecycle management for AsyncIO backend.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional, Set, Callable
from dataclasses import dataclass, field

from otpylib.runtime.data import ProcessInfo, ProcessCharacteristics
from otpylib.runtime.atoms import TASK, STARTING, NORMAL, SHUTDOWN


class ProcessMailbox:
    """Simple mailbox using asyncio.Queue."""

    def __init__(self, maxsize: int = 0):
        self.queue = asyncio.Queue(maxsize=maxsize)
        self.closed = False

    async def send(self, message: Any) -> None:
        if self.closed:
            raise RuntimeError("Mailbox is closed")
        await self.queue.put(message)

    async def receive(self, timeout: Optional[float] = None) -> Any:
        if self.closed:
            raise RuntimeError("Mailbox is closed")
        if timeout is not None:
            return await asyncio.wait_for(self.queue.get(), timeout)
        return await self.queue.get()

    def close(self) -> None:
        self.closed = True
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break


@dataclass
class Process:
    """Internal process representation (BEAM-parity semantics)."""

    pid: str
    func: Callable
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    name: Optional[str] = None
    characteristics: Optional[ProcessCharacteristics] = None
    trap_exits: bool = False

    # Process info
    info: ProcessInfo = field(init=False)

    # Task
    task: Optional[asyncio.Task] = field(default=None, init=False)

    # Mailbox
    mailbox: Optional[ProcessMailbox] = field(default=None, init=False)

    # Relationships
    links: Set[str] = field(default_factory=set, init=False)
    monitors: Dict[str, str] = field(default_factory=dict, init=False)      # ref -> target pid
    monitored_by: Dict[str, str] = field(default_factory=dict, init=False)  # ref -> watcher pid

    def __post_init__(self):
        self.info = ProcessInfo(
            pid=self.pid,
            process_type=TASK,
            name=self.name,
            state=STARTING,
            created_at=time.time(),
            characteristics=self.characteristics,
            trap_exits=self.trap_exits,
        )

    def is_alive(self) -> bool:
        return self.task is not None and not self.task.done()

    async def run(self) -> Any:
        """
        Run the process function.

        Returns:
            Exit reason (NORMAL, SHUTDOWN, or exception instance).
        """
        reason: Any = NORMAL
        try:
            result = await self.func(*self.args, **self.kwargs)
            reason = NORMAL
        except asyncio.CancelledError:
            reason = SHUTDOWN
        except Exception as e:
            reason = e
        return reason
