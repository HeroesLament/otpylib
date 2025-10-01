"""
Test gen_server basic API and lifecycle.
"""
import types
import asyncio
import pytest
from otpylib import gen_server, process


@pytest.mark.asyncio
async def test_start_and_stop(test_state):
    """Test basic server start and stop."""
    async def tester():
        async def init(state):
            return state
        
        mod = types.SimpleNamespace(init=init)
        pid = await gen_server.start(mod, test_state)
        
        assert process.is_alive(pid)
        
        await process.exit(pid, "shutdown")
        await asyncio.sleep(0.05)
        
        assert not process.is_alive(pid)
    
    test_pid = await process.spawn(tester, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_init_failure(test_state):
    """Test that init failure prevents server start."""
    async def tester():
        async def init(state):
            raise RuntimeError("init failed")
        
        mod = types.SimpleNamespace(init=init)
        
        try:
            await gen_server.start(mod, test_state)
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "init failed" in str(e)
    
    test_pid = await process.spawn(tester, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_terminate_callback(test_state):
    """Test that terminate is called on shutdown."""
    async def tester():
        async def init(state):
            return state
        
        async def terminate(reason, state):
            state.terminated = True
            state.terminate_reason = reason
        
        mod = types.SimpleNamespace(init=init, terminate=terminate)
        pid = await gen_server.start(mod, test_state)
        
        await process.exit(pid, "shutdown")
        await asyncio.sleep(0.1)
        
        assert test_state.terminated
        assert test_state.terminate_reason == "shutdown"
    
    test_pid = await process.spawn(tester, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)
