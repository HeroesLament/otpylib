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