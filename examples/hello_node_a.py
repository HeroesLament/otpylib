#!/usr/bin/env python3
"""
Node A - Ping Node

Starts up, registers with EPMD, and sends "ping" messages to Node B.
When it receives "pong" back, waits 1 second and sends another "ping".

Run this first, then run hello_node_b.py in another terminal.
"""

import asyncio
from otpylib import distribution, process, atom, gen_server
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend, AsyncIODistribution


class PingPongModule:
    """Node A module - sends PING and receives PONG"""
    
    __name__ = "PingPongModule"
    
    @staticmethod
    async def init(init_arg):
        print("[Node A] PingPong server started!")
        return {"count": 0}
    
    @staticmethod
    async def handle_info(message, state):
        count = state.get("count", 0)
        
        # Check if it's a pong message
        if isinstance(message, tuple) and len(message) >= 1:
            msg_type = message[0]
            
            # Handle atom types
            if hasattr(msg_type, 'value'):
                msg_type_str = msg_type.value
            else:
                msg_type_str = str(msg_type)
            
            if msg_type_str == "pong":
                print(f"[Node A] <- Received PONG #{count}")
                
                # Wait 1 second then send ping
                await asyncio.sleep(1.0)
                print(f"[Node A] -> Sending PING #{count + 1}")
                await distribution.send("nodeb@127.0.0.1", "pong_server", 
                                       (atom.ensure("ping"),))
                
                return gen_server.NoReply(), {**state, "count": count + 1}
            
            elif msg_type_str == "start":
                await asyncio.sleep(0.5)
                await distribution.send("nodeb@127.0.0.1", "pong_server",
                                       (atom.ensure("ping"),))
                return gen_server.NoReply(), state
        return gen_server.NoReply(), state
    
    @staticmethod
    async def terminate(reason, state):
        print(f"[Node A] Terminating: {reason}")


async def node_a_app():
    """Main application process for Node A"""
    await gen_server.start_link(PingPongModule, None, name="ping_server")
    
    # Wait for Node B to be available, then start
    connected = False
    while not connected:
        try:
            await asyncio.sleep(2)
            # Try to connect to Node B
            await distribution.connect("nodeb@127.0.0.1")
            connected = True
            
            # Send start message to ourselves to begin
            await process.send("ping_server", (atom.ensure("start"),))
            break
        except Exception as e:
            # Node B not ready yet
            print(f"[Node A] Connection failed: {e}, retrying...")
            pass
    
    # Keep running
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        print("[Node A] Application cancelled")
        raise


async def main():
    # Initialize backend
    backend = AsyncIOBackend()
    process.use_runtime(backend)
    
    # Initialize distribution
    dist = AsyncIODistribution(backend, "nodea@127.0.0.1", "pingpong")
    await dist.start()
    distribution.use_distribution(dist)
    
    # Spawn the application as a process
    app_pid = await process.spawn(node_a_app)
    print(f"   App process spawned: {app_pid}")
    
    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\n\n[Node A] Shutting down...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nGoodbye!")