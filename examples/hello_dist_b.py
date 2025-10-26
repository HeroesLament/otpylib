#!/usr/bin/env python3
"""
Node B - Distributed Test (Using Transparent Process API)

Run hello_dist_a.py first, then run this.

Tests transparent distributed communication using process.send()
"""

import asyncio
from otpylib.runtime.backends.base import Pid
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime.backends.asyncio_backend.distribution import AsyncIODistribution
from otpylib.runtime.registry import set_runtime, set_distribution
from otpylib import process, atom, distribution


async def test_client():
    """Client that tests distributed features using transparent process API"""
    print(f"[node_b/test_client] Started with PID: {process.self()}")
    
    # Test 1: Connect to Node A
    print("\n" + "=" * 60)
    print("TEST 1: Connecting to Node A")
    print("=" * 60)
    try:
        await distribution.connect("node_a@127.0.0.1")
        print("✓ Connected to node_a@127.0.0.1")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return
    
    # Test 2: Send message to registered process (using tuple notation)
    print("\n" + "=" * 60)
    print("TEST 2: Sending to remote registered process")
    print("=" * 60)
    try:
        print("Sending ping to 'test_server' on Node A using process.send()...")
        # Use transparent tuple notation: (name, node)
        await process.send(("test_server", "node_a@127.0.0.1"), 
                          (atom.ensure('ping'), process.self()))
        print("✓ Message sent using process.send()")
        
        # Wait for pong
        print("Waiting for pong response...")
        msg = await process.receive(timeout=5.0)
        print(f"✓ Received response: {msg}")
    except Exception as e:
        print(f"✗ Message test failed: {e}")
    
    # Test 3: Get remote PID and send directly
    print("\n" + "=" * 60)
    print("TEST 3: Getting remote PID and sending directly")
    print("=" * 60)
    try:
        print("Requesting PID from test_server...")
        await process.send(("test_server", "node_a@127.0.0.1"),
                          (atom.ensure('get_pid'), process.self()))
        
        msg = await process.receive(timeout=5.0)
        if isinstance(msg, tuple) and msg[0] == atom.ensure('pid'):
            remote_pid: Pid = msg[1]
            print(f"✓ Got remote PID: {remote_pid}")
            
            # Test 4: Create remote link (transparent!)
            print("\n" + "=" * 60)
            print("TEST 4: Creating remote link (transparent)")
            print("=" * 60)
            try:
                print(f"Linking to remote PID: {remote_pid}")
                await process.link(remote_pid)
                print("✓ Remote link created (backend auto-detected remote)")
                print("  (If Node A's test_server crashes, we'll receive EXIT signal)")
            except Exception as e:
                print(f"✗ Link failed: {e}")
            
            # Test 5: Create remote monitor (transparent!)
            print("\n" + "=" * 60)
            print("TEST 5: Creating remote monitor (transparent)")
            print("=" * 60)
            try:
                print(f"Monitoring remote PID: {remote_pid}")
                ref = await process.monitor(remote_pid)
                print(f"✓ Remote monitor created (ref: {ref})")
                print("  (If Node A's test_server crashes, we'll receive DOWN message)")
            except Exception as e:
                print(f"✗ Monitor failed: {e}")
            
            # Test 6: Send directly to remote PID (transparent!)
            print("\n" + "=" * 60)
            print("TEST 6: Direct PID send (transparent)")
            print("=" * 60)
            try:
                print(f"Sending 'hello' directly to remote PID...")
                await process.send(remote_pid, (atom.ensure('hello'), process.self()))
                print("✓ Message sent using process.send(remote_pid, msg)")
                print("  (Backend automatically routed to remote node)")
            except Exception as e:
                print(f"✗ Direct send failed: {e}")
            
    except Exception as e:
        print(f"✗ Failed to get remote PID: {e}")
    
    # Keep running and print any messages received
    print("\n" + "=" * 60)
    print("Listening for messages (Ctrl+C to exit)")
    print("Try killing Node A to test exit signal propagation")
    print("=" * 60)
    
    while True:
        try:
            msg = await process.receive(timeout=10.0)
            
            # Check message type
            if isinstance(msg, tuple) and len(msg) >= 3:
                if msg[0] == atom.ensure('EXIT'):
                    print(f"\n⚠️  EXIT SIGNAL:")
                    print(f"    From: {msg[1]}")
                    print(f"    Reason: {msg[2]}")
                elif msg[0] == atom.ensure('DOWN'):
                    print(f"\n⚠️  DOWN MESSAGE:")
                    print(f"    Ref: {msg[1]}")
                    print(f"    Type: {msg[2]}")
                    print(f"    PID: {msg[3]}")
                    print(f"    Reason: {msg[4]}")
                else:
                    print(f"\n📨 Message: {msg}")
            else:
                print(f"\n📨 Message: {msg}")
                
        except TimeoutError:
            # No message, keep waiting
            pass


async def main():
    # Initialize backend
    backend = AsyncIOBackend()
    await backend.initialize()
    set_runtime(backend)
    
    # Initialize distribution
    dist = AsyncIODistribution(backend, "node_b@127.0.0.1", cookie="secret")
    await dist.start(port=0)
    set_distribution(dist)
    
    print("=" * 60)
    print(f"Node B started!")
    print(f"  Name: node_b@127.0.0.1")
    print(f"  Port: {dist.port}")
    print(f"  Cookie: secret")
    print("=" * 60)
    
    # Spawn test client
    pid = await process.spawn(test_client, mailbox=True, trap_exits=True)
    print(f"\n✓ Spawned test_client: {pid}\n")
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\nShutting down Node B...")
        await backend.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
