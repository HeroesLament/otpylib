"""
Helper functions and tasks for static supervisor tests.

Static supervisors manage long-running processes that should always be kept alive.
All functions here follow BEAM/OTP semantics: they spawn a worker process and return its PID.
"""

import asyncio
from otpylib import process


# Core long-running tasks

async def sample_task(test_data):
    """Spawns a long-running task that increments counter forever."""
    async def worker():
        while True:
            test_data.exec_count += 1
            await asyncio.sleep(0.05)
    
    return await process.spawn(worker, mailbox=True)


async def sample_task_long_running(test_data):
    """Spawns an explicit long-running task that never exits."""
    async def worker():
        while True:
            test_data.exec_count += 1
            await asyncio.sleep(0.1)
    
    return await process.spawn(worker, mailbox=True)


async def sample_task_with_delay(test_data, delay=0.1):
    """Spawns a task that runs with a delay, then repeats forever."""
    async def worker():
        while True:
            test_data.exec_count += 1
            await asyncio.sleep(delay)
    
    return await process.spawn(worker, mailbox=True)


# Tasks that occasionally crash (to test restart behavior)

async def sample_task_error(test_data):
    """Spawns a task that crashes periodically but should be restarted."""
    async def worker():
        while True:
            test_data.exec_count += 1
            test_data.error_count += 1
            raise RuntimeError("Simulated error for testing restart")
    
    return await process.spawn(worker, mailbox=True)


async def occasional_crash_task(test_data, crash_after=5):
    """Spawns a task that crashes after N iterations to test restart."""
    async def worker():
        iteration = 0
        while True:
            iteration += 1
            test_data.exec_count += 1
            await asyncio.sleep(0.1)
            
            if iteration >= crash_after:
                raise RuntimeError(f"Crashed after {crash_after} iterations")
    
    return await process.spawn(worker, mailbox=True)


# Server-like tasks (simulate real services)

async def database_server(test_data):
    """Spawns a database server that must always be running."""
    async def worker():
        while True:
            test_data.exec_count += 1
            await asyncio.sleep(0.1)
            if test_data.exec_count % 20 == 0:
                raise RuntimeError("Database connection lost")
    
    return await process.spawn(worker, mailbox=True)


async def web_server(test_data):
    """Spawns a web server that must always be running."""
    async def worker():
        while True:
            test_data.exec_count += 1
            await asyncio.sleep(0.05)
    
    return await process.spawn(worker, mailbox=True)


async def cache_server(test_data):
    """Spawns a cache server that must always be running."""
    async def worker():
        while True:
            test_data.exec_count += 1
            await asyncio.sleep(0.08)
    
    return await process.spawn(worker, mailbox=True)


# Tasks for testing supervisor hierarchies

async def worker_task(test_data, worker_id):
    """Spawns a generic worker task for testing multiple children."""
    async def worker():
        while True:
            test_data.exec_count += 1
            await asyncio.sleep(0.1)
            if test_data.exec_count % 15 == 0 and worker_id == 1:
                raise RuntimeError(f"Worker {worker_id} error")
    
    return await process.spawn(worker, mailbox=True)


# Tasks for testing dependencies

async def dependent_task_a(test_data):
    """Spawns task A in a dependent pair."""
    async def worker():
        while True:
            test_data.exec_count += 1
            await asyncio.sleep(0.1)
            if test_data.exec_count % 7 == 0:
                raise RuntimeError("Task A failure")
    
    return await process.spawn(worker, mailbox=True)


async def dependent_task_b(test_data):
    """Spawns task B that depends on task A."""
    async def worker():
        while True:
            if test_data.exec_count > 0:
                test_data.exec_count += 1
            await asyncio.sleep(0.1)
    
    return await process.spawn(worker, mailbox=True)


async def independent_task(test_data):
    """Spawns independent task for one_for_one strategy testing."""
    async def worker():
        local_count = 0
        while True:
            local_count += 1
            test_data.exec_count += 1
            await asyncio.sleep(0.1)
            if local_count % 5 == 0:
                raise RuntimeError("Independent failure")
    
    return await process.spawn(worker, mailbox=True)


# Health monitoring tasks

async def health_check_server(test_data):
    """Spawns a server that can be health-checked."""
    async def worker():
        healthy = True
        while True:
            test_data.exec_count += 1
            
            if test_data.exec_count % 10 == 0:
                healthy = False
            
            if not healthy and test_data.exec_count % 15 == 0:
                raise RuntimeError("Health check failed")
            
            if test_data.exec_count % 20 == 0:
                healthy = True
            
            await asyncio.sleep(0.05)
    
    return await process.spawn(worker, mailbox=True)


async def monitored_task(test_data, crash_after=None):
    """Spawns a task that can be monitored and optionally crashes."""
    async def worker():
        iterations = 0
        while True:
            iterations += 1
            test_data.exec_count += 1
            
            if crash_after and iterations >= crash_after:
                raise RuntimeError(f"Crashed after {crash_after} iterations")
            
            await asyncio.sleep(0.05)
    
    return await process.spawn(worker, mailbox=True)


# Stateful server tasks

async def stateful_server(test_data, initial_state=0):
    """Spawns a server that maintains state across iterations (lost on restart)."""
    async def worker():
        state = initial_state
        while True:
            state += 1
            test_data.exec_count = state
            await asyncio.sleep(0.1)
            if state > 5:
                raise RuntimeError("State overflow")
    
    return await process.spawn(worker, mailbox=True)


async def counter_server(test_data):
    """Spawns a simple counter server that increments on each loop."""
    async def worker():
        while True:
            test_data.exec_count += 1
            await asyncio.sleep(0.05)
            if test_data.exec_count > 10:
                test_data.exec_count = 0
    
    return await process.spawn(worker, mailbox=True)


async def run_in_process(coro_func, name="test_proc"):
    """Run the given coroutine inside a spawned process and wait for it to finish."""
    pid = await process.spawn(coro_func, name=name, mailbox=True)
    try:
        while process.is_alive(pid):
            await asyncio.sleep(0.05)
    finally:
        if process.is_alive(pid):
            await process.exit(pid, "shutdown")
        await asyncio.sleep(0.05)