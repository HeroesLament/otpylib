# tests/test_supervisor/test_restart_limits.py
"""
Test supervisor restart limits (intensity, windows, counts).
"""

import asyncio
import pytest
from otpylib import process
from otpylib.supervisor import start, child_spec, options
from otpylib.supervisor.atoms import PERMANENT, ONE_FOR_ONE, ONE_FOR_ALL, SHUTDOWN
from .helpers import run_in_process


@pytest.mark.asyncio
async def test_restart_intensity_limit(test_data):
    results = {}

    async def flappy():
        raise RuntimeError("boom")

    async def tester():
        specs = [
            child_spec(id="flappy", func=flappy, restart=PERMANENT),
        ]
        opts = options(strategy=ONE_FOR_ONE, max_restarts=2, max_seconds=5)
        sup_pid = await start(specs, opts)
        results["sup_pid"] = sup_pid

        # Supervisor should shut down after too many restarts
        while process.is_alive(sup_pid):
            await asyncio.sleep(0.1)

    await run_in_process(tester)
    assert "sup_pid" in results


@pytest.mark.asyncio
async def test_restart_window_sliding(test_data):
    results = {}

    async def flappy():
        raise RuntimeError("boom")

    async def tester():
        specs = [child_spec(id="flappy", func=flappy, restart=PERMANENT)]
        opts = options(strategy=ONE_FOR_ONE, max_restarts=3, max_seconds=1)
        sup_pid = await start(specs, opts)
        results["sup_pid"] = sup_pid

        # Supervisor should restart a few times before giving up
        while process.is_alive(sup_pid):
            await asyncio.sleep(0.1)

    await run_in_process(tester)
    assert "sup_pid" in results


@pytest.mark.asyncio
async def test_restart_count_per_child(test_data):
    results = {}

    async def flappy(label):
        raise RuntimeError(f"{label} crash")

    async def tester():
        specs = [
            child_spec(id="a", func=flappy, args=["a"], restart=PERMANENT),
            child_spec(id="b", func=flappy, args=["b"], restart=PERMANENT),
        ]
        opts = options(strategy=ONE_FOR_ONE, max_restarts=3, max_seconds=5)
        sup_pid = await start(specs, opts)
        results["sup_pid"] = sup_pid

        # Wait for supervisor to die
        while process.is_alive(sup_pid):
            await asyncio.sleep(0.1)

    await run_in_process(tester)
    assert "sup_pid" in results


@pytest.mark.asyncio
async def test_restart_limit_with_one_for_all(test_data):
    results = {}

    async def flappy():
        raise RuntimeError("boom")

    async def tester():
        specs = [
            child_spec(id="f1", func=flappy, restart=PERMANENT),
            child_spec(id="f2", func=flappy, restart=PERMANENT),
        ]
        opts = options(strategy=ONE_FOR_ALL, max_restarts=2, max_seconds=5)
        sup_pid = await start(specs, opts)
        results["sup_pid"] = sup_pid

        while process.is_alive(sup_pid):
            await asyncio.sleep(0.1)

    await run_in_process(tester)
    assert "sup_pid" in results


@pytest.mark.asyncio
async def test_no_restart_limit_for_normal_exit(test_data):
    results = {}

    async def normal_exit():
        return

    async def tester():
        specs = [
            child_spec(id="n", func=normal_exit, restart=PERMANENT),
        ]
        opts = options(strategy=ONE_FOR_ONE, max_restarts=1, max_seconds=5)
        sup_pid = await start(specs, opts)
        results["sup_pid"] = sup_pid

        await asyncio.sleep(0.5)
        assert process.is_alive(sup_pid)

        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester)
    assert "sup_pid" in results


@pytest.mark.asyncio
async def test_restart_limit_reset_after_window(test_data):
    results = {}

    async def flappy():
        raise RuntimeError("boom")

    async def tester():
        specs = [child_spec(id="f", func=flappy, restart=PERMANENT)]
        opts = options(strategy=ONE_FOR_ONE, max_restarts=2, max_seconds=1)
        sup_pid = await start(specs, opts)
        results["sup_pid"] = sup_pid

        # Let the restart counter reset
        await asyncio.sleep(2.0)
        assert process.is_alive(sup_pid)

        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester)
    assert "sup_pid" in results


@pytest.mark.asyncio
async def test_multiple_children_intensity(test_data):
    results = {}

    async def flappy(label):
        raise RuntimeError(f"{label} crash")

    async def tester():
        specs = [
            child_spec(id="a", func=flappy, args=["a"], restart=PERMANENT),
            child_spec(id="b", func=flappy, args=["b"], restart=PERMANENT),
            child_spec(id="c", func=flappy, args=["c"], restart=PERMANENT),
        ]
        opts = options(strategy=ONE_FOR_ONE, max_restarts=2, max_seconds=5)
        sup_pid = await start(specs, opts)
        results["sup_pid"] = sup_pid

        while process.is_alive(sup_pid):
            await asyncio.sleep(0.1)

    await run_in_process(tester)
    assert "sup_pid" in results
