#!/usr/bin/env python3
"""
Multi GenServer Logging Example

Demonstrates three different gen_servers with distinct logging patterns
to show clean, readable logging output.
"""

import anyio
import types
import random
from otpylib import gen_server, logging, mailbox


# === Database Manager GenServer ===
db_callbacks = types.SimpleNamespace()

async def db_init(_init_arg):
    """Initialize database manager."""
    logger = logging.getLogger("database_manager")
    logger.info("Database manager starting")
    return {"connections": 0, "queries": 0, "errors": 0}

db_callbacks.init = db_init

async def db_handle_call(message, _caller, state):
    """Handle database operations."""
    logger = logging.getLogger("database_manager")
    
    match message:
        case ("query", sql):
            state["queries"] += 1
            # Simulate random success/failure
            if random.random() > 0.2:
                execution_time = random.randint(5, 200)
                rows = random.randint(0, 100)
                logger.info(f"Query executed successfully in {execution_time}ms, {rows} rows affected")
                return (gen_server.Reply(payload="success"), state)
            else:
                state["errors"] += 1
                logger.error(f"Query failed with DB_TIMEOUT error (total errors: {state['errors']})")
                return (gen_server.Reply(payload="error"), state)
        
        case "get_stats":
            success_rate = round((state["queries"] - state["errors"]) / max(state["queries"], 1) * 100, 2)
            logger.debug(f"Stats requested - queries: {state['queries']}, errors: {state['errors']}, success: {success_rate}%")
            return (gen_server.Reply(payload=state), state)
        
        case _:
            logger.warning(f"Unknown database operation: {message}")
            return (gen_server.Reply(payload="unknown"), state)

db_callbacks.handle_call = db_handle_call

async def db_handle_cast(message, state):
    """Handle database casts."""
    logger = logging.getLogger("database_manager")
    
    match message:
        case "stop":
            logger.info("Database manager received stop command")
            return (gen_server.Stop(), state)
        case _:
            logger.debug(f"Unknown cast: {message}")
            return (gen_server.NoReply(), state)

db_callbacks.handle_cast = db_handle_cast

async def db_terminate(reason, state):
    logger = logging.getLogger("database_manager")
    logger.info(f"Database manager shutting down - reason: {reason}, final stats: {state}")

db_callbacks.terminate = db_terminate


# === HTTP Server GenServer ===
http_callbacks = types.SimpleNamespace()

async def http_init(_init_arg):
    """Initialize HTTP server."""
    logger = logging.getLogger("http_server")
    logger.info("HTTP server starting on 0.0.0.0:8080 with 4 workers")
    return {"requests": 0, "active_connections": 0}

http_callbacks.init = http_init

async def http_handle_call(message, _caller, state):
    """Handle HTTP requests."""
    logger = logging.getLogger("http_server")
    
    match message:
        case ("request", method, path, client_ip):
            state["requests"] += 1
            state["active_connections"] += 1
            
            # Simulate different response types
            status_codes = [200, 200, 200, 404, 500, 301]
            status = random.choice(status_codes)
            response_time = random.randint(10, 500)
            request_id = f"req_{state['requests']}"
            
            if status >= 400:
                logger.warning(f"{method} {path} from {client_ip} -> {status} in {response_time}ms [{request_id}]")
            else:
                bytes_sent = random.randint(100, 5000)
                logger.info(f"{method} {path} from {client_ip} -> {status} in {response_time}ms, {bytes_sent} bytes [{request_id}]")
            
            state["active_connections"] -= 1
            return (gen_server.Reply(payload=status), state)
        
        case "health_check":
            memory_mb = random.randint(50, 200)
            logger.debug(f"Health check - {state['active_connections']} active connections, {state['requests']} total requests, {memory_mb}MB memory")
            return (gen_server.Reply(payload="healthy"), state)
        
        case _:
            logger.error(f"Invalid HTTP server command: {message}")
            return (gen_server.Reply(payload="invalid"), state)

http_callbacks.handle_call = http_handle_call

async def http_handle_cast(message, state):
    """Handle HTTP server casts."""
    logger = logging.getLogger("http_server")
    
    match message:
        case "stop":
            logger.info("HTTP server received stop command")
            return (gen_server.Stop(), state)
        case _:
            logger.debug(f"Unknown cast: {message}")
            return (gen_server.NoReply(), state)

http_callbacks.handle_cast = http_handle_cast

async def http_terminate(reason, state):
    logger = logging.getLogger("http_server")
    logger.info(f"HTTP server shutting down - served {state['requests']} total requests")

http_callbacks.terminate = http_terminate


# === Task Queue GenServer ===
queue_callbacks = types.SimpleNamespace()

async def queue_init(_init_arg):
    """Initialize task queue."""
    logger = logging.getLogger("task_queue")
    logger.info("Task queue starting with max size 1000, 2 worker threads")
    return {"pending": [], "completed": 0, "failed": 0}

queue_callbacks.init = queue_init

async def queue_handle_call(message, _caller, state):
    """Handle queue operations."""
    logger = logging.getLogger("task_queue")
    
    match message:
        case ("enqueue", task_type, priority):
            task_id = f"{task_type}_{len(state['pending']) + state['completed'] + state['failed']}"
            state["pending"].append(task_id)
            
            logger.info(f"Task enqueued: {task_id} (type: {task_type}, priority: {priority}) - queue size: {len(state['pending'])}")
            return (gen_server.Reply(payload=task_id), state)
        
        case "process_next":
            if state["pending"]:
                task_id = state["pending"].pop(0)
                
                # Simulate task processing
                if random.random() > 0.15:
                    state["completed"] += 1
                    processing_time = random.randint(100, 2000)
                    logger.info(f"Task completed: {task_id} in {processing_time}ms - queue size: {len(state['pending'])}")
                    return (gen_server.Reply(payload="completed"), state)
                else:
                    state["failed"] += 1
                    logger.error(f"Task failed: {task_id} with PROCESSING_ERROR - queue size: {len(state['pending'])}")
                    return (gen_server.Reply(payload="failed"), state)
            else:
                logger.debug("No tasks in queue")
                return (gen_server.Reply(payload="empty"), state)
        
        case "get_metrics":
            pending = len(state["pending"])
            completed = state["completed"]
            failed = state["failed"]
            logger.debug(f"Queue metrics - pending: {pending}, completed: {completed}, failed: {failed}")
            return (gen_server.Reply(payload={"pending": pending, "completed": completed, "failed": failed}), state)
        
        case _:
            logger.warning(f"Unknown queue operation: {message}")
            return (gen_server.Reply(payload="unknown"), state)

queue_callbacks.handle_call = queue_handle_call

async def queue_handle_cast(message, state):
    """Handle task queue casts."""
    logger = logging.getLogger("task_queue")
    
    match message:
        case "stop":
            logger.info("Task queue received stop command")
            return (gen_server.Stop(), state)
        case _:
            logger.debug(f"Unknown cast: {message}")
            return (gen_server.NoReply(), state)

queue_callbacks.handle_cast = queue_handle_cast

async def queue_terminate(reason, state):
    logger = logging.getLogger("task_queue")
    pending = len(state["pending"])
    logger.info(f"Task queue shutting down - {pending} pending, {state['completed']} completed, {state['failed']} failed")

queue_callbacks.terminate = queue_terminate


async def main():
    """Demonstrate multiple gen_servers with different logging patterns."""
    print("=== Multi GenServer Logging Example ===")
    
    # Configure logging with pretty human-readable output
    logging.configure_logging(logging.LogLevel.INFO)
    
    async with anyio.create_task_group() as tg:
        # Start all three servers
        await tg.start(gen_server.start, db_callbacks, None, "database_mgr")
        await tg.start(gen_server.start, http_callbacks, None, "http_server")
        await tg.start(gen_server.start, queue_callbacks, None, "task_queue")
        
        await anyio.sleep(0.5)  # Let servers start
        
        print("\n--- Simulating database operations ---")
        await gen_server.call("database_mgr", ("query", "SELECT * FROM users WHERE active = true"))
        await gen_server.call("database_mgr", ("query", "UPDATE products SET price = price * 1.1 WHERE category = 'electronics'"))
        await gen_server.call("database_mgr", ("query", "INSERT INTO logs (message, timestamp) VALUES ('System started', NOW())"))
        
        print("\n--- Simulating HTTP requests ---")
        await gen_server.call("http_server", ("request", "GET", "/api/users", "192.168.1.100"))
        await gen_server.call("http_server", ("request", "POST", "/api/orders", "10.0.1.50"))
        await gen_server.call("http_server", ("request", "GET", "/nonexistent", "172.16.0.25"))
        await gen_server.call("http_server", "health_check")
        
        print("\n--- Simulating task queue operations ---")
        await gen_server.call("task_queue", ("enqueue", "email_send", "high"))
        await gen_server.call("task_queue", ("enqueue", "image_resize", "normal"))
        await gen_server.call("task_queue", ("enqueue", "backup_database", "low"))
        await gen_server.call("task_queue", "process_next")
        await gen_server.call("task_queue", "process_next")
        
        print("\n--- Getting final stats ---")
        db_stats = await gen_server.call("database_mgr", "get_stats")
        queue_metrics = await gen_server.call("task_queue", "get_metrics")
        print(f"DB Stats: {db_stats}")
        print(f"Queue Metrics: {queue_metrics}")
        
        # Stop all servers (fire-and-forget)
        await gen_server.cast("database_mgr", "stop")
        await gen_server.cast("http_server", "stop") 
        await gen_server.cast("task_queue", "stop")
    
    print("Done")


if __name__ == "__main__":
    mailbox.init_mailbox_registry()
    anyio.run(main)
