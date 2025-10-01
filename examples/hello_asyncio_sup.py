#!/usr/bin/env python3
"""
Supervisor Example using Atoms

Demonstrates supervisor with proper atom imports for strategies and restart types.
"""

import asyncio
from otpylib import process, supervisor
from otpylib.runtime import set_runtime
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend

# Import atoms from supervisor module
from otpylib.supervisor import (
    PERMANENT, TRANSIENT, TEMPORARY,
    ONE_FOR_ONE, ONE_FOR_ALL, REST_FOR_ONE,
    NORMAL, SHUTDOWN
)


# === Worker Processes ===

async def stable_worker():
    """A stable worker that runs forever."""
    pid = process.self()
    print(f"[stable:{pid[:8]}] Starting stable worker")
    
    count = 0
    while True:
        count += 1
        if count % 10 == 0:
            print(f"[stable:{pid[:8]}] Still working... (iteration {count})")
        await asyncio.sleep(1)


async def flaky_worker():
    """A worker that crashes periodically."""
    pid = process.self()
    print(f"[flaky:{pid[:8]}] Starting flaky worker")
    
    # Run for 5-10 seconds then crash
    runtime = 5 + (hash(pid) % 6)
    print(f"[flaky:{pid[:8]}] Will crash in {runtime} seconds")
    
    await asyncio.sleep(runtime)
    print(f"[flaky:{pid[:8]}] CRASHING!")
    raise RuntimeError("Flaky worker failure")


async def temporary_task():
    """A task that runs once and completes."""
    pid = process.self()
    print(f"[temp:{pid[:8]}] Starting temporary task")
    
    # Do some work
    for i in range(3):
        print(f"[temp:{pid[:8]}] Working... {i+1}/3")
        await asyncio.sleep(1)
    
    print(f"[temp:{pid[:8]}] Task completed successfully")
    # Normal exit - should not restart with TEMPORARY


async def transient_worker():
    """A worker that may fail or succeed."""
    pid = process.self()
    print(f"[trans:{pid[:8]}] Starting transient worker")
    
    # 50/50 chance to fail or complete normally
    if hash(pid) % 2 == 0:
        print(f"[trans:{pid[:8]}] Running normally for 5 seconds")
        await asyncio.sleep(5)
        print(f"[trans:{pid[:8]}] Completing normally")
        # Normal completion - won't restart with TRANSIENT
    else:
        print(f"[trans:{pid[:8]}] Will fail in 3 seconds")
        await asyncio.sleep(3)
        print(f"[trans:{pid[:8]}] FAILING!")
        raise RuntimeError("Transient worker failure")
        # Abnormal exit - will restart with TRANSIENT


# === Demo Functions ===

async def demo_one_for_one():
    """Demonstrate ONE_FOR_ONE strategy."""
    print("\n=== ONE_FOR_ONE Strategy Demo ===")
    print("When one child fails, only that child is restarted\n")
    
    children = [
        supervisor.child_spec(
            id="stable1",
            func=stable_worker,
            restart=PERMANENT
        ),
        supervisor.child_spec(
            id="flaky1",
            func=flaky_worker,
            restart=PERMANENT  
        ),
        supervisor.child_spec(
            id="stable2",
            func=stable_worker,
            restart=PERMANENT
        )
    ]
    
    opts = supervisor.options(
        strategy=ONE_FOR_ONE,
        max_restarts=3,
        max_seconds=10
    )
    
    sup_pid = await supervisor.start(children, opts, name="one_for_one_sup")
    print(f"Started supervisor: {sup_pid[:12]}")
    
    # Let it run for 20 seconds to see restarts
    await asyncio.sleep(20)
    
    print("\nStopping ONE_FOR_ONE supervisor")
    await process.exit(sup_pid, SHUTDOWN)
    await asyncio.sleep(1)


async def demo_one_for_all():
    """Demonstrate ONE_FOR_ALL strategy."""
    print("\n=== ONE_FOR_ALL Strategy Demo ===")
    print("When one child fails, ALL children are restarted\n")
    
    children = [
        supervisor.child_spec(
            id="stable3",
            func=stable_worker,
            restart=PERMANENT
        ),
        supervisor.child_spec(
            id="flaky2",
            func=flaky_worker,
            restart=PERMANENT
        ),
        supervisor.child_spec(
            id="stable4",
            func=stable_worker,
            restart=PERMANENT
        )
    ]
    
    opts = supervisor.options(
        strategy=ONE_FOR_ALL,
        max_restarts=2,
        max_seconds=15
    )
    
    sup_pid = await supervisor.start(children, opts, name="one_for_all_sup")
    print(f"Started supervisor: {sup_pid[:12]}")
    
    # Let it run to see all children restart together
    await asyncio.sleep(15)
    
    print("\nStopping ONE_FOR_ALL supervisor")
    await process.exit(sup_pid, SHUTDOWN)
    await asyncio.sleep(1)


async def demo_restart_types():
    """Demonstrate different restart types."""
    print("\n=== Restart Types Demo ===")
    print("PERMANENT: Always restarts")
    print("TRANSIENT: Restarts only on abnormal exit")
    print("TEMPORARY: Never restarts\n")
    
    children = [
        supervisor.child_spec(
            id="permanent_flaky",
            func=flaky_worker,
            restart=PERMANENT
        ),
        supervisor.child_spec(
            id="transient_worker",
            func=transient_worker,
            restart=TRANSIENT
        ),
        supervisor.child_spec(
            id="temporary_task",
            func=temporary_task,
            restart=TEMPORARY
        )
    ]
    
    opts = supervisor.options(
        strategy=ONE_FOR_ONE,
        max_restarts=5,
        max_seconds=30
    )
    
    sup_pid = await supervisor.start(children, opts, name="restart_types_sup")
    print(f"Started supervisor: {sup_pid[:12]}")
    
    # Let it run to see different restart behaviors
    await asyncio.sleep(20)
    
    print("\nChecking final state:")
    all_procs = process.processes()
    print(f"Active processes: {len(all_procs)}")
    
    print("\nStopping restart types supervisor")
    await process.exit(sup_pid, SHUTDOWN)
    await asyncio.sleep(1)


async def main():
    """Main demo runner."""
    print("=== Supervisor Atoms Example ===")
    print("Demonstrating supervisor strategies and restart types\n")
    
    # Configure logging to see supervisor debug output
    import logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Initialize runtime
    backend = AsyncIOBackend()
    await backend.initialize()
    set_runtime(backend)
    
    # Run demos
    await demo_one_for_one()
    await demo_one_for_all()
    await demo_restart_types()
    
    # Final status
    print("\n=== Final Status ===")
    remaining = process.processes()
    if remaining:
        print(f"Remaining processes: {len(remaining)}")
        for pid in remaining[:5]:  # Show first 5
            print(f"  - {pid[:12]}")
    else:
        print("All processes cleaned up successfully")
    
    # Shutdown
    print("\nShutting down runtime...")
    await backend.shutdown()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
