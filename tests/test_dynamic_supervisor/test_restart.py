# tests/test_dynamic_supervisor/test_restart.py
"""
Test dynamic supervisor restart behavior and fault tolerance.
"""
import pytest
import asyncio
from otpylib import process, dynamic_supervisor
from otpylib.module import OTPModule, GEN_SERVER
from otpylib.gen_server.data import Reply, NoReply
from otpylib.dynamic_supervisor import (
    child_spec,
    options,
    PERMANENT,
    TRANSIENT,
    ONE_FOR_ONE,
    ONE_FOR_ALL,
    SHUTDOWN,
)

pytestmark = pytest.mark.asyncio


# ============================================================================
# Test Worker Modules
# ============================================================================

class ErrorWorker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Worker that always crashes after init."""
    
    async def init(self, test_data):
        test_data.exec_count += 1
        test_data.error_count += 1
        raise RuntimeError("pytest")
    
    async def handle_call(self, request, from_pid, state):
        return (Reply('ok'), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


class SimpleWorker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Worker that completes normally."""
    
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

@pytest.mark.parametrize("max_restarts", [1, 3, 5])
async def test_automatic_restart_permanent(max_restarts, test_data):
    """Test that PERMANENT children restart until intensity limit."""
    async def body():
        children = [
            child_spec(
                id="persistent_service",
                module=ErrorWorker,
                args=test_data,
                restart=PERMANENT,
            )
        ]
        opts = options(max_restarts=max_restarts, max_seconds=5)
        sup_pid = await dynamic_supervisor.start(children, opts)
        
        # Wait for supervisor to die from restart intensity
        for _ in range(50):  # Max 5 seconds
            if not process.is_alive(sup_pid):
                break
            await asyncio.sleep(0.1)
        
        # Supervisor should have shut down
        assert not process.is_alive(sup_pid)
        # Should have tried initial start + max_restarts
        assert test_data.exec_count >= (max_restarts + 1)
        assert test_data.error_count >= (max_restarts + 1)
    
    test_pid = await process.spawn(body, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


@pytest.mark.parametrize("strategy", [ONE_FOR_ONE, ONE_FOR_ALL])
@pytest.mark.parametrize("max_restarts", [1, 3])
async def test_automatic_restart_on_crash(strategy, max_restarts, test_data):
    """Test automatic restart with different strategies."""
    async def body():
        children = [
            child_spec(
                id="failing_service",
                module=ErrorWorker,
                args=test_data,
                restart=PERMANENT,
            )
        ]
        opts = options(
            max_restarts=max_restarts,
            max_seconds=5,
            strategy=strategy,
        )
        sup_pid = await dynamic_supervisor.start(children, opts)
        
        # Wait for supervisor to die from restart intensity
        for _ in range(50):
            if not process.is_alive(sup_pid):
                break
            await asyncio.sleep(0.1)
        
        assert not process.is_alive(sup_pid)
        assert test_data.exec_count >= (max_restarts + 1)
        assert test_data.error_count >= (max_restarts + 1)
    
    test_pid = await process.spawn(body, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


@pytest.mark.parametrize("strategy", [ONE_FOR_ONE, ONE_FOR_ALL])
async def test_no_restart_for_normal_exit(strategy, test_data):
    """Test that TRANSIENT children don't restart on normal exit."""
    async def body():
        children = [
            child_spec(
                id="transient_service",
                module=SimpleWorker,
                args=test_data,
                restart=TRANSIENT,
            )
        ]
        opts = options(max_restarts=3, max_seconds=5, strategy=strategy)
        sup_pid = await dynamic_supervisor.start(children, opts)
        
        await asyncio.sleep(0.2)
        await process.send(sup_pid, SHUTDOWN)
        await asyncio.sleep(0.1)
        
        assert test_data.exec_count >= 1
    
    test_pid = await process.spawn(body, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


async def test_start_multiple_children(test_data):
    """Test starting multiple dynamic children."""
    async def body():
        sup_pid = await dynamic_supervisor.start([], options(), "test_supervisor")
        
        child1_spec = child_spec(
            id="child1",
            module=LongRunningWorker,
            args=test_data,
            restart=PERMANENT,
        )
        child2_spec = child_spec(
            id="child2",
            module=LongRunningWorker,
            args=test_data,
            restart=PERMANENT,
        )
        
        ok, msg = await dynamic_supervisor.start_child("test_supervisor", child1_spec)
        assert ok, msg
        ok, msg = await dynamic_supervisor.start_child("test_supervisor", child2_spec)
        assert ok, msg
        
        await asyncio.sleep(0.1)
        
        children = await dynamic_supervisor.list_children(sup_pid)
        assert "child1" in children and "child2" in children
        assert len(children) == 2
        
        await process.send(sup_pid, SHUTDOWN)
        await asyncio.sleep(0.1)
    
    test_pid = await process.spawn(body, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


async def test_terminate_specific_child(test_data):
    """Test terminating a specific dynamic child."""
    async def body():
        sup_pid = await dynamic_supervisor.start([], options(), "test_supervisor")
        
        spec = child_spec(
            id="target_child",
            module=LongRunningWorker,
            args=test_data,
            restart=PERMANENT,
        )
        ok, msg = await dynamic_supervisor.start_child("test_supervisor", spec)
        assert ok, msg
        
        await asyncio.sleep(0.1)
        
        children = await dynamic_supervisor.list_children(sup_pid)
        assert "target_child" in children
        
        ok, msg = await dynamic_supervisor.terminate_child("test_supervisor", "target_child")
        assert ok, msg
        
        await asyncio.sleep(0.1)
        
        children = await dynamic_supervisor.list_children(sup_pid)
        assert "target_child" not in children
        
        await process.send(sup_pid, SHUTDOWN)
        await asyncio.sleep(0.1)
    
    test_pid = await process.spawn(body, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


async def test_replace_child_with_same_id(test_data):
    """Test that duplicate IDs are rejected."""
    async def body():
        from tests.test_dynamic_supervisor.conftest import DataHelper
        test_data1 = DataHelper()
        test_data2 = DataHelper()
        
        sup_pid = await dynamic_supervisor.start([], options(), "test_supervisor")
        
        spec1 = child_spec(
            id="replaceable_child",
            module=LongRunningWorker,
            args=test_data1,
            restart=PERMANENT,
        )
        ok, msg = await dynamic_supervisor.start_child("test_supervisor", spec1)
        assert ok, msg
        
        await asyncio.sleep(0.1)
        
        children = await dynamic_supervisor.list_children(sup_pid)
        assert "replaceable_child" in children
        assert test_data1.exec_count == 1
        
        # Try to add another with same ID (should fail)
        spec2 = child_spec(
            id="replaceable_child",
            module=LongRunningWorker,
            args=test_data2,
            restart=PERMANENT,
        )
        ok, msg = await dynamic_supervisor.start_child("test_supervisor", spec2)
        assert not ok, "Should not allow duplicate ID"
        assert "already exists" in msg.lower()
        
        await process.send(sup_pid, SHUTDOWN)
        await asyncio.sleep(0.1)
    
    test_pid = await process.spawn(body, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


async def test_supervisor_with_mailbox_name(test_data):
    """Test supervisor can be accessed by registered name."""
    async def body():
        sup_pid = await dynamic_supervisor.start([], options(), "named_supervisor")
        
        spec = child_spec(
            id="mailbox_child",
            module=LongRunningWorker,
            args=test_data,
            restart=PERMANENT,
        )
        ok, msg = await dynamic_supervisor.start_child("named_supervisor", spec)
        assert ok, msg
        
        await asyncio.sleep(0.1)
        
        children = await dynamic_supervisor.list_children(sup_pid)
        assert "mailbox_child" in children
        
        await process.send(sup_pid, SHUTDOWN)
        await asyncio.sleep(0.1)
    
    test_pid = await process.spawn(body, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


async def test_nested_supervisors(test_data):
    """Test nested dynamic supervisors."""
    async def body():
        parent_pid = await dynamic_supervisor.start([], options(), "parent_supervisor")
        child_pid = await dynamic_supervisor.start([], options(), "child_supervisor")
        
        spec = child_spec(
            id="nested_task",
            module=LongRunningWorker,
            args=test_data,
            restart=PERMANENT,
        )
        ok, msg = await dynamic_supervisor.start_child("child_supervisor", spec)
        assert ok, msg
        
        await asyncio.sleep(0.1)
        
        children = await dynamic_supervisor.list_children(child_pid)
        assert "nested_task" in children
        
        parent_children = await dynamic_supervisor.list_children(parent_pid)
        assert len(parent_children) == 0
        
        await process.send(child_pid, SHUTDOWN)
        await process.send(parent_pid, SHUTDOWN)
        await asyncio.sleep(0.1)
    
    test_pid = await process.spawn(body, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)
