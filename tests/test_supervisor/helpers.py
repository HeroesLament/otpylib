"""Helper functions and tasks for supervisor tests."""

import anyio


async def sample_task(test_data):
    """Long-running task that just increments counter forever."""
    while True:
        test_data.exec_count += 1
        await anyio.sleep(0.05)  # simulate ongoing work


async def sample_task_error(test_data):
    """Task that increments counter then raises error repeatedly."""
    while True:
        test_data.exec_count += 1
        test_data.error_count += 1
        # Simulate a crash on each iteration
        raise RuntimeError("pytest")


async def sample_task_long_running(test_data):
    """Explicit long-running task that never exits."""
    while True:
        test_data.exec_count += 1
        await anyio.sleep_forever()


async def sample_task_with_delay(test_data, delay=0.1):
    """Task that runs with a delay, then repeats forever."""
    while True:
        test_data.exec_count += 1
        await anyio.sleep(delay)


async def sample_task_with_completion(test_data):
    """Task that runs once, signals completion, and then stops."""
    test_data.exec_count += 1
    test_data.completed.set()
