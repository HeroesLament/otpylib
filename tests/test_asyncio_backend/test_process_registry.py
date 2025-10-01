"""
Test process name registry.
"""

import asyncio
import pytest
from otpylib.runtime.backends.base import NameAlreadyRegisteredError, ProcessNotFoundError, RuntimeBackend
from otpylib.runtime.atoms import atom

from conftest import ProcessTracker


@pytest.mark.asyncio
async def test_register_name(runtime: RuntimeBackend, process_tracker: ProcessTracker):
    """Test registering a process name."""
    async def named_proc():
        await runtime.register("my_process")
        await asyncio.sleep(0.1)
    
    pid = await process_tracker.spawn(named_proc)
    await asyncio.sleep(0.01)
    
    # Should be able to find by name
    found_pid = runtime.whereis("my_process")
    assert found_pid == pid


@pytest.mark.asyncio
async def test_register_duplicate_name(runtime: RuntimeBackend, process_tracker: ProcessTracker):
    """Test that duplicate names raise error."""
    async def proc1():
        await runtime.register("duplicate")
        await asyncio.sleep(0.1)
    
    async def proc2():
        await asyncio.sleep(0.01)  # Let proc1 register first
        with pytest.raises(NameAlreadyRegisteredError):
            await runtime.register("duplicate")
    
    await process_tracker.spawn(proc1)
    await process_tracker.spawn(proc2)
    
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_unregister(runtime: RuntimeBackend, process_tracker: ProcessTracker):
    """Test unregistering a name."""
    async def named_proc():
        await runtime.register("temp_name")
        await asyncio.sleep(0.05)
        await runtime.unregister("temp_name")
        await asyncio.sleep(0.05)
    
    pid = await process_tracker.spawn(named_proc)
    
    await asyncio.sleep(0.02)
    assert runtime.whereis("temp_name") == pid
    
    await asyncio.sleep(0.05)
    assert runtime.whereis("temp_name") is None


@pytest.mark.asyncio
async def test_whereis_dead_process(runtime: RuntimeBackend, process_tracker: ProcessTracker):
    """Test whereis cleans up dead process names."""
    async def short_lived():
        await runtime.register("dying")
        # Exit immediately
    
    await process_tracker.spawn(short_lived)
    await asyncio.sleep(0.05)
    
    # whereis should return None and clean up
    result = runtime.whereis("dying")
    assert result is None
    
    # Name should be available for reuse
    async def new_proc():
        await runtime.register("dying")  # Should work
        await asyncio.sleep(0.1)
    
    await process_tracker.spawn(new_proc)
    await asyncio.sleep(0.01)
    
    assert runtime.whereis("dying") is not None


@pytest.mark.asyncio
async def test_registered(runtime: RuntimeBackend, process_tracker: ProcessTracker):
    """Test listing all registered names."""
    names = ["proc_a", "proc_b", "proc_c"]
    
    async def named_proc(name):
        await runtime.register(name)
        await asyncio.sleep(0.1)
    
    for name in names:
        await process_tracker.spawn(named_proc, args=[name])
    
    await asyncio.sleep(0.01)
    
    registered = runtime.registered()
    for name in names:
        assert name in registered


@pytest.mark.asyncio
async def test_name_survives_after_register(runtime: RuntimeBackend, process_tracker: ProcessTracker):
    """Test that process name is retained in process info."""
    async def named_proc():
        await runtime.register("persistent")
        pid = runtime.self()
        info = runtime.process_info(pid)
        assert info.name == "persistent"
        await asyncio.sleep(0.1)
    
    await process_tracker.spawn(named_proc)
    await asyncio.sleep(0.05)
