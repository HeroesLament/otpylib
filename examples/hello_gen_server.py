#!/usr/bin/env python3
"""
Hello World GenServer Example - Standalone (no supervisor)

Minimal example showing GenServer without supervision.
"""

import asyncio
import types
from otpylib import gen_server, process
from otpylib.runtime import set_runtime
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend


# Create callbacks namespace
callbacks = types.SimpleNamespace()

async def init(_init_arg):
    return {"counter": 0}

async def handle_call(message, _caller, state):
    match message:
        case "get":
            return (gen_server.Reply(payload=state["counter"]), state)
        case ("add", amount):
            old = state["counter"]
            state["counter"] += amount
            return (gen_server.Reply(payload=old), state)
        case _:
            error = NotImplementedError(f"Unknown call: {message}")
            return (gen_server.Reply(payload=error), state)

async def handle_cast(message, state):
    match message:
        case "increment":
            state["counter"] += 1
            return (gen_server.NoReply(), state)
        case _:
            print(f"Unknown cast: {message}")
            return (gen_server.NoReply(), state)

callbacks.init = init
callbacks.handle_call = handle_call
callbacks.handle_cast = handle_cast


async def demo():
    """Run the demo in a process context."""
    # Start GenServer (handshake requires process context)
    await gen_server.start(callbacks, None, "counter")
    
    print("Counter:", await gen_server.call("counter", "get"))
    
    await gen_server.cast("counter", "increment")
    print("After increment:", await gen_server.call("counter", "get"))
    
    old = await gen_server.call("counter", ("add", 5))
    print(f"Added 5 (was {old}):", await gen_server.call("counter", "get"))


async def main():
    backend = AsyncIOBackend()
    await backend.initialize()
    set_runtime(backend)
    
    # Spawn demo in a process (required for gen_server.start handshake)
    await process.spawn(demo, mailbox=True)
    
    await asyncio.sleep(1)  # Let demo complete
    await backend.shutdown()


if __name__ == "__main__":
    asyncio.run(main())