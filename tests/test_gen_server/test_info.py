"""
Test gen_server info message handling.
"""
import asyncio
import pytest
from otpylib import gen_server, process
from otpylib.module import OTPModule, GEN_SERVER
from otpylib.gen_server.data import NoReply, Stop, Reply


class InfoHandlerServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Gen server that handles info messages."""
    
    async def init(self, test_state):
        self.test_state = test_state
        return test_state
    
    async def handle_call(self, request, from_pid, state):
        return (Reply('ok'), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, msg, state):
        self.test_state.messages.append(msg)
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


class StopOnInfoServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Gen server that stops on specific info message."""
    
    async def init(self, test_state):
        self.test_state = test_state
        return test_state
    
    async def handle_call(self, request, from_pid, state):
        return (Reply('ok'), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, msg, state):
        if msg == "stop":
            return (Stop("stopped"), state)
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


@pytest.mark.asyncio
async def test_handle_info(test_state):
    """Test that info messages are handled."""
    async def tester():
        pid = await gen_server.start(InfoHandlerServer, init_arg=test_state)
        
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
        pid = await gen_server.start(StopOnInfoServer, init_arg=test_state)
        
        await process.send(pid, "stop")
        
        await asyncio.sleep(0.1)
        assert not process.is_alive(pid)
    
    test_pid = await process.spawn(tester, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)
