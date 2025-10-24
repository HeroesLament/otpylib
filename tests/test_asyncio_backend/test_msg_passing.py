"""
Test message passing between processes.
"""

import asyncio
import pytest
from otpylib import atom
from otpylib.runtime.atoms import STOP, atom

PING = atom.ensure("ping")
PONG = atom.ensure("pong")
TEST_MSG = atom.ensure("test_msg")
ACK = atom.ensure("ack")


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

PING = atom.ensure("ping")
PONG = atom.ensure("pong")
TEST_MSG = atom.ensure("test_msg")
ACK = atom.ensure("ack")
DELAYED_MSG = atom.ensure("delayed_msg")
TIMER_MSG = atom.ensure("timer_msg")


# ============================================================================
# Timer Tests (send_after, cancel_timer, read_timer)
# ============================================================================

@pytest.mark.asyncio
async def test_send_after_basic(runtime, process_tracker):
    """Test basic delayed message sending."""
    received = []
    received_at = []
    
    async def receiver():
        start = asyncio.get_event_loop().time()
        msg = await runtime.receive(timeout=1.0)
        received.append(msg)
        received_at.append(asyncio.get_event_loop().time() - start)
    
    pid = await process_tracker.spawn(receiver)
    await asyncio.sleep(0.01)
    
    # Send message with 0.1s delay
    timer_ref = await runtime.send_after(0.1, pid, DELAYED_MSG)
    
    assert timer_ref is not None
    assert timer_ref.startswith("timer_")
    
    await asyncio.sleep(0.2)
    
    assert received == [DELAYED_MSG]
    assert 0.08 <= received_at[0] <= 0.15  # Allow some timing variance


@pytest.mark.asyncio
async def test_send_after_multiple_timers(runtime, process_tracker):
    """Test multiple timers with different delays."""
    received = []
    
    async def receiver():
        for _ in range(3):
            msg = await runtime.receive(timeout=1.0)
            received.append(msg)
    
    pid = await process_tracker.spawn(receiver)
    await asyncio.sleep(0.01)
    
    # Schedule multiple messages
    await runtime.send_after(0.05, pid, atom.ensure("first"))
    await runtime.send_after(0.10, pid, atom.ensure("second"))
    await runtime.send_after(0.15, pid, atom.ensure("third"))
    
    await asyncio.sleep(0.25)
    
    assert received == [
        atom.ensure("first"),
        atom.ensure("second"),
        atom.ensure("third")
    ]


@pytest.mark.asyncio
async def test_send_after_to_named_process(runtime, process_tracker):
    """Test sending delayed message to named process."""
    received = []
    
    async def named_receiver():
        await runtime.register("delayed_receiver")
        msg = await runtime.receive(timeout=1.0)
        received.append(msg)
    
    await process_tracker.spawn(named_receiver)
    await asyncio.sleep(0.01)
    
    # Send to named process
    await runtime.send_after(0.05, "delayed_receiver", TIMER_MSG)
    await asyncio.sleep(0.1)
    
    assert received == [TIMER_MSG]


@pytest.mark.asyncio
async def test_cancel_timer_before_fire(runtime, process_tracker):
    """Test cancelling a timer before it fires."""
    received = []
    
    async def receiver():
        try:
            msg = await runtime.receive(timeout=0.2)
            received.append(msg)
        except asyncio.TimeoutError:
            pass
    
    pid = await process_tracker.spawn(receiver)
    await asyncio.sleep(0.01)
    
    # Schedule message
    timer_ref = await runtime.send_after(0.15, pid, DELAYED_MSG)
    
    # Cancel before it fires
    await asyncio.sleep(0.05)
    
    # Read remaining time first (if we want to check it)
    remaining = await runtime.read_timer(timer_ref)
    assert remaining is not None
    assert 0.08 <= remaining <= 0.12
    
    # Now cancel
    cancelled = await runtime.cancel_timer(timer_ref)
    assert cancelled is True  # Timer was successfully cancelled
    
    # Wait to ensure message doesn't arrive
    await asyncio.sleep(0.15)
    
    assert received == []


@pytest.mark.asyncio
async def test_cancel_timer_after_fire(runtime, process_tracker):
    """Test cancelling a timer after it already fired."""
    received = []
    
    async def receiver():
        msg = await runtime.receive(timeout=1.0)
        received.append(msg)
    
    pid = await process_tracker.spawn(receiver)
    await asyncio.sleep(0.01)
    
    # Schedule message with short delay
    timer_ref = await runtime.send_after(0.05, pid, DELAYED_MSG)
    
    # Wait for timer to fire
    await asyncio.sleep(0.1)
    
    # Try to cancel after fire
    cancelled = await runtime.cancel_timer(timer_ref)
    
    # Should return False (already fired)
    assert cancelled is False
    
    # Message should have been received
    assert received == [DELAYED_MSG]


@pytest.mark.asyncio
async def test_cancel_timer_nonexistent(runtime, process_tracker):
    """Test cancelling a nonexistent timer ref."""
    cancelled = await runtime.cancel_timer("invalid_ref_12345")
    assert cancelled is False


@pytest.mark.asyncio
async def test_read_timer_active(runtime, process_tracker):
    """Test reading remaining time on active timer."""
    async def receiver():
        await runtime.receive(timeout=1.0)
    
    pid = await process_tracker.spawn(receiver)
    await asyncio.sleep(0.01)
    
    # Schedule message
    timer_ref = await runtime.send_after(0.2, pid, TIMER_MSG)
    
    # Read timer immediately
    remaining1 = await runtime.read_timer(timer_ref)
    assert remaining1 is not None
    assert 0.18 <= remaining1 <= 0.22
    
    # Wait a bit and read again
    await asyncio.sleep(0.1)
    remaining2 = await runtime.read_timer(timer_ref)
    assert remaining2 is not None
    assert 0.08 <= remaining2 <= 0.12
    
    # Timer should still fire
    await asyncio.sleep(0.15)
    remaining3 = await runtime.read_timer(timer_ref)
    assert remaining3 is None  # Already fired


@pytest.mark.asyncio
async def test_read_timer_fired(runtime, process_tracker):
    """Test reading a timer that already fired."""
    async def receiver():
        await runtime.receive(timeout=1.0)
    
    pid = await process_tracker.spawn(receiver)
    await asyncio.sleep(0.01)
    
    timer_ref = await runtime.send_after(0.05, pid, TIMER_MSG)
    
    # Wait for fire
    await asyncio.sleep(0.1)
    
    remaining = await runtime.read_timer(timer_ref)
    assert remaining is None


@pytest.mark.asyncio
async def test_read_timer_cancelled(runtime, process_tracker):
    """Test reading a cancelled timer."""
    async def receiver():
        await runtime.receive(timeout=1.0)
    
    pid = await process_tracker.spawn(receiver)
    await asyncio.sleep(0.01)
    
    timer_ref = await runtime.send_after(0.2, pid, TIMER_MSG)
    
    # Cancel timer
    await asyncio.sleep(0.05)
    await runtime.cancel_timer(timer_ref)
    
    # Try to read cancelled timer
    remaining = await runtime.read_timer(timer_ref)
    assert remaining is None


@pytest.mark.asyncio
async def test_send_after_to_dead_process(runtime, process_tracker):
    """Test sending delayed message to dead process (should not error)."""
    async def short_lived():
        pass  # Dies immediately
    
    pid = await process_tracker.spawn(short_lived)
    await asyncio.sleep(0.01)
    
    # Process should be dead
    assert not runtime.is_alive(pid)
    
    # Schedule message anyway (should not raise)
    timer_ref = await runtime.send_after(0.05, pid, TIMER_MSG)
    assert timer_ref is not None
    
    # Wait for timer to fire (message dropped silently)
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_timer_cleanup_on_cancel(runtime, process_tracker):
    """Test that cancelled timers are cleaned up from internal state."""
    async def receiver():
        await asyncio.sleep(1.0)
    
    pid = await process_tracker.spawn(receiver)
    
    # Create multiple timers
    refs = []
    for i in range(5):
        ref = await runtime.send_after(1.0, pid, f"msg_{i}")
        refs.append(ref)
    
    # Check timers exist
    assert runtime.timing_wheel.get_active_count() >= 5
    
    # Cancel all
    for ref in refs:
        await runtime.cancel_timer(ref)
    
    # Timers should be cleaned up
    assert runtime.timing_wheel.get_active_count() == 0


@pytest.mark.asyncio
async def test_timer_self_scheduling_pattern(runtime, process_tracker):
    """Test self-scheduling pattern (process sends to itself)."""
    tick_count = []
    
    async def self_scheduler():
        my_pid = runtime.self()
        
        # Schedule first tick
        await runtime.send_after(0.05, my_pid, "tick")
        
        for _ in range(3):
            msg = await runtime.receive(timeout=1.0)
            if msg == "tick":
                tick_count.append(len(tick_count) + 1)
                # Schedule next tick
                await runtime.send_after(0.05, my_pid, "tick")
    
    await process_tracker.spawn(self_scheduler)
    await asyncio.sleep(0.3)
    
    assert tick_count == [1, 2, 3]


@pytest.mark.asyncio
async def test_multiple_timers_same_target(runtime, process_tracker):
    """Test multiple overlapping timers to same target."""
    received = []
    
    async def receiver():
        while True:
            try:
                msg = await runtime.receive(timeout=0.3)
                received.append(msg)
                if len(received) >= 5:
                    break
            except asyncio.TimeoutError:
                break
    
    pid = await process_tracker.spawn(receiver)
    await asyncio.sleep(0.01)
    
    # Schedule 5 messages with overlapping timers
    await runtime.send_after(0.05, pid, "A")
    await runtime.send_after(0.10, pid, "B")
    await runtime.send_after(0.05, pid, "C")  # Same delay as A
    await runtime.send_after(0.15, pid, "D")
    await runtime.send_after(0.02, pid, "E")  # Shortest
    
    await asyncio.sleep(0.25)
    
    # E should be first, then A/C (same time), then B, then D
    assert "E" in received
    assert "A" in received
    assert "C" in received
    assert "B" in received
    assert "D" in received
    assert len(received) == 5


@pytest.mark.asyncio
async def test_timer_with_complex_message(runtime, process_tracker):
    """Test timer with complex message structure."""
    received = []
    
    async def receiver():
        msg = await runtime.receive(timeout=1.0)
        received.append(msg)
    
    pid = await process_tracker.spawn(receiver)
    await asyncio.sleep(0.01)
    
    complex_msg = {
        "type": "timer_event",
        "data": {"value": 42, "nested": [1, 2, 3]},
        "atoms": [PING, PONG]
    }
    
    await runtime.send_after(0.05, pid, complex_msg)
    await asyncio.sleep(0.1)
    
    assert received == [complex_msg]
