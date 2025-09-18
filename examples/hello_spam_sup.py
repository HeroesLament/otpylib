#!/usr/bin/env python3
"""
Hello Supervisor with SPAM Runtime

A supervisor example that demonstrates SPAM scheduling integration.
"""

import anyio
from otpylib import supervisor, mailbox, types
from otpylib.runtime import set_runtime
from otpylib.spam.runtime import SPAMRuntime
from otpylib.spam.backend import SPAMBackend

async def hello_service():
    """A service worker that runs indefinitely."""
    counter = 0
    while True:
        counter += 1
        print(f"Hello from service! (message {counter})")
        await anyio.sleep(1)

async def main():
    """Run supervisor with SPAM runtime."""
    print("=== Hello Supervisor with SPAM ===")
    mailbox.init_mailbox_registry()
    
    # Option 1: Context manager approach
    async with SPAMRuntime() as spam_runtime:
        # Set SPAM as the active runtime backend
        set_runtime(SPAMBackend(spam_runtime))
        
        # Now supervisor.start() will use SPAM scheduling transparently
        children = [
            supervisor.child_spec(
                id="hello_service",
                task=hello_service,
                args=[],
                restart=types.Permanent(),
            ),
        ]
        
        opts = supervisor.options()
        
        async with anyio.create_task_group() as tg:
            handle = await tg.start(supervisor.start, children, opts)
            print(f"SPAM-managed supervisor started with {len(handle.list_children())} children")
            
            await anyio.sleep(10.0)
            await handle.shutdown()

if __name__ == "__main__":
    anyio.run(main)