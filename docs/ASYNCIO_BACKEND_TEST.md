# Test Structure for AsyncIO Backend

## Directory Structure

```
tests/
└── test_backend_asyncio/
    ├── __init__.py
    ├── conftest.py                 # Shared fixtures for all backend tests
    ├── test_process_lifecycle.py   # Basic spawn, exit, termination
    ├── test_message_passing.py     # Send, receive, mailbox behavior
    ├── test_process_registry.py    # Name registration, whereis, etc.
    ├── test_process_links.py       # Link semantics and exit propagation
    ├── test_process_monitors.py    # Monitor semantics and DOWN messages
    ├── test_edge_cases.py          # Race conditions, error handling
    └── test_performance.py         # Optional performance benchmarks
```

## conftest.py - Core Fixtures

```python
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
```

## test_process_lifecycle.py

```python
"""
Test basic process lifecycle: spawn, run, exit, terminate.
"""

import asyncio
import pytest
from otpylib.runtime.atoms import NORMAL, KILLED, RUNNING, TERMINATED


@pytest.mark.asyncio
async def test_spawn_simple_process(runtime, process_tracker):
    """Test spawning a simple process."""
    executed = False
    
    async def simple_process():
        nonlocal executed
        executed = True
    
    pid = await process_tracker.spawn(simple_process)
    
    assert pid is not None
    assert pid.startswith("pid_")
    
    # Give it time to run
    await asyncio.sleep(0.01)
    
    assert executed
    assert not runtime.is_alive(pid)


@pytest.mark.asyncio
async def test_spawn_with_args(runtime, process_tracker):
    """Test spawning with arguments."""
    result = {}
    
    async def process_with_args(x, y, name="test"):
        result['x'] = x
        result['y'] = y
        result['name'] = name
    
    await process_tracker.spawn(
        process_with_args,
        args=[10, 20],
        kwargs={'name': 'custom'}
    )
    
    await asyncio.sleep(0.01)
    
    assert result == {'x': 10, 'y': 20, 'name': 'custom'}


@pytest.mark.asyncio
async def test_process_normal_exit(runtime, process_tracker, event_recorder):
    """Test process exits normally when function returns."""
    async def normal_process():
        event_recorder.record("started")
        await asyncio.sleep(0.01)
        event_recorder.record("exiting")
        # Implicit return = normal exit
    
    pid = await process_tracker.spawn(normal_process)
    
    await asyncio.sleep(0.05)
    
    assert not runtime.is_alive(pid)
    assert event_recorder.get_order() == ["started", "exiting"]


@pytest.mark.asyncio
async def test_process_exception_exit(runtime, process_tracker):
    """Test process exits with exception."""
    async def crashing_process():
        await asyncio.sleep(0.01)
        raise ValueError("Test crash")
    
    pid = await process_tracker.spawn(crashing_process)
    
    await asyncio.sleep(0.05)
    
    assert not runtime.is_alive(pid)


@pytest.mark.asyncio
async def test_process_killed(runtime, process_tracker):
    """Test killing a process."""
    async def long_running():
        while True:
            await asyncio.sleep(0.1)
    
    pid = await process_tracker.spawn(long_running)
    
    assert runtime.is_alive(pid)
    
    await runtime.exit(pid, KILLED)
    await asyncio.sleep(0.01)
    
    assert not runtime.is_alive(pid)


@pytest.mark.asyncio
async def test_process_info(runtime, process_tracker):
    """Test process info retrieval."""
    async def test_process():
        await asyncio.sleep(1.0)  # Long running
    
    pid = await process_tracker.spawn(
        test_process,
        name="test_proc"
    )
    
    info = runtime.process_info(pid)
    
    assert info is not None
    assert info.pid == pid
    assert info.name == "test_proc"
    assert info.state == RUNNING
    assert info.created_at > 0
    
    # Kill and check again
    await runtime.exit(pid, KILLED)
    await asyncio.sleep(0.01)
    
    # Process should be gone
    info = runtime.process_info(pid)
    assert info is None


@pytest.mark.asyncio
async def test_self_in_process(runtime, process_tracker):
    """Test runtime.self() returns current process PID."""
    captured_pid = None
    spawned_pid = None
    
    async def check_self():
        nonlocal captured_pid
        captured_pid = runtime.self()
        assert captured_pid is not None
    
    spawned_pid = await process_tracker.spawn(check_self)
    await asyncio.sleep(0.01)
    
    assert captured_pid == spawned_pid


@pytest.mark.asyncio
async def test_self_outside_process(runtime):
    """Test runtime.self() returns None outside process context."""
    assert runtime.self() is None


@pytest.mark.asyncio
async def test_multiple_processes(runtime, process_tracker):
    """Test spawning multiple processes."""
    counter = {'count': 0}
    
    async def increment():
        counter['count'] += 1
        await asyncio.sleep(0.01)
    
    # Spawn multiple processes
    pids = []
    for _ in range(10):
        pid = await process_tracker.spawn(increment)
        pids.append(pid)
    
    # All should be alive initially
    alive_count = sum(1 for pid in pids if runtime.is_alive(pid))
    assert alive_count > 0
    
    # Wait for all to complete
    await asyncio.sleep(0.05)
    
    assert counter['count'] == 10
    
    # All should be dead now
    alive_count = sum(1 for pid in pids if runtime.is_alive(pid))
    assert alive_count == 0


@pytest.mark.asyncio
async def test_process_cleanup_on_exception(runtime, process_tracker):
    """Test that process is cleaned up even if it crashes."""
    async def crasher():
        await asyncio.sleep(0.01)
        raise RuntimeError("Intentional crash")
    
    pid = await process_tracker.spawn(crasher)
    initial_count = len(runtime.processes())
    
    await asyncio.sleep(0.05)
    
    # Process should be cleaned up
    assert not runtime.is_alive(pid)
    assert pid not in runtime.processes()
    
    # Process count should decrease
    final_count = len(runtime.processes())
    assert final_count < initial_count
```

## test_message_passing.py

```python
"""
Test message passing between processes.
"""

import asyncio
import pytest
from otpylib.runtime.atoms import PING, PONG, TEST_MSG, ACK, STOP, atom


@pytest.mark.asyncio
async def test_send_receive_basic(runtime, process_tracker):
    """Test basic send and receive."""
    received = []
    
    async def receiver():
        msg = await runtime.receive()
        received.append(msg)
    
    pid = await process_tracker.spawn(receiver)
    await asyncio.sleep(0.01)
    
    await runtime.send(pid, TEST_MSG)
    await asyncio.sleep(0.01)
    
    assert received == [TEST_MSG]


@pytest.mark.asyncio
async def test_send_multiple_messages(runtime, process_tracker):
    """Test sending multiple messages maintains order."""
    received = []
    
    async def receiver():
        for _ in range(3):
            msg = await runtime.receive()
            received.append(msg)
    
    pid = await process_tracker.spawn(receiver)
    await asyncio.sleep(0.01)
    
    messages = [
        atom.ensure("msg1"),
        atom.ensure("msg2"),
        atom.ensure("msg3")
    ]
    
    for msg in messages:
        await runtime.send(pid, msg)
    
    await asyncio.sleep(0.05)
    
    assert received == messages


@pytest.mark.asyncio
async def test_receive_timeout(runtime, process_tracker):
    """Test receive with timeout."""
    timed_out = False
    
    async def receiver():
        nonlocal timed_out
        try:
            await runtime.receive(timeout=0.05)
        except asyncio.TimeoutError:
            timed_out = True
    
    await process_tracker.spawn(receiver)
    await asyncio.sleep(0.1)
    
    assert timed_out


@pytest.mark.asyncio
async def test_send_to_named_process(runtime, process_tracker):
    """Test sending to a named process."""
    received = []
    
    async def named_receiver():
        await runtime.register("receiver")
        msg = await runtime.receive()
        received.append(msg)
    
    await process_tracker.spawn(named_receiver)
    await asyncio.sleep(0.01)
    
    # Send using name instead of PID
    await runtime.send("receiver", TEST_MSG)
    await asyncio.sleep(0.01)
    
    assert received == [TEST_MSG]


@pytest.mark.asyncio
async def test_send_to_dead_process(runtime, process_tracker):
    """Test that sending to dead process doesn't error (drops silently)."""
    async def short_lived():
        pass  # Dies immediately
    
    pid = await process_tracker.spawn(short_lived)
    await asyncio.sleep(0.01)
    
    # Process should be dead
    assert not runtime.is_alive(pid)
    
    # Sending should not raise
    await runtime.send(pid, TEST_MSG)


@pytest.mark.asyncio
async def test_mailbox_overflow(runtime, process_tracker):
    """Test mailbox behavior when full."""
    blocking_send = False
    
    async def slow_receiver():
        # Don't receive, let mailbox fill
        await asyncio.sleep(1.0)
    
    # Create process with small mailbox
    pid = await runtime.spawn(
        slow_receiver,
        mailbox=True  # Mailbox is created with maxsize=100 by default
    )
    
    # Try to overflow - this should handle gracefully
    # Either block, drop, or buffer (implementation specific)
    for i in range(150):
        await runtime.send(pid, f"msg_{i}")
    
    # If we get here, sends completed (didn't block forever)
    assert True


@pytest.mark.asyncio
async def test_bidirectional_communication(runtime, process_tracker, echo_server):
    """Test request-reply pattern."""
    response = None
    
    async def client():
        nonlocal response
        my_pid = runtime.self()
        
        # Send request with our PID
        await runtime.send("echo", (my_pid, TEST_MSG))
        
        # Wait for response
        response = await runtime.receive(timeout=0.5)
    
    await process_tracker.spawn(client)
    await asyncio.sleep(0.05)
    
    assert response is not None
    assert response == (ACK, TEST_MSG)


@pytest.mark.asyncio
async def test_broadcast_pattern(runtime, process_tracker):
    """Test broadcasting to multiple processes."""
    received = {1: [], 2: [], 3: []}
    
    async def listener(listener_id):
        await runtime.register(f"listener_{listener_id}")
        while True:
            try:
                msg = await runtime.receive(timeout=0.1)
                received[listener_id].append(msg)
                if msg == STOP:
                    break
            except asyncio.TimeoutError:
                break
    
    # Start listeners
    for i in range(1, 4):
        await process_tracker.spawn(listener, args=[i])
    
    await asyncio.sleep(0.02)
    
    # Broadcast messages
    for i in range(1, 4):
        await runtime.send(f"listener_{i}", PING)
    
    await asyncio.sleep(0.02)
    
    # Stop all
    for i in range(1, 4):
        await runtime.send(f"listener_{i}", STOP)
    
    await asyncio.sleep(0.02)
    
    # Check all received
    for i in range(1, 4):
        assert received[i] == [PING, STOP]


@pytest.mark.asyncio
async def test_process_without_mailbox(runtime, process_tracker):
    """Test that process without mailbox can't receive."""
    error_raised = False
    
    async def no_mailbox_proc():
        nonlocal error_raised
        try:
            await runtime.receive()
        except RuntimeError:
            error_raised = True
    
    # Spawn without mailbox
    pid = await runtime.spawn(no_mailbox_proc, mailbox=False)
    
    await asyncio.sleep(0.05)
    
    assert error_raised
```

## test_process_links.py

```python
"""
Test process linking and exit propagation.
"""

import asyncio
import pytest
from otpylib.runtime.atoms import NORMAL, KILLED, EXIT, atom


@pytest.mark.asyncio
async def test_bidirectional_link(runtime, process_tracker):
    """Test that links are bidirectional."""
    async def proc_a():
        await runtime.register("proc_a")
        await runtime.link("proc_b")
        await asyncio.sleep(1.0)
    
    async def proc_b():
        await runtime.register("proc_b")
        await asyncio.sleep(1.0)
    
    pid_a = await process_tracker.spawn(proc_a)
    pid_b = await process_tracker.spawn(proc_b)
    
    await asyncio.sleep(0.02)
    
    # Check both processes have the link
    proc_a_info = runtime._processes.get(pid_a)
    proc_b_info = runtime._processes.get(pid_b)
    
    assert pid_b in proc_a_info.links
    assert pid_a in proc_b_info.links


@pytest.mark.asyncio
async def test_exit_propagation(runtime, process_tracker):
    """Test that abnormal exit propagates to linked processes."""
    async def parent():
        await runtime.register("parent")
        child = await runtime.spawn_link(child_proc)
        await asyncio.sleep(1.0)  # Wait longer than child
    
    async def child_proc():
        await asyncio.sleep(0.05)
        raise RuntimeError("Child crash")
    
    parent_pid = await process_tracker.spawn(parent)
    
    await asyncio.sleep(0.01)
    assert runtime.is_alive(parent_pid)
    
    # Wait for child to crash and propagation
    await asyncio.sleep(0.1)
    
    # Parent should be dead due to link
    assert not runtime.is_alive(parent_pid)


@pytest.mark.asyncio
async def test_normal_exit_no_propagation(runtime, process_tracker):
    """Test that normal exit doesn't propagate."""
    async def parent():
        await runtime.register("parent")
        child = await runtime.spawn_link(child_proc)
        await asyncio.sleep(0.2)
    
    async def child_proc():
        await asyncio.sleep(0.05)
        # Normal return - should not kill parent
    
    parent_pid = await process_tracker.spawn(parent)
    
    await asyncio.sleep(0.1)
    
    # Parent should still be alive after child's normal exit
    assert runtime.is_alive(parent_pid)


@pytest.mark.asyncio
async def test_trap_exits(runtime, process_tracker):
    """Test trap_exits converts exit signals to messages."""
    received = []
    
    async def supervisor():
        await runtime.register("supervisor")
        child = await runtime.spawn_link(child_proc)
        
        while True:
            try:
                msg = await runtime.receive(timeout=0.2)
                received.append(msg)
                
                if isinstance(msg, tuple) and msg[0] == EXIT:
                    break
            except asyncio.TimeoutError:
                break
    
    async def child_proc():
        await asyncio.sleep(0.05)
        raise RuntimeError("Child error")
    
    # Spawn supervisor with trap_exits
    sup_pid = await runtime.spawn(supervisor, trap_exits=True)
    
    await asyncio.sleep(0.15)
    
    # Supervisor should still be alive
    assert runtime.is_alive(sup_pid)
    
    # Should have received EXIT message
    assert len(received) == 1
    assert received[0][0] == EXIT
    assert isinstance(received[0][2], RuntimeError)


@pytest.mark.asyncio
async def test_unlink(runtime, process_tracker):
    """Test unlinking processes."""
    async def proc_a():
        await runtime.register("proc_a")
        await runtime.link("proc_b")
        await asyncio.sleep(0.05)
        await runtime.unlink("proc_b")
        await asyncio.sleep(0.2)
    
    async def proc_b():
        await runtime.register("proc_b")
        await asyncio.sleep(0.1)
        raise RuntimeError("proc_b crash")
    
    pid_a = await process_tracker.spawn(proc_a)
    pid_b = await process_tracker.spawn(proc_b)
    
    await asyncio.sleep(0.15)
    
    # proc_b should have crashed
    assert not runtime.is_alive(pid_b)
    
    # proc_a should still be alive (unlinked before crash)
    assert runtime.is_alive(pid_a)


@pytest.mark.asyncio
async def test_circular_links(runtime, process_tracker):
    """Test circular linking behavior."""
    async def proc_a():
        await runtime.register("proc_a")
        await runtime.link("proc_b")
        await asyncio.sleep(0.1)
    
    async def proc_b():
        await runtime.register("proc_b")
        await runtime.link("proc_c")
        await asyncio.sleep(0.1)
    
    async def proc_c():
        await runtime.register("proc_c")
        await runtime.link("proc_a")  # Circular!
        await asyncio.sleep(0.05)
        raise RuntimeError("proc_c crash")
    
    pid_a = await process_tracker.spawn(proc_a)
    pid_b = await process_tracker.spawn(proc_b)
    pid_c = await process_tracker.spawn(proc_c)
    
    await asyncio.sleep(0.02)  # Let links establish
    
    # All should be alive initially
    assert runtime.is_alive(pid_a)
    assert runtime.is_alive(pid_b)
    assert runtime.is_alive(pid_c)
    
    await asyncio.sleep(0.1)  # Wait for crash and propagation
    
    # All should be dead due to circular links
    assert not runtime.is_alive(pid_a)
    assert not runtime.is_alive(pid_b)
    assert not runtime.is_alive(pid_c)


@pytest.mark.asyncio
async def test_spawn_link(runtime, process_tracker):
    """Test spawn_link helper."""
    async def parent():
        # spawn_link should spawn and link atomically
        child = await runtime.spawn_link(child_proc)
        
        # Verify link exists
        parent_pid = runtime.self()
        parent_info = runtime._processes.get(parent_pid)
        assert child in parent_info.links
        
        await asyncio.sleep(0.1)
    
    async def child_proc():
        await asyncio.sleep(0.05)
    
    await process_tracker.spawn(parent)
    await asyncio.sleep(0.15)


@pytest.mark.asyncio
async def test_killed_bypasses_trap_exits(runtime, process_tracker):
    """Test that KILLED reason bypasses trap_exits."""
    async def trapper():
        await asyncio.sleep(1.0)  # Should not reach
    
    pid = await runtime.spawn(trapper, trap_exits=True)
    
    assert runtime.is_alive(pid)
    
    # KILLED should terminate even with trap_exits
    await runtime.exit(pid, KILLED)
    await asyncio.sleep(0.02)
    
    assert not runtime.is_alive(pid)
```

## test_process_monitors.py

```python
"""
Test process monitoring and DOWN messages.
"""

import asyncio
import pytest
from otpylib.runtime.atoms import DOWN, NORMAL, atom


@pytest.mark.asyncio
async def test_monitor_basic(runtime, process_tracker):
    """Test basic monitoring."""
    down_msg = None
    
    async def watcher():
        target_pid = runtime.whereis("target")
        ref = await runtime.monitor(target_pid)
        
        # Wait for DOWN message
        msg = await runtime.receive()
        nonlocal down_msg
        down_msg = msg
    
    async def target():
        await runtime.register("target")
        await asyncio.sleep(0.05)
        # Exit normally
    
    await process_tracker.spawn(watcher)
    await asyncio.sleep(0.01)
    await process_tracker.spawn(target)
    
    await asyncio.sleep(0.1)
    
    # Check DOWN message format
    assert down_msg is not None
    assert down_msg[0] == DOWN
    assert down_msg[1].startswith("ref_")  # Monitor reference
    assert down_msg[3] == NORMAL  # Exit reason


@pytest.mark.asyncio
async def test_monitor_abnormal_exit(runtime, process_tracker):
    """Test monitoring process that exits abnormally."""
    down_msg = None
    
    async def watcher():
        target_pid = runtime.whereis("target")
        ref = await runtime.monitor(target_pid)
        
        msg = await runtime.receive()
        nonlocal down_msg
        down_msg = msg
    
    async def target():
        await runtime.register("target")
        await asyncio.sleep(0.05)
        raise ValueError("Target crashed")
    
    await process_tracker.spawn(watcher)
    await asyncio.sleep(0.01)
    await process_tracker.spawn(target)
    
    await asyncio.sleep(0.1)
    
    assert down_msg is not None
    assert down_msg[0] == DOWN
    assert isinstance(down_msg[3], ValueError)


@pytest.mark.asyncio
async def test_monitor_multiple_times(runtime, process_tracker):
    """Test monitoring same process multiple times."""
    refs = []
    down_msgs = []
    
    async def watcher():
        target_pid = runtime.whereis("target")
        
        # Monitor same process twice
        ref1 = await runtime.monitor(target_pid)
        ref2 = await runtime.monitor(target_pid)
        
        refs.append(ref1)
        refs.append(ref2)
        
        # Should get two DOWN messages
        for _ in range(2):
            msg = await runtime.receive(timeout=0.2)
            down_msgs.append(msg)
    
    async def target():
        await runtime.register("target")
        await asyncio.sleep(0.05)
    
    await process_tracker.spawn(watcher)
    await asyncio.sleep(0.01)
    await process_tracker.spawn(target)
    
    await asyncio.sleep(0.15)
    
    # Should have different refs
    assert refs[0] != refs[1]
    
    # Should get two DOWN messages
    assert len(down_msgs) == 2
    assert all(msg[0] == DOWN for msg in down_msgs)


@pytest.mark.asyncio
async def test_demonitor(runtime, process_tracker):
    """Test demonitoring stops DOWN messages."""
    got_down = False
    
    async def watcher():
        target_pid = runtime.whereis("target")
        ref = await runtime.monitor(target_pid)
        
        # Demonitor before target exits
        await asyncio.sleep(0.03)
        await runtime.demonitor(ref)
        
        # Should not receive DOWN
        try:
            msg = await runtime.receive(timeout=0.1)
            nonlocal got_down
            got_down = True
        except asyncio.TimeoutError:
            pass
    
    async def target():
        await runtime.register("target")
        await asyncio.sleep(0.05)
    
    await process_tracker.spawn(watcher)
    await asyncio.sleep(0.01)
    await process_tracker.spawn(target)
    
    await asyncio.sleep(0.2)
    
    assert not got_down


@pytest.mark.asyncio
async def test_monitor_vs_link(runtime, process_tracker):
    """Test that monitoring doesn't cause exit propagation."""
    async def watcher():
        target_pid = runtime.whereis("target")
        ref = await runtime.monitor(target_pid)
        
        # Receive DOWN but don't exit
        msg = await runtime.receive()
        assert msg[0] == DOWN
        
        # Keep running
        await asyncio.sleep(0.1)
    
    async def target():
        await runtime.register("target")
        await asyncio.sleep(0.05)
        raise RuntimeError("Target crash")
    
    watcher_pid = await process_tracker.spawn(watcher)
    await asyncio.sleep(0.01)
    await process_tracker.spawn(target)
    
    await asyncio.sleep(0.1)
    
    # Watcher should still be alive (monitor doesn't propagate)
    assert runtime.is_alive(watcher_pid)


@pytest.mark.asyncio
async def test_spawn_monitor(runtime, process_tracker):
    """Test spawn_monitor helper."""
    down_msg = None
    
    async def parent():
        # spawn_monitor should return (pid, ref)
        child_pid, ref = await runtime.spawn_monitor(child_proc)
        
        assert child_pid.startswith("pid_")
        assert ref.startswith("ref_")
        
        # Wait for DOWN
        msg = await runtime.receive()
        nonlocal down_msg
        down_msg = msg
    
    async def child_proc():
        await asyncio.sleep(0.05)
    
    await process_tracker.spawn(parent)
    await asyncio.sleep(0.1)
    
    assert down_msg is not None
    assert down_msg[0] == DOWN
```

## test_process_registry.py

```python
"""
Test process name registry.
"""

import asyncio
import pytest
from otpylib.runtime.backends.base import NameAlreadyRegisteredError, ProcessNotFoundError
from otpylib.runtime.atoms import atom


@pytest.mark.asyncio
async def test_register_name(runtime, process_tracker):
    """Test registering a process name."""
    async def named_proc():
        await runtime.register("my_process")
        await asyncio.sleep(0.1)
    
    pid = await process_tracker.spawn(named_proc)
    await asyncio.sleep(0.01)
    
    # Should be able to find by name
    found_pid = runtime.whereis("my_process")
    assert found_pid == pid


@pytest.mark.asyncio
async def test_register_duplicate_name(runtime, process_tracker):
    """Test that duplicate names raise error."""
    async def proc1():
        await runtime.register("duplicate")
        await asyncio.sleep(0.1)
    
    async def proc2():
        await asyncio.sleep(0.01)  # Let proc1 register first
        with pytest.raises(NameAlreadyRegisteredError):
            await runtime.register("duplicate")
    
    await process_tracker.spawn(proc1)
    await process_tracker.spawn(proc2)
    
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_unregister(runtime, process_tracker):
    """Test unregistering a name."""
    async def named_proc():
        await runtime.register("temp_name")
        await asyncio.sleep(0.05)
        await runtime.unregister("temp_name")
        await asyncio.sleep(0.05)
    
    pid = await process_tracker.spawn(named_proc)
    
    await asyncio.sleep(0.02)
    assert runtime.whereis("temp_name") == pid
    
    await asyncio.sleep(0.05)
    assert runtime.whereis("temp_name") is None


@pytest.mark.asyncio
async def test_whereis_dead_process(runtime, process_tracker):
    """Test whereis cleans up dead process names."""
    async def short_lived():
        await runtime.register("dying")
        # Exit immediately
    
    await process_tracker.spawn(short_lived)
    await asyncio.sleep(0.05)
    
    # whereis should return None and clean up
    result = runtime.whereis("dying")
    assert result is None
    
    # Name should be available for reuse
    async def new_proc():
        await runtime.register("dying")  # Should work
        await asyncio.sleep(0.1)
    
    await process_tracker.spawn(new_proc)
    await asyncio.sleep(0.01)
    
    assert runtime.whereis("dying") is not None


@pytest.mark.asyncio
async def test_registered(runtime, process_tracker):
    """Test listing all registered names."""
    names = ["proc_a", "proc_b", "proc_c"]
    
    async def named_proc(name):
        await runtime.register(name)
        await asyncio.sleep(0.1)
    
    for name in names:
        await process_tracker.spawn(named_proc, args=[name])
    
    await asyncio.sleep(0.01)
    
    registered = runtime.registered()
    for name in names:
        assert name in registered


@pytest.mark.asyncio
async def test_name_survives_after_register(runtime, process_tracker):
    """Test that process name is retained in process info."""
    async def named_proc():
        await runtime.register("persistent")
        pid = runtime.self()
        info = runtime.process_info(pid)
        assert info.name == "persistent"
        await asyncio.sleep(0.1)
    
    await process_tracker.spawn(named_proc)
    await asyncio.sleep(0.05)
```

## test_edge_cases.py

```python
"""
Test edge cases and race conditions.
"""

import asyncio
import pytest
from otpylib.runtime.atoms import KILLED, EXIT, DOWN, atom
from otpylib.runtime.backends.base import ProcessNotFoundError, NotInProcessError


@pytest.mark.asyncio
async def test_link_to_dead_process(runtime, process_tracker):
    """Test linking to already dead process."""
    async def short_lived():
        pass  # Dies immediately
    
    dead_pid = await process_tracker.spawn(short_lived)
    await asyncio.sleep(0.01)
    
    async def late_linker():
        with pytest.raises(ProcessNotFoundError):
            await runtime.link(dead_pid)
    
    await process_tracker.spawn(late_linker)
    await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_monitor_dead_process(runtime, process_tracker):
    """Test monitoring already dead process."""
    async def short_lived():
        pass
    
    dead_pid = await process_tracker.spawn(short_lived)
    await asyncio.sleep(0.01)
    
    async def late_monitor():
        with pytest.raises(ProcessNotFoundError):
            await runtime.monitor(dead_pid)
    
    await process_tracker.spawn(late_monitor)
    await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_exit_during_spawn(runtime, process_tracker):
    """Test exit signal during process startup."""
    async def slow_starter():
        await asyncio.sleep(0.1)  # Slow startup
        # Should never reach here
        assert False, "Process should have been killed during startup"
    
    pid = await process_tracker.spawn(slow_starter)
    
    # Kill immediately
    await runtime.exit(pid, KILLED)
    
    await asyncio.sleep(0.15)
    
    assert not runtime.is_alive(pid)


@pytest.mark.asyncio
async def test_concurrent_register(runtime, process_tracker):
    """Test concurrent registration attempts."""
    errors = []
    success = []
    
    async def try_register(index):
        try:
            await runtime.register("contested")
            success.append(index)
        except NameAlreadyRegisteredError:
            errors.append(index)
        await asyncio.sleep(0.1)
    
    # Spawn multiple processes trying to register same name
    for i in range(5):
        await process_tracker.spawn(try_register, args=[i])
    
    await asyncio.sleep(0.15)
    
    # Exactly one should succeed
    assert len(success) == 1
    assert len(errors) == 4


@pytest.mark.asyncio
async def test_receive_after_mailbox_closed(runtime, process_tracker):
    """Test receive behavior after process cleanup."""
    async def receiver():
        await asyncio.sleep(0.05)
        # Mailbox might be closed by now
        try:
            await runtime.receive(timeout=0.01)
        except (RuntimeError, asyncio.TimeoutError):
            pass  # Expected
    
    pid = await process_tracker.spawn(receiver)
    
    # Kill while it's sleeping
    await asyncio.sleep(0.01)
    await runtime.exit(pid, KILLED)
    
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_circular_monitors(runtime, process_tracker):
    """Test processes monitoring each other."""
    down_msgs = {'a': [], 'b': []}
    
    async def proc_a():
        await runtime.register("proc_a")
        ref = await runtime.monitor("proc_b")
        
        msg = await runtime.receive()
        down_msgs['a'].append(msg)
    
    async def proc_b():
        await runtime.register("proc_b")
        await asyncio.sleep(0.01)  # Let proc_a start
        ref = await runtime.monitor("proc_a")
        
        # Exit first
        await asyncio.sleep(0.05)
    
    pid_a = await process_tracker.spawn(proc_a)
    await asyncio.sleep(0.01)
    pid_b = await process_tracker.spawn(proc_b)
    
    await asyncio.sleep(0.1)
    
    # proc_a should get DOWN for proc_b
    assert len(down_msgs['a']) == 1
    assert down_msgs['a'][0][0] == DOWN


@pytest.mark.asyncio
async def test_link_and_monitor_same_process(runtime, process_tracker):
    """Test both linking and monitoring the same process."""
    messages = []
    
    async def watcher():
        await runtime.register("watcher")
        
        target_pid = runtime.whereis("target")
        await runtime.link(target_pid)
        ref = await runtime.monitor(target_pid)
        
        # With trap_exits, should get both EXIT and DOWN
        while True:
            try:
                msg = await runtime.receive(timeout=0.2)
                messages.append(msg)
            except asyncio.TimeoutError:
                break
    
    async def target():
        await runtime.register("target")
        await asyncio.sleep(0.05)
        raise RuntimeError("Target error")
    
    await runtime.spawn(watcher, trap_exits=True)
    await asyncio.sleep(0.01)
    await process_tracker.spawn(target)
    
    await asyncio.sleep(0.15)
    
    # Should get both EXIT (from link) and DOWN (from monitor)
    msg_types = [msg[0] for msg in messages]
    assert EXIT in msg_types
    assert DOWN in msg_types


@pytest.mark.asyncio
async def test_exit_cleanup_race(runtime, process_tracker):
    """Test that exit effects complete before cleanup."""
    received_down = False
    
    async def monitor_proc():
        target = await runtime.spawn(quick_exit)
        ref = await runtime.monitor(target)
        
        # Target exits immediately - we should still get DOWN
        msg = await runtime.receive(timeout=0.5)
        nonlocal received_down
        received_down = (msg[0] == DOWN)
    
    async def quick_exit():
        pass  # Exit immediately
    
    await process_tracker.spawn(monitor_proc)
    await asyncio.sleep(0.1)
    
    assert received_down


@pytest.mark.asyncio
async def test_operations_outside_process(runtime):
    """Test that process operations fail outside process context."""
    # These should raise NotInProcessError
    with pytest.raises(NotInProcessError):
        await runtime.link("some_pid")
    
    with pytest.raises(NotInProcessError):
        await runtime.unlink("some_pid")
    
    with pytest.raises(NotInProcessError):
        await runtime.monitor("some_pid")
    
    with pytest.raises(NotInProcessError):
        await runtime.receive()
```

This gives you a comprehensive test suite for your AsyncIO backend that:

1. **Tests all primitives** before moving to higher-level abstractions
2. **Uses proper fixtures** for isolation and cleanup
3. **Tests edge cases** and race conditions
4. **Verifies BEAM semantics** are preserved
5. **Uses atoms correctly** throughout

This should help you identify and fix those runtime gremlins before they affect your gen_server implementation!
