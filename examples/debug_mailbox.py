#!/usr/bin/env python3
"""
Debug script to investigate mailbox test failures.
Run with: python debug_mailbox.py
"""

import anyio
import sys
import traceback
from otpylib import mailbox
from otpylib.mailbox.core import NameAlreadyExist, MailboxDoesNotExist


async def test_receive_timeout():
    """Test 1: Investigate receive timeout behavior"""
    print("\n=== TEST 1: Receive Timeout ===")
    
    mailbox._init()
    
    async def consumer(mbox_id):
        try:
            print(f"Consumer waiting for message with 0.1s timeout...")
            message = await mailbox.receive(mbox_id, timeout=0.1)
            print(f"Received: {message}")
            return message
        except TimeoutError as e:
            print(f"Consumer got TimeoutError: {e}")
            raise
        except Exception as e:
            print(f"Consumer got unexpected error: {type(e).__name__}: {e}")
            raise
    
    try:
        # Create mailbox
        mid = mailbox.create()
        print(f"Created mailbox: {mid}")
        
        # Start consumer in task group
        async with anyio.create_task_group() as tg:
            async def run_consumer():
                try:
                    result = await consumer(mid)
                    print(f"Consumer result: {result}")
                except TimeoutError:
                    print("TimeoutError propagated to task")
                except Exception as e:
                    print(f"Exception in task: {type(e).__name__}: {e}")
            
            tg.start_soon(run_consumer)
            
            # Don't send any message - let it timeout
            await anyio.sleep(0.2)
            print("Main task done waiting")
            
    except ExceptionGroup as eg:
        print(f"Got ExceptionGroup with {len(eg.exceptions)} exceptions:")
        for i, e in enumerate(eg.exceptions):
            print(f"  [{i}] {type(e).__name__}: {e}")
    except Exception as e:
        print(f"Unexpected error in main: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        mailbox.destroy(mid)
        print("Mailbox destroyed")


async def test_register_collision():
    """Test 2: Investigate name registration collision"""
    print("\n=== TEST 2: Register Collision ===")
    
    mailbox._init()
    
    mid1 = None
    mid2 = None
    
    try:
        # Create first mailbox with name
        mid1 = mailbox.create()
        print(f"Created mailbox 1: {mid1}")
        
        mailbox.register(mid1, 'pytest')
        print("Registered mailbox 1 as 'pytest'")
        
        # Try to create second mailbox with same name
        mid2 = mailbox.create()
        print(f"Created mailbox 2: {mid2}")
        
        try:
            mailbox.register(mid2, 'pytest')
            print("ERROR: Should not have succeeded registering duplicate name!")
        except NameAlreadyExist as e:
            print(f"Got expected NameAlreadyExist: {e}")
        
        # Now unregister first and try again
        mailbox.unregister('pytest')
        print("Unregistered 'pytest'")
        
        mailbox.register(mid2, 'pytest')
        print("Successfully registered mailbox 2 as 'pytest'")
        
        # Verify we can send to it
        await mailbox.send('pytest', 'test message')
        msg = await mailbox.receive(mid2, timeout=0.1)
        print(f"Received on mailbox 2: {msg}")
        
    except Exception as e:
        print(f"Unexpected error: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        if mid1:
            mailbox.destroy(mid1)
            print("Destroyed mailbox 1")
        if mid2:
            mailbox.destroy(mid2)
            print("Destroyed mailbox 2")


async def test_unregister_behavior():
    """Test 3: Investigate unregister behavior"""
    print("\n=== TEST 3: Unregister Behavior ===")
    
    mailbox._init()
    
    mid = None
    
    try:
        # Create and register mailbox
        mid = mailbox.create()
        print(f"Created mailbox: {mid}")
        
        mailbox.register(mid, 'pytest')
        print("Registered as 'pytest'")
        
        # Send a message to verify it works
        await mailbox.send('pytest', 'message 1')
        msg = await mailbox.receive(mid, timeout=0.1)
        print(f"Received: {msg}")
        
        # Unregister the name
        mailbox.unregister('pytest')
        print("Unregistered 'pytest'")
        
        # Try to send to the name (should fail)
        try:
            await mailbox.send('pytest', 'message 2')
            print("ERROR: Should not have succeeded sending to unregistered name!")
        except MailboxDoesNotExist as e:
            print(f"Got expected MailboxDoesNotExist: {e}")
        
        # But we should still be able to send using the mid directly
        await mailbox.send(mid, 'message 3')
        msg = await mailbox.receive(mid, timeout=0.1)
        print(f"Received via mid directly: {msg}")
        
    except Exception as e:
        print(f"Unexpected error: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        if mid:
            mailbox.destroy(mid)
            print("Destroyed mailbox")


async def test_context_manager():
    """Test 4: Investigate context manager behavior"""
    print("\n=== TEST 4: Context Manager ===")
    
    mailbox._init()
    
    try:
        # Test without name
        async with mailbox.open() as mid:
            print(f"Opened mailbox: {mid}")
            await mailbox.send(mid, 'test')
            msg = await mailbox.receive(mid, timeout=0.1)
            print(f"Received: {msg}")
        print("Context manager exited successfully")
        
        # Test with name
        async with mailbox.open(name='test_ctx') as mid:
            print(f"Opened named mailbox: {mid}")
            await mailbox.send('test_ctx', 'test via name')
            msg = await mailbox.receive(mid, timeout=0.1)
            print(f"Received: {msg}")
        print("Named context manager exited successfully")
        
        # Verify name is cleaned up
        try:
            await mailbox.send('test_ctx', 'should fail')
            print("ERROR: Name wasn't cleaned up!")
        except MailboxDoesNotExist:
            print("Name was properly cleaned up")
            
    except Exception as e:
        print(f"Unexpected error: {type(e).__name__}: {e}")
        traceback.print_exc()


async def main():
    """Run all debug tests"""
    print("Starting mailbox debug investigation...")
    
    await test_receive_timeout()
    await test_register_collision()
    await test_unregister_behavior()
    await test_context_manager()
    
    print("\n=== Debug Complete ===")


if __name__ == "__main__":
    try:
        anyio.run(main)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)