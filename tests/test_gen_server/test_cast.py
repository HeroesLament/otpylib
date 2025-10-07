"""
Test gen_server cast (fire-and-forget) behavior.
"""
import asyncio
import pytest
from otpylib import gen_server, process
from otpylib.module import OTPModule, GEN_SERVER
from otpylib.gen_server.data import NoReply, Stop, Reply


class EventCollectorServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Gen server that collects cast events."""
    
    async def init(self, test_state):
        self.test_state = test_state
        return test_state
    
    async def handle_call(self, request, from_pid, state):
        return (Reply('ok'), state)
    
    async def handle_cast(self, msg, state):
        self.test_state.events.append(msg)
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


class StopOnCastServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Gen server that stops on specific cast message."""
    
    async def init(self, test_state):
        self.test_state = test_state
        return test_state
    
    async def handle_call(self, request, from_pid, state):
        return (Reply('ok'), state)
    
    async def handle_cast(self, msg, state):
        if msg == "stop":
            return (Stop("stopped"), state)
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


class CounterServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Gen server with counter that can be modified via cast."""
    
    async def init(self, test_state):
        self.test_state = test_state
        return test_state
    
    async def handle_call(self, msg, from_pid, state):
        if msg == "get":
            return (Reply(self.test_state.counter), state)
        return (Reply("unknown"), state)
    
    async def handle_cast(self, msg, state):
        if msg == "increment":
            self.test_state.counter += 1
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


@pytest.mark.asyncio
async def test_simple_cast(test_state):
    """Test basic cast pattern."""
    async def tester():
        pid = await gen_server.start(EventCollectorServer, init_arg=test_state)
        
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
        pid = await gen_server.start(StopOnCastServer, init_arg=test_state)
        
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
        pid = await gen_server.start(CounterServer, init_arg=test_state)
        
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
