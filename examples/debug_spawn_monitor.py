# examples/debug_spawn_monitor.py
import asyncio
import logging

from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime import set_runtime
from otpylib import atom, process
from otpylib.runtime.atoms import DOWN

logging.basicConfig(level=logging.DEBUG)

print("\n=== Debug: spawn_monitor helper ===")

async def child_proc():
    print("[child] running, will exit shortly")
    await asyncio.sleep(0.05)
    print("[child] exiting now ✅")

async def parent():
    # Spawn a child with monitor
    child_pid, ref = await process.spawn_monitor(child_proc)
    print(f"[parent] spawn_monitor -> child={child_pid}, ref={ref}")

    # Wait for DOWN
    try:
        msg = await process.receive(timeout=0.5)
        print("[parent] got message:", msg)
        if (
            isinstance(msg, tuple)
            and len(msg) == 5
            and msg[0] == DOWN
            and msg[1] == ref
            and msg[2] == atom.ensure("process")
            and msg[3] == child_pid
            and msg[4] == atom.ensure("normal")
        ):
            print("✅ PASS: received proper DOWN from child exit")
        else:
            print("❌ FAIL: wrong message shape", msg)
    except asyncio.TimeoutError:
        print("❌ FAIL: no DOWN received")

async def main():
    runtime = AsyncIOBackend()
    await runtime.initialize()
    set_runtime(runtime)

    await process.spawn(parent)
    await asyncio.sleep(0.3)

    print("[main] processes left:", process.processes())
    await runtime.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
