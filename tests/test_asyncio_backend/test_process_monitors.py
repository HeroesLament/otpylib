# tests/test_asyncio_backend/test_process_monitors.py

import pytest
import asyncio
from otpylib import process
from otpylib.runtime import set_runtime
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime.atoms import DOWN, PROCESS, NORMAL



@pytest.mark.asyncio
async def test_spawn_monitor_normal():
    runtime = AsyncIOBackend()
    set_runtime(runtime)
    await runtime.initialize()

    async def child():
        await asyncio.sleep(0.01)
        return  # normal exit

    async def parent():
        child_pid, ref = await process.spawn_monitor(child)
        # Expect a DOWN with reason=normal
        msg = await process.receive(timeout=0.5)
        assert msg[0] == DOWN, f"Expected DOWN, got {msg}"
        assert msg[1] == ref
        assert msg[2] == process.atom("process")
        assert msg[3] == child_pid
        assert msg[4] == NORMAL, f"Expected normal, got {msg[4]}"

    await runtime.spawn(parent)
    await asyncio.sleep(0.1)
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_spawn_monitor_crash():
    """
    Verify that spawn_monitor delivers a DOWN message when the child crashes,
    with proper 5-arity tuple shape: (DOWN, ref, 'process', child_pid, reason).
    """

    async def child():
        raise RuntimeError("child crashed!")

    async def parent():
        # Spawn and monitor the crashing child
        child_pid, ref = await process.spawn_monitor(child)
        msg = await process.receive(timeout=0.5)

        # Verify shape of DOWN message
        assert isinstance(msg, tuple)
        assert len(msg) == 5

        tag, mon_ref, kind, pid, reason = msg
        assert tag == DOWN
        assert mon_ref == ref
        assert kind == PROCESS
        assert pid == child_pid
        assert isinstance(reason, RuntimeError)
        assert "child crashed!" in str(reason)

    # Setup runtime
    runtime = AsyncIOBackend()
    set_runtime(runtime)
    await runtime.initialize()

    await process.spawn(parent)

    # Let processes run
    await asyncio.sleep(0.1)

    # Teardown
    await runtime.shutdown()
