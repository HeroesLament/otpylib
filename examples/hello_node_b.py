#!/usr/bin/env python3
"""
Node B - Pong Node

Starts up, registers with EPMD, and receives "ping" messages from Node A.
When it receives "ping", immediately sends "pong" back.

Run hello_node_a.py first, then run this in another terminal.
"""

import asyncio
from otpylib import distribution, process, atom, gen_server
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend, AsyncIODistribution


class PongPongModule:
    """Node B module - receives PING and sends PONG"""
    
    __name__ = "PongPongModule"
    
    @staticmethod
    async def init(init_arg):
        print("[Node B] PongPong server started!")
        return {"count": 0}
    
    @staticmethod
    async def handle_info(message, state):
        count = state.get("count", 0)
        
        # Check if it's a ping message
        if isinstance(message, tuple) and len(message) >= 1:
            msg_type = message[0]
            
            # Handle atom types
            if hasattr(msg_type, 'value'):
                msg_type_str = msg_type.value
            else:
                msg_type_str = str(msg_type)
            
            if msg_type_str == "ping":
                print(f"[Node B] <- Received PING #{count}")
                
                # Immediately send pong back
                print(f"[Node B] -> Sending PONG #{count}")
                await distribution.send("nodea@127.0.0.1", "ping_server",
                                       (atom.ensure("pong"),))
                
                return gen_server.NoReply(), {**state, "count": count + 1}
        
        print(f"[Node B] Received unknown message: {message}")
        return gen_server.NoReply(), state
    
    @staticmethod
    async def terminate(reason, state):
        print(f"[Node B] Terminating: {reason}")


async def node_b_app():
    """Main application process for Node B"""
    print("\n" + "=" * 60)
    print("Node B - Pong Node")
    print("=" * 60 + "\n")
    
    # Start pong server and register it
    print("3. Starting PongPong server...")
    await gen_server.start_link(PongPongModule, None, name="pong_server")
    print("   ✓ PongPong server registered as 'pong_server'")
    
    print("\n" + "=" * 60)
    print("Ready! Waiting for ping from Node A...")
    print("=" * 60 + "\n")
    
    # Keep running
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        print("[Node B] Application cancelled")
        raise


async def main():
    # Initialize backend
    print("1. Initializing AsyncIO backend...")
    backend = AsyncIOBackend()
    process.use_runtime(backend)
    print("   ✓ Backend ready")
    
    # Initialize distribution
    print("2. Setting up distribution layer...")
    dist = AsyncIODistribution(backend, "nodeb@127.0.0.1", "pingpong")
    await dist.start()
    distribution.use_distribution(dist)
    print(f"   ✓ Node 'nodeb@127.0.0.1' listening on port {dist.port}")
    
    # Spawn the application as a process
    app_pid = await process.spawn(node_b_app)
    print(f"   ✓ App process spawned: {app_pid}")
    
    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\n\n[Node B] Shutting down...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nGoodbye!")