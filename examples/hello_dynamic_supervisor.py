#!/usr/bin/env python3
"""
Hello Dynamic Supervisor

A simple dynamic supervisor example that starts empty,
then adds a worker task at runtime.
"""

import anyio
from otpylib import dynamic_supervisor, supervisor, mailbox


async def hello_worker(worker_id: str):
    """A simple worker that prints messages."""
    for i in range(3):
        print(f"Hello from worker {worker_id}! (message {i+1})")
        await anyio.sleep(1.0)
    
    print(f"Worker {worker_id} finished")


async def main():
    """Run dynamic supervisor and add workers at runtime."""
    print("=== Hello Dynamic Supervisor ===")
    
    # Basic supervisor options
    opts = supervisor.options()
    
    async with anyio.create_task_group() as tg:
        # Start dynamic supervisor with a name so we can reference it
        tg.start_soon(dynamic_supervisor.start, opts, "worker_pool")
        
        # Give the supervisor a moment to start
        await anyio.sleep(0.1)
        
        print("Dynamic supervisor started")
        
        # Add first worker using the named supervisor
        worker_spec = supervisor.child_spec(
            id="worker_1",
            task=hello_worker,
            args=["1"],
            restart=supervisor.restart_strategy.TEMPORARY,
        )
        
        await dynamic_supervisor.start_child("worker_pool", worker_spec)
        print("Added worker 1")
        
        # Wait a bit, then add second worker
        await anyio.sleep(2.0)
        
        worker_spec_2 = supervisor.child_spec(
            id="worker_2", 
            task=hello_worker,
            args=["2"],
            restart=supervisor.restart_strategy.TEMPORARY,
        )
        
        await dynamic_supervisor.start_child("worker_pool", worker_spec_2)
        print("Added worker 2")
        
        # Let workers run for a while
        await anyio.sleep(5.0)
    
    print("Dynamic supervisor demo done")


if __name__ == "__main__":
    mailbox.init_mailbox_registry()
    
    anyio.run(main)