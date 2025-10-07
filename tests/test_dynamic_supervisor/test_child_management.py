"""
Test dynamic supervisor child management operations.
"""
import pytest
import asyncio
from otpylib import process
from otpylib.module import OTPModule, GEN_SERVER
from otpylib.gen_server.data import Reply, NoReply
from otpylib.dynamic_supervisor import (
    start,
    start_child,
    terminate_child,
    list_children,
    child_spec,
    options,
    PERMANENT,
    TRANSIENT,
    SHUTDOWN,
)

pytestmark = pytest.mark.asyncio


# ============================================================================
# Test Worker Modules
# ============================================================================

class CompletionWorker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Worker that completes immediately after incrementing counter."""
    
    async def init(self, test_data):
        test_data.exec_count += 1
        if hasattr(test_data, 'completed'):
            test_data.completed.set()
        return {'test_data': test_data}
    
    async def handle_call(self, request, from_pid, state):
        return (Reply('ok'), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


class LongRunningWorker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Worker that runs indefinitely."""
    
    async def init(self, test_data):
        test_data.exec_count += 1
        return {'test_data': test_data}
    
    async def handle_call(self, request, from_pid, state):
        return (Reply('ok'), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


# ============================================================================
# Tests
# ============================================================================

async def test_start_multiple_children(test_data):
    """Test starting multiple dynamic children."""
    async def body():
        sup_pid = await start([], options(), name="test-multiple-children")
        
        for i in range(3):
            spec = child_spec(
                id=f"worker-{i}",
                module=CompletionWorker,
                args=test_data,
                restart=TRANSIENT,
            )
            ok, msg = await start_child(sup_pid, spec)
            assert ok, f"Failed to start child: {msg}"
        
        await asyncio.sleep(0.2)
        assert test_data.exec_count == 3
        
        await process.send(sup_pid, SHUTDOWN)
        await asyncio.sleep(0.1)
    
    test_pid = await process.spawn(body, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


async def test_terminate_specific_child(test_data):
    """Test terminating a specific dynamic child."""
    async def body():
        sup_pid = await start([], options(), name="test-terminate-child")
        
        spec = child_spec(
            id="long-runner",
            module=LongRunningWorker,
            args=test_data,
            restart=PERMANENT,
        )
        ok, msg = await start_child(sup_pid, spec)
        assert ok, f"Failed to start child: {msg}"
        
        await asyncio.sleep(0.1)
        assert test_data.exec_count == 1
        
        children = await list_children(sup_pid)
        assert "long-runner" in children
        
        ok, msg = await terminate_child(sup_pid, "long-runner")
        assert ok, f"Failed to terminate child: {msg}"
        
        await asyncio.sleep(0.1)
        children = await list_children(sup_pid)
        assert "long-runner" not in children
        
        await process.send(sup_pid, SHUTDOWN)
        await asyncio.sleep(0.1)
    
    test_pid = await process.spawn(body, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


async def test_replace_child_with_same_id(test_data):
    """Test replacing a child by starting another with the same ID."""
    async def body():
        sup_pid = await start([], options(), name="test-replace-child")
        
        # Start first worker
        spec1 = child_spec(
            id="worker",
            module=LongRunningWorker,
            args=test_data,
            restart=PERMANENT,
        )
        ok, msg = await start_child(sup_pid, spec1)
        assert ok, f"Failed to start first child: {msg}"
        
        await asyncio.sleep(0.1)
        assert test_data.exec_count == 1
        
        children = await list_children(sup_pid)
        assert "worker" in children
        
        # Try to start second worker with same ID (should fail)
        spec2 = child_spec(
            id="worker",
            module=CompletionWorker,
            args=test_data,
            restart=TRANSIENT,
        )
        ok, msg = await start_child(sup_pid, spec2)
        assert not ok, "Should not allow duplicate child ID"
        assert "already exists" in msg.lower()
        
        await asyncio.sleep(0.1)
        # exec_count should still be 1 (second child never started)
        assert test_data.exec_count == 1
        
        await process.send(sup_pid, SHUTDOWN)
        await asyncio.sleep(0.1)
    
    test_pid = await process.spawn(body, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)
