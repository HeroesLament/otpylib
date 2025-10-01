# tests/test_supervisor/test_restart_strategies.py
"""
Test supervisor restart strategies (one_for_one, one_for_all, rest_for_one).
"""

import asyncio
import pytest
from otpylib import process
from otpylib.supervisor import start, child_spec, options
from otpylib.supervisor.atoms import (
    PERMANENT, ONE_FOR_ONE, ONE_FOR_ALL, REST_FOR_ONE, SHUTDOWN
)
from .helpers import run_in_process


@pytest.mark.asyncio
async def test_one_for_one_restart(test_data):
    results = {}

    async def flappy(label):
        if test_data.exec_count == 0:
            raise RuntimeError(f"{label} crash")
        test_data.exec_count += 1
        await asyncio.sleep(0.1)

    async def tester():
        specs = [child_spec(id="f", func=flappy, args=["f"], restart=PERMANENT)]
        opts = options(strategy=ONE_FOR_ONE, max_restarts=5, max_seconds=5)
        sup_pid = await start(specs, opts)
        results["sup_pid"] = sup_pid

        await asyncio.sleep(0.5)
        status = await process.send(sup_pid, ("get_status", "f", process.self()))
        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester)
    assert "sup_pid" in results


@pytest.mark.asyncio
async def test_one_for_all_restart(test_data):
    results = {}

    async def flappy(label):
        if test_data.exec_count == 0 and label == "f1":
            raise RuntimeError("f1 crash")
        test_data.exec_count += 1
        await asyncio.sleep(0.1)

    async def tester():
        specs = [
            child_spec(id="f1", func=flappy, args=["f1"], restart=PERMANENT),
            child_spec(id="f2", func=flappy, args=["f2"], restart=PERMANENT),
        ]
        opts = options(strategy=ONE_FOR_ALL, max_restarts=5, max_seconds=5)
        sup_pid = await start(specs, opts)
        results["sup_pid"] = sup_pid

        await asyncio.sleep(0.5)
        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester)
    assert "sup_pid" in results


@pytest.mark.asyncio
async def test_rest_for_one_restart(test_data):
    results = {}

    async def flappy(label):
        if test_data.exec_count == 0 and label == "mid":
            raise RuntimeError("mid crash")
        test_data.exec_count += 1
        await asyncio.sleep(0.1)

    async def tester():
        specs = [
            child_spec(id="first", func=flappy, args=["first"], restart=PERMANENT),
            child_spec(id="mid", func=flappy, args=["mid"], restart=PERMANENT),
            child_spec(id="last", func=flappy, args=["last"], restart=PERMANENT),
        ]
        opts = options(strategy=REST_FOR_ONE, max_restarts=5, max_seconds=5)
        sup_pid = await start(specs, opts)
        results["sup_pid"] = sup_pid

        await asyncio.sleep(0.5)
        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester)
    assert "sup_pid" in results


@pytest.mark.asyncio
async def test_permanent_children_always_restart(test_data):
    results = {"restarts": 0}

    async def flappy():
        results["restarts"] += 1
        if results["restarts"] < 2:
            raise RuntimeError("first crash")
        await asyncio.sleep(0.1)

    async def tester():
        specs = [child_spec(id="p", func=flappy, restart=PERMANENT)]
        sup_pid = await start(specs)
        results["sup_pid"] = sup_pid

        await asyncio.sleep(0.5)
        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester)
    assert results["restarts"] >= 2
    assert "sup_pid" in results


@pytest.mark.asyncio
async def test_mixed_crash_patterns(test_data):
    results = {"events": []}

    async def worker(label, crash=False):
        results["events"].append(f"{label}_start")
        if crash:
            raise RuntimeError(f"{label} crash")
        await asyncio.sleep(0.1)

    async def tester():
        specs = [
            child_spec(id="a", func=worker, args=["a", True], restart=PERMANENT),
            child_spec(id="b", func=worker, args=["b", False], restart=PERMANENT),
        ]
        opts = options(strategy=ONE_FOR_ONE, max_restarts=5, max_seconds=5)
        sup_pid = await start(specs, opts)
        results["sup_pid"] = sup_pid

        await asyncio.sleep(0.5)
        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester)
    assert "a_start" in results["events"]
    assert "b_start" in results["events"]
    assert "sup_pid" in results
