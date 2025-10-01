# examples/debug_monitor_multi.py
import asyncio
import logging

from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime import set_runtime
from otpylib import process
from otpylib.runtime.atoms import DOWN

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("debug")

print("\n=== Debug: monitor multiple refs on same target ===")

async def watched():
    print("[watched] running, will exit soon 💥")
    await asyncio.sleep(0.05)
    raise RuntimeError("watched crash")

async def watcher():
    self_pid = process.self()
    print(f"[watcher] started as {self_pid}")

    # Find watched PID
    await asyncio.sleep(0.01)
    targets = [
        pid for pid in process.processes()
        if pid != self_pid
    ]
    if not targets:
        print("[watcher] no watched found")
        return
    target_pid = targets[0]

    # Monitor twice
    ref1 = await process.monitor(target_pid)
    ref2 = await process.monitor(target_pid)
    print(f"[watcher] monitoring {target_pid} with refs {ref1}, {ref2}")

    down_msgs = []
    for _ in range(2):
        try:
            msg = await process.receive(timeout=0.5)
            down_msgs.append(msg)
            print("[watcher] got message:", msg)
        except asyncio.TimeoutError:
            print("[watcher] timeout waiting for DOWN")

    if len(down_msgs) == 2 and all(m[0] == DOWN for m in down_msgs):
        print("✅ PASS: got two DOWN messages for two monitors")
    else:
        print("❌ FAIL: expected 2 DOWN, got", len(down_msgs))

async def main():
    runtime = AsyncIOBackend()
    await runtime.initialize()
    set_runtime(runtime)

    await process.spawn(watched)
    await process.spawn(watcher)

    await asyncio.sleep(0.3)

    print("[main] processes left:", process.processes())
    await runtime.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
