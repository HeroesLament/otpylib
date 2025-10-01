"""
Simple test to verify linking behavior step by step.
"""

import asyncio
import logging
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend
from otpylib.runtime.atoms import EXIT, KILLED

logging.basicConfig(level=logging.DEBUG)


async def test_trap_exits_simple():
    """Simplest possible test of trap_exits."""
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    print("\n=== Simple Trap Exits Test ===")
    
    messages = []
    done = False
    
    async def supervisor():
        print(f"Supervisor {runtime.self()} starting")
        
        # Just receive messages
        while not done:
            try:
                msg = await runtime.receive(timeout=0.1)
                print(f"Supervisor received: {msg}")
                messages.append(msg)
            except asyncio.TimeoutError:
                continue
    
    # Spawn with trap_exits
    sup_pid = await runtime.spawn(supervisor, trap_exits=True)
    print(f"Spawned supervisor: {sup_pid}")
    
    # Send it an EXIT message directly
    await runtime.send(sup_pid, (EXIT, "test_pid", "test_reason"))
    
    await asyncio.sleep(0.2)
    
    # Check if it's still alive
    alive = runtime.is_alive(sup_pid)
    print(f"Supervisor alive after EXIT message: {alive}")
    print(f"Messages received: {messages}")
    
    # Stop it
    done = True
    await asyncio.sleep(0.2)
    
    await runtime.shutdown()
    return alive


async def test_process_info_timing():
    """Test when process info becomes available."""
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    print("\n=== Process Info Timing Test ===")
    
    async def test_proc():
        pid = runtime.self()
        info = runtime.process_info(pid)
        print(f"Inside process - PID: {pid}, Info exists: {info is not None}")
        if info:
            print(f"  State: {info.state}, trap_exits: {info.trap_exits}")
        await asyncio.sleep(0.5)
    
    # Test with trap_exits
    pid = await runtime.spawn(test_proc, trap_exits=True)
    print(f"Spawned process: {pid}")
    
    # Check immediately
    info = runtime.process_info(pid)
    if info:
        print(f"Outside process - State: {info.state}, trap_exits: {info.trap_exits}")
    
    await asyncio.sleep(0.1)
    
    # Check again
    info = runtime.process_info(pid)
    if info:
        print(f"After 0.1s - State: {info.state}, trap_exits: {info.trap_exits}")
    
    await asyncio.sleep(0.5)
    await runtime.shutdown()


async def test_spawn_link_simple():
    """Test spawn_link behavior."""
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    print("\n=== Simple Spawn Link Test ===")
    
    parent_died = False
    
    async def parent():
        nonlocal parent_died
        try:
            print(f"Parent {runtime.self()} starting")
            
            # Use spawn_link
            child = await runtime.spawn_link(child_proc)
            print(f"Parent linked to child: {child}")
            
            # Wait
            await asyncio.sleep(1.0)
            print("Parent survived (shouldn't happen)")
        except asyncio.CancelledError:
            parent_died = True
            print("Parent cancelled due to link")
            raise
    
    async def child_proc():
        print(f"Child {runtime.self()} starting")
        await asyncio.sleep(0.1)
        print("Child crashing")
        raise RuntimeError("Child crash")
    
    parent_pid = await runtime.spawn(parent)
    
    # Wait for propagation
    await asyncio.sleep(0.5)
    
    parent_alive = runtime.is_alive(parent_pid)
    print(f"Parent alive: {parent_alive}, Parent died flag: {parent_died}")
    
    await runtime.shutdown()
    return not parent_alive  # Should be dead


async def main():
    # Test 1: Trap exits
    result1 = await test_trap_exits_simple()
    print(f"\nTrap exits test: {'PASS' if result1 else 'FAIL'}")
    
    # Test 2: Process info
    await test_process_info_timing()
    
    # Test 3: Spawn link
    result3 = await test_spawn_link_simple()
    print(f"\nSpawn link test: {'PASS' if result3 else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())