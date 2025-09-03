import pytest
import anyio

from otpylib import supervisor, dynamic_supervisor
from otpylib.types import StartupSync


pytestmark = pytest.mark.anyio


async def worker_pool_manager():
    """Example task that manages a worker pool."""
    # This would normally manage worker allocation
    await anyio.sleep(0.1)


async def worker_task(worker_id: int):
    """Example worker task."""
    await anyio.sleep(0.05)
    return f"worker-{worker_id}-done"


async def test_nested_supervisors(mailbox_env):
    """Test dynamic supervisor as child of regular supervisor."""
    async with anyio.create_task_group() as tg:
        # Create a supervisor that manages a dynamic supervisor
        opts = supervisor.options()
        
        # Create dynamic supervisor as a child spec
        children = [
            supervisor.child_spec(
                id='worker_pool',
                task=dynamic_supervisor.start,
                args=[opts, 'worker-pool', None],  # No sync needed here
                restart=supervisor.restart_strategy.PERMANENT,
            ),
        ]
        
        # Start the parent supervisor
        tg.start_soon(supervisor.start, children, opts)
        
        # Give it time to start
        await anyio.sleep(0.2)
        
        # Now add workers to the dynamic supervisor
        for i in range(3):
            worker_spec = supervisor.child_spec(
                id=f'worker-{i}',
                task=worker_task,
                args=[i],
                restart=supervisor.restart_strategy.TEMPORARY,
            )
            await dynamic_supervisor.start_child('worker-pool', worker_spec)
        
        # Let workers complete
        await anyio.sleep(0.3)
        
        # Cancel everything
        tg.cancel_scope.cancel()


async def test_supervisor_with_mailbox_name(mailbox_env):
    """Test that dynamic supervisor can be accessed by name."""
    async with anyio.create_task_group() as tg:
        # Start dynamic supervisor with a well-known name
        opts = supervisor.options()
        
        sync = StartupSync()
        tg.start_soon(dynamic_supervisor.start, opts, 'named-supervisor', sync)
        mid = await sync.wait()
        
        # Should be able to use either the name or the mailbox ID
        child_spec = supervisor.child_spec(
            id="test-worker",
            task=worker_task,
            args=[42],
            restart=supervisor.restart_strategy.TEMPORARY,
        )
        
        # Add child using name
        await dynamic_supervisor.start_child('named-supervisor', child_spec)
        
        # Add another child using mailbox ID
        child_spec2 = supervisor.child_spec(
            id="test-worker-2",
            task=worker_task,
            args=[43],
            restart=supervisor.restart_strategy.TEMPORARY,
        )
        await dynamic_supervisor.start_child(mid, child_spec2)
        
        # Let them complete
        await anyio.sleep(0.2)
        
        # Cancel everything
        tg.cancel_scope.cancel()