# examples/debug_supervisor_handshake.py

import asyncio
import logging

from otpylib import process, supervisor
from otpylib.runtime import set_runtime
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend

logging.basicConfig(level=logging.DEBUG, format="%(message)s")


async def flappy_child(label: str, crash_after: float):
    print(f"[child:{label}] started, will crash in {crash_after}s")
    await asyncio.sleep(crash_after)
    raise RuntimeError(f"{label} crashed!")


async def stable_child(label: str):
    print(f"[child:{label}] started, stable")
    while True:
        await asyncio.sleep(0.2)


async def run_supervisor():
    """This runs inside a managed process, so we can call supervisor.start()."""

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

    sup_pid = await supervisor.start(
        specs,
        supervisor.options(strategy=supervisor.ONE_FOR_ALL, max_restarts=3, max_seconds=5),
        name="test_supervisor",
    )
    print(f"[debug] supervisor started as {sup_pid}")

    # By the time start() returns, children are guaranteed alive
    flappy_pid = process.whereis("flappy_service")
    stable_pid = process.whereis("stable_service")
    print(f"[debug] children registered: flappy={flappy_pid}, stable={stable_pid}")

    # Let crash/restart cycles happen
    await asyncio.sleep(2.0)

    for cid in ("flappy", "stable"):
        status = await supervisor.get_child_status(sup_pid, cid)
        print(f"[debug] status[{cid}]={status}")

    # shut down supervisor
    await process.send(sup_pid, supervisor.SHUTDOWN)


async def main():
    print("\n=== Debug: Supervisor OTP handshake ===")

    runtime = AsyncIOBackend()
    await runtime.initialize()
    set_runtime(runtime)

    # Spawn a process to run the supervisor logic
    pid = await process.spawn(run_supervisor, name="handshake_tester")
    print(f"[main] spawned tester process {pid}")

    # Give it time to run
    await asyncio.sleep(3.0)

    await runtime.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
