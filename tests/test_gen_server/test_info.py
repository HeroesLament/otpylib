"""
Test gen_server info message handling.
"""
import types
import asyncio
import pytest
from otpylib import gen_server, process


@pytest.mark.asyncio
async def test_handle_info(test_state):
    """Test that info messages are handled."""
    async def tester():
        async def init(state):
            return state
        
        async def handle_info(msg, state):
            state.messages.append(msg)
            return gen_server.NoReply(), state
        
        mod = types.SimpleNamespace(__name__="test_mod", init=init, handle_info=handle_info)
        pid = await gen_server.start(mod, test_state)
        
        await process.send(pid, "info1")
        await process.send(pid, ("tuple", "info"))
        
        await asyncio.sleep(0.1)
        
        assert test_state.messages == ["info1", ("tuple", "info")]
        
        await process.exit(pid, "shutdown")
        await asyncio.sleep(0.05)
    
    test_pid = await process.spawn(tester, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_info_with_stop(test_state):
    """Test that info handler can trigger Stop."""
    async def tester():
        async def init(state):
            return state
        
        async def handle_info(msg, state):
            if msg == "stop":
                return gen_server.Stop("stopped"), state
            return gen_server.NoReply(), state
        
        mod = types.SimpleNamespace(__name__="test_mod", init=init, handle_info=handle_info)
        pid = await gen_server.start(mod, test_state)
        
        await process.send(pid, "stop")
        
        await asyncio.sleep(0.1)
        assert not process.is_alive(pid)
    
    test_pid = await process.spawn(tester, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)
