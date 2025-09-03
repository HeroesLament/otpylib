import pytest
import anyio

from otpylib import supervisor, dynamic_supervisor
from otpylib.types import StartupSync

from tests.test_dynamic_supervisor.helpers import sample_task_long_running, sample_task_with_completion


pytestmark = pytest.mark.anyio


async def test_start_multiple_children(test_data, mailbox_env):
    """Test starting multiple children dynamically."""
    async with anyio.create_task_group() as tg:
        # Start dynamic supervisor
        opts = supervisor.options()
        
        sync = StartupSync()
        tg.start_soon(dynamic_supervisor.start, opts, 'test-multiple-children', sync)
        mid = await sync.wait()

        # Add multiple children
        for i in range(3):
            child_spec = supervisor.child_spec(
                id=f"worker-{i}",
                task=sample_task_with_completion,
                args=[test_data],
                restart=supervisor.restart_strategy.TEMPORARY,
            )
            await dynamic_supervisor.start_child(mid, child_spec)

        # Wait for all to complete
        await anyio.sleep(0.2)
        
        # Cancel everything
        tg.cancel_scope.cancel()

    assert test_data.exec_count == 3


async def test_terminate_specific_child(test_data, mailbox_env):
    """Test terminating a specific child."""
    async with anyio.create_task_group() as tg:
        # Start dynamic supervisor
        opts = supervisor.options()
        
        sync = StartupSync()
        tg.start_soon(dynamic_supervisor.start, opts, 'test-terminate-child', sync)
        mid = await sync.wait()

        # Add long-running child
        child_spec = supervisor.child_spec(
            id="long-runner",
            task=sample_task_long_running,
            args=[test_data],
            restart=supervisor.restart_strategy.TEMPORARY,
        )
        await dynamic_supervisor.start_child(mid, child_spec)
        
        # Wait for it to start
        await anyio.sleep(0.1)
        assert test_data.exec_count == 1
        
        # Terminate the child
        await dynamic_supervisor.terminate_child(mid, "long-runner")
        
        # Wait a bit and verify it doesn't restart (TEMPORARY strategy)
        await anyio.sleep(0.2)
        assert test_data.exec_count == 1  # Should still be 1
        
        # Cancel everything
        tg.cancel_scope.cancel()


async def test_replace_child_with_same_id(test_data, mailbox_env):
    """Test that adding a child with existing ID replaces the old one."""
    async with anyio.create_task_group() as tg:
        # Start dynamic supervisor
        opts = supervisor.options()
        
        sync = StartupSync()
        tg.start_soon(dynamic_supervisor.start, opts, 'test-replace-child', sync)
        mid = await sync.wait()

        # Add first child
        child_spec1 = supervisor.child_spec(
            id="worker",
            task=sample_task_long_running,
            args=[test_data],
            restart=supervisor.restart_strategy.TEMPORARY,
        )
        await dynamic_supervisor.start_child(mid, child_spec1)
        
        # Wait for it to start
        await anyio.sleep(0.1)
        assert test_data.exec_count == 1
        
        # Add second child with same ID (should cancel first)
        child_spec2 = supervisor.child_spec(
            id="worker",  # Same ID
            task=sample_task_with_completion,
            args=[test_data],
            restart=supervisor.restart_strategy.TEMPORARY,
        )
        await dynamic_supervisor.start_child(mid, child_spec2)
        
        # Wait for new child to run
        await anyio.sleep(0.1)
        assert test_data.exec_count == 2  # Both should have started
        
        # Cancel everything
        tg.cancel_scope.cancel()