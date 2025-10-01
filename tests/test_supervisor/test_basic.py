"""
Test basic supervisor operations and lifecycle.
"""

import asyncio
import pytest
from otpylib import process
from otpylib.supervisor import start, start_link, child_spec, options
from otpylib.supervisor.atoms import (
    ONE_FOR_ONE, GET_CHILD_STATUS, LIST_CHILDREN, SHUTDOWN
)
from .helpers import sample_task, sample_task_long_running, run_in_process


@pytest.mark.asyncio
async def test_supervisor_start(test_data):
    """Test starting a supervisor with children."""
    results = {}

    async def tester():
        children = [
            child_spec(id="worker1", func=sample_task_long_running, args=[test_data]),
            child_spec(id="worker2", func=sample_task_long_running, args=[test_data]),
        ]
        sup_pid = await start(children)
        results["sup_pid"] = sup_pid

        assert process.is_alive(sup_pid)
        await asyncio.sleep(0.1)
        assert test_data.exec_count > 0

        await process.exit(sup_pid, SHUTDOWN)
        await asyncio.sleep(0.1)
        assert not process.is_alive(sup_pid)

    await run_in_process(tester)
    assert "sup_pid" in results


@pytest.mark.asyncio
async def test_supervisor_start_link(test_data):
    """Test start_link creates linked supervisor."""
    async def parent_process():
        children = [
            child_spec(id="child", func=sample_task_long_running, args=[test_data])
        ]
        sup_pid = await start_link(children)
        await asyncio.sleep(1.0)  # if supervisor dies, parent dies too
        return sup_pid

    parent_pid = await process.spawn(parent_process, name="parent_proc", mailbox=True)
    await asyncio.sleep(0.1)

    assert process.is_alive(parent_pid)

    await process.exit(parent_pid, SHUTDOWN)
    await asyncio.sleep(0.1)
    assert not process.is_alive(parent_pid)


@pytest.mark.asyncio
async def test_get_child_status(test_data):
    """Test getting child status via supervisor messages."""
    received_status = {}

    async def tester():
        children = [
            child_spec(
                id="worker",
                func=sample_task_long_running,
                args=[test_data],
                name="test_worker",
            )
        ]
        sup_pid = await start(children)
        await asyncio.sleep(0.1)

        await process.send(sup_pid, (GET_CHILD_STATUS, "worker", process.self()))
        received_status["worker"] = await process.receive(timeout=1.0)

        await process.send(sup_pid, (GET_CHILD_STATUS, "unknown", process.self()))
        received_status["unknown"] = await process.receive(timeout=1.0)

        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester)

    assert received_status["worker"] is not None
    assert "pid" in received_status["worker"]
    assert received_status["worker"]["alive"] is True
    assert received_status["worker"]["restart_count"] == 0
    assert received_status["unknown"] is None


@pytest.mark.asyncio
async def test_list_children(test_data):
    """Test listing all children."""
    received_list = None

    async def tester():
        nonlocal received_list
        children = [
            child_spec(id="worker1", func=sample_task, args=[test_data]),
            child_spec(id="worker2", func=sample_task, args=[test_data]),
            child_spec(id="worker3", func=sample_task, args=[test_data]),
        ]
        sup_pid = await start(children)
        await asyncio.sleep(0.1)

        await process.send(sup_pid, (LIST_CHILDREN, process.self()))
        received_list = await process.receive(timeout=1.0)

        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester)

    assert received_list is not None
    assert set(received_list) == {"worker1", "worker2", "worker3"}


@pytest.mark.asyncio
async def test_children_start_in_order(test_data):
    """Test that children start in specification order."""
    results = {}

    async def tester():
        start_order = []

        async def ordered_task(task_id):
            start_order.append(task_id)
            await asyncio.sleep(1.0)

        children = [
            child_spec(id="first", func=ordered_task, args=["first"]),
            child_spec(id="second", func=ordered_task, args=["second"]),
            child_spec(id="third", func=ordered_task, args=["third"]),
        ]
        sup_pid = await start(children)
        await asyncio.sleep(0.1)

        results["order"] = start_order.copy()
        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester)

    assert results["order"] == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_supervisor_with_options(test_data):
    """Test supervisor with custom options."""
    results = {}

    async def tester():
        children = [
            child_spec(id="worker", func=sample_task_long_running, args=[test_data])
        ]
        opts = options(max_restarts=5, max_seconds=10, strategy=ONE_FOR_ONE)
        sup_pid = await start(children, opts)
        results["sup_pid"] = sup_pid

        assert process.is_alive(sup_pid)
        await asyncio.sleep(0.1)
        assert test_data.exec_count > 0

        await process.exit(sup_pid, SHUTDOWN)

    await run_in_process(tester)

    assert "sup_pid" in results
