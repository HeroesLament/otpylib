"""
Helper functions and tasks for static supervisor tests.

Static supervisors manage long-running processes that should always be kept alive.
"""

import asyncio
from otpylib import process


# Core long-running tasks

async def sample_task(test_data):
    """Long-running task that increments counter forever."""
    while True:
        test_data.exec_count += 1
        await asyncio.sleep(0.05)  # simulate ongoing work


async def sample_task_long_running(test_data):
    """Explicit long-running task that never exits."""
    while True:
        test_data.exec_count += 1
        await asyncio.sleep(0.1)  # Simulate work while other tasks run


async def sample_task_with_delay(test_data, delay=0.1):
    """Task that runs with a delay, then repeats forever."""
    while True:
        test_data.exec_count += 1
        await asyncio.sleep(delay)


# Tasks that occasionally crash (to test restart behavior)

async def sample_task_error(test_data):
    """Task that crashes periodically but should be restarted."""
    while True:
        test_data.exec_count += 1
        test_data.error_count += 1
        # Simulate a crash - supervisor should restart us
        raise RuntimeError("Simulated error for testing restart")


async def occasional_crash_task(test_data, crash_after=5):
    """Task that crashes after N iterations to test restart."""
    iteration = 0
    while True:
        iteration += 1
        test_data.exec_count += 1
        await asyncio.sleep(0.1)
        
        if iteration >= crash_after:
            raise RuntimeError(f"Crashed after {crash_after} iterations")


# Server-like tasks (simulate real services)

async def database_server(test_data):
    """Simulates a database server that must always be running."""
    while True:
        test_data.exec_count += 1
        # Simulate database operations
        await asyncio.sleep(0.1)
        # Occasionally simulate a connection error that requires restart
        if test_data.exec_count % 20 == 0:
            raise RuntimeError("Database connection lost")


async def web_server(test_data):
    """Simulates a web server that must always be running."""
    while True:
        test_data.exec_count += 1
        # Simulate handling requests
        await asyncio.sleep(0.05)


async def cache_server(test_data):
    """Simulates a cache server that must always be running."""
    while True:
        test_data.exec_count += 1
        # Simulate cache operations
        await asyncio.sleep(0.08)


# Tasks for testing supervisor hierarchies

async def worker_task(test_data, worker_id):
    """Generic worker task for testing multiple children."""
    while True:
        test_data.exec_count += 1
        await asyncio.sleep(0.1)
        # Workers can crash occasionally
        if test_data.exec_count % 15 == 0 and worker_id == 1:
            raise RuntimeError(f"Worker {worker_id} error")


# Tasks for testing dependencies

async def dependent_task_a(test_data):
    """Task A in a dependent pair."""
    while True:
        test_data.exec_count += 1
        await asyncio.sleep(0.1)
        # Crash occasionally to test rest_for_one strategy
        if test_data.exec_count % 7 == 0:
            raise RuntimeError("Task A failure")


async def dependent_task_b(test_data):
    """Task B that depends on task A."""
    while True:
        # Only increment if A has run
        if test_data.exec_count > 0:
            test_data.exec_count += 1
        await asyncio.sleep(0.1)


async def independent_task(test_data):
    """Independent task for one_for_one strategy testing."""
    local_count = 0
    while True:
        local_count += 1
        test_data.exec_count += 1
        await asyncio.sleep(0.1)
        # Crash independently
        if local_count % 5 == 0:
            raise RuntimeError("Independent failure")


# Health monitoring tasks

async def health_check_server(test_data):
    """Server that can be health-checked."""
    healthy = True
    while True:
        test_data.exec_count += 1
        
        # Simulate becoming unhealthy
        if test_data.exec_count % 10 == 0:
            healthy = False
        
        # Crash if unhealthy for too long
        if not healthy and test_data.exec_count % 15 == 0:
            raise RuntimeError("Health check failed")
        
        # Recover
        if test_data.exec_count % 20 == 0:
            healthy = True
        
        await asyncio.sleep(0.05)


async def monitored_task(test_data, crash_after=None):
    """Task that can be monitored and optionally crashes."""
    iterations = 0
    while True:
        iterations += 1
        test_data.exec_count += 1
        
        if crash_after and iterations >= crash_after:
            raise RuntimeError(f"Crashed after {crash_after} iterations")
        
        await asyncio.sleep(0.05)


# Stateful server tasks

async def stateful_server(test_data, initial_state=0):
    """Server that maintains state across iterations (lost on restart)."""
    state = initial_state
    while True:
        state += 1
        test_data.exec_count = state
        await asyncio.sleep(0.1)
        # Crash if state gets too high (for testing restart with state reset)
        if state > 5:
            raise RuntimeError("State overflow")


async def counter_server(test_data):
    """Simple counter server that increments on each loop."""
    while True:
        test_data.exec_count += 1
        await asyncio.sleep(0.05)
        # Simulate handling messages
        if test_data.exec_count > 10:
            # Reset counter periodically
            test_data.exec_count = 0


async def run_in_process(coro_func, name="test_proc"):
    """Run the given coroutine inside a spawned process and wait for it to finish."""
    pid = await process.spawn(coro_func, name=name, mailbox=True)
    try:
        while process.is_alive(pid):
            await asyncio.sleep(0.05)
    finally:
        # Ensure process is fully cleaned up
        if process.is_alive(pid):
            await process.exit(pid, "shutdown")
        # Give time for cleanup
        await asyncio.sleep(0.05)
