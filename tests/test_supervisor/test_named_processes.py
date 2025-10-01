# tests/test_supervisor/test_named_processes.py
"""
Tests for supervisors with named children and supervisors.
"""

import asyncio
import pytest
from otpylib import process, supervisor
from otpylib.supervisor.atoms import PERMANENT, ONE_FOR_ONE, SHUTDOWN

from .helpers import sample_task, sample_task_error


async def run_in_process(coro_func, name="test_proc"):
    """Run the given coroutine inside a spawned process and wait until it exits."""
    pid = await process.spawn(coro_func, name=name, mailbox=True)
    while process.is_alive(pid):
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_named_children(test_data):
    async def tester():
        children = [
            supervisor.child_spec(
                id="child1",
                func=sample_task,
                args=[test_data],
                restart=PERMANENT,
                name="named_child1",
            ),
            supervisor.child_spec(
                id="child2",
                func=sample_task,
                args=[test_data],
                restart=PERMANENT,
                name="named_child2",
            ),
        ]

        sup_pid = await supervisor.start(children, supervisor.options(strategy=ONE_FOR_ONE))
        await asyncio.sleep(0.1)

        # Both children should be registered by name
        assert process.whereis("named_child1") is not None
        assert process.whereis("named_child2") is not None

        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester, name="test_named_children")


@pytest.mark.asyncio
async def test_named_child_restart(test_data):
    async def tester():
        async def flappy():
            raise RuntimeError("boom")

        children = [
            supervisor.child_spec(
                id="flappy",
                func=flappy,
                restart=PERMANENT,
                name="flappy_child",
            )
        ]

        sup_pid = await supervisor.start(children, supervisor.options(strategy=ONE_FOR_ONE))
        await asyncio.sleep(0.2)

        # The child should have restarted and been re-registered
        assert process.whereis("flappy_child") is not None

        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester, name="test_named_child_restart")


@pytest.mark.asyncio
async def test_named_supervisor_hierarchy(test_data):
    async def tester():
        # Inner supervisor spec
        inner_children = [
            supervisor.child_spec(
                id="worker",
                func=sample_task,
                args=[test_data],
                restart=PERMANENT,
                name="inner_worker",
            )
        ]

        inner_spec = supervisor.child_spec(
            id="inner_sup",
            func=lambda: supervisor.start(inner_children),
            restart=PERMANENT,
            name="inner_supervisor",
        )

        # Outer supervisor runs inner as child
        sup_pid = await supervisor.start([inner_spec], supervisor.options(strategy=ONE_FOR_ONE))
        await asyncio.sleep(0.2)

        # Verify inner supervisor and child exist
        assert process.whereis("inner_supervisor") is not None
        assert process.whereis("inner_worker") is not None

        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester, name="test_named_supervisor_hierarchy")


@pytest.mark.asyncio
async def test_name_cleanup_on_child_exit(test_data):
    async def tester():
        children = [
            supervisor.child_spec(
                id="crasher",
                func=sample_task_error,
                args=[test_data],
                restart=PERMANENT,
                name="crash_child",
            )
        ]

        sup_pid = await supervisor.start(children, supervisor.options(strategy=ONE_FOR_ONE))
        await asyncio.sleep(0.1)

        # Name should be registered initially
        assert process.whereis("crash_child") is not None

        # After crash/restart cycle, old name should be cleaned
        await asyncio.sleep(0.3)
        assert process.whereis("crash_child") is not None

        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester, name="test_name_cleanup_on_child_exit")


@pytest.mark.asyncio
async def test_name_reuse_after_restart(test_data):
    async def tester():
        async def flappy():
            raise RuntimeError("crash and burn")

        children = [
            supervisor.child_spec(
                id="flappy",
                func=flappy,
                restart=PERMANENT,
                name="reused_child",
            )
        ]

        sup_pid = await supervisor.start(children, supervisor.options(strategy=ONE_FOR_ONE))
        await asyncio.sleep(0.5)

        # After a few restarts, the same name should always be re-usable
        pid1 = process.whereis("reused_child")
        await asyncio.sleep(0.2)
        pid2 = process.whereis("reused_child")

        assert pid1 is None or pid2 is not None

        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester, name="test_name_reuse_after_restart")


@pytest.mark.asyncio
async def test_supervisor_name_conflict(test_data):
    async def tester():
        children = [
            supervisor.child_spec(
                id="child",
                func=sample_task,
                args=[test_data],
                restart=PERMANENT,
                name="conflict_child",
            )
        ]

        # Start supervisor with conflicting name
        sup_pid1 = await supervisor.start(children, name="named_sup")
        with pytest.raises(RuntimeError):
            await supervisor.start(children, name="named_sup")

        await process.exit(sup_pid1, SHUTDOWN)

    await run_in_process(tester, name="test_supervisor_name_conflict")
