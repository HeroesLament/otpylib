#!/usr/bin/env python3
"""
Hello World GenServer Example

This demonstrates a basic gen_server that maintains a counter and responds to
increment/get requests. Shows the fundamental gen_server pattern with
synchronous calls and asynchronous casts.
"""

import anyio
import types
from otpylib import gen_server, mailbox


# Create a namespace to hold our callbacks (simulates an Erlang module)
callbacks = types.SimpleNamespace()


# GenServer state initialization
async def init(_init_arg):
    """Initialize the counter at 0."""
    return {"counter": 0}

callbacks.init = init


# Handle synchronous calls (request-response)
async def handle_call(message, _caller, state):
    """Handle call messages."""
    match message:
        case "get":
            # Return current counter value
            return (gen_server.Reply(payload=state["counter"]), state)
        
        case ("add", amount):
            # Add to counter and return old value
            old_value = state["counter"]
            state["counter"] += amount
            return (gen_server.Reply(payload=old_value), state)
        
        case _:
            # Unknown call
            error = NotImplementedError(f"Unknown call: {message}")
            return (gen_server.Reply(payload=error), state)

callbacks.handle_call = handle_call


# Handle asynchronous casts (fire-and-forget)
async def handle_cast(message, state):
    """Handle cast messages."""
    match message:
        case "increment":
            # Increment counter
            state["counter"] += 1
            return (gen_server.NoReply(), state)
        
        case "reset":
            # Reset counter to 0
            state["counter"] = 0
            return (gen_server.NoReply(), state)
        
        case "stop":
            # Gracefully stop the server
            return (gen_server.Stop(), state)
        
        case _:
            # Unknown cast, just ignore
            print(f"Unknown cast message: {message}")
            return (gen_server.NoReply(), state)

callbacks.handle_cast = handle_cast


# Handle info messages (direct mailbox sends)
async def handle_info(message, state):
    """Handle info messages sent directly to mailbox."""
    match message:
        case "status":
            print(f"Counter status: {state['counter']}")
        
        case _:
            print(f"Received info: {message}")
    
    return (gen_server.NoReply(), state)

callbacks.handle_info = handle_info


# Optional cleanup on termination
async def terminate(reason, state):
    """Called when the gen_server terminates."""
    if reason is not None:
        print(f"Counter server terminated with error: {reason}")
    else:
        print("Counter server terminated normally")
    
    print(f"Final counter value: {state['counter']}")

callbacks.terminate = terminate


async def demo_client():
    """Demonstrate the counter server in action."""
    print("=== Hello GenServer Demo ===\n")
    
    # Test synchronous calls
    print("1. Getting initial counter value...")
    value = await gen_server.call("counter", "get")
    print(f"   Counter: {value}")
    
    print("\n2. Adding 5 to counter...")
    old_value = await gen_server.call("counter", ("add", 5))
    print(f"   Old value: {old_value}")
    new_value = await gen_server.call("counter", "get")
    print(f"   New value: {new_value}")
    
    # Test asynchronous casts
    print("\n3. Incrementing counter (async)...")
    await gen_server.cast("counter", "increment")
    value = await gen_server.call("counter", "get")
    print(f"   Counter after increment: {value}")
    
    # Test direct mailbox messaging
    print("\n4. Sending status request via mailbox...")
    await mailbox.send("counter", "status")
    
    # Wait a moment for the message to be processed
    await anyio.sleep(0.1)
    
    print("\n5. Resetting counter...")
    await gen_server.cast("counter", "reset")
    value = await gen_server.call("counter", "get")
    print(f"   Counter after reset: {value}")
    
    print("\n6. Stopping server...")
    await gen_server.cast("counter", "stop")


async def main():
    """Main application entry point."""
    async with anyio.create_task_group() as tg:
        # Start the counter gen_server
        tg.start_soon(gen_server.start, callbacks, None, "counter")
        
        # Give the server a moment to start
        await anyio.sleep(0.1)
        
        # Run the demo
        await demo_client()


if __name__ == "__main__":
    mailbox.init_mailbox_registry()
    
    # Run the demo
    anyio.run(main)