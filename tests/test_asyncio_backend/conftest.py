"""
Shared fixtures for AsyncIO backend tests.
"""

import asyncio
import pytest
import pytest_asyncio
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field

from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend
from otpylib.runtime.atoms import (
    EXIT, DOWN, NORMAL, KILLED, RUNNING, WAITING, TERMINATED,
    atom
)

# Test atoms
PING = atom.ensure("ping")
PONG = atom.ensure("pong")
STOP = atom.ensure("stop")
TEST_MSG = atom.ensure("test_msg")
ACK = atom.ensure("ack")


@dataclass
class ProcessTracker:
    """Helper to track spawned processes for cleanup."""
    runtime: AsyncIOBackend
    spawned_pids: List[str] = field(default_factory=list)
    
    async def spawn(self, *args, **kwargs) -> str:
        """Spawn and track a process."""
        pid = await self.runtime.spawn(*args, **kwargs)
        self.spawned_pids.append(pid)
        return pid
    
    async def cleanup(self):
        """Kill all tracked processes."""
        for pid in self.spawned_pids:
            if self.runtime.is_alive(pid):
                try:
                    await self.runtime.exit(pid, KILLED)
                except:
                    pass  # Process might already be dead


@dataclass
class MessageCollector:
    """Helper to collect messages for verification."""
    runtime: AsyncIOBackend
    pid: Optional[str] = None
    messages: List[Any] = field(default_factory=list)
    
    async def start(self):
        """Start the collector process."""
        async def collector_loop():
            await self.runtime.register("collector")
            while True:
                try:
                    msg = await self.runtime.receive(timeout=0.5)
                    self.messages.append(msg)
                    
                    # Stop on STOP atom
                    if msg == STOP:
                        break
                        
                except asyncio.TimeoutError:
                    continue
                    
        self.pid = await self.runtime.spawn(collector_loop)
        await asyncio.sleep(0.01)  # Let it register
        return self.pid
    
    async def send(self, message: Any):
        """Send a message to the collector."""
        if self.pid:
            await self.runtime.send(self.pid, message)
    
    async def stop(self):
        """Stop the collector."""
        if self.pid and self.runtime.is_alive(self.pid):
            await self.runtime.send(self.pid, STOP)
            await asyncio.sleep(0.01)


@pytest_asyncio.fixture
async def runtime():
    """Fresh runtime instance for each test."""
    backend = AsyncIOBackend()
    await backend.initialize()
    
    yield backend
    
    # Force shutdown and cleanup
    await backend.shutdown()
    await backend.reset()


@pytest_asyncio.fixture
async def process_tracker(runtime):
    """Process tracker for automatic cleanup."""
    tracker = ProcessTracker(runtime)
    yield tracker
    await tracker.cleanup()


@pytest_asyncio.fixture
async def message_collector(runtime):
    """Message collector for testing message flow."""
    collector = MessageCollector(runtime)
    yield collector
    
    # Cleanup
    if collector.pid and runtime.is_alive(collector.pid):
        await collector.stop()


@pytest_asyncio.fixture
async def echo_server(runtime):
    """Simple echo server process."""
    async def echo_loop():
        await runtime.register("echo")
        while True:
            try:
                msg = await runtime.receive(timeout=1.0)
                
                if msg == STOP:
                    break
                    
                # Echo back with ACK
                if isinstance(msg, tuple) and len(msg) == 2:
                    sender, content = msg
                    await runtime.send(sender, (ACK, content))
                    
            except asyncio.TimeoutError:
                continue
    
    pid = await runtime.spawn(echo_loop)
    await asyncio.sleep(0.01)  # Let it register
    
    yield pid
    
    # Cleanup
    if runtime.is_alive(pid):
        await runtime.send("echo", STOP)


@pytest_asyncio.fixture
async def linked_pair(runtime, process_tracker):
    """Create a pair of linked processes."""
    pids = {}
    
    async def proc_a():
        await runtime.register("proc_a")
        await runtime.link("proc_b")
        while True:
            msg = await runtime.receive()
            if msg == STOP:
                break
    
    async def proc_b():
        await runtime.register("proc_b")
        while True:
            msg = await runtime.receive()
            if msg == STOP:
                break
    
    pids['a'] = await process_tracker.spawn(proc_a)
    pids['b'] = await process_tracker.spawn(proc_b)
    
    await asyncio.sleep(0.02)  # Let them start and link
    
    return pids


@pytest_asyncio.fixture
async def monitor_pair(runtime, process_tracker):
    """Create a monitoring relationship."""
    refs = {}
    pids = {}
    events = []
    
    async def watcher():
        await runtime.register("watcher")
        ref = await runtime.monitor("target")
        refs['monitor'] = ref
        
        while True:
            msg = await runtime.receive()
            events.append(msg)
            
            if msg == STOP:
                break
    
    async def target():
        await runtime.register("target")
        await asyncio.sleep(0.1)  # Stay alive briefly
    
    pids['watcher'] = await process_tracker.spawn(watcher)
    await asyncio.sleep(0.01)  # Let watcher start
    pids['target'] = await process_tracker.spawn(target)
    
    return {
        'pids': pids,
        'refs': refs,
        'events': events
    }


@pytest.fixture
def assert_eventually():
    """Helper for eventual consistency assertions."""
    async def _assert_eventually(
        condition: Callable[[], bool],
        timeout: float = 1.0,
        interval: float = 0.01,
        message: str = "Condition not met"
    ):
        """Assert that a condition becomes true eventually."""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            if condition():
                return
            await asyncio.sleep(interval)
        raise AssertionError(f"{message} after {timeout}s")
    
    return _assert_eventually


@pytest.fixture
def event_recorder():
    """Record events with timestamps for ordering verification."""
    events = []
    
    def record(event_type: str, **data):
        events.append({
            'type': event_type,
            'time': asyncio.get_event_loop().time(),
            **data
        })
    
    return {
        'record': record,
        'events': events,
        'get_order': lambda: [e['type'] for e in events],
        'clear': lambda: events.clear()
    }
