#!/usr/bin/env python3
"""
dynamic_self_msg_pool.py

A dynamic supervisor managing self-messaging workers that can be
added and removed at runtime.
"""

import anyio
import anyio.abc
from otpylib import dynamic_supervisor, mailbox, types
import random


async def self_messaging_worker(worker_id: str, tick_interval: float = 2.0):
    """
    A worker that sends periodic messages to itself.
    
    Args:
        worker_id: Unique identifier for this worker
        tick_interval: How often to tick (seconds)
    """
    # Create a mailbox for this worker
    async with mailbox.open(worker_id) as mid:
        tick_count = 0
        work_count = 0
        
        print(f"🚀 {worker_id} started (interval: {tick_interval}s)")
        
        # Send initial tick to ourselves
        await mailbox.send(worker_id, "tick")
        
        while True:
            msg = await mailbox.receive(mid)
            
            match msg:
                case "tick":
                    tick_count += 1
                    print(f"  ⏰ {worker_id}: Tick #{tick_count}")
                    
                    # Every 3 ticks, send ourselves work
                    if tick_count % 3 == 0:
                        await mailbox.send(worker_id, f"work_{tick_count}")
                    
                    # Schedule next tick
                    async def send_next_tick():
                        await anyio.sleep(tick_interval)
                        try:
                            await mailbox.send(worker_id, "tick")
                        except:
                            pass  # Worker might be shutting down
                    
                    # Need a task group to spawn the background task
                    # In real code, you'd manage this differently
                    
                case str(msg) if msg.startswith("work_"):
                    work_count += 1
                    print(f"  💼 {worker_id}: Processing {msg} (#{work_count})")
                    await anyio.sleep(0.1)  # Simulate work
                    
                case {"type": "external_work", "data": data}:
                    work_count += 1
                    print(f"  📥 {worker_id}: External work: {data}")
                    # Send self a completion message
                    await mailbox.send(worker_id, "work_done")
                    
                case "work_done":
                    print(f"  ✅ {worker_id}: Work completed")
                    
                case "stop":
                    print(f"👋 {worker_id}: Stopping (stats: {tick_count} ticks, {work_count} work)")
                    break
                    
                case _:
                    print(f"  ❓ {worker_id}: Unknown message: {msg}")


async def ticker_task(worker_id: str, interval: float):
    """Separate ticker task that sends ticks to a worker."""
    while True:
        await anyio.sleep(interval)
        try:
            await mailbox.send(worker_id, "tick")
        except:
            break  # Worker gone


async def main():
    """Run dynamic supervisor with self-messaging workers."""
    print("=== Dynamic Self-Messaging Worker Pool ===\n")
    
    # Dynamic supervisor options
    opts = dynamic_supervisor.options(
        strategy=types.OneForOne(),
        max_restarts=3,
        max_seconds=60
    )
    
    async with anyio.create_task_group() as tg:
        # Start dynamic supervisor
        handle = await tg.start(
            dynamic_supervisor.start,
            [],  # Start with no children
            opts,
            "worker_pool"  # Supervisor name
        )
        
        print("Dynamic supervisor started")
        
        # Phase 1: Add first worker with its ticker
        print("\n📌 Phase 1: Adding worker_1...")
        
        worker_1_spec = dynamic_supervisor.child_spec(
            id="worker_1",
            task=self_messaging_worker,
            args=["worker_1", 2.0],
            restart=types.Permanent()
        )
        result = await dynamic_supervisor.start_child("worker_pool", worker_1_spec)
        print(f"  Result: {result}")
        
        # Add ticker for worker_1
        ticker_1_spec = dynamic_supervisor.child_spec(
            id="ticker_1",
            task=ticker_task,
            args=["worker_1", 2.0],
            restart=types.Permanent()
        )
        await dynamic_supervisor.start_child("worker_pool", ticker_1_spec)
        
        await anyio.sleep(5.0)
        
        # Phase 2: Add second worker with faster tick
        print("\n📌 Phase 2: Adding worker_2 (fast)...")
        
        worker_2_spec = dynamic_supervisor.child_spec(
            id="worker_2",
            task=self_messaging_worker,
            args=["worker_2", 1.0],
            restart=types.Permanent()
        )
        await dynamic_supervisor.start_child("worker_pool", worker_2_spec)
        
        ticker_2_spec = dynamic_supervisor.child_spec(
            id="ticker_2",
            task=ticker_task,
            args=["worker_2", 1.0],
            restart=types.Permanent()
        )
        await dynamic_supervisor.start_child("worker_pool", ticker_2_spec)
        
        await anyio.sleep(5.0)
        
        # Phase 3: Send external work
        print("\n📌 Phase 3: Sending external work...")
        
        await mailbox.send("worker_1", {"type": "external_work", "data": "Task-A"})
        await mailbox.send("worker_2", {"type": "external_work", "data": "Task-B"})
        
        await anyio.sleep(3.0)
        
        # Phase 4: Add temporary worker
        print("\n📌 Phase 4: Adding temporary worker...")
        
        temp_worker_spec = dynamic_supervisor.child_spec(
            id="temp_worker",
            task=self_messaging_worker,
            args=["temp_worker", 1.5],
            restart=types.Transient()  # Won't restart if it exits normally
        )
        await dynamic_supervisor.start_child("worker_pool", temp_worker_spec)
        
        temp_ticker_spec = dynamic_supervisor.child_spec(
            id="temp_ticker",
            task=ticker_task,
            args=["temp_worker", 1.5],
            restart=types.Transient()
        )
        await dynamic_supervisor.start_child("worker_pool", temp_ticker_spec)
        
        await anyio.sleep(4.0)
        
        # Phase 5: Stop temporary worker
        print("\n📌 Phase 5: Stopping temporary worker...")
        
        await mailbox.send("temp_worker", "stop")
        await anyio.sleep(1.0)
        
        # Show active children
        children = handle.list_children()
        print(f"\n📊 Active children: {len(children)}")
        for child_id in children:
            print(f"  - {child_id}")
        
        await anyio.sleep(3.0)
        
        # Phase 6: Shutdown
        print("\n📌 Phase 6: Shutting down...")
        
        # Stop all workers
        for worker in ["worker_1", "worker_2"]:
            try:
                await mailbox.send(worker, "stop")
            except:
                pass
        
        await anyio.sleep(1.0)
        
        # Shutdown supervisor
        await handle.shutdown()
    
    print("\nSupervisor stopped")


# Initialize mailbox registry and run
mailbox.init_mailbox_registry()
anyio.run(main)
