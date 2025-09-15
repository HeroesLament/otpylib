#!/usr/bin/env python3
"""
Hello Dynamic Supervisor

A simple dynamic supervisor example that starts empty,
then adds worker tasks at runtime.

All worker functions now properly support the task_status parameter
as required by the updated otpylib 0.3.4 API.
"""

import anyio
import anyio.abc
from otpylib import dynamic_supervisor, mailbox
from otpylib.types import Transient, Permanent, OneForOne
from result import Ok, Err


async def hello_worker(worker_id: str, *, task_status: anyio.abc.TaskStatus):
    """A simple worker that prints messages."""
    # Signal that the worker has started successfully
    task_status.started()
    
    for i in range(5):
        print(f"Hello from worker {worker_id}! (message {i+1})")
        await anyio.sleep(1.0)
    
    print(f"Worker {worker_id} finished normally")


async def long_running_worker(worker_id: str, *, task_status: anyio.abc.TaskStatus):
    """A worker that runs indefinitely until cancelled."""
    # Signal that the worker has started successfully
    task_status.started()
    
    counter = 0
    try:
        while True:
            counter += 1
            print(f"Long-running worker {worker_id} tick {counter}")
            await anyio.sleep(2.0)
    except anyio.get_cancelled_exc_class():
        print(f"Long-running worker {worker_id} was cancelled after {counter} ticks")
        raise


async def worker_health_check(child_id: str, child_process) -> "Result[None, str]":
    """Simple health check that always passes."""
    return Ok(None)


async def main():
    """Run dynamic supervisor and add workers at runtime."""
    print("=== Hello Dynamic Supervisor ===")
    
    opts = dynamic_supervisor.options(
        max_restarts=2,
        max_seconds=10,
        strategy=OneForOne()
    )
    
    mailbox.init_mailbox_registry()
    
    async with anyio.create_task_group() as tg:
        supervisor_handle = await tg.start(
            dynamic_supervisor.start,
            [],
            opts,
            "worker_pool"
        )
        
        print("Dynamic supervisor started")
        
        # Add temporary workers
        worker_spec_1 = dynamic_supervisor.child_spec(
            id="temp_worker_1",
            task=hello_worker,
            args=["TEMP-1"],
            restart=Transient(),
            health_check_enabled=False
        )
        
        await dynamic_supervisor.start_child("worker_pool", worker_spec_1)
        await anyio.sleep(2.0)
        
        worker_spec_2 = dynamic_supervisor.child_spec(
            id="temp_worker_2", 
            task=hello_worker,
            args=["TEMP-2"],
            restart=Transient(),
            health_check_enabled=False
        )
        
        await dynamic_supervisor.start_child("worker_pool", worker_spec_2)
        await anyio.sleep(1.0)
        
        # Add persistent worker with health checks
        persistent_worker_spec = dynamic_supervisor.child_spec(
            id="persistent_worker",
            task=long_running_worker,
            args=["PERSISTENT"],
            restart=Permanent(),
            health_check_enabled=True,
            health_check_interval=10.0,
            health_check_fn=worker_health_check
        )
        
        await dynamic_supervisor.start_child("worker_pool", persistent_worker_spec)
        
        # Show status
        await anyio.sleep(3.0)
        print(f"Active children: {supervisor_handle.list_children()}")
        
        # Let workers run
        await anyio.sleep(8.0)
        
        # Terminate persistent worker
        await dynamic_supervisor.terminate_child("worker_pool", "persistent_worker")
        
        # Add final worker
        final_worker_spec = dynamic_supervisor.child_spec(
            id="final_worker",
            task=hello_worker,
            args=["FINAL"],
            restart=Transient()
        )
        
        await dynamic_supervisor.start_child("worker_pool", final_worker_spec)
        await anyio.sleep(6.0)
        
        await supervisor_handle.shutdown()
    
    print("Demo completed")


if __name__ == "__main__":
    anyio.run(main)
