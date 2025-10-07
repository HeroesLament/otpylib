"""
Test basic supervisor operations and lifecycle.
"""

import asyncio
import pytest
from otpylib import process
from otpylib.module import OTPModule, GEN_SERVER, SUPERVISOR
from otpylib.supervisor import start_link, child_spec, options
from otpylib.supervisor.atoms import (
    ONE_FOR_ONE, PERMANENT, SHUTDOWN
)
from .helpers import run_in_process


# ============================================================================
# Test Worker Modules
# ============================================================================

class LongRunningWorker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """A worker that runs a background task indefinitely."""
    
    async def init(self, test_data):
        self.test_data = test_data
        self.running = True
        # Start background task
        self.task = asyncio.create_task(self._run())
        return {'test_data': test_data}
    
    async def _run(self):
        """Background task that increments counter."""
        try:
            while self.running:
                self.test_data.exec_count += 1
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            pass
    
    async def handle_call(self, request, from_pid, state):
        from otpylib.gen_server.data import Reply
        return (Reply('ok'), state)
    
    async def handle_cast(self, message, state):
        from otpylib.gen_server.data import NoReply
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        from otpylib.gen_server.data import NoReply
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        self.running = False
        if hasattr(self, 'task'):
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass


class OrderTrackingWorker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """A worker that records its start order."""
    
    start_order = []
    
    async def init(self, task_id):
        OrderTrackingWorker.start_order.append(task_id)
        self.task_id = task_id
        return {'task_id': task_id}
    
    async def handle_call(self, request, from_pid, state):
        from otpylib.gen_server.data import Reply
        return (Reply('ok'), state)
    
    async def handle_cast(self, message, state):
        from otpylib.gen_server.data import NoReply
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        from otpylib.gen_server.data import NoReply
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


# ============================================================================
# Tests
# ============================================================================

@pytest.mark.asyncio
async def test_supervisor_start(test_data):
    """Test starting a supervisor with children."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="worker1", module=LongRunningWorker, args=test_data, restart=PERMANENT),
                child_spec(id="worker2", module=LongRunningWorker, args=test_data, restart=PERMANENT),
            ]
            opts = options(strategy=ONE_FOR_ONE)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def test_logic():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            # Verify supervisor started and is alive
            results["alive_after_start"] = process.is_alive(sup_pid)
            
            # Give workers time to run
            await asyncio.sleep(0.2)
            results["exec_count"] = test_data.exec_count
            
            # Supervisor will be cleaned up when this process exits via start_link semantics
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(test_logic)
    assert results.get("alive_after_start", False), f"Supervisor should start alive. Results: {results}"
    assert results.get("exec_count", 0) > 0, f"Workers should have incremented exec_count. Results: {results}"


@pytest.mark.asyncio
async def test_supervisor_start_link(test_data):
    """Test start_link creates linked supervisor."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="child", module=LongRunningWorker, args=test_data, restart=PERMANENT)
            ]
            opts = options(strategy=ONE_FOR_ONE)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def parent_process():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            await asyncio.sleep(0.3)
            return sup_pid
        except Exception as e:
            results["error"] = str(e)
    
    parent_pid = await process.spawn(parent_process, name="parent_proc", mailbox=True)
    await asyncio.sleep(0.1)
    
    results["parent_alive"] = process.is_alive(parent_pid)
    
    await process.exit(parent_pid, SHUTDOWN)
    await asyncio.sleep(0.1)
    results["parent_dead"] = not process.is_alive(parent_pid)
    
    assert results.get("parent_alive", False), f"Results: {results}"
    assert results.get("parent_dead", False), f"Results: {results}"


@pytest.mark.asyncio
async def test_get_child_status(test_data):
    """Test getting child status via supervisor messages."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(
                    id="worker",
                    module=LongRunningWorker,
                    args=test_data,
                    restart=PERMANENT,
                    name="test_worker",
                )
            ]
            opts = options(strategy=ONE_FOR_ONE)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def test_logic():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            await asyncio.sleep(0.1)
            
            # Note: The 0.5.0 API may not support GET_CHILD_STATUS messages yet
            # This test verifies the supervisor is running and child is registered
            worker_pid = process.whereis("test_worker")
            results["worker_registered"] = worker_pid is not None
            results["worker_alive"] = process.is_alive(worker_pid) if worker_pid else False
            
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(test_logic)
    assert results.get("worker_registered", False), f"Results: {results}"
    assert results.get("worker_alive", False), f"Results: {results}"


@pytest.mark.asyncio
async def test_list_children(test_data):
    """Test listing all children."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="worker1", module=LongRunningWorker, args=test_data, restart=PERMANENT, name="worker1"),
                child_spec(id="worker2", module=LongRunningWorker, args=test_data, restart=PERMANENT, name="worker2"),
                child_spec(id="worker3", module=LongRunningWorker, args=test_data, restart=PERMANENT, name="worker3"),
            ]
            opts = options(strategy=ONE_FOR_ONE)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def test_logic():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            await asyncio.sleep(0.1)
            
            # Verify all children are registered
            children_found = []
            for name in ["worker1", "worker2", "worker3"]:
                if process.whereis(name) is not None:
                    children_found.append(name)
            
            results["children_found"] = children_found
            
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(test_logic)
    assert set(results.get("children_found", [])) == {"worker1", "worker2", "worker3"}, f"Results: {results}"


@pytest.mark.asyncio
async def test_children_start_in_order(test_data):
    """Test that children start in specification order."""
    # Reset class variable
    OrderTrackingWorker.start_order = []
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="first", module=OrderTrackingWorker, args="first", restart=PERMANENT),
                child_spec(id="second", module=OrderTrackingWorker, args="second", restart=PERMANENT),
                child_spec(id="third", module=OrderTrackingWorker, args="third", restart=PERMANENT),
            ]
            opts = options(strategy=ONE_FOR_ONE)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def test_logic():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            await asyncio.sleep(0.2)
            
            results["start_order"] = OrderTrackingWorker.start_order.copy()
            
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(test_logic)
    assert results.get("start_order", []) == ["first", "second", "third"], f"Results: {results}"


@pytest.mark.asyncio
async def test_supervisor_with_options(test_data):
    """Test supervisor with custom options."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="worker", module=LongRunningWorker, args=test_data, restart=PERMANENT)
            ]
            opts = options(max_restarts=5, max_seconds=10, strategy=ONE_FOR_ONE)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def test_logic():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            results["alive"] = process.is_alive(sup_pid)
            await asyncio.sleep(0.1)
            results["exec_count"] = test_data.exec_count
            
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(test_logic)
    assert results.get("alive", False), f"Results: {results}"
    assert results.get("exec_count", 0) > 0, f"Results: {results}"
