import pytest
from otpylib import mailbox
from otpylib import process
from otpylib.dynamic_supervisor import (
    start,
    child_spec,
    options,
    DynamicSupervisorHandle,
    PERMANENT,
    TRANSIENT,
)
from tests.test_dynamic_supervisor.helpers import (
    sample_task_long_running,
    sample_task_with_completion,
)

pytestmark = pytest.mark.asyncio


async def test_start_multiple_children(test_data, log_handler):
    async def body():
        mailbox.init_mailbox_registry()
        sup_pid = await start([], options(), name="test-multiple-children")
        handle = DynamicSupervisorHandle(sup_pid)

        for i in range(3):
            spec = child_spec(
                id=f"worker-{i}",
                func=sample_task_with_completion,
                args=[test_data],
                restart=TRANSIENT,
            )
            ok, msg = await handle.start_child(spec)
            assert ok, msg

        assert test_data.exec_count == 3
        await handle.shutdown()

    await process.spawn(body, mailbox=False)  # run inside process context


async def test_terminate_specific_child(test_data, log_handler):
    async def body():
        mailbox.init_mailbox_registry()
        sup_pid = await start([], options(), name="test-terminate-child")
        handle = DynamicSupervisorHandle(sup_pid)

        spec = child_spec(
            id="long-runner",
            func=sample_task_long_running,
            args=[test_data],
            restart=PERMANENT,
        )
        ok, msg = await handle.start_child(spec)
        assert ok, msg

        assert test_data.exec_count == 1
        assert "long-runner" in await handle.list_children()

        ok, msg = await handle.terminate_child("long-runner")
        assert ok, msg

        children = await handle.list_children()
        assert "long-runner" not in children
        await handle.shutdown()

    await process.spawn(body, mailbox=False)


async def test_replace_child_with_same_id(test_data, log_handler):
    async def body():
        mailbox.init_mailbox_registry()
        sup_pid = await start([], options(), name="test-replace-child")
        handle = DynamicSupervisorHandle(sup_pid)

        spec1 = child_spec(
            id="worker",
            func=sample_task_long_running,
            args=[test_data],
            restart=PERMANENT,
        )
        ok, msg = await handle.start_child(spec1)
        assert ok, msg
        assert test_data.exec_count == 1
        assert "worker" in await handle.list_children()

        spec2 = child_spec(
            id="worker",
            func=sample_task_with_completion,
            args=[test_data],
            restart=TRANSIENT,
        )
        ok, msg = await handle.start_child(spec2)
        assert ok, msg
        assert test_data.exec_count == 2

        children = await handle.list_children()
        assert "worker" not in children or len(children) == 0
        await handle.shutdown()

    await process.spawn(body, mailbox=False)
