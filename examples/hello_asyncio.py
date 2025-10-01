#!/usr/bin/env python3
"""
examples/hello_runtime.py

First example of using the otpylib process module.
Tests basic process spawning, message passing, and linking.
"""

import asyncio
from otpylib import process
from otpylib.runtime import set_runtime
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend


async def worker(name: str, count: int):
    """A simple worker process that counts."""
    for i in range(count):
        print(f"[{name}] Count: {i}")
        await asyncio.sleep(0.5)
    
    print(f"[{name}] Finished")


async def ping_pong_server():
    """A process that responds to ping messages."""
    # Register our name
    await process.register("ping_server")
    print(f"[ping_server] Started")
    
    while True:
        msg = await process.receive()
        print(f"[ping_server] Received: {msg}")
        
        if msg == "ping":
            print(f"[ping_server] Would send pong back")
        elif msg == "stop":
            print(f"[ping_server] Stopping")
            break
        else:
            print(f"[ping_server] Unknown message: {msg}")
    
    print(f"[ping_server] Exiting")


async def main():
    """Main entry point."""
    print("=== Hello Runtime Example ===\n")
    
    # Initialize runtime backend
    backend = AsyncIOBackend()
    await backend.initialize()
    set_runtime(backend)
    
    # Test 1: Simple spawning
    print("Test 1: Spawning simple workers")
    pid1 = await process.spawn(worker, args=["worker1", 3])
    pid2 = await process.spawn(worker, args=["worker2", 2])
    print(f"Spawned PIDs: {pid1}, {pid2}")
    
    # Wait a bit
    await asyncio.sleep(2)
    
    # Test 2: Message passing
    print("\nTest 2: Message passing")
    server_pid = await process.spawn(ping_pong_server)
    
    # Give server time to register
    await asyncio.sleep(0.1)
    
    # Send messages
    await process.send("ping_server", "ping")
    await process.send("ping_server", "hello")
    await process.send("ping_server", "stop")
    
    # Wait for processes to finish
    await asyncio.sleep(3)
    
    # Test 3: Process info
    print("\nTest 3: Process information")
    all_pids = process.processes()
    print(f"Active processes: {all_pids}")
    
    # Test 4: Registry
    print("\nTest 4: Name registry")
    names = process.registered()
    print(f"Registered names: {names}")
    
    # Cleanup
    print("\nShutting down...")
    await backend.shutdown()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
