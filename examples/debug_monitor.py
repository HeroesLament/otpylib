# examples/debug_monitor.py
import asyncio
import logging
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime.atoms import DOWN

logging.basicConfig(level=logging.DEBUG)

async def watched_proc(*, task_status=None):
    print("[watched] crashing now 💥")
    raise RuntimeError("watched crash")

async def watcher_proc(*, task_status=None):
    backend = watcher_proc.backend
    pid_watched = await backend.spawn(watched_proc)
    ref = await backend.monitor(pid_watched)
    print(f"[watcher] monitoring {pid_watched} with ref={ref}")

    msg = await backend.receive()
    print(f"[watcher] got monitor msg: {msg}")

async def main():
    backend = AsyncIOBackend()
    await backend.initialize()
    watcher_proc.backend = backend

    print("\n=== Debug: monitor DOWN message ===")
    pid_watcher = await backend.spawn(watcher_proc, name="watcher")
    await asyncio.sleep(0.5)

    print(f"[main] is_alive(watcher)? {backend.is_alive(pid_watcher)}")
    print(f"[main] processes={backend.processes()}")

    await backend.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
