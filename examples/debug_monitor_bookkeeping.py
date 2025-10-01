# examples/debug_monitor_bookkeeping.py
import asyncio
import logging

from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime.atoms import DOWN

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("debug")

print("\n=== Debug: monitor bookkeeping (BEAM-style) ===")

async def watched():
    print("[watched] running, will crash soon 💥")
    await asyncio.sleep(0.05)
    raise RuntimeError("watched crash")

async def watcher():
    self_pid = runtime.self()
    print(f"[watcher] started as {self_pid}")

    # Wait for watched to show up
    await asyncio.sleep(0.01)
    targets = [
        pid for pid, p in runtime._processes.items()
        if p.name is None and pid != self_pid
    ]
    if not targets:
        print("[watcher] no watched found")
        return
    target_pid = targets[0]

    # Create monitor
    ref = await runtime.monitor(target_pid)
    print(f"[watcher] monitoring {target_pid} with ref={ref}")

    # --- BEAM-pure: inspect bookkeeping BEFORE exit ---
    print("[bookkeeping] before crash:")
    print(" - watcher.monitors:", runtime._processes[self_pid].monitors)
    print(" - watched.monitored_by:", runtime._processes[target_pid].monitored_by)

    # Wait for DOWN
    try:
        msg = await runtime.receive(timeout=0.5)
        print("[watcher] got message:", msg)
        if msg[0] == DOWN:
            print("✅ PASS: got DOWN")
    except asyncio.TimeoutError:
        print("❌ FAIL: no DOWN received")

async def main():
    global runtime
    runtime = AsyncIOBackend()
    await runtime.initialize()

    await runtime.spawn(watched)
    await runtime.spawn(watcher)

    await asyncio.sleep(0.3)

    print("[main] processes left:", list(runtime._processes.keys()))
    await runtime.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
