#!/usr/bin/env python3
"""
Hello Supervisor

A simple supervisor example that manages a long-running service worker.
"""

import anyio
import anyio.abc
from otpylib import supervisor, mailbox, types


async def hello_service():
    """A service worker that runs indefinitely."""
    counter = 0
    while True:
        counter += 1
        print(f"Hello from service! (message {counter})")
        await anyio.sleep(1)


async def main():
    """Run supervisor with a permanent service."""
    print("=== Hello Supervisor ===")
    
    # Define one permanent service
    children = [
        supervisor.child_spec(
            id="hello_service",
            task=hello_service,
            args=[],
            restart=types.Permanent(),
        ),
    ]
    
    # Basic supervisor options
    opts = supervisor.options()
    
    # Start supervisor with proper task status handling
    async def run_supervisor():
        async with anyio.create_task_group() as tg:
            # Start the supervisor as a background task with task_status
            handle = await tg.start(supervisor.start, children, opts)
            
            # The supervisor is now running, we have a handle to control it
            print(f"Supervisor started, managing {len(handle.list_children())} children")
            
            # Run for 10 seconds for demo
            await anyio.sleep(10.0)
            
            # Shut down gracefully
            await handle.shutdown()
    
    try:
        await run_supervisor()
    except KeyboardInterrupt:
        pass
    
    print("Supervisor stopped")


if __name__ == "__main__":
    mailbox.init_mailbox_registry()
    
    anyio.run(main)
