#!/usr/bin/env python3
"""
Dynamic Supervisor Example (Add/Remove + Restart Strategy)

Demonstrates dynamic supervisor usage with:
- Static + dynamic child management
- Restart strategies (with a flaky worker)
"""

import asyncio
import logging
from otpylib import process
from otpylib.runtime import set_runtime
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend

from otpylib.dynamic_supervisor import (
    start, DynamicSupervisorHandle, child_spec, options,
    PERMANENT, ONE_FOR_ONE, ONE_FOR_ALL, SHUTDOWN
)


# === Worker Tasks ===

async def simple_worker(name: str):
    pid = process.self()
    print(f"[{name}:{pid[:8]}] Starting worker")
    counter = 0
    while True:
        counter += 1
        if counter % 5 == 0:
            print(f"[{name}:{pid[:8]}] Still alive (count={counter})")
        await asyncio.sleep(1)


async def flaky_worker(name: str):
    pid = process.self()
    print(f"[{name}:{pid[:8]}] Starting flaky worker")
    lifetime = 3 + (hash(pid) % 5)  # crash after 3–7 seconds
    print(f"[{name}:{pid[:8]}] Will crash in {lifetime} seconds")
    await asyncio.sleep(lifetime)
    print(f"[{name}:{pid[:8]}] CRASHING!")
    raise RuntimeError("flaky failure")


# === Demo Logic (must run in processes) ===

async def demo_dynamic_add():
    """Demo dynamic add/remove."""
    print("\n=== Dynamic Add/Remove Demo ===")

    children = [
        child_spec(id="static_worker", func=simple_worker, args=["static"], restart=PERMANENT)
    ]

    sup_pid = await start(children, options(strategy=ONE_FOR_ONE), name="dyn_sup")
    handle = DynamicSupervisorHandle(sup_pid)

    print("Initial children:", await handle.list_children())

    ok, msg = await handle.start_child(
        child_spec(id="dynamic_worker", func=simple_worker, args=["dyn"], restart=PERMANENT)
    )
    print("Add result:", ok, msg)
    print("Children now:", await handle.which_children())

    await asyncio.sleep(5)

    ok, msg = await handle.terminate_child("dynamic_worker")
    print("Terminate result:", ok, msg)
    print("Children now:", await handle.list_children())

    await handle.shutdown()


async def demo_restart_strategy():
    """Demo restart strategy with flaky worker."""
    print("\n=== Restart Strategy Demo ===")
    print("Strategy: ONE_FOR_ALL — when one fails, all restart.\n")

    children = [
        child_spec(id="stable", func=simple_worker, args=["stable"], restart=PERMANENT),
        child_spec(id="flaky", func=flaky_worker, args=["flaky"], restart=PERMANENT),
        child_spec(id="stable2", func=simple_worker, args=["stable2"], restart=PERMANENT),
    ]

    sup_pid = await start(children, options(strategy=ONE_FOR_ALL, max_restarts=3, max_seconds=10), name="restart_sup")
    handle = DynamicSupervisorHandle(sup_pid)

    print("Supervisor started, waiting for crash+restart cycles...")
    await asyncio.sleep(20)

    print("Children state after restarts:", await handle.which_children())
    await handle.shutdown()


# === Main Runner ===

async def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    backend = AsyncIOBackend()
    await backend.initialize()
    set_runtime(backend)

    # 🔑 Run demos inside spawned processes
    await process.spawn(demo_dynamic_add)
    await process.spawn(demo_restart_strategy)

    await asyncio.sleep(1)  # let supervisors shut down
    await backend.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
