# tests/test_supervisor/test_restart.py
"""
Tests for supervisor restart behavior with ONE_FOR_ALL strategy.
"""

import asyncio
import pytest
from otpylib import process, supervisor
from otpylib.supervisor.atoms import PERMANENT, ONE_FOR_ALL, SHUTDOWN


async def run_in_process(coro_func, name="test_proc"):
    """Run a coroutine inside a spawned process and wait until it exits."""
    pid = await process.spawn(coro_func, name=name, mailbox=True)
    while process.is_alive(pid):
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_one_for_all_restart():
    """Verify ONE_FOR_ALL strategy restarts all children when one crashes."""

    async def flappy_child(label: str):
        raise RuntimeError(f"{label} crashed!")

    async def stable_child(label: str):
        while True:
            await asyncio.sleep(0.1)

    async def tester():
        specs = [
            supervisor.child_spec(
                id="flappy",
                func=flappy_child,
                args=["flappy"],
                restart=PERMANENT,
                name="flappy_service",
            ),
            supervisor.child_spec(
                id="stable",
                func=stable_child,
                args=["stable"],
                restart=PERMANENT,
                name="stable_service",
            ),
        ]

        sup_pid = await supervisor.start(
            specs,
            supervisor.options(strategy=ONE_FOR_ALL, max_restarts=3, max_seconds=5),
            name="test_sup",
        )

        # Give time for crash/restart cycle
        await asyncio.sleep(0.5)

        # After restart, both children should be alive again
        flappy_pid = process.whereis("flappy_service")
        stable_pid = process.whereis("stable_service")
        assert flappy_pid is not None
        assert stable_pid is not None

        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester, name="test_one_for_all_restart")
