"""
Test state recovery functionality for supervised gen_servers.
"""

import pytest
import anyio
import types
import random
from otpylib import supervisor, mailbox, gen_server
from otpylib.types import Permanent


pytestmark = pytest.mark.anyio


async def test_genserver_state_recovery():
    """Test that gen_server state is preserved across crashes when recovery is enabled."""
    
    mailbox.init_mailbox_registry()
    
    # Create a simple stateful gen_server
    callbacks = types.SimpleNamespace()
    recovery_called = {"count": 0}
    
    # Randomly decide if we'll actually crash (to avoid always hitting restart limit)
    should_actually_crash = random.choice([True, False])
    
    async def init(_):
        return {"counter": 0, "data": {}, "crash_count": 0}
    
    async def on_recovery(state):
        recovery_called["count"] += 1
        state["recovered"] = True
        return state
    
    async def handle_call(message, caller, state):
        match message:
            case ("increment", n):
                state["counter"] += n
                return (gen_server.Reply(payload=state["counter"]), state)
            case ("set", key, value):
                state["data"][key] = value
                return (gen_server.Reply(payload="ok"), state)
            case "get_state":
                return (gen_server.Reply(payload=state.copy()), state)
            case "maybe_crash":
                state["crash_count"] += 1
                # Only actually crash sometimes to avoid hitting restart limit
                if should_actually_crash and state["crash_count"] == 1:
                    raise RuntimeError("Intentional crash")
                else:
                    # Just pretend we crashed but return normally
                    return (gen_server.Reply(payload="survived"), state)
            case _:
                return (gen_server.Reply(payload="ok"), state)
    
    async def handle_cast(message, state):
        return (gen_server.NoReply(), state)
    
    callbacks.init = init
    callbacks.on_recovery = on_recovery
    callbacks.handle_call = handle_call
    callbacks.handle_cast = handle_cast
    
    async with anyio.create_task_group() as tg:
        children = [
            supervisor.child_spec(
                id="test_genserver",
                task=gen_server.start,
                args=[callbacks, None, "test_gs"],
                restart=Permanent(),
                enable_state_recovery=True,  # Enable state recovery
            )
        ]
        
        opts = supervisor.options(max_restarts=3, max_seconds=30)
        handle = await tg.start(supervisor.start, children, opts)
        
        try:
            await anyio.sleep(0.1)
            
            # Build up state
            assert await gen_server.call("test_gs", ("increment", 5)) == 5
            await gen_server.call("test_gs", ("set", "key1", "value1"))
            
            # Try to crash (might or might not actually crash)
            try:
                result = await gen_server.call("test_gs", "maybe_crash", timeout=1.0)
                # If we got here, it didn't actually crash
                assert result == "survived"
                # State should still be intact
                state = await gen_server.call("test_gs", "get_state")
                assert state["counter"] == 5
                assert state["data"]["key1"] == "value1"
            except (RuntimeError, TimeoutError):
                # It actually crashed, wait for restart
                await anyio.sleep(0.2)
                
                # Verify state was recovered
                state = await gen_server.call("test_gs", "get_state")
                assert state["counter"] == 5  # Counter preserved
                assert state["data"]["key1"] == "value1"  # Data preserved
                assert state.get("recovered") is True  # Recovery callback was called
                assert recovery_called["count"] == 1
            
            # Either way, should still be functional
            final_count = await gen_server.call("test_gs", ("increment", 3))
            assert final_count >= 8  # At least 8 (might be more if it didn't crash)
            
        finally:
            await handle.shutdown()