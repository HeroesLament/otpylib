#!/usr/bin/env python3
"""
hello_self_msg_wkr.py

A simple self-messaging worker using just mailbox and supervisor.
Shows how a worker can send messages to itself for periodic tasks.
"""

import anyio
import anyio.abc
from otpylib import supervisor, mailbox, types


async def ticker_task():
    """A separate task that sends periodic ticks to the worker."""
    while True:
        await anyio.sleep(2.0)
        try:
            await mailbox.send("worker", "tick")
        except:
            # Worker might have stopped
            break


async def self_messaging_worker():
    """A worker that processes messages including self-sent ones."""
    # Create a mailbox for this worker
    async with mailbox.open("worker") as mid:
        tick_count = 0
        work_count = 0
        
        print("🚀 Worker started")
        
        while True:
            # Receive messages
            msg = await mailbox.receive(mid)
            
            match msg:
                case "tick":
                    tick_count += 1
                    print(f"⏰ Tick #{tick_count}")
                    
                    # Every 3 ticks, send ourselves a work message
                    if tick_count % 3 == 0:
                        print(f"   → Triggering work after {tick_count} ticks")
                        await mailbox.send("worker", "do_work")
                    
                case "do_work":
                    work_count += 1
                    print(f"💼 Doing work #{work_count}")
                    await anyio.sleep(0.1)  # Simulate work
                    
                case "stop":
                    print("👋 Worker stopping")
                    break
                    
                case _:
                    print(f"❓ Unknown message: {msg}")
        
        print(f"📊 Final stats: {tick_count} ticks, {work_count} work items")


async def main():
    """Run supervisor with self-messaging worker."""
    print("=== Self-Messaging Worker Demo ===")
    
    # Define both the worker and the ticker as supervised children
    children = [
        supervisor.child_spec(
            id="self_msg_worker",
            task=self_messaging_worker,
            args=[],
            restart=types.Permanent(),
        ),
        supervisor.child_spec(
            id="ticker",
            task=ticker_task,
            args=[],
            restart=types.Permanent(),
        ),
    ]
    
    # Basic supervisor options
    opts = supervisor.options()
    
    # Start supervisor
    async def run_supervisor():
        async with anyio.create_task_group() as tg:
            # Start the supervisor
            handle = await tg.start(supervisor.start, children, opts)
            
            print(f"Supervisor started, managing {len(handle.list_children())} children")
            
            # Run for 15 seconds
            await anyio.sleep(15.0)
            
            # Send stop message to worker
            print("\n🛑 Shutting down...")
            await mailbox.send("worker", "stop")
            await anyio.sleep(0.5)
            
            # Shut down supervisor
            await handle.shutdown()
    
    try:
        await run_supervisor()
    except KeyboardInterrupt:
        pass
    
    print("Supervisor stopped")


# Initialize mailbox registry and run
mailbox.init_mailbox_registry()
anyio.run(main)
