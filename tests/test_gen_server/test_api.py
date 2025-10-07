"""
Test gen_server basic API and lifecycle.
"""
import asyncio
import pytest
from otpylib import gen_server, process
from otpylib.module import OTPModule, GEN_SERVER
from otpylib.gen_server.data import NoReply, Reply


class BasicServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Basic gen server for testing start/stop."""
    
    async def init(self, test_state):
        self.test_state = test_state
        return test_state
    
    async def handle_call(self, request, from_pid, state):
        return (Reply('ok'), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


class FailingInitServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Gen server that fails during init."""
    
    async def init(self, test_state):
        raise RuntimeError("init failed")
    
    async def handle_call(self, request, from_pid, state):
        return (Reply('ok'), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


class TerminateCallbackServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Gen server that tracks termination."""
    
    async def init(self, test_state):
        self.test_state = test_state
        return test_state
    
    async def handle_call(self, request, from_pid, state):
        return (Reply('ok'), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        self.test_state.terminated = True
        self.test_state.terminate_reason = reason


@pytest.mark.asyncio
async def test_start_and_stop(test_state):
    """Test basic server start and stop."""
    async def tester():
        pid = await gen_server.start(BasicServer, init_arg=test_state)
        
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
        try:
            await gen_server.start(FailingInitServer, init_arg=test_state)
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
        pid = await gen_server.start(TerminateCallbackServer, init_arg=test_state)
        
        await process.exit(pid, "shutdown")
        await asyncio.sleep(0.1)
        
        assert test_state.terminated
        assert test_state.terminate_reason == "shutdown"
    
    test_pid = await process.spawn(tester, mailbox=True)
    while process.is_alive(test_pid):
        await asyncio.sleep(0.05)
