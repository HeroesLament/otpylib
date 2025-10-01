"""
Debug unlink semantics (BEAM-style)

This script verifies that after linking and then unlinking two processes,
a crash in one does not propagate to the other.
"""

import asyncio
import logging
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend

logging.basicConfig(level=logging.DEBUG)


async def debug_unlink():
    runtime = AsyncIOBackend()
    await runtime.initialize()

    print("\n=== Debug: unlink semantics (BEAM-style) ===")

    async def proc_a():
        pid = runtime.self()
        print(f"[proc_a] started pid={pid}")
        await runtime.register("proc_a")

        msg = await runtime.receive(timeout=0.5)
        print(f"[proc_a] got message: {msg}")

        print("[proc_a] calling LINK → proc_b")
        await runtime.link("proc_b")
        await asyncio.sleep(0.05)

        print("[proc_a] calling UNLINK → proc_b")
        await runtime.unlink("proc_b")

        # Survive even if proc_b crashes
        await asyncio.sleep(0.3)
        print("[proc_a] survived unlink ✅")

    async def proc_b():
        pid = runtime.self()
        print(f"[proc_b] started pid={pid}")
        await runtime.register("proc_b")
        await runtime.send("proc_a", ("ready", "proc_b"))

        await asyncio.sleep(0.1)
        print("[proc_b] crashing now 💥")
        raise RuntimeError("proc_b crash")

    pid_a = await runtime.spawn(proc_a)
    pid_b = await runtime.spawn(proc_b)

    await asyncio.sleep(0.6)

    print(f"[main] is_alive(proc_a)? {runtime.is_alive(pid_a)}")
    print(f"[main] is_alive(proc_b)? {runtime.is_alive(pid_b)}")

    await runtime.shutdown()


if __name__ == "__main__":
    asyncio.run(debug_unlink())
