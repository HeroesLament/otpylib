"""Helper functions and tasks for dynamic supervisor tests."""

import anyio


# Sample tasks for testing

async def sample_task(test_data, *, task_status):
    """Simple task that increments counter."""
    task_status.started()
    test_data.exec_count += 1


async def sample_task_error(test_data, *, task_status):
    """Task that increments counter then raises error."""
    task_status.started()
    test_data.exec_count += 1
    test_data.error_count += 1
    raise RuntimeError("pytest")


async def sample_task_long_running(test_data, *, task_status):
    """Task that runs indefinitely."""
    task_status.started()
    test_data.exec_count += 1
    await anyio.sleep_forever()


async def sample_task_with_completion(test_data, *, task_status):
    """Task that signals completion."""
    task_status.started()
    test_data.exec_count += 1
    test_data.completed.set()


async def sample_task_with_delay(test_data, delay: float = 0.1, *, task_status):
    """Task that runs for a specified delay then completes."""
    task_status.started()
    test_data.exec_count += 1
    await anyio.sleep(delay)