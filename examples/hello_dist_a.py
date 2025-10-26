#!/usr/bin/env python3
"""
Node A - Distributed Test

Run this first in one terminal.
Then run hello_dist_b.py in another terminal.

Tests:
- Message passing to remote node
- Remote link
- Remote monitor
"""

import asyncio
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime.backends.asyncio_backend.distribution import AsyncIODistribution
from otpylib.runtime.registry import set_runtime, set_distribution
from otpylib.distribution.etf import Pid
from otpylib import process, atom


async def test_server():
    """Simple server that responds to pings"""
    print(f"[node_a/test_server] Started with PID: {process.self()}")
    print(f"[node_a/test_server] Registered as 'test_server'")
    print(f"[node_a/test_server] Waiting for messages...")
    
    while True:
        msg = await process.receive()
        print(f"[node_a/test_server] Received: {msg}")
        
        if isinstance(msg, tuple) and len(msg) >= 2:
            cmd = msg[0]
            
            if cmd == atom.ensure('ping'):
                from_pid = msg[1]
                print(f"[node_a/test_server] Sending pong to {from_pid}")
                await process.send(from_pid, (atom.ensure('pong'), process.self()))
            
            elif cmd == atom.ensure('get_pid'):
                from_pid = msg[1]
                print(f"[node_a/test_server] Sending my PID to {from_pid}")
                await process.send(from_pid, (atom.ensure('pid'), process.self()))


async def main():
    # Initialize backend
    backend = AsyncIOBackend()
    await backend.initialize()
    set_runtime(backend)
    
    # Initialize distribution
    dist = AsyncIODistribution(backend, "node_a@127.0.0.1", cookie="secret")
    await dist.start()  # Use ephemeral port
    set_distribution(dist)
    
    print("=" * 60)
    print(f"Node A started!")
    print(f"  Name: node_a@127.0.0.1")
    print(f"  Port: {dist.port}")
    print(f"  Cookie: secret")
    print("=" * 60)
    
    # Spawn and register test server
    pid = await process.spawn(test_server, name="test_server")
    print(f"\n✓ Spawned test_server: {pid}")
    print(f"✓ Registered as 'test_server'\n")
    
    print("Waiting for Node B to connect...")
    print("(Run hello_dist_b.py in another terminal)\n")
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\nShutting down Node A...")
        await backend.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
