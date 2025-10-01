# examples/debug_spawn_monitor_crash.py
import asyncio
import logging

from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime import set_runtime
from otpylib import process
from otpylib.runtime.atoms import DOWN, atom

logging.basicConfig(level=logging.DEBUG)

print("\n=== Debug: spawn_monitor helper with crash ===")


async def child():
    print("[child] running, will crash soon 💥")
    await asyncio.sleep(0.05)
    raise RuntimeError("child crashed!")


async def parent():
    # Use the high-level process API
    child_pid, ref = await process.spawn_monitor(child)
    print(f"[parent] spawn_monitor -> child={child_pid}, ref={ref}")

    try:
        msg = await process.receive(timeout=1.0)
        print("[parent] got message:", msg)
        if (
            isinstance(msg, tuple)
            and len(msg) == 5
            and msg[0] == DOWN
            and msg[1] == ref
            and msg[2] == atom.ensure("process")
            and msg[3] == child_pid
            and isinstance(msg[4], RuntimeError)
        ):
            print("✅ PASS: received proper DOWN from child crash")
        else:
            print("❌ FAIL: wrong message shape", msg)
    except asyncio.TimeoutError:
        print("❌ FAIL: no DOWN received")


async def main():
    runtime = AsyncIOBackend()
    set_runtime(runtime)
    await runtime.initialize()

    await process.spawn(parent)

    await asyncio.sleep(0.3)
    print("[main] processes left:", process.processes())
    await runtime.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
