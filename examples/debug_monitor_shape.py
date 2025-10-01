# examples/debug_monitor_shape.py
import asyncio
import logging
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime.atoms import DOWN

logging.basicConfig(level=logging.DEBUG)


async def watcher(runtime: AsyncIOBackend):
    await asyncio.sleep(0.05)  # let target register
    target_pid = runtime.whereis("target")
    if not target_pid:
        print("[watcher] no target found")
        return

    ref = await runtime.monitor(target_pid)
    print(f"[watcher] monitoring {target_pid} with ref={ref}")

    try:
        msg = await runtime.receive(timeout=1.0)
        print(f"[watcher] got message: {msg}")
        if isinstance(msg, tuple) and msg[0] == DOWN:
            print(f"✅ DOWN message shape ok (len={len(msg)})")
        else:
            print("❌ Unexpected message format")
    except asyncio.TimeoutError:
        print("❌ FAIL: no DOWN message received")


async def target(runtime: AsyncIOBackend):
    await runtime.register("target")
    await asyncio.sleep(0.1)
    print("[target] exiting normally")


async def main():
    runtime = AsyncIOBackend()
    await runtime.initialize()

    print("\n=== Debug: monitor DOWN message shape ===")
    await runtime.spawn(watcher, args=[runtime], name="watcher")
    await runtime.spawn(target, args=[runtime])

    await asyncio.sleep(0.5)
    print("[main] processes left:", runtime.processes())
    print("[main] is_alive(watcher)?", runtime.is_alive("watcher"))

    await runtime.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
