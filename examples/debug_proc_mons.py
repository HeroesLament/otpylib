"""
Debug script to understand monitor behavior.
"""

import asyncio
import logging
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend
from otpylib.runtime.atoms import DOWN, NORMAL

logging.basicConfig(level=logging.DEBUG)


async def test_basic_monitor():
    """Test basic monitoring."""
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    print("\n=== Basic Monitor Test ===")
    
    messages = []
    
    async def watcher():
        print(f"Watcher {runtime.self()} starting")
        
        # Wait for target to register
        await asyncio.sleep(0.05)
        
        # Monitor by name
        target_pid = runtime.whereis("target")
        print(f"Target PID: {target_pid}")
        
        if target_pid:
            ref = await runtime.monitor(target_pid)
            print(f"Monitoring with ref: {ref}")
        else:
            print("Target not found!")
            return
        
        # Wait for DOWN message
        try:
            msg = await runtime.receive(timeout=1.0)
            print(f"Watcher received: {msg}")
            messages.append(msg)
        except asyncio.TimeoutError:
            print("Watcher timeout - no message received")
    
    async def target():
        await runtime.register("target")
        print(f"Target {runtime.self()} registered")
        await asyncio.sleep(0.1)
        print("Target exiting normally")
    
    # Start watcher first
    watcher_pid = await runtime.spawn(watcher)
    await asyncio.sleep(0.01)
    
    # Then target
    target_pid = await runtime.spawn(target)
    
    # Wait for completion
    await asyncio.sleep(0.5)
    
    print(f"Messages received: {messages}")
    
    # Check if watcher is still alive
    watcher_alive = runtime.is_alive(watcher_pid)
    print(f"Watcher still alive: {watcher_alive}")
    
    await runtime.shutdown()
    
    return len(messages) > 0


async def test_monitor_crash():
    """Test monitoring a crashing process."""
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    print("\n=== Monitor Crash Test ===")
    
    messages = []
    
    async def watcher():
        print(f"Watcher {runtime.self()} starting")
        
        # Wait for target
        await asyncio.sleep(0.05)
        target_pid = runtime.whereis("crasher")
        
        if target_pid:
            ref = await runtime.monitor(target_pid)
            print(f"Monitoring crasher with ref: {ref}")
        else:
            print("Crasher not found!")
            return
        
        # Wait for DOWN
        try:
            msg = await runtime.receive(timeout=1.0)
            print(f"Watcher received: {msg}")
            messages.append(msg)
            
            # Check message format
            if msg and isinstance(msg, tuple) and len(msg) >= 4:
                print(f"  DOWN type: {msg[0]}")
                print(f"  Ref: {msg[1]}")
                print(f"  PID: {msg[2]}")
                print(f"  Reason: {msg[3]}")
        except asyncio.TimeoutError:
            print("Watcher timeout")
    
    async def crasher():
        await runtime.register("crasher")
        print(f"Crasher {runtime.self()} registered")
        await asyncio.sleep(0.1)
        print("Crasher about to crash!")
        raise RuntimeError("Intentional crash")
    
    # Start watcher first
    await runtime.spawn(watcher)
    await asyncio.sleep(0.01)
    
    # Then crasher
    await runtime.spawn(crasher)
    
    # Wait for everything
    await asyncio.sleep(0.5)
    
    print(f"Messages received: {messages}")
    
    await runtime.shutdown()
    
    return len(messages) > 0


async def test_multiple_monitors():
    """Test multiple monitors on same process."""
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    print("\n=== Multiple Monitors Test ===")
    
    refs = []
    messages = []
    
    async def multi_watcher():
        print(f"Multi-watcher {runtime.self()} starting")
        
        # Wait for target
        await asyncio.sleep(0.05)
        target_pid = runtime.whereis("target")
        
        if not target_pid:
            print("Target not found!")
            return
        
        # Monitor same process twice
        ref1 = await runtime.monitor(target_pid)
        ref2 = await runtime.monitor(target_pid)
        
        print(f"Monitor refs: {ref1}, {ref2}")
        refs.append(ref1)
        refs.append(ref2)
        
        # Should get two DOWN messages
        for i in range(2):
            try:
                msg = await runtime.receive(timeout=0.5)
                print(f"Received message {i+1}: {msg}")
                messages.append(msg)
            except asyncio.TimeoutError:
                print(f"Timeout waiting for message {i+1}")
                break
    
    async def target():
        await runtime.register("target")
        print(f"Target {runtime.self()} registered")
        await asyncio.sleep(0.1)
        print("Target exiting")
    
    # Start watcher
    await runtime.spawn(multi_watcher)
    await asyncio.sleep(0.01)
    
    # Start target
    await runtime.spawn(target)
    
    # Wait
    await asyncio.sleep(0.7)
    
    print(f"Total messages received: {len(messages)}")
    print(f"Unique refs: {len(set(refs))}")
    
    await runtime.shutdown()
    
    return len(messages) == 2


async def main():
    result1 = await test_basic_monitor()
    print(f"\nBasic monitor test: {'PASS' if result1 else 'FAIL'}")
    
    result2 = await test_monitor_crash()
    print(f"\nMonitor crash test: {'PASS' if result2 else 'FAIL'}")
    
    result3 = await test_multiple_monitors()
    print(f"\nMultiple monitors test: {'PASS' if result3 else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
