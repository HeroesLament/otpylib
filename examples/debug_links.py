"""
Debug script for AsyncIOBackend link semantics with BEAM-style handshakes.

Covers:
  1. Unlink symmetry (proc_a should survive after unlinking)
  2. Circular links (all die if one crashes)

Each process participates in a "ready" handshake before links or crashes.
"""

import asyncio
import logging
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend

logging.basicConfig(level=logging.DEBUG)


async def debug_unlink_symmetry():
    print("\n=== Debug: unlink symmetry ===")
    runtime = AsyncIOBackend()
    await runtime.initialize()

    async def controller():
        pid = runtime.self()
        print(f"[controller] started with pid={pid}")

        # Register self so children can send "ready"
        await runtime.register("controller")

        proc_a = await runtime.spawn(proc_a_func)
        proc_b = await runtime.spawn(proc_b_func)

        # Wait for both readiness messages
        ready_a = await runtime.receive(timeout=1.0)
        ready_b = await runtime.receive(timeout=1.0)
        print(f"[controller] got readiness: {ready_a}, {ready_b}")

        # Link + unlink
        await runtime.link(proc_a)
        await runtime.link(proc_b)
        print(f"[controller] linked {proc_a} <-> {proc_b}")
        await runtime.unlink(proc_b)
        print(f"[controller] unlinked {proc_a} <-> {proc_b}")

        # Wait for crash
        await asyncio.sleep(0.3)
        alive_a = runtime.is_alive(proc_a)
        alive_b = runtime.is_alive(proc_b)
        print(f"[controller] alive? a={alive_a}, b={alive_b}")

    async def proc_a_func():
        pid = runtime.self()
        print(f"[proc_a] pid={pid} started")
        # Notify controller we are ready
        await runtime.send("controller", ("ready", "proc_a"))
        try:
            await asyncio.sleep(0.5)
            print("[proc_a] survived")
        except asyncio.CancelledError:
            print("[proc_a] cancelled unexpectedly")
            raise

    async def proc_b_func():
        pid = runtime.self()
        print(f"[proc_b] pid={pid} started")
        # Notify controller we are ready
        await runtime.send("controller", ("ready", "proc_b"))
        await asyncio.sleep(0.1)
        print("[proc_b] crashing now")
        raise RuntimeError("boom")

    controller_pid = await runtime.spawn(controller, name="controller")
    await asyncio.sleep(1.0)
    await runtime.shutdown()


async def debug_circular_links():
    print("\n=== Debug: circular link behavior ===")
    runtime = AsyncIOBackend()
    await runtime.initialize()

    async def controller():
        pid = runtime.self()
        print(f"[controller] started with pid={pid}")

        # Register self so children can message us
        await runtime.register("controller")

        proc_a = await runtime.spawn(proc_a_func)
        proc_b = await runtime.spawn(proc_b_func)
        proc_c = await runtime.spawn(proc_c_func)

        # Collect all readiness
        for _ in range(3):
            msg = await runtime.receive(timeout=1.0)
            print(f"[controller] got readiness: {msg}")

        # Now link in a circle
        await runtime.link(proc_a)
        await runtime.link(proc_b)
        await runtime.link(proc_c)
        print(f"[controller] circular links established among {proc_a}, {proc_b}, {proc_c}")

        await asyncio.sleep(0.3)
        print(f"[controller] initial alive: "
              f"a={runtime.is_alive(proc_a)}, "
              f"b={runtime.is_alive(proc_b)}, "
              f"c={runtime.is_alive(proc_c)}")

        await asyncio.sleep(0.5)
        print(f"[controller] after crash: "
              f"a={runtime.is_alive(proc_a)}, "
              f"b={runtime.is_alive(proc_b)}, "
              f"c={runtime.is_alive(proc_c)}")

    async def proc_a_func():
        pid = runtime.self()
        await runtime.send("controller", ("ready", "proc_a"))
        print(f"[proc_a] pid={pid} started")
        await asyncio.sleep(1.0)

    async def proc_b_func():
        pid = runtime.self()
        await runtime.send("controller", ("ready", "proc_b"))
        print(f"[proc_b] pid={pid} started")
        await asyncio.sleep(1.0)

    async def proc_c_func():
        pid = runtime.self()
        await runtime.send("controller", ("ready", "proc_c"))
        print(f"[proc_c] pid={pid} started")
        # Delay crash until after links are set
        await asyncio.sleep(0.2)
        print("[proc_c] crashing now")
        raise RuntimeError("proc_c crash")

    controller_pid = await runtime.spawn(controller, name="controller")
    await asyncio.sleep(1.2)
    await runtime.shutdown()


async def main():
    await debug_unlink_symmetry()
    await debug_circular_links()


if __name__ == "__main__":
    asyncio.run(main())
