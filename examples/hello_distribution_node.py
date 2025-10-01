#!/usr/bin/env python3
"""
Simple Distribution Demo using OTPYLIB API

SETUP:
1. Start Erlang node:
   erl -name test@127.0.0.1 -setcookie mycookie

2. In Erlang shell:
   register(test_proc, self()).
   
3. Run this script:
   python hello_distribution_node.py

4. In Erlang shell:
   flush().
"""

import asyncio
from otpylib import distribution, process, atom
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend, AsyncIODistribution


async def debug_epmd_lookup():
    """Debug EPMD lookup to see exact response"""
    import struct
    
    print("\n" + "=" * 60)
    print("EPMD Debug - Looking up 'test' node")
    print("=" * 60 + "\n")
    
    try:
        reader, writer = await asyncio.open_connection('127.0.0.1', 4369)
        
        # Send PORT2_REQ
        name_bytes = b'test'
        message = struct.pack('>HB', len(name_bytes) + 1, 122) + name_bytes
        
        print(f"Sending EPMD PORT2_REQ for 'test'")
        print(f"Request hex: {message.hex()}")
        
        writer.write(message)
        await writer.drain()
        
        # Read response
        response = await reader.read(1024)
        
        print(f"\nReceived {len(response)} bytes")
        print(f"Response hex: {response.hex()}")
        
        if len(response) > 0:
            print(f"\nByte-by-byte parsing:")
            print(f"  [0] Result code: {response[0]} (expect 119 for PORT2_RESP)")
            
            if len(response) >= 3:
                port = struct.unpack('>H', response[1:3])[0]
                print(f"  [1:3] Port (big-endian): {port}")
            
            if len(response) >= 4:
                print(f"  [3] Node type: {response[3]}")
            
            if len(response) >= 5:
                print(f"  [4] Protocol: {response[4]}")
            
            if len(response) >= 7:
                high_ver = struct.unpack('>H', response[5:7])[0]
                print(f"  [5:7] High version: {high_ver}")
            
            if len(response) >= 9:
                low_ver = struct.unpack('>H', response[7:9])[0]
                print(f"  [7:9] Low version: {low_ver}")
            
            if len(response) >= 11:
                name_len = struct.unpack('>H', response[9:11])[0]
                print(f"  [9:11] Name length: {name_len}")
                
                if len(response) >= 11 + name_len:
                    name = response[11:11+name_len]
                    print(f"  [11:{11+name_len}] Name: {name.decode('utf-8')}")
        
        writer.close()
        await writer.wait_closed()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    print("\n" + "=" * 60)
    print("OTPYLIB Distribution Demo")
    print("=" * 60 + "\n")
    
    # First, debug EPMD to see what's there
    await debug_epmd_lookup()
    
    print("\n" + "=" * 60)
    print("Now setting up OTPYLIB distribution...")
    print("=" * 60 + "\n")
    
    # Initialize the AsyncIO backend
    print("1. Initializing AsyncIO backend...")
    backend = AsyncIOBackend()
    process.use_runtime(backend)
    print("   ✓ Backend ready")
    
    # Initialize distribution
    print("2. Setting up distribution layer...")
    dist = AsyncIODistribution(backend, "otpylib@127.0.0.1", "mycookie")
    await dist.start()
    distribution.use_distribution(dist)
    print(f"   ✓ Node listening...")
    
    print("\n" + "=" * 60)
    print("Ready! Now connecting to Erlang...")
    print("=" * 60 + "\n")
    
    try:
        # Connect to Erlang node
        print("Connecting to test@127.0.0.1...")
        await distribution.connect("test@127.0.0.1")
        print("   ✓ Connected!")
        
        # Send a message
        print("\nSending message to 'test_proc'...")
        message = (
            atom.ensure("hello"),
            atom.ensure("from"),
            "OTPYLIB"
        )
        
        await distribution.send("test@127.0.0.1", "test_proc", message)
        
        print("\n" + "=" * 60)
        print("Message sent!")
        print("In your Erlang shell, run: flush()")
        print("You should see: {hello,from,<<\"OTPYLIB\">>}")
        print("=" * 60 + "\n")
        
        # Send a few more messages to demonstrate
        print("Sending more messages...")
        
        await distribution.send("test@127.0.0.1", "test_proc", 
                               (atom.ensure("ping"), 1))
        
        await distribution.send("test@127.0.0.1", "test_proc",
                               (atom.ensure("data"), {"count": 42, "status": "ok"}))
        
        await distribution.send("test@127.0.0.1", "test_proc",
                               [1, 2, 3, atom.ensure("done")])
        
        print("   ✓ Sent 3 more messages - check with flush()")
        
        # Keep connection alive
        print(f"\nNode '{distribution.node_name()}' is running on port {distribution.port()}")
        print("Press Ctrl+C to stop.\n")
        await asyncio.Event().wait()
        
    except ConnectionError as e:
        print(f"\n❌ Connection Error: {e}")
        print("\nMake sure you:")
        print("1. Started Erlang: erl -name test@127.0.0.1 -setcookie mycookie")
        print("2. Registered process: register(test_proc, self()).")
    
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        await distribution.shutdown()
        await backend.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nGoodbye!")