#!/usr/bin/env python3
"""
Hello AsyncIO GenServer Example

Demonstrates using gen_server with the new process API and asyncio runtime.
No anyio, no supervisors - just pure process-based gen_server.
"""

import asyncio
import types
from otpylib import gen_server, process
from otpylib.runtime import set_runtime
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend


# Create a namespace to hold our callbacks (simulates an Erlang module)
counter_server = types.SimpleNamespace()


# ----------------------------------------------------------------------
# Callbacks
# ----------------------------------------------------------------------

async def init(_init_arg):
    """Initialize the counter at 0."""
    print("[counter] Initializing with counter=0")
    return {"counter": 0, "operations": 0}

counter_server.init = init


async def handle_call(message, caller, state):
    """Handle call messages."""
    state["operations"] += 1
    match message:
        case "get":
            return (gen_server.Reply(payload=state["counter"]), state)
        case ("add", amount):
            old_value = state["counter"]
            state["counter"] += amount
            print(f"[counter] Adding {amount}, counter: {old_value} -> {state['counter']}")
            return (gen_server.Reply(payload=old_value), state)
        case "stats":
            stats = {"counter": state["counter"], "operations": state["operations"]}
            return (gen_server.Reply(payload=stats), state)
        case _:
            return (gen_server.Reply(payload=NotImplementedError(str(message))), state)

counter_server.handle_call = handle_call


async def handle_cast(message, state):
    """Handle cast messages."""
    state["operations"] += 1
    match message:
        case "increment":
            state["counter"] += 1
            print(f"[counter] Incremented to {state['counter']}")
            return (gen_server.NoReply(), state)
        case ("multiply", factor):
            old_value = state["counter"]
            state["counter"] *= factor
            print(f"[counter] Multiplied by {factor}: {old_value} -> {state['counter']}")
            return (gen_server.NoReply(), state)
        case "reset":
            print(f"[counter] Reset from {state['counter']} to 0")
            state["counter"] = 0
            return (gen_server.NoReply(), state)
        case "stop":
            print("[counter] Stop requested")
            return (gen_server.Stop(), state)
        case _:
            print(f"[counter] Unknown cast message: {message}")
            return (gen_server.NoReply(), state)

counter_server.handle_cast = handle_cast


async def handle_info(message, state):
    """Handle info messages sent directly to the process."""
    match message:
        case "ping":
            print(f"[counter] Pong! (counter={state['counter']})")
        case ("echo", text):
            print(f"[counter] Echo: {text}")
        case _:
            print(f"[counter] Received info: {message}")
    return (gen_server.NoReply(), state)

counter_server.handle_info = handle_info


async def terminate(reason, state):
    """Called when the gen_server terminates."""
    if reason:
        print(f"[counter] Terminated with reason: {reason}")
    else:
        print("[counter] Terminated normally")
    print(f"[counter] Final state: counter={state['counter']}, operations={state['operations']}")

counter_server.terminate = terminate


# ----------------------------------------------------------------------
# Demo client
# ----------------------------------------------------------------------

async def demo_client(pid):
    print("\n=== GenServer Client Demo ===\n")

    print("1. Getting initial counter value...")
    value = await gen_server.call("counter", "get")
    print(f"   Result: {value}\n")

    print("2. Adding 5 to counter...")
    old_value = await gen_server.call("counter", ("add", 5))
    print(f"   Returned old value: {old_value}")
    new_value = await gen_server.call("counter", "get")
    print(f"   Current value: {new_value}\n")

    print("3. Incrementing counter (cast)...")
    await gen_server.cast("counter", "increment")
    await asyncio.sleep(0.05)
    value = await gen_server.call("counter", "get")
    print(f"   Counter after increment: {value}\n")

    print("4. Multiplying by 2 (cast)...")
    await gen_server.cast("counter", ("multiply", 2))
    await asyncio.sleep(0.05)
    value = await gen_server.call("counter", "get")
    print(f"   Counter after multiply: {value}\n")

    print("5. Sending info messages...")
    await process.send("counter", "ping")
    await process.send("counter", ("echo", "Hello from client!"))
    await asyncio.sleep(0.05)
    print()

    print("6. Getting statistics...")
    stats = await gen_server.call("counter", "stats")
    print(f"   Stats: {stats}\n")

    print("7. Resetting counter...")
    await gen_server.cast("counter", "reset")
    await asyncio.sleep(0.05)
    value = await gen_server.call("counter", "get")
    print(f"   Counter after reset: {value}\n")

    print("8. Stopping server...")
    await gen_server.cast("counter", "stop")
    await asyncio.sleep(0.1)

    if process.is_alive(pid):
        print("   Server still alive (unexpected)")
    else:
        print("   Server stopped (expected)")


# ----------------------------------------------------------------------
# Main entry
# ----------------------------------------------------------------------

async def main():
    print("=== Hello AsyncIO GenServer Example ===")
    print("Using process API with AsyncIO backend\n")

    backend = AsyncIOBackend()
    await backend.initialize()
    set_runtime(backend)

    print("Starting counter gen_server...")
    pid = await gen_server.start(counter_server, name="counter")
    print(f"Counter server started with PID: {pid}\n")

    await demo_client(pid)

    print("\n=== Final Status ===")
    if process.is_alive(pid):
        print(f"Process {pid} is still alive (unexpected)")
    else:
        print(f"Process {pid} has terminated (expected)")

    print("\nShutting down runtime...")
    await backend.shutdown()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
