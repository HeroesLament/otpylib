#!/usr/bin/env python3
"""
Hello Logging GenServer

A simple gen_server that demonstrates logging functionality.
"""

import anyio
import types
from otpylib import gen_server, logging, mailbox


# Create callbacks namespace
callbacks = types.SimpleNamespace()


async def init(_init_arg):
    """Initialize with logging."""
    logger = logging.getLogger("hello_logger_server")
    logger.info("Hello Logger GenServer starting up")
    return {"message_count": 0}

callbacks.init = init


async def handle_call(message, _caller, state):
    """Handle calls with logging."""
    logger = logging.getLogger("hello_logger_server")
    
    match message:
        case "get_count":
            logger.info("Getting message count", count=state["message_count"])
            return (gen_server.Reply(payload=state["message_count"]), state)
        
        case "hello":
            state["message_count"] += 1
            logger.info("Received hello message", 
                       total_messages=state["message_count"])
            return (gen_server.Reply(payload="Hello back!"), state)
        
        case _:
            logger.warning("Unknown call received", message=message)
            return (gen_server.Reply(payload="Unknown command"), state)

callbacks.handle_call = handle_call


async def handle_cast(message, state):
    """Handle casts with logging."""
    logger = logging.getLogger("hello_logger_server")
    
    match message:
        case "stop":
            logger.info("Received stop command")
            return (gen_server.Stop(), state)
        
        case _:
            logger.debug("Unknown cast", message=message)
            return (gen_server.NoReply(), state)

callbacks.handle_cast = handle_cast


async def terminate(reason, state):
    """Log termination."""
    logger = logging.getLogger("hello_logger_server")
    logger.info("GenServer shutting down", 
                reason=reason, 
                final_count=state["message_count"])

callbacks.terminate = terminate


async def main():
    """Demonstrate logging in a GenServer."""
    print("=== Hello Logging GenServer ===")
    
    # Configure logging
    logging.configure_logging(logging.LogLevel.INFO)
    
    async with anyio.create_task_group() as tg:
        # Start the server
        tg.start_soon(gen_server.start, callbacks, None, "hello_logger")
        
        await anyio.sleep(0.1)  # Let server start
        
        # Use the server with logging
        response = await gen_server.call("hello_logger", "hello")
        print(f"Response: {response}")
        
        await gen_server.call("hello_logger", "hello")
        count = await gen_server.call("hello_logger", "get_count")
        print(f"Message count: {count}")
        
        # Stop the server
        await gen_server.cast("hello_logger", "stop")
    
    print("Done")


if __name__ == "__main__":
    mailbox.init_mailbox_registry()
    
    anyio.run(main)