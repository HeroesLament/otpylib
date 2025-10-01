"""
Debug script to understand why links aren't working as expected.
"""

import asyncio
import logging
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend
from otpylib.runtime.atoms import EXIT, KILLED

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)


async def test_basic_link():
    """Test basic linking behavior."""
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    print("\n=== Testing Basic Link ===")
    
    # Track what happens
    events = []
    
    async def parent():
        events.append("parent_started")
        pid = runtime.self()
        print(f"Parent started: {pid}")
        
        # Spawn and link to child
        child_pid = await runtime.spawn_link(child_proc)
        events.append(f"parent_linked_to_{child_pid}")
        print(f"Parent linked to child: {child_pid}")
        
        # Wait to see if we die when child dies
        for i in range(10):
            await asyncio.sleep(0.1)
            events.append(f"parent_alive_{i}")
            print(f"Parent still alive after {i*0.1:.1f}s")
    
    async def child_proc():
        events.append("child_started")
        pid = runtime.self()
        print(f"Child started: {pid}")
        
        await asyncio.sleep(0.2)
        events.append("child_crashing")
        print("Child about to crash!")
        raise RuntimeError("Child intentional crash")
    
    parent_pid = await runtime.spawn(parent)
    print(f"Spawned parent: {parent_pid}")
    
    # Check status over time
    for i in range(10):
        await asyncio.sleep(0.1)
        parent_alive = runtime.is_alive(parent_pid)
        print(f"After {i*0.1:.1f}s: Parent alive = {parent_alive}")
        if not parent_alive:
            break
    
    print(f"\nEvents: {events}")
    
    await runtime.shutdown()


async def test_trap_exits():
    """Test trap_exits behavior."""
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    print("\n=== Testing Trap Exits ===")
    
    received_messages = []
    
    async def supervisor():
        pid = runtime.self()
        print(f"Supervisor started (trap_exits=True): {pid}")
        
        # Spawn and link child
        child = await runtime.spawn_link(child_proc)
        print(f"Supervisor linked to child: {child}")
        
        # Should receive EXIT as message, not die
        while True:
            try:
                msg = await runtime.receive(timeout=0.5)
                print(f"Supervisor received: {msg}")
                received_messages.append(msg)
                
                if isinstance(msg, tuple) and msg[0] == EXIT:
                    print(f"Got EXIT message from {msg[1]} with reason {msg[2]}")
                    break
            except asyncio.TimeoutError:
                print("Supervisor receive timeout")
                break
        
        print("Supervisor still running after EXIT")
        await asyncio.sleep(0.2)
    
    async def child_proc():
        pid = runtime.self()
        print(f"Child started: {pid}")
        await asyncio.sleep(0.1)
        print("Child crashing!")
        raise RuntimeError("Child error")
    
    # Note: Pass trap_exits=True here
    sup_pid = await runtime.spawn(supervisor, trap_exits=True)
    print(f"Spawned supervisor with trap_exits: {sup_pid}")
    
    # Monitor supervisor status
    for i in range(10):
        await asyncio.sleep(0.1)
        alive = runtime.is_alive(sup_pid)
        print(f"After {i*0.1:.1f}s: Supervisor alive = {alive}")
        if not alive:
            print("Supervisor died unexpectedly!")
            break
    
    print(f"\nReceived messages: {received_messages}")
    
    await runtime.shutdown()


async def test_unlink():
    """Test unlinking behavior."""
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    print("\n=== Testing Unlink ===")
    
    async def proc_a():
        pid = runtime.self()
        print(f"Proc A started: {pid}")
        
        # Wait for B to register
        await asyncio.sleep(0.05)
        
        # Link to B
        await runtime.link("proc_b")
        print("Proc A linked to proc_b")
        
        # Unlink from B
        await asyncio.sleep(0.05)
        await runtime.unlink("proc_b")
        print("Proc A unlinked from proc_b")
        
        # Should survive B's crash
        for i in range(5):
            await asyncio.sleep(0.1)
            print(f"Proc A still alive after unlink ({i})")
    
    async def proc_b():
        await runtime.register("proc_b")
        pid = runtime.self()
        print(f"Proc B started and registered: {pid}")
        
        # Wait then crash
        await asyncio.sleep(0.2)
        print("Proc B crashing!")
        raise RuntimeError("proc_b crash")
    
    pid_a = await runtime.spawn(proc_a)
    pid_b = await runtime.spawn(proc_b)
    
    print(f"Spawned A: {pid_a}, B: {pid_b}")
    
    # Monitor both processes
    for i in range(10):
        await asyncio.sleep(0.1)
        a_alive = runtime.is_alive(pid_a)
        b_alive = runtime.is_alive(pid_b)
        print(f"After {i*0.1:.1f}s: A={a_alive}, B={b_alive}")
        
        if not b_alive and a_alive:
            print("SUCCESS: B died but A survived due to unlink")
        elif not a_alive:
            print("FAILURE: A died (shouldn't have)")
            break
    
    await runtime.shutdown()


async def main():
    """Run all debug tests."""
    await test_basic_link()
    await test_trap_exits()
    await test_unlink()


if __name__ == "__main__":
    asyncio.run(main())
