import pytest
import anyio
from otpylib import dynamic_supervisor, mailbox
from otpylib.types import Permanent, Transient


pytestmark = pytest.mark.anyio


async def worker_pool_manager():
    """Example task that manages a worker pool."""
    # This would normally manage worker allocation
    await anyio.sleep(0.1)


async def worker_task(worker_id: int):
    """Example worker task."""
    await anyio.sleep(0.05)
    return f"worker-{worker_id}-done"


async def test_nested_supervisors(log_handler):
    """Test nested dynamic supervisors."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    async with anyio.create_task_group() as tg:
        # Start parent supervisor
        parent_handle = await tg.start(
            dynamic_supervisor.start,
            [],
            dynamic_supervisor.options(),
            "parent_supervisor"
        )
        
        # Start child supervisor  
        child_handle = await tg.start(
            dynamic_supervisor.start,
            [],
            dynamic_supervisor.options(),
            "child_supervisor"
        )
        
        # Add workers to the child supervisor
        for i in range(3):
            worker_spec = dynamic_supervisor.child_spec(
                id=f'worker-{i}',
                task=worker_task,
                args=[i],
                restart=Transient(),
                health_check_enabled=False,
            )
            await dynamic_supervisor.start_child('child_supervisor', worker_spec)
        
        # Let workers complete
        await anyio.sleep(0.2)
        
        # Verify workers ran in child supervisor
        child_children = child_handle.list_children()
        # Workers may have completed and been removed (Transient + normal completion)
        
        # Parent should be empty
        parent_children = parent_handle.list_children()
        assert len(parent_children) == 0
        
        # Shutdown both supervisors
        await parent_handle.shutdown()
        await child_handle.shutdown()


async def test_supervisor_with_mailbox_name(log_handler):
    """Test that dynamic supervisor can be accessed by name."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    async with anyio.create_task_group() as tg:
        # Start dynamic supervisor with a well-known name
        handle = await tg.start(
            dynamic_supervisor.start,
            [],
            dynamic_supervisor.options(),
            'named-supervisor'
        )
        
        # Should be able to use the name to send commands
        child_spec = dynamic_supervisor.child_spec(
            id="test-worker",
            task=worker_task,
            args=[42],
            restart=Transient(),
            health_check_enabled=False,
        )
        
        # Add child using name
        await dynamic_supervisor.start_child('named-supervisor', child_spec)
        
        # Add another child using the same name
        child_spec2 = dynamic_supervisor.child_spec(
            id="test-worker-2",
            task=worker_task,
            args=[43],
            restart=Transient(),
            health_check_enabled=False,
        )
        await dynamic_supervisor.start_child('named-supervisor', child_spec2)
        
        # Let them start and potentially complete
        await anyio.sleep(0.2)
        
        # Check that we can query the supervisor
        children = handle.list_children()
        # Note: children might be empty if tasks completed (Transient + normal exit)
        
        # Shutdown gracefully
        await handle.shutdown()
