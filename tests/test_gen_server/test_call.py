"""
Test gen_server call/reply behavior.
"""
import asyncio
import pytest
from otpylib import gen_server, process
from otpylib.module import OTPModule, GEN_SERVER
from otpylib.gen_server.data import NoReply, Stop, Reply


class KeyValueServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Gen server that stores key-value pairs."""
    
    async def init(self, test_state):
        self.test_state = test_state
        return test_state
    
    async def handle_call(self, msg, from_pid, state):
        if msg == "get":
            return (Reply(self.test_state.data), state)
        elif isinstance(msg, tuple) and msg[0] == "set":
            key, val = msg[1], msg[2]
            self.test_state.data[key] = val
            return (Reply("ok"), state)
        return (Reply("unknown"), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


class StopOnCallServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Gen server that stops on specific call."""
    
    async def init(self, test_state):
        self.test_state = test_state
        return test_state
    
    async def handle_call(self, msg, from_pid, state):
        if msg == "stop":
            return (Stop("stopped"), state)
        return (Reply("ok"), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


class CounterCallServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Gen server with counter modified via calls."""
    
    async def init(self, test_state):
        self.test_state = test_state
        return test_state
    
    async def handle_call(self, msg, from_pid, state):
        if msg == "increment":
            self.test_state.counter += 1
            return (Reply(self.test_state.counter), state)
        return (Reply("unknown"), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


@pytest.mark.asyncio
async def test_simple_call(test_state):
    """Test basic call/reply pattern."""
    async def tester():
        pid = await gen_server.start(KeyValueServer, init_arg=test_state)
        
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
        pid = await gen_server.start(StopOnCallServer, init_arg=test_state)
        
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
        pid = await gen_server.start(CounterCallServer, init_arg=test_state)
        
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
