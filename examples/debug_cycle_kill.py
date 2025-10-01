import asyncio
import logging
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend

logging.basicConfig(level=logging.DEBUG)

async def proc_a(*, task_status=None):
    backend = proc_a.backend
    pid_b = await backend.spawn(proc_b)
    await backend.link(pid_b)
    print(f"[proc_a] linked to {pid_b}")
    await asyncio.sleep(1)

async def proc_b(*, task_status=None):
    backend = proc_b.backend
    pid_a = await backend.whereis("proc_a")
    if pid_a:
        await backend.link(pid_a)
    print(f"[proc_b] linked to {pid_a}")
    raise RuntimeError("proc_b crash 💥")

async def main():
    backend = AsyncIOBackend()
    await backend.initialize()
    proc_a.backend = backend
    proc_b.backend = backend

    pid_a = await backend.spawn(proc_a, name="proc_a")
    await asyncio.sleep(1.5)

    print(f"[main] is_alive(proc_a)? {backend.is_alive(pid_a)}")
    print(f"[main] processes={backend.processes()}")

    await backend.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
