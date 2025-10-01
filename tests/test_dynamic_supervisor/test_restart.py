# tests/test_dynamic_supervisor/test_restart.py
import pytest
import asyncio

from otpylib import process, dynamic_supervisor
from otpylib.dynamic_supervisor import (
    child_spec,
    options,
    DynamicSupervisorHandle,
    PERMANENT,
    TRANSIENT,
)
from otpylib.types import OneForOne, OneForAll
from .helpers import (
    sample_task_error,
    sample_task_long_running,
    sample_task,
)
from .conftest import DataHelper

pytestmark = pytest.mark.asyncio


def _find_runtime_error(exc_group):
    """Recursively find RuntimeError in nested ExceptionGroups."""
    for exc in exc_group.exceptions:
        if isinstance(exc, RuntimeError) and "Dynamic supervisor shutting down" in str(exc):
            return True
        elif isinstance(exc, ExceptionGroup):
            if _find_runtime_error(exc):
                return True
    return False


@pytest.mark.parametrize("max_restarts", [1, 3, 5])
async def test_automatic_restart_permanent(max_restarts, test_data, log_handler):
    async def body():
        with pytest.raises(ExceptionGroup) as exc_info:
            children = [
                child_spec(
                    id="persistent_service",
                    func=sample_task_error,
                    args=[test_data],
                    restart=PERMANENT,
                )
            ]
            opts = options(max_restarts=max_restarts, max_seconds=5)
            await dynamic_supervisor.start(children, opts)
            await asyncio.sleep(0.5)

        assert _find_runtime_error(exc_info.value)
        assert test_data.exec_count >= (max_restarts + 1)
        assert test_data.error_count >= (max_restarts + 1)

    await process.spawn(body)


@pytest.mark.parametrize("strategy", [OneForOne(), OneForAll()])
@pytest.mark.parametrize("max_restarts", [1, 3, 5])
async def test_automatic_restart_on_crash(strategy, max_restarts, test_data, log_handler):
    async def body():
        with pytest.raises(ExceptionGroup) as exc_info:
            children = [
                child_spec(
                    id="failing_service",
                    func=sample_task_error,
                    args=[test_data],
                    restart=PERMANENT,
                )
            ]
            opts = options(
                max_restarts=max_restarts,
                max_seconds=5,
                strategy=strategy,
            )
            await dynamic_supervisor.start(children, opts)
            await asyncio.sleep(0.5)

        assert _find_runtime_error(exc_info.value)
        assert test_data.exec_count >= (max_restarts + 1)
        assert test_data.error_count >= (max_restarts + 1)

    await process.spawn(body)


@pytest.mark.parametrize("strategy", [OneForOne(), OneForAll()])
async def test_no_restart_for_normal_exit(strategy, test_data, log_handler):
    async def body():
        children = [
            child_spec(
                id="transient_service",
                func=sample_task,
                args=[test_data],
                restart=TRANSIENT,
            )
        ]
        opts = options(max_restarts=3, max_seconds=5, strategy=strategy)
        handle = await dynamic_supervisor.start(children, opts)
        await asyncio.sleep(0.2)
        await handle.shutdown()

        assert test_data.exec_count >= 1

    await process.spawn(body)


async def test_start_multiple_children(test_data, log_handler):
    async def body():
        handle = await dynamic_supervisor.start([], options(), "test_supervisor")

        child1_spec = child_spec(
            id="child1",
            func=sample_task_long_running,
            args=[test_data],
            restart=PERMANENT,
        )
        child2_spec = child_spec(
            id="child2",
            func=sample_task_long_running,
            args=[test_data],
            restart=PERMANENT,
        )

        ok, msg = await dynamic_supervisor.start_child("test_supervisor", child1_spec)
        assert ok, msg
        ok, msg = await dynamic_supervisor.start_child("test_supervisor", child2_spec)
        assert ok, msg
        await asyncio.sleep(0.1)

        children = await handle.list_children()
        assert "child1" in children and "child2" in children
        assert len(children) == 2

        dynamic_children = await handle.list_dynamic_children()
        assert "child1" in dynamic_children and "child2" in dynamic_children

        await handle.shutdown()

    await process.spawn(body)


async def test_terminate_specific_child(test_data, log_handler):
    async def body():
        handle = await dynamic_supervisor.start([], options(), "test_supervisor")

        spec = child_spec(
            id="target_child",
            func=sample_task_long_running,
            args=[test_data],
            restart=PERMANENT,
        )
        ok, msg = await dynamic_supervisor.start_child("test_supervisor", spec)
        assert ok, msg
        await asyncio.sleep(0.1)

        children = await handle.list_children()
        assert "target_child" in children

        ok, msg = await dynamic_supervisor.terminate_child("test_supervisor", "target_child")
        assert ok, msg
        await asyncio.sleep(0.1)

        children = await handle.list_children()
        assert "target_child" not in children

        await handle.shutdown()

    await process.spawn(body)


async def test_replace_child_with_same_id(test_data, log_handler):
    async def body():
        test_data1 = DataHelper()
        test_data2 = DataHelper()

        handle = await dynamic_supervisor.start([], options(), "test_supervisor")

        spec1 = child_spec(
            id="replaceable_child",
            func=sample_task_long_running,
            args=[test_data1],
            restart=PERMANENT,
        )
        ok, msg = await dynamic_supervisor.start_child("test_supervisor", spec1)
        assert ok, msg
        await asyncio.sleep(0.1)

        children = await handle.list_children()
        assert "replaceable_child" in children
        assert test_data1.exec_count == 1

        spec2 = child_spec(
            id="replaceable_child",
            func=sample_task_long_running,
            args=[test_data2],
            restart=PERMANENT,
        )
        ok, msg = await dynamic_supervisor.start_child("test_supervisor", spec2)
        assert ok, msg
        await asyncio.sleep(0.1)

        children = await handle.list_children()
        assert children.count("replaceable_child") == 1
        assert test_data2.exec_count == 1

        await handle.shutdown()

    await process.spawn(body)


async def test_supervisor_with_mailbox_name(test_data, log_handler):
    async def body():
        handle = await dynamic_supervisor.start([], options(), "named_supervisor")

        spec = child_spec(
            id="mailbox_child",
            func=sample_task_long_running,
            args=[test_data],
            restart=PERMANENT,
        )
        ok, msg = await dynamic_supervisor.start_child("named_supervisor", spec)
        assert ok, msg
        await asyncio.sleep(0.1)

        children = await handle.list_children()
        assert "mailbox_child" in children

        await handle.shutdown()

    await process.spawn(body)


async def test_nested_supervisors(test_data, log_handler):
    async def body():
        parent_handle = await dynamic_supervisor.start([], options(), "parent_supervisor")
        child_handle = await dynamic_supervisor.start([], options(), "child_supervisor")

        spec = child_spec(
            id="nested_task",
            func=sample_task_long_running,
            args=[test_data],
            restart=PERMANENT,
        )
        ok, msg = await dynamic_supervisor.start_child("child_supervisor", spec)
        assert ok, msg
        await asyncio.sleep(0.1)

        children = await child_handle.list_children()
        assert "nested_task" in children

        parent_children = await parent_handle.list_children()
        assert len(parent_children) == 0

        await parent_handle.shutdown()
        await child_handle.shutdown()

    await process.spawn(body)
