#!/usr/bin/env python3
"""
Hello Supervisor

A simple supervisor example that manages a long-running service worker.
"""

import anyio
from otpylib import supervisor, mailbox


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
            restart=supervisor.restart_strategy.PERMANENT,
        ),
    ]
    
    # Basic supervisor options
    opts = supervisor.options()
    
    # Start supervisor - runs until explicitly cancelled
    try:
        with anyio.move_on_after(10.0):  # Cancel after 10 seconds for demo
            await supervisor.start(children, opts)
    except KeyboardInterrupt:
        pass
    
    print("Supervisor stopped")


if __name__ == "__main__":
    mailbox.init_mailbox_registry()
    
    anyio.run(main)