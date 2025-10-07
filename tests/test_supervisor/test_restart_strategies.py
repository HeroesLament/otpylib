# tests/test_supervisor/test_restart_strategies.py
"""
Test supervisor restart strategies (one_for_one, one_for_all, rest_for_one).
"""

import asyncio
import pytest
from otpylib import process, gen_server
from otpylib.module import OTPModule, GEN_SERVER, SUPERVISOR
from otpylib.supervisor import start_link, child_spec, options
from otpylib.supervisor.atoms import (
    PERMANENT, ONE_FOR_ONE, ONE_FOR_ALL, REST_FOR_ONE, SHUTDOWN
)
from .helpers import run_in_process


# ============================================================================
# Test Worker Modules
# ============================================================================

class CrashOnceWorker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Worker that starts successfully but crashes when receiving 'crash' message."""
    
    crash_counts = {}
    
    async def init(self, label):
        self.label = label
        self.has_crashed = False
        
        # Track number of times this worker has been started
        if label not in CrashOnceWorker.crash_counts:
            CrashOnceWorker.crash_counts[label] = 0
        CrashOnceWorker.crash_counts[label] += 1
        
        # Schedule a crash shortly after startup on first start only
        if CrashOnceWorker.crash_counts[label] == 1:
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
        if message == 'crash' and not self.has_crashed:
            self.has_crashed = True
            raise RuntimeError(f"{self.label} crash")
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


class ConditionalCrashWorker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Worker that crashes only if label matches crash_label."""
    
    crash_counts = {}
    
    async def init(self, args):
        label, crash_label = args
        self.label = label
        self.crash_label = crash_label
        self.has_crashed = False
        
        if label not in ConditionalCrashWorker.crash_counts:
            ConditionalCrashWorker.crash_counts[label] = 0
        ConditionalCrashWorker.crash_counts[label] += 1
        
        # Schedule a crash if this is the target and first start
        if ConditionalCrashWorker.crash_counts[label] == 1 and label == crash_label:
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
        if message == 'crash' and not self.has_crashed:
            self.has_crashed = True
            raise RuntimeError(f"{self.label} crash")
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


class EventTrackingWorker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Worker that tracks events and optionally crashes after start."""
    
    spawn_counts = {}
    events = []
    
    async def init(self, args):
        label, should_crash = args
        self.label = label
        self.should_crash = should_crash
        self.has_crashed = False
        
        if label not in EventTrackingWorker.spawn_counts:
            EventTrackingWorker.spawn_counts[label] = 0
        EventTrackingWorker.spawn_counts[label] += 1
        
        EventTrackingWorker.events.append(f"{label}_start")
        
        # Schedule a crash if needed on first start only
        if should_crash and EventTrackingWorker.spawn_counts[label] == 1:
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
        if message == 'crash' and not self.has_crashed:
            self.has_crashed = True
            raise RuntimeError(f"{self.label} crash")
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


# ============================================================================
# Tests
# ============================================================================

@pytest.mark.asyncio
async def test_one_for_one_restart(test_data):
    """Test ONE_FOR_ONE strategy restarts only the crashed child."""
    results = {}
    
    # Reset crash counts
    CrashOnceWorker.crash_counts = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="f", module=CrashOnceWorker, args="f", restart=PERMANENT)
            ]
            opts = options(strategy=ONE_FOR_ONE, max_restarts=5, max_seconds=5)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            # Give supervisor time to start children, handle crash, and restart
            await asyncio.sleep(0.5)
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
            import traceback
            results["traceback"] = traceback.format_exc()
    
    await run_in_process(tester)
    if "error" in results:
        print(f"Error: {results['error']}")
        print(f"Traceback: {results.get('traceback', 'N/A')}")
    
    # Worker should have been started at least twice (initial + restart)
    assert CrashOnceWorker.crash_counts.get("f", 0) >= 2, f"Expected at least 2 starts, got {CrashOnceWorker.crash_counts}"
    assert "sup_pid" in results, f"Results: {results}"


@pytest.mark.asyncio
async def test_one_for_all_restart(test_data):
    """Test ONE_FOR_ALL strategy restarts all children when one crashes."""
    results = {}
    
    # Reset crash counts
    ConditionalCrashWorker.crash_counts = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="f1", module=ConditionalCrashWorker, args=("f1", "f1"), restart=PERMANENT),
                child_spec(id="f2", module=ConditionalCrashWorker, args=("f2", "f1"), restart=PERMANENT),
            ]
            opts = options(strategy=ONE_FOR_ALL, max_restarts=5, max_seconds=5)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            await asyncio.sleep(0.5)
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester)
    
    # Both workers should have been restarted due to one_for_all strategy
    assert ConditionalCrashWorker.crash_counts.get("f1", 0) >= 2, f"f1 should restart, got {ConditionalCrashWorker.crash_counts}"
    assert ConditionalCrashWorker.crash_counts.get("f2", 0) >= 2, f"f2 should restart too, got {ConditionalCrashWorker.crash_counts}"
    assert "sup_pid" in results, f"Results: {results}"


@pytest.mark.asyncio
async def test_rest_for_one_restart(test_data):
    """Test REST_FOR_ONE strategy restarts crashed child and all following children."""
    results = {}
    
    # Reset crash counts
    ConditionalCrashWorker.crash_counts = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="first", module=ConditionalCrashWorker, args=("first", "mid"), restart=PERMANENT),
                child_spec(id="mid", module=ConditionalCrashWorker, args=("mid", "mid"), restart=PERMANENT),
                child_spec(id="last", module=ConditionalCrashWorker, args=("last", "mid"), restart=PERMANENT),
            ]
            opts = options(strategy=REST_FOR_ONE, max_restarts=5, max_seconds=5)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            await asyncio.sleep(0.5)
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester)
    
    # First should only start once (not affected by mid's crash)
    assert ConditionalCrashWorker.crash_counts.get("first", 0) == 1, f"first should not restart, got {ConditionalCrashWorker.crash_counts}"
    # Mid and last should both restart
    assert ConditionalCrashWorker.crash_counts.get("mid", 0) >= 2, f"mid should restart, got {ConditionalCrashWorker.crash_counts}"
    assert ConditionalCrashWorker.crash_counts.get("last", 0) >= 2, f"last should restart too, got {ConditionalCrashWorker.crash_counts}"
    assert "sup_pid" in results, f"Results: {results}"


@pytest.mark.asyncio
async def test_permanent_children_always_restart(test_data):
    """Test that PERMANENT children are always restarted after crashes."""
    results = {"restarts": 0}
    
    # Reset crash counts
    CrashOnceWorker.crash_counts = {}
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="p", module=CrashOnceWorker, args="p", restart=PERMANENT)
            ]
            return (specs, options())
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            await asyncio.sleep(0.5)
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester)
    
    # Worker should be started twice: once initially, once after crash
    assert CrashOnceWorker.crash_counts.get("p", 0) >= 2, f"Expected at least 2 starts, got {CrashOnceWorker.crash_counts}"
    assert "sup_pid" in results, f"Results: {results}"


@pytest.mark.asyncio
async def test_mixed_crash_patterns(test_data):
    """Test supervisor with mix of crashing and stable children."""
    results = {"events": []}
    
    # Reset class state
    EventTrackingWorker.spawn_counts = {}
    EventTrackingWorker.events = []
    
    class TestSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
        async def init(self, arg):
            specs = [
                child_spec(id="a", module=EventTrackingWorker, args=("a", True), restart=PERMANENT),
                child_spec(id="b", module=EventTrackingWorker, args=("b", False), restart=PERMANENT),
            ]
            opts = options(strategy=ONE_FOR_ONE, max_restarts=5, max_seconds=5)
            return (specs, opts)
        
        async def terminate(self, reason, state):
            pass
    
    async def tester():
        try:
            sup_pid = await start_link(TestSupervisor, init_arg=None)
            results["sup_pid"] = sup_pid
            
            await asyncio.sleep(0.5)
            await process.exit(sup_pid, SHUTDOWN)
        except Exception as e:
            results["error"] = str(e)
    
    await run_in_process(tester)
    
    # Copy events from class to results
    results["events"] = EventTrackingWorker.events.copy()
    
    # Both workers should have started, and 'a' should have restarted
    assert "a_start" in results["events"], f"Results: {results}"
    assert "b_start" in results["events"], f"Results: {results}"
    # 'a' should appear twice (initial + restart), 'b' only once
    assert results["events"].count("a_start") >= 2, f"a should restart, events: {results['events']}"
    assert results["events"].count("b_start") == 1, f"b should not restart, events: {results['events']}"
    assert "sup_pid" in results, f"Results: {results}"
