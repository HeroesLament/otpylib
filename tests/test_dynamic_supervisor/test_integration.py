# tests/test_dynamic_supervisor/test_integration.py
import pytest
import asyncio

from otpylib import process
from otpylib import dynamic_supervisor
from otpylib.dynamic_supervisor import (
    child_spec,
    options,
    DynamicSupervisorHandle,
    PERMANENT,
    TRANSIENT,
)

pytestmark = pytest.mark.asyncio


async def worker_pool_manager():
    """Example task that manages a worker pool."""
    await asyncio.sleep(0.1)


async def worker_task(worker_id: int):
    """Example worker task."""
    await asyncio.sleep(0.05)
    return f"worker-{worker_id}-done"


async def test_nested_supervisors(log_handler):
    """Test nested dynamic supervisors."""

    async def body():
        # Start parent supervisor
        parent_pid = await dynamic_supervisor.start(
            [],
            options(),
            "parent_supervisor",
        )
        parent_handle = DynamicSupervisorHandle(parent_pid)

        # Start child supervisor
        child_pid = await dynamic_supervisor.start(
            [],
            options(),
            "child_supervisor",
        )
        child_handle = DynamicSupervisorHandle(child_pid)

        # Add workers to the child supervisor
        for i in range(3):
            spec = child_spec(
                id=f"worker-{i}",
                func=worker_task,
                args=[i],
                restart=TRANSIENT,
            )
            ok, msg = await child_handle.start_child(spec)
            assert ok, msg

        # Let workers complete
        await asyncio.sleep(0.2)

        # Parent should be empty
        parent_children = await parent_handle.list_children()
        assert len(parent_children) == 0

        # Shutdown both supervisors
        await parent_handle.shutdown()
        await child_handle.shutdown()

    await process.spawn(body)


async def test_supervisor_with_mailbox_name(log_handler):
    """Test that dynamic supervisor can be accessed by name."""

    async def body():
        # Start dynamic supervisor with a well-known name
        sup_pid = await dynamic_supervisor.start(
            [],
            options(),
            "named-supervisor",
        )
        handle = DynamicSupervisorHandle(sup_pid)

        # Add first child
        spec1 = child_spec(
            id="test-worker",
            func=worker_task,
            args=[42],
            restart=TRANSIENT,
        )
        ok, msg = await dynamic_supervisor.start_child("named-supervisor", spec1)
        assert ok, msg

        # Add second child
        spec2 = child_spec(
            id="test-worker-2",
            func=worker_task,
            args=[43],
            restart=TRANSIENT,
        )
        ok, msg = await dynamic_supervisor.start_child("named-supervisor", spec2)
        assert ok, msg

        # Let them start and potentially complete
        await asyncio.sleep(0.2)

        # Query supervisor
        children = await handle.list_children()
        assert isinstance(children, list)

        # Shutdown gracefully
        await handle.shutdown()

    await process.spawn(body)
