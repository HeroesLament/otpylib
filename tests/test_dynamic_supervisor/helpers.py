"""Helper functions and tasks for dynamic supervisor tests."""

import anyio


# Sample tasks for testing

async def sample_task(test_data):
    """Simple task that increments counter."""
    test_data.exec_count += 1


async def sample_task_error(test_data):
    """Task that increments counter then raises error."""
    test_data.exec_count += 1
    test_data.error_count += 1
    raise RuntimeError("pytest")


async def sample_task_long_running(test_data):
    """Task that runs indefinitely."""
    test_data.exec_count += 1
    await anyio.sleep_forever()


async def sample_task_with_completion(test_data):
    """Task that signals completion."""
    test_data.exec_count += 1
    test_data.completed.set()