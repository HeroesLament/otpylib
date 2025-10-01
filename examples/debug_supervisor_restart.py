# examples/debug_supervisor_restart.py
import asyncio
import logging

from otpylib import process, supervisor
from otpylib.runtime import set_runtime
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend

logging.basicConfig(level=logging.DEBUG)

print("\n=== Debug: Supervisor restart behavior ===")

# -----------------------------------------------------------------------------
# Child tasks
# -----------------------------------------------------------------------------

async def flappy_child(label: str, crash_after: float):
    """Child that always crashes after a delay."""
    print(f"[child:{label}] started, will crash in {crash_after}s")
    await asyncio.sleep(crash_after)
    raise RuntimeError(f"{label} crashed!")

async def stable_child(label: str):
    """Child that never crashes unless killed by sup."""
    print(f"[child:{label}] started, stable")
    while True:
        await asyncio.sleep(0.1)

# -----------------------------------------------------------------------------
# Debug main
# -----------------------------------------------------------------------------

async def main():
    # Init runtime
    runtime = AsyncIOBackend()
    await runtime.initialize()
    set_runtime(runtime)

    # Build child specs
    specs = [
        supervisor.child_spec(
            id="flappy",
            func=flappy_child,
            args=["flappy", 0.2],
            restart=supervisor.PERMANENT,
            name="flappy_service",
        ),
        supervisor.child_spec(
            id="stable",
            func=stable_child,
            args=["stable"],
            restart=supervisor.PERMANENT,
            name="stable_service",
        ),
    ]

    # Start supervisor
    sup_pid = await supervisor.start(
        specs,
        supervisor.options(strategy=supervisor.ONE_FOR_ALL, max_restarts=3, max_seconds=5),
        name="test_supervisor",
    )
    print(f"[main] supervisor started as {sup_pid}")

    # Let it run a bit
    await asyncio.sleep(2.0)

    # Check children
    print("[main] children after crash cycles:")
    for name in ("flappy_service", "stable_service"):
        pid = process.whereis(name)
        print(f" - {name}: {pid} (alive={process.is_alive(pid) if pid else False})")

    # OTP-style shutdown (send SHUTDOWN, not exit)
    if process.is_alive(sup_pid):
        print("[main] sending SHUTDOWN to supervisor…")
        await process.send(sup_pid, supervisor.SHUTDOWN)
        await asyncio.sleep(0.5)
        print("[main] shutdown complete")

    await runtime.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
