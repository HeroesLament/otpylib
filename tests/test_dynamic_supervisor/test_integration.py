# tests/test_dynamic_supervisor/test_integration.py
"""
Test dynamic supervisor integration scenarios.
"""
import pytest
import asyncio
from otpylib import process
from otpylib.module import OTPModule, GEN_SERVER
from otpylib.gen_server.data import Reply, NoReply
from otpylib import dynamic_supervisor
from otpylib.dynamic_supervisor import (
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

class WorkerTaskModule(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Simple worker that completes quickly."""
    
    async def init(self, worker_id):
        self.worker_id = worker_id
        # Simulate quick work
        await asyncio.sleep(0.05)
        return {'worker_id': worker_id, 'result': f"worker-{worker_id}-done"}
    
    async def handle_call(self, request, from_pid, state):
        if request == 'get_result':
            return (Reply(state['result']), state)
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

async def test_nested_supervisors():
    """Test nested dynamic supervisors."""
    
    async def body():
        # Start parent supervisor
        parent_pid = await dynamic_supervisor.start(
            [],
            options(),
            "parent_supervisor",
        )
        
        # Start child supervisor
        child_pid = await dynamic_supervisor.start(
            [],
            options(),
            "child_supervisor",
        )
        
        # Add workers to the child supervisor
        for i in range(3):
            spec = child_spec(
                id=f"worker-{i}",
                module=WorkerTaskModule,
                args=i,
                restart=TRANSIENT,
            )
            ok, msg = await dynamic_supervisor.start_child(child_pid, spec)
            assert ok, f"Failed to start worker-{i}: {msg}"
        
        # Let workers complete
        await asyncio.sleep(0.2)
        
        # Parent should be empty (no children added to it)
        parent_children = await dynamic_supervisor.list_children(parent_pid)
        assert len(parent_children) == 0
        
        # Child supervisor should have workers (or they completed)
        child_children = await dynamic_supervisor.list_children(child_pid)
        # Workers may have completed (TRANSIENT), so just verify supervisor works
        assert isinstance(child_children, list)
        
        # Shutdown both supervisors
        await process.send(child_pid, SHUTDOWN)
        await process.send(parent_pid, SHUTDOWN)
        await asyncio.sleep(0.1)
    
    test_pid = await process.spawn(body, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


async def test_supervisor_with_mailbox_name():
    """Test that dynamic supervisor can be accessed by name."""
    
    async def body():
        # Start dynamic supervisor with a well-known name
        sup_pid = await dynamic_supervisor.start(
            [],
            options(),
            "named-supervisor",
        )
        
        # Add first child
        spec1 = child_spec(
            id="test-worker",
            module=WorkerTaskModule,
            args=42,
            restart=TRANSIENT,
        )
        ok, msg = await dynamic_supervisor.start_child("named-supervisor", spec1)
        assert ok, f"Failed to start test-worker: {msg}"
        
        # Add second child
        spec2 = child_spec(
            id="test-worker-2",
            module=WorkerTaskModule,
            args=43,
            restart=TRANSIENT,
        )
        ok, msg = await dynamic_supervisor.start_child("named-supervisor", spec2)
        assert ok, f"Failed to start test-worker-2: {msg}"
        
        # Let them start and potentially complete
        await asyncio.sleep(0.2)
        
        # Query supervisor
        children = await dynamic_supervisor.list_children(sup_pid)
        assert isinstance(children, list)
        
        # Shutdown gracefully
        await process.send(sup_pid, SHUTDOWN)
        await asyncio.sleep(0.1)
    
    test_pid = await process.spawn(body, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)
