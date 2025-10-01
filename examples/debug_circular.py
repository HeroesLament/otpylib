# examples/debug_circular.py
import asyncio
import logging

from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend

logging.basicConfig(level=logging.DEBUG)


async def proc_a(runtime: AsyncIOBackend):
    pid = runtime.self()
    print(f"[proc_a] started pid={pid}")
    await runtime.register("proc_a")

    # Wait for proc_b to exist, then link
    msg = await runtime.receive(timeout=0.5)
    print(f"[proc_a] got message: {msg}")
    await runtime.link("proc_b")
    print(f"[proc_a] linked → proc_b")

    try:
        await asyncio.sleep(1.0)
        print("[proc_a] finished normally (unexpected) ❌")
    except asyncio.CancelledError:
        print("[proc_a] cancelled due to circular link crash ✅")
        raise


async def proc_b(runtime: AsyncIOBackend):
    pid = runtime.self()
    print(f"[proc_b] started pid={pid}")
    await runtime.register("proc_b")

    # Signal readiness to proc_a
    await runtime.send("proc_a", ("ready", "proc_b"))

    # Wait for proc_c to exist, then link
    msg = await runtime.receive(timeout=0.5)
    print(f"[proc_b] got message: {msg}")
    await runtime.link("proc_c")
    print(f"[proc_b] linked → proc_c")

    try:
        await asyncio.sleep(1.0)
        print("[proc_b] finished normally (unexpected) ❌")
    except asyncio.CancelledError:
        print("[proc_b] cancelled due to circular link crash ✅")
        raise


async def proc_c(runtime: AsyncIOBackend):
    pid = runtime.self()
    print(f"[proc_c] started pid={pid}")
    await runtime.register("proc_c")

    # Signal readiness to proc_b
    await runtime.send("proc_b", ("ready", "proc_c"))

    # Complete the circle by linking to proc_a
    await asyncio.sleep(0.05)  # ensure others are ready
    await runtime.link("proc_a")
    print(f"[proc_c] linked → proc_a (circle complete)")

    # Crash after a moment
    await asyncio.sleep(0.1)
    print("[proc_c] crashing now 💥")
    raise RuntimeError("proc_c crash")


async def main():
    print("\n=== Debug: circular link semantics (BEAM-style) ===")
    runtime = AsyncIOBackend()
    await runtime.initialize()

    pid_a = await runtime.spawn(proc_a, args=[runtime])
    pid_b = await runtime.spawn(proc_b, args=[runtime])
    pid_c = await runtime.spawn(proc_c, args=[runtime])

    await asyncio.sleep(1.0)

    alive_a = runtime.is_alive(pid_a)
    alive_b = runtime.is_alive(pid_b)
    alive_c = runtime.is_alive(pid_c)
    print(f"[main] is_alive(proc_a)? {alive_a}")
    print(f"[main] is_alive(proc_b)? {alive_b}")
    print(f"[main] is_alive(proc_c)? {alive_c}")

    await runtime.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
