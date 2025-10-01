# examples/debug_monitor_down.py
import asyncio
import logging

from otpylib import process
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime.atoms import DOWN

logging.basicConfig(level=logging.DEBUG)

async def watcher(runtime: AsyncIOBackend, watched_pid: str, *, task_status=None):
    """Watcher process: sets up monitor and waits for DOWN."""
    ref = await runtime.monitor(watched_pid)
    print(f"[watcher] monitoring {watched_pid} with ref={ref}")

    try:
        msg = await runtime.receive(timeout=2.0)
        print(f"[watcher] got message: {msg}")
        if msg and msg[0] == DOWN:
            print("✅ PASS: DOWN message delivered")
        else:
            print("❌ FAIL: unexpected message")
    except asyncio.TimeoutError:
        print("❌ FAIL: timeout waiting for DOWN")

async def watched(*, task_status=None):
    print("[watched] crashing now 💥")
    raise RuntimeError("watched crash")

async def main():
    print("\n=== Debug: monitor DOWN delivery (must be inside a process) ===")
    runtime = AsyncIOBackend()
    await runtime.initialize()
    process.use_runtime(runtime)

    # Spawn watched first
    watched_pid = await runtime.spawn(watched)

    # Spawn watcher (which will call monitor inside its own process)
    watcher_pid = await runtime.spawn(
        watcher, args=[runtime, watched_pid], name="watcher"
    )

    # Let things run
    await asyncio.sleep(1)

    print("[main] processes:", runtime.processes())
    print("[main] is_alive(watcher)?", runtime.is_alive(watcher_pid))

    await runtime.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
