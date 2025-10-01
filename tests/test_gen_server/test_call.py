"""
Test gen_server call/reply behavior.
"""
import types
import asyncio
import pytest
from otpylib import gen_server, process


@pytest.mark.asyncio
async def test_simple_call(test_state):
    """Test basic call/reply pattern."""
    async def tester():
        async def init(state):
            return state
        
        async def handle_call(msg, caller, state):
            if msg == "get":
                return gen_server.Reply(state.data), state
            elif isinstance(msg, tuple) and msg[0] == "set":
                key, val = msg[1], msg[2]
                state.data[key] = val
                return gen_server.Reply("ok"), state
            return gen_server.Reply("unknown"), state
        
        mod = types.SimpleNamespace(init=init, handle_call=handle_call)
        pid = await gen_server.start(mod, test_state)
        
        result = await gen_server.call(pid, "get")
        assert result == {}
        
        result = await gen_server.call(pid, ("set", "foo", "bar"))
        assert result == "ok"
        assert test_state.data == {"foo": "bar"}
        
        await process.exit(pid, "shutdown")
        await asyncio.sleep(0.05)
    
    test_pid = await process.spawn(tester, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_call_with_stop(test_state):
    """Test that Stop action terminates the server."""
    async def tester():
        async def init(state):
            return state
        
        async def handle_call(msg, caller, state):
            if msg == "stop":
                return gen_server.Stop("stopped"), state
            return gen_server.Reply("ok"), state
        
        mod = types.SimpleNamespace(init=init, handle_call=handle_call)
        pid = await gen_server.start(mod, test_state)
        
        from otpylib.gen_server.core import GenServerExited
        try:
            await gen_server.call(pid, "stop")
            assert False, "Should have raised GenServerExited"
        except GenServerExited:
            pass
        
        await asyncio.sleep(0.05)
        assert not process.is_alive(pid)
    
    test_pid = await process.spawn(tester, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_call_modifies_state(test_state):
    """Test that call handlers can modify state."""
    async def tester():
        async def init(state):
            return state
        
        async def handle_call(msg, caller, state):
            if msg == "increment":
                state.counter += 1
                return gen_server.Reply(state.counter), state
            return gen_server.Reply("unknown"), state
        
        mod = types.SimpleNamespace(init=init, handle_call=handle_call)
        pid = await gen_server.start(mod, test_state)
        
        result1 = await gen_server.call(pid, "increment")
        assert result1 == 1
        
        result2 = await gen_server.call(pid, "increment")
        assert result2 == 2
        
        assert test_state.counter == 2
        
        await process.exit(pid, "shutdown")
        await asyncio.sleep(0.05)
    
    test_pid = await process.spawn(tester, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)
