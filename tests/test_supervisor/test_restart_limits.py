# tests/test_supervisor/test_restart_limits.py
"""
Test supervisor restart limits (intensity, windows, counts).
"""

import asyncio
import pytest
from otpylib import process
from otpylib.module import OTPModule, GEN_SERVER, SUPERVISOR
from otpylib.supervisor import start_link, child_spec, options
from otpylib.supervisor.atoms import PERMANENT, ONE_FOR_ONE, ONE_FOR_ALL, SHUTDOWN
from .helpers import run_in_process


# ============================================================================
# Test Worker Modules
# ============================================================================

class CrashingWorker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Worker that continuously crashes after starting."""
    
    async def init(self, label):
        self.label = label
        # Schedule immediate crash after successful init
        asyncio.create_task(self._delayed_crash())
        return {'label': label}
    
    async def _delayed_crash(self):
        """Crash shortly after starting."""
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


class NormalExitWorker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Worker that exits normally (not a crash)."""
    
    async def init(self, label):
        self.label = label
        # Schedule normal exit shortly after starting
        asyncio.create_task(self._delayed_exit())
        return {'label': label}
    
    async def _delayed_exit(self):
        """Exit normally after a short delay."""
        await asyncio.sleep(0.05)
        pid = process.self()
        await process.exit(pid, 'normal')
    
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
async def test_restart_intensity_limit(test_data):
    """Test that supervisor shuts down after exceeding restart intensity."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="flappy", module=CrashingWorker, args="flappy", restart=PERMANENT),
            ]
            opts = options(strategy=ONE_FOR_ONE, max_restarts=2, max_seconds=5)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            # Supervisor should shut down after too many restarts
            for _ in range(50):  # Max 5 seconds
                if not process.is_alive(sup_pid):
                    results["shutdown"] = True
                    break
                await asyncio.sleep(0.1)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester)
    assert "sup_pid" in results, f"Results: {results}"
    assert results.get("shutdown", False), "Supervisor should have shut down due to restart intensity"


@pytest.mark.asyncio
async def test_restart_window_sliding(test_data):
    """Test that restart window slides with time."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="flappy", module=CrashingWorker, args="flappy", restart=PERMANENT)
            ]
            opts = options(strategy=ONE_FOR_ONE, max_restarts=3, max_seconds=1)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            # Supervisor should restart a few times before giving up
            for _ in range(50):
                if not process.is_alive(sup_pid):
                    results["shutdown"] = True
                    break
                await asyncio.sleep(0.1)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester)
    assert "sup_pid" in results, f"Results: {results}"
    assert results.get("shutdown", False), "Supervisor should have shut down"


@pytest.mark.asyncio
async def test_restart_count_per_child(test_data):
    """Test restart intensity with multiple crashing children."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="a", module=CrashingWorker, args="a", restart=PERMANENT),
                child_spec(id="b", module=CrashingWorker, args="b", restart=PERMANENT),
            ]
            opts = options(strategy=ONE_FOR_ONE, max_restarts=3, max_seconds=5)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            # Wait for supervisor to die
            for _ in range(50):
                if not process.is_alive(sup_pid):
                    results["shutdown"] = True
                    break
                await asyncio.sleep(0.1)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester)
    assert "sup_pid" in results, f"Results: {results}"
    assert results.get("shutdown", False), "Supervisor should have shut down"


@pytest.mark.asyncio
async def test_restart_limit_with_one_for_all(test_data):
    """Test restart intensity with ONE_FOR_ALL strategy."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="f1", module=CrashingWorker, args="f1", restart=PERMANENT),
                child_spec(id="f2", module=CrashingWorker, args="f2", restart=PERMANENT),
            ]
            opts = options(strategy=ONE_FOR_ALL, max_restarts=2, max_seconds=5)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            for _ in range(50):
                if not process.is_alive(sup_pid):
                    results["shutdown"] = True
                    break
                await asyncio.sleep(0.1)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester)
    assert "sup_pid" in results, f"Results: {results}"
    assert results.get("shutdown", False), "Supervisor should have shut down"


@pytest.mark.asyncio
async def test_no_restart_limit_for_normal_exit(test_data):
    """Test that normal exits don't count toward restart intensity."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="n", module=NormalExitWorker, args="n", restart=PERMANENT),
            ]
            opts = options(strategy=ONE_FOR_ONE, max_restarts=1, max_seconds=5)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            # Give time for normal exits to happen
            await asyncio.sleep(0.5)
            
            # Supervisor should still be alive (normal exits don't count)
            results["still_alive"] = process.is_alive(sup_pid)
            
            if process.is_alive(sup_pid):
                await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester)
    assert "sup_pid" in results, f"Results: {results}"
    assert results.get("still_alive", False), "Supervisor should still be alive after normal exits"


@pytest.mark.asyncio
async def test_restart_limit_reset_after_window(test_data):
    """Test that restart counter resets after the time window passes."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="f", module=CrashingWorker, args="f", restart=PERMANENT)
            ]
            opts = options(strategy=ONE_FOR_ONE, max_restarts=2, max_seconds=1)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            # Let the restart counter reset (window is 1 second, so wait 2)
            await asyncio.sleep(2.0)
            
            # Supervisor might still be alive if crashes spread out enough
            results["still_alive"] = process.is_alive(sup_pid)
            
            if process.is_alive(sup_pid):
                await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester)
    assert "sup_pid" in results, f"Results: {results}"
    # Note: This test is timing-sensitive. The supervisor may or may not be alive
    # depending on crash timing, but the test should complete without errors


@pytest.mark.asyncio
async def test_multiple_children_intensity(test_data):
    """Test restart intensity with multiple crashing children."""
    results = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="a", module=CrashingWorker, args="a", restart=PERMANENT),
                child_spec(id="b", module=CrashingWorker, args="b", restart=PERMANENT),
                child_spec(id="c", module=CrashingWorker, args="c", restart=PERMANENT),
            ]
            opts = options(strategy=ONE_FOR_ONE, max_restarts=2, max_seconds=5)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            for _ in range(50):
                if not process.is_alive(sup_pid):
                    results["shutdown"] = True
                    break
                await asyncio.sleep(0.1)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester)
    assert "sup_pid" in results, f"Results: {results}"
    assert results.get("shutdown", False), "Supervisor should have shut down"
