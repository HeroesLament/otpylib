import pytest
import anyio
from otpylib import dynamic_supervisor, mailbox
from otpylib.types import Permanent, Transient

from tests.test_dynamic_supervisor.helpers import sample_task_long_running, sample_task_with_completion


pytestmark = pytest.mark.anyio


async def test_start_multiple_children(test_data, log_handler):
    """Test starting multiple children dynamically."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    async with anyio.create_task_group() as tg:
        # Start dynamic supervisor using proper task_status pattern
        opts = dynamic_supervisor.options()
        
        handle = await tg.start(
            dynamic_supervisor.start, 
            [],  # Start empty
            opts, 
            'test-multiple-children'
        )

        # Add multiple children
        for i in range(3):
            child_spec = dynamic_supervisor.child_spec(
                id=f"worker-{i}",
                task=sample_task_with_completion,
                args=[test_data],
                restart=Transient(),  # Use proper restart strategy
                health_check_enabled=False,
            )
            await dynamic_supervisor.start_child('test-multiple-children', child_spec)

        # Wait for all to complete
        await anyio.sleep(0.2)
        
        # Shutdown gracefully
        await handle.shutdown()

    assert test_data.exec_count == 3


async def test_terminate_specific_child(test_data, log_handler):
    """Test terminating a specific child."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    async with anyio.create_task_group() as tg:
        # Start dynamic supervisor using proper task_status pattern
        opts = dynamic_supervisor.options()
        
        handle = await tg.start(
            dynamic_supervisor.start, 
            [],  # Start empty
            opts, 
            'test-terminate-child'
        )

        # Add long-running child
        child_spec = dynamic_supervisor.child_spec(
            id="long-runner",
            task=sample_task_long_running,
            args=[test_data],
            restart=Permanent(),  # Use Permanent so we can test termination
            health_check_enabled=False,
        )
        await dynamic_supervisor.start_child('test-terminate-child', child_spec)
        
        # Wait for it to start
        await anyio.sleep(0.1)
        assert test_data.exec_count == 1
        
        # Verify child is running
        assert "long-runner" in handle.list_children()
        
        # Terminate the child
        await dynamic_supervisor.terminate_child('test-terminate-child', "long-runner")
        
        # Wait a bit and verify it's gone
        await anyio.sleep(0.1)
        assert "long-runner" not in handle.list_children()
        assert test_data.exec_count == 1  # Should still be 1
        
        # Shutdown gracefully
        await handle.shutdown()


async def test_replace_child_with_same_id(test_data, log_handler):
    """Test that adding a child with existing ID replaces the old one."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    async with anyio.create_task_group() as tg:
        # Start dynamic supervisor using proper task_status pattern
        opts = dynamic_supervisor.options()
        
        handle = await tg.start(
            dynamic_supervisor.start, 
            [],  # Start empty
            opts, 
            'test-replace-child'
        )

        # Add first child
        child_spec1 = dynamic_supervisor.child_spec(
            id="worker",
            task=sample_task_long_running,
            args=[test_data],
            restart=Permanent(),
            health_check_enabled=False,
        )
        await dynamic_supervisor.start_child('test-replace-child', child_spec1)
        
        # Wait for it to start
        await anyio.sleep(0.1)
        assert test_data.exec_count == 1
        
        # Verify first child is running
        assert "worker" in handle.list_children()
        
        # Add second child with same ID (should cancel first)
        child_spec2 = dynamic_supervisor.child_spec(
            id="worker",  # Same ID
            task=sample_task_with_completion,
            args=[test_data],
            restart=Transient(),
            health_check_enabled=False,
        )
        await dynamic_supervisor.start_child('test-replace-child', child_spec2)
        
        # Wait for new child to run and complete
        await anyio.sleep(0.2)
        assert test_data.exec_count == 2  # Both should have started
        
        # Since second child is Transient and completes normally, it should be removed
        # The child list should be empty after completion
        children = handle.list_children()
        assert "worker" not in children or len(children) == 0
        
        # Shutdown gracefully
        await handle.shutdown()
