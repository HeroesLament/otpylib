# examples/debug_link_crash.py
import asyncio
import logging
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime.atoms import EXIT

logging.basicConfig(level=logging.DEBUG)

async def child_proc(*, task_status=None):
    print("[child] crashing now 💥")
    raise RuntimeError("child crash")

async def parent_proc(*, task_status=None):
    backend = parent_proc.backend
    pid_child = await backend.spawn(child_proc)
    await backend.link(pid_child)
    print(f"[parent] linked to child {pid_child}")
    await asyncio.sleep(0.2)  # give crash time to propagate

async def main():
    backend = AsyncIOBackend()
    await backend.initialize()
    parent_proc.backend = backend

    print("\n=== Debug: bidirectional link crash ===")
    pid_parent = await backend.spawn(parent_proc, name="parent")
    await asyncio.sleep(0.5)

    print(f"[main] is_alive(parent)? {backend.is_alive(pid_parent)}")
    print(f"[main] processes={backend.processes()}")

    await backend.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
