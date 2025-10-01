"""
Test gen_server cast (fire-and-forget) behavior.
"""
import types
import asyncio
import pytest
from otpylib import gen_server, process


@pytest.mark.asyncio
async def test_simple_cast(test_state):
    """Test basic cast pattern."""
    async def tester():
        async def init(state):
            return state
        
        async def handle_cast(msg, state):
            state.events.append(msg)
            return gen_server.NoReply(), state
        
        mod = types.SimpleNamespace(init=init, handle_cast=handle_cast)
        pid = await gen_server.start(mod, test_state)
        
        await gen_server.cast(pid, "event1")
        await gen_server.cast(pid, "event2")
        
        await asyncio.sleep(0.1)
        
        assert test_state.events == ["event1", "event2"]
        
        await process.exit(pid, "shutdown")
        await asyncio.sleep(0.05)
    
    test_pid = await process.spawn(tester, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_cast_with_stop(test_state):
    """Test that cast can trigger Stop."""
    async def tester():
        async def init(state):
            return state
        
        async def handle_cast(msg, state):
            if msg == "stop":
                return gen_server.Stop("stopped"), state
            return gen_server.NoReply(), state
        
        mod = types.SimpleNamespace(init=init, handle_cast=handle_cast)
        pid = await gen_server.start(mod, test_state)
        
        await gen_server.cast(pid, "stop")
        
        await asyncio.sleep(0.1)
        assert not process.is_alive(pid)
    
    test_pid = await process.spawn(tester, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_cast_modifies_state(test_state):
    """Test that cast can modify server state."""
    async def tester():
        async def init(state):
            return state
        
        async def handle_call(msg, caller, state):
            if msg == "get":
                return gen_server.Reply(state.counter), state
            return gen_server.Reply("unknown"), state
        
        async def handle_cast(msg, state):
            if msg == "increment":
                state.counter += 1
            return gen_server.NoReply(), state
        
        mod = types.SimpleNamespace(
            init=init, 
            handle_call=handle_call,
            handle_cast=handle_cast
        )
        pid = await gen_server.start(mod, test_state)
        
        await gen_server.cast(pid, "increment")
        await gen_server.cast(pid, "increment")
        await gen_server.cast(pid, "increment")
        
        await asyncio.sleep(0.1)
        
        result = await gen_server.call(pid, "get")
        assert result == 3
        
        await process.exit(pid, "shutdown")
        await asyncio.sleep(0.05)
    
    test_pid = await process.spawn(tester, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)
