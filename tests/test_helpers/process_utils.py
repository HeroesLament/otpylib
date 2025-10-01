# tests/helpers/process_utils.py
"""
Process test utilities.

Provides helpers to run test bodies inside a proper otpylib process context,
so that supervisor and mailbox APIs behave consistently in tests.
"""

import pytest
from otpylib import process


async def run_in_process(func, *args, **kwargs):
    """
    Run an async test function body inside a spawned process.

    The child process executes `func(*args, **kwargs)` and sends the result
    or exception back to the parent. The parent awaits the reply.

    Example:
        async def test_example():
            async def body():
                return 42
            result = await run_in_process(body)
            assert result == 42
    """
    parent = process.self()
    result_ref = {"value": None, "error": None}

    async def _runner():
        try:
            value = await func(*args, **kwargs)
            await process.send(parent, ("ok", value))
        except Exception as e:
            await process.send(parent, ("error", e))

    # Spawn child inside process system
    await process.spawn(_runner, name=f"test-{func.__name__}")

    # Wait for child reply
    tag, payload = await process.receive()
    if tag == "ok":
        return payload
    elif tag == "error":
        raise payload
    else:
        raise RuntimeError(f"Unexpected message from test child: {tag!r}, {payload!r}")
