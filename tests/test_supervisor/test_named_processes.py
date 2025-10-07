# tests/test_supervisor/test_named_processes.py
"""
Tests for supervisors with named children and supervisors.
"""

import asyncio
import pytest
from otpylib import process
from otpylib.module import OTPModule, GEN_SERVER, SUPERVISOR
from otpylib.supervisor import start_link, child_spec, options
from otpylib.supervisor.atoms import PERMANENT, ONE_FOR_ONE, SHUTDOWN
from .helpers import run_in_process


# ============================================================================
# Test Worker Modules
# ============================================================================

class StableWorker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """A stable worker that runs indefinitely."""
    
    async def init(self, test_data):
        self.test_data = test_data
        # Start a background task to increment counter
        asyncio.create_task(self._run())
        return {'test_data': test_data}
    
    async def _run(self):
        """Background task that increments counter."""
        while True:
            self.test_data.exec_count += 1
            await asyncio.sleep(0.05)
    
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


class CrashingWorker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """A worker that crashes once after starting, then runs successfully."""
    
    crash_counts = {}
    
    async def init(self, label):
        self.label = label
        
        # Track crash count for this label
        if label not in CrashingWorker.crash_counts:
            CrashingWorker.crash_counts[label] = 0
        CrashingWorker.crash_counts[label] += 1
        
        # Only crash on first start
        if CrashingWorker.crash_counts[label] == 1:
            asyncio.create_task(self._delayed_crash())
        
        return {'label': label}
    
    async def _delayed_crash(self):
        """Crash after a short delay."""
        await asyncio.sleep(0.05)
        pid = process.self()
        await process.send(pid, 'crash')
    
    async def handle_call(self, request, from_pid, state):
        from otpylib.gen_server.data import Reply
        return (Reply('ok'), state)
    
    async def handle_cast(self, message, state):
        from otpylib.gen_server.data import NoReply
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        from otpylib.gen_server.data import NoReply
        if message == 'crash':
            raise RuntimeError(f"{self.label} crash")
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


# ============================================================================
# Tests
# ============================================================================

@pytest.mark.asyncio
async def test_named_children(test_data):
    """Test that children can be registered with names."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(
                    id="child1",
                    module=StableWorker,
                    args=test_data,
                    restart=PERMANENT,
                    name="named_child1",
                ),
                child_spec(
                    id="child2",
                    module=StableWorker,
                    args=test_data,
                    restart=PERMANENT,
                    name="named_child2",
                ),
            ]
            opts = options(strategy=ONE_FOR_ONE)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            await asyncio.sleep(0.1)
            
            # Both children should be registered by name
            child1_pid = process.whereis("named_child1")
            child2_pid = process.whereis("named_child2")
            results["child1_registered"] = child1_pid is not None
            results["child2_registered"] = child2_pid is not None
            
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester, name="test_named_children")
    assert results.get("child1_registered", False), f"Results: {results}"
    assert results.get("child2_registered", False), f"Results: {results}"


@pytest.mark.asyncio
async def test_named_child_restart(test_data):
    """Test that named children are re-registered after restart."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(
                    id="flappy",
                    module=CrashingWorker,
                    args="flappy",
                    restart=PERMANENT,
                    name="flappy_child",
                )
            ]
            opts = options(strategy=ONE_FOR_ONE, max_restarts=5, max_seconds=5)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            # Wait for crash and restart
            await asyncio.sleep(0.3)
            
            # The child should have restarted and been re-registered
            flappy_pid = process.whereis("flappy_child")
            results["child_reregistered"] = flappy_pid is not None
            
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester, name="test_named_child_restart")
    assert results.get("child_reregistered", False), f"Results: {results}"


@pytest.mark.asyncio
async def test_named_supervisor_hierarchy(test_data):
    """Test supervisor hierarchy with named supervisors and children."""
    results = {}
    
    # Inner supervisor that manages a worker
    class InnerSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(
                    id="worker",
                    module=StableWorker,
                    args=test_data,
                    restart=PERMANENT,
                    name="inner_worker",
                )
            ]
            opts = options(strategy=ONE_FOR_ONE)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    # Outer supervisor that manages inner supervisor
    class OuterSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(
                    id="inner_sup",
                    module=InnerSupervisor,
                    args=None,
                    restart=PERMANENT,
                    name="inner_supervisor",
                )
            ]
            opts = options(strategy=ONE_FOR_ONE)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(OuterSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            await asyncio.sleep(0.2)
            
            # Verify inner supervisor and child exist
            inner_sup_pid = process.whereis("inner_supervisor")
            inner_worker_pid = process.whereis("inner_worker")
            results["inner_sup_registered"] = inner_sup_pid is not None
            results["inner_worker_registered"] = inner_worker_pid is not None
            
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester, name="test_named_supervisor_hierarchy")
    assert results.get("inner_sup_registered", False), f"Results: {results}"
    assert results.get("inner_worker_registered", False), f"Results: {results}"


@pytest.mark.asyncio
async def test_name_cleanup_on_child_exit(test_data):
    """Test that names are properly cleaned up and re-registered on restart."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(
                    id="crasher",
                    module=CrashingWorker,
                    args="crasher",
                    restart=PERMANENT,
                    name="crash_child",
                )
            ]
            opts = options(strategy=ONE_FOR_ONE, max_restarts=5, max_seconds=5)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            await asyncio.sleep(0.1)
            
            # Name should be registered initially
            pid1 = process.whereis("crash_child")
            results["initial_registered"] = pid1 is not None
            
            # After crash/restart cycle, name should still be registered
            await asyncio.sleep(0.3)
            pid2 = process.whereis("crash_child")
            results["after_restart_registered"] = pid2 is not None
            
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester, name="test_name_cleanup_on_child_exit")
    assert results.get("initial_registered", False), f"Results: {results}"
    assert results.get("after_restart_registered", False), f"Results: {results}"


@pytest.mark.asyncio
async def test_name_reuse_after_restart(test_data):
    """Test that the same name is reusable after restarts."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(
                    id="flappy",
                    module=CrashingWorker,
                    args="flappy",
                    restart=PERMANENT,
                    name="reused_child",
                )
            ]
            opts = options(strategy=ONE_FOR_ONE, max_restarts=10, max_seconds=5)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            await asyncio.sleep(0.3)
            
            # After a few restarts, the same name should always be re-usable
            pid1 = process.whereis("reused_child")
            results["first_check"] = pid1
            
            await asyncio.sleep(0.2)
            pid2 = process.whereis("reused_child")
            results["second_check"] = pid2
            
            # Name should be consistently available
            results["name_available"] = pid2 is not None
            
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester, name="test_name_reuse_after_restart")
    assert results.get("name_available", False), f"Results: {results}"


@pytest.mark.asyncio
async def test_supervisor_name_conflict(test_data):
    """Test that starting a supervisor with a conflicting name raises an error."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(
                    id="child",
                    module=StableWorker,
                    args=test_data,
                    restart=PERMANENT,
                    name="conflict_child",
                )
            ]
            opts = options(strategy=ONE_FOR_ONE)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            # Start first supervisor with a name
            sup_pid1 = await start_link(TestSupervisor, init_arg=None, name="named_sup")
            results["sup_pid1"] = sup_pid1
            
            # Try to start second supervisor with same name - should fail
            try:
                sup_pid2 = await start_link(TestSupervisor, init_arg=None, name="named_sup")
                results["conflict_detected"] = False
            except RuntimeError as e:
                results["conflict_detected"] = True
                results["error_message"] = str(e)
            
            await process.exit(sup_pid1, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester, name="test_supervisor_name_conflict")
    assert results.get("conflict_detected", False), f"Should detect name conflict. Results: {results}"
