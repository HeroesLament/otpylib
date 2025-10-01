# examples/debug_supervisor_intensity.py
"""
Debug script: Supervisor intensity limits

Demonstrates how the supervisor shuts itself down when the
restart intensity (max_restarts within max_seconds) is exceeded.
"""

import asyncio

from otpylib import process, supervisor
from otpylib.runtime import set_runtime
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend

async def flappy_child(label: str):
    """Crashes immediately every time."""
    print(f"[child:{label}] starting, about to crash")
    raise RuntimeError(f"{label} crashed intentionally!")


async def tester():
    """Runs inside a process: sets up and observes supervisor behavior."""
    specs = [
        supervisor.child_spec(
            id="flappy",
            func=flappy_child,
            args=["flappy"],
            restart=supervisor.PERMANENT,
            name="flappy_service",
        )
    ]

    opts = supervisor.options(
        strategy=supervisor.ONE_FOR_ONE,
        max_restarts=2,
        max_seconds=3,
    )

    # Start supervisor (OTP handshake)
    sup_pid = await supervisor.start(specs, opts, name="intensity_sup")
    print(f"[tester] supervisor started as {sup_pid}")

    # Poll until supervisor dies due to intensity exceeded
    while process.is_alive(sup_pid):
        status = await supervisor.get_child_status(sup_pid, "flappy")
        print(f"[tester] flappy status: {status}")
        await asyncio.sleep(0.2)

    print("[tester] supervisor terminated due to intensity limit")


async def main():
    print("\n=== Debug: Supervisor intensity limits ===")

    runtime = AsyncIOBackend()
    await runtime.initialize()
    set_runtime(runtime)

    try:
        # Spawn tester as a process (so process.receive/send are legal)
        pid = await process.spawn(tester, name="intensity_tester", mailbox=True)
        print(f"[main] spawned tester process {pid}")

        # Keep runtime alive until tester exits
        while process.is_alive(pid):
            await asyncio.sleep(0.5)
    finally:
        await runtime.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
