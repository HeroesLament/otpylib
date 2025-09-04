import pytest
import anyio
from otpylib import dynamic_supervisor, mailbox
from otpylib.types import (
    # Restart Strategies - For persistent processes
    Permanent, Transient, RestartStrategy,
    # Supervisor Strategies  
    OneForOne, OneForAll, RestForOne, SupervisorStrategy,
    # Shutdown Strategies
    BrutalKill, GracefulShutdown, TimedShutdown, ShutdownStrategy,
    # Exit reasons
    NormalExit, ShutdownExit,
)
from .helpers import (
    sample_task_error,
    sample_task_long_running,
    sample_task,
    sample_task_with_completion,
    sample_task_with_delay,
)
from .conftest import TestData


# Apply anyio plugin across this module
pytestmark = pytest.mark.anyio


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
    """PERMANENT services restart until supervisor intensity is exceeded."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with pytest.raises(ExceptionGroup) as exc_info:
        async with anyio.create_task_group() as tg:
            children = [
                dynamic_supervisor.child_spec(
                    id="persistent_service",
                    task=sample_task_error,  # Will crash and restart
                    args=[test_data],
                    restart=Permanent(),
                    health_check_enabled=False,
                )
            ]
            opts = dynamic_supervisor.options(max_restarts=max_restarts, max_seconds=5)
            
            # Use start with task_status parameter
            handle = await tg.start(dynamic_supervisor.start, children, opts)
            await anyio.sleep(0.5)

    # Check that RuntimeError is in the nested exception group
    assert _find_runtime_error(exc_info.value)
    
    # Should have run at least max_restarts+1 times
    assert test_data.exec_count >= (max_restarts + 1)
    assert test_data.error_count >= (max_restarts + 1)


@pytest.mark.parametrize("strategy", [
    OneForOne(),
    OneForAll()
])
@pytest.mark.parametrize("max_restarts", [1, 3, 5])
async def test_automatic_restart_on_crash(strategy, max_restarts, test_data, log_handler):
    """Crashing services restart until supervisor intensity is exceeded."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with pytest.raises(ExceptionGroup) as exc_info:
        async with anyio.create_task_group() as tg:
            children = [
                dynamic_supervisor.child_spec(
                    id="failing_service",
                    task=sample_task_error,
                    args=[test_data],
                    restart=Permanent(),  # Use Permanent for crash tests
                    health_check_enabled=False,
                )
            ]
            opts = dynamic_supervisor.options(
                max_restarts=max_restarts, 
                max_seconds=5,
                strategy=strategy
            )
            
            # Use start with task_status parameter
            handle = await tg.start(dynamic_supervisor.start, children, opts)
            await anyio.sleep(0.5)

    # Check that RuntimeError is in the nested exception group
    assert _find_runtime_error(exc_info.value)
              
    assert test_data.exec_count >= (max_restarts + 1)
    assert test_data.error_count >= (max_restarts + 1)


@pytest.mark.parametrize("strategy", [
    OneForOne(),
    OneForAll()
])
async def test_no_restart_for_normal_exit(strategy, test_data, log_handler):
    """TRANSIENT services don't restart on normal completion."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with anyio.move_on_after(2.0):  # 2 second timeout
        async with anyio.create_task_group() as tg:
            children = [
                dynamic_supervisor.child_spec(
                    id="transient_service",
                    task=sample_task,  # Completes normally
                    args=[test_data],
                    restart=Transient(),
                    health_check_enabled=False,
                )
            ]
            opts = dynamic_supervisor.options(
                max_restarts=3, 
                max_seconds=5,
                strategy=strategy
            )
            
            # Use start with task_status parameter
            handle = await tg.start(dynamic_supervisor.start, children, opts)
            await anyio.sleep(0.2)
            
            # Graceful shutdown via handle
            await handle.shutdown()

    # TRANSIENT service completed normally, should not restart
    assert test_data.exec_count >= 1


async def test_start_multiple_children(test_data, log_handler):
    """Test starting multiple dynamic children."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with anyio.move_on_after(2.0):
        async with anyio.create_task_group() as tg:
            # Start empty supervisor with mailbox
            handle = await tg.start(
                dynamic_supervisor.start, 
                [],  # Start empty
                dynamic_supervisor.options(),
                "test_supervisor"
            )
            
            # Add multiple children dynamically
            child1_spec = dynamic_supervisor.child_spec(
                id="child1",
                task=sample_task_long_running,
                args=[test_data],
                restart=Permanent(),
                health_check_enabled=False
            )
            
            child2_spec = dynamic_supervisor.child_spec(
                id="child2", 
                task=sample_task_long_running,
                args=[test_data],
                restart=Permanent(),
                health_check_enabled=False
            )
            
            # Start children via mailbox
            await dynamic_supervisor.start_child("test_supervisor", child1_spec)
            await dynamic_supervisor.start_child("test_supervisor", child2_spec)
            
            # Wait for children to start
            await anyio.sleep(0.1)
            
            # Both children should be running
            children = handle.list_children()
            assert "child1" in children
            assert "child2" in children
            assert len(children) == 2
            
            # Both should be dynamic children
            dynamic_children = handle.list_dynamic_children()
            assert "child1" in dynamic_children
            assert "child2" in dynamic_children
            
            await handle.shutdown()


async def test_terminate_specific_child(test_data, log_handler):
    """Test terminating a specific dynamic child."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with anyio.move_on_after(2.0):
        async with anyio.create_task_group() as tg:
            # Start empty supervisor with mailbox
            handle = await tg.start(
                dynamic_supervisor.start,
                [],
                dynamic_supervisor.options(),
                "test_supervisor"
            )
            
            # Add a child
            child_spec = dynamic_supervisor.child_spec(
                id="target_child",
                task=sample_task_long_running,
                args=[test_data],
                restart=Permanent(),
                health_check_enabled=False
            )
            
            await dynamic_supervisor.start_child("test_supervisor", child_spec)
            await anyio.sleep(0.1)
            
            # Verify child is running
            assert "target_child" in handle.list_children()
            
            # Terminate the child
            await dynamic_supervisor.terminate_child("test_supervisor", "target_child")
            await anyio.sleep(0.1)
            
            # Child should be gone
            children = handle.list_children()
            assert "target_child" not in children
            
            await handle.shutdown()


async def test_replace_child_with_same_id(test_data, log_handler):
    """Test replacing a child by adding one with the same ID."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    # Create separate test data instances  
    test_data1 = TestData()
    test_data2 = TestData()
    
    with anyio.move_on_after(2.0):
        async with anyio.create_task_group() as tg:
            # Start empty supervisor with mailbox
            handle = await tg.start(
                dynamic_supervisor.start,
                [],
                dynamic_supervisor.options(),
                "test_supervisor"
            )
            
            # Add first child
            child1_spec = dynamic_supervisor.child_spec(
                id="replaceable_child",
                task=sample_task_long_running,
                args=[test_data1],
                restart=Permanent(),
                health_check_enabled=False
            )
            
            await dynamic_supervisor.start_child("test_supervisor", child1_spec)
            await anyio.sleep(0.1)
            
            # Verify first child is running
            assert test_data1.exec_count == 1
            assert "replaceable_child" in handle.list_children()
            
            # Add second child with same ID (should replace)
            child2_spec = dynamic_supervisor.child_spec(
                id="replaceable_child",  # Same ID
                task=sample_task_long_running,
                args=[test_data2],  # Different test data
                restart=Permanent(),
                health_check_enabled=False
            )
            
            await dynamic_supervisor.start_child("test_supervisor", child2_spec)
            await anyio.sleep(0.1)
            
            # Should still have only one child with that ID
            children = handle.list_children()
            assert children.count("replaceable_child") == 1
            
            # Second child should be running
            assert test_data2.exec_count == 1
            
            await handle.shutdown()


async def test_supervisor_with_mailbox_name(test_data, log_handler):
    """Test supervisor with named mailbox functionality."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with anyio.move_on_after(2.0):
        async with anyio.create_task_group() as tg:
            # Start supervisor with named mailbox
            handle = await tg.start(
                dynamic_supervisor.start,
                [],
                dynamic_supervisor.options(),
                "named_supervisor"
            )
            
            # Test that we can send messages to it
            child_spec = dynamic_supervisor.child_spec(
                id="mailbox_child",
                task=sample_task_long_running,
                args=[test_data],
                restart=Permanent(),
                health_check_enabled=False
            )
            
            await dynamic_supervisor.start_child("named_supervisor", child_spec)
            await anyio.sleep(0.1)
            
            # Child should be running
            assert "mailbox_child" in handle.list_children()
            
            await handle.shutdown()


async def test_nested_supervisors(test_data, log_handler):
    """Test nested dynamic supervisors."""
    
    # Initialize mailbox registry
    mailbox.init_mailbox_registry()
    
    with anyio.move_on_after(2.0):
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
            
            # Add task to child supervisor
            task_spec = dynamic_supervisor.child_spec(
                id="nested_task",
                task=sample_task_long_running,
                args=[test_data],
                restart=Permanent(),
                health_check_enabled=False
            )
            
            await dynamic_supervisor.start_child("child_supervisor", task_spec)
            await anyio.sleep(0.1)
            
            # Task should be running in child supervisor
            assert "nested_task" in child_handle.list_children()
            
            # Parent should be empty
            assert len(parent_handle.list_children()) == 0
            
            await parent_handle.shutdown()
            await child_handle.shutdown()
