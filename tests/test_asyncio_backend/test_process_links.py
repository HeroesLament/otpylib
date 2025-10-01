"""
Test process linking and exit propagation.
"""

import asyncio
import pytest
from otpylib.runtime.atoms import NORMAL, KILLED, EXIT, atom


async def wait_for(condition, timeout=1.0, interval=0.01):
    """Wait for a condition to become true."""
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        if condition():
            return True
        await asyncio.sleep(interval)
    return False


@pytest.mark.asyncio
async def test_bidirectional_link(runtime, process_tracker):
    """Test that links are bidirectional by verifying death propagation."""
    proc_a_died = False
    proc_b_died = False
    
    async def proc_a():
        nonlocal proc_a_died
        try:
            await runtime.register("proc_a")
            # Wait for proc_b to register
            await asyncio.sleep(0.02)
            await runtime.link("proc_b")
            # Stay alive until killed by link
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            proc_a_died = True
            raise
    
    async def proc_b():
        nonlocal proc_b_died
        try:
            await runtime.register("proc_b")
            # Crash after a short delay
            await asyncio.sleep(0.1)
            raise RuntimeError("proc_b crash")
        except asyncio.CancelledError:
            proc_b_died = True
            raise
    
    pid_a = await process_tracker.spawn(proc_a)
    pid_b = await process_tracker.spawn(proc_b)
    
    # Wait for both to die (b crashes, a dies from link)
    await wait_for(lambda: not runtime.is_alive(pid_a) and not runtime.is_alive(pid_b), timeout=0.5)
    
    # Both should be dead
    assert not runtime.is_alive(pid_a), "proc_a should die when linked proc_b crashes"
    assert not runtime.is_alive(pid_b), "proc_b should be dead from crash"


@pytest.mark.asyncio
async def test_exit_propagation(runtime, process_tracker):
    """Test that abnormal exit propagates to linked processes."""
    parent_died = False
    
    async def parent():
        nonlocal parent_died
        try:
            child = await runtime.spawn_link(child_proc)
            # Wait - should be killed by child crash
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            parent_died = True
            raise
    
    async def child_proc():
        await asyncio.sleep(0.05)
        raise RuntimeError("Child crash")
    
    parent_pid = await process_tracker.spawn(parent)
    
    # Parent should die when child crashes
    await wait_for(lambda: not runtime.is_alive(parent_pid), timeout=0.5)
    
    assert not runtime.is_alive(parent_pid), "Parent should die when linked child crashes"
    assert parent_died, "Parent should have been cancelled"


@pytest.mark.asyncio
async def test_normal_exit_no_propagation(runtime, process_tracker):
    """Test that normal exit doesn't propagate."""
    parent_completed = False
    
    async def parent():
        nonlocal parent_completed
        child = await runtime.spawn_link(child_proc)
        # Wait for child to exit normally
        await asyncio.sleep(0.2)
        parent_completed = True
    
    async def child_proc():
        await asyncio.sleep(0.05)
        # Normal return - should NOT kill parent
        return "normal completion"
    
    parent_pid = await process_tracker.spawn(parent)
    
    # Wait for parent to complete normally
    await wait_for(lambda: parent_completed, timeout=0.5)
    
    # Parent should complete normally, not be killed
    assert parent_completed, "Parent should complete normally"
    assert not runtime.is_alive(parent_pid), "Parent should be done (not killed, just completed)"


@pytest.mark.asyncio
async def test_trap_exits(runtime, process_tracker):
    """Test trap_exits converts exit signals to messages."""
    received_exit = False
    supervisor_alive = True
    
    async def supervisor():
        nonlocal received_exit, supervisor_alive
        
        # Spawn and link child
        child = await runtime.spawn_link(child_proc)
        
        # Should receive EXIT as message, not die
        try:
            msg = await runtime.receive(timeout=0.5)
            if isinstance(msg, tuple) and msg[0] == EXIT:
                received_exit = True
                # Continue running after receiving EXIT
                await asyncio.sleep(0.1)
                supervisor_alive = runtime.is_alive(runtime.self())
        except asyncio.TimeoutError:
            pass
    
    async def child_proc():
        await asyncio.sleep(0.05)
        raise RuntimeError("Child error")
    
    # Spawn supervisor with trap_exits=True
    sup_pid = await runtime.spawn(supervisor, trap_exits=True)
    
    # Wait for child to crash and supervisor to process it
    await asyncio.sleep(0.3)
    
    # Check results
    assert received_exit, "Supervisor should receive EXIT message"
    assert supervisor_alive, "Supervisor should stay alive with trap_exits"
    
    # Supervisor should still be running
    still_alive = runtime.is_alive(sup_pid)
    
    # Clean up if still running
    if still_alive:
        await runtime.exit(sup_pid, KILLED)
        await wait_for(lambda: not runtime.is_alive(sup_pid), timeout=0.5)


@pytest.mark.asyncio
async def test_unlink(runtime, process_tracker):
    """Test unlinking processes with BEAM semantics.
    
    Important:
    - unlink/1 only protects you *after* it’s called.
    - If the other process crashes before unlink/1, you still die.
    """

    proc_a_survived = False

    async def proc_a():
        nonlocal proc_a_survived
        await runtime.register("proc_a")

        # Wait until proc_b is fully alive and signals readiness
        msg = await runtime.receive(timeout=0.5)
        assert msg == ("ready", "proc_b")

        # Link and immediately unlink before proc_b has a chance to crash
        await runtime.link("proc_b")
        await runtime.unlink("proc_b")

        # Now proc_b’s crash should not affect proc_a
        await asyncio.sleep(0.3)
        proc_a_survived = True

    async def proc_b():
        await runtime.register("proc_b")
        # Tell proc_a that we're alive and ready to be linked
        await runtime.send("proc_a", ("ready", "proc_b"))
        await asyncio.sleep(0.1)
        raise RuntimeError("proc_b crash")

    # Spawn both processes
    pid_a = await process_tracker.spawn(proc_a)
    pid_b = await process_tracker.spawn(proc_b)

    # Wait for proc_b to crash
    await wait_for(lambda: not runtime.is_alive(pid_b), timeout=0.5)

    # Wait a bit more to ensure proc_a survives
    await asyncio.sleep(0.35)

    # proc_a should have survived and completed
    assert proc_a_survived, "proc_a should survive after unlinking"
    assert not runtime.is_alive(pid_a), "proc_a should have completed normally"


@pytest.mark.asyncio
async def test_circular_links(runtime, process_tracker):
    """Test circular linking behavior - all die if one crashes."""

    async def proc_a():
        await runtime.register("proc_a")
        # Wait for proc_b readiness
        msg = await runtime.receive(timeout=0.5)
        assert msg == ("ready", "proc_b")
        await runtime.link("proc_b")
        await asyncio.sleep(1.0)

    async def proc_b():
        await runtime.register("proc_b")
        # Tell proc_a we're ready, then wait for proc_c
        await runtime.send("proc_a", ("ready", "proc_b"))
        msg = await runtime.receive(timeout=0.5)
        assert msg == ("ready", "proc_c")
        await runtime.link("proc_c")
        await asyncio.sleep(1.0)

    async def proc_c():
        await runtime.register("proc_c")
        # Tell proc_b we're ready, then crash
        await runtime.send("proc_b", ("ready", "proc_c"))
        await asyncio.sleep(0.1)
        raise RuntimeError("proc_c crash")

    pid_a = await process_tracker.spawn(proc_a)
    pid_b = await process_tracker.spawn(proc_b)
    pid_c = await process_tracker.spawn(proc_c)

    # Verify all are initially alive
    await wait_for(lambda: runtime.is_alive(pid_a) and runtime.is_alive(pid_b) and runtime.is_alive(pid_c),
                   timeout=0.2)

    # Wait for crash propagation
    await wait_for(
        lambda: not runtime.is_alive(pid_a)
        and not runtime.is_alive(pid_b)
        and not runtime.is_alive(pid_c),
        timeout=1.0,
    )

    assert not runtime.is_alive(pid_a), "proc_a should die from circular link"
    assert not runtime.is_alive(pid_b), "proc_b should die from circular link"
    assert not runtime.is_alive(pid_c), "proc_c should die from crash"


@pytest.mark.asyncio
async def test_spawn_link(runtime, process_tracker):
    """Test spawn_link helper."""
    parent_died = False
    
    async def parent():
        nonlocal parent_died
        try:
            # spawn_link should establish link atomically
            child = await runtime.spawn_link(child_proc)
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            parent_died = True
            raise
    
    async def child_proc():
        await asyncio.sleep(0.05)
        raise RuntimeError("Child crash")
    
    parent_pid = await process_tracker.spawn(parent)
    
    # Parent should die when child crashes
    await wait_for(lambda: not runtime.is_alive(parent_pid), timeout=0.5)
    
    assert not runtime.is_alive(parent_pid), "Parent should die from spawn_link child crash"
    assert parent_died, "Parent should have been cancelled"


@pytest.mark.asyncio
async def test_killed_bypasses_trap_exits(runtime, process_tracker):
    """Test that KILLED reason bypasses trap_exits."""
    async def trapper():
        # Even with trap_exits, KILLED should terminate
        await asyncio.sleep(1.0)
    
    pid = await runtime.spawn(trapper, trap_exits=True)
    
    assert runtime.is_alive(pid)
    
    # KILLED should terminate even with trap_exits
    await runtime.exit(pid, KILLED)
    
    # Should die quickly
    await wait_for(lambda: not runtime.is_alive(pid), timeout=0.5)
    
    assert not runtime.is_alive(pid), "KILLED should bypass trap_exits"
