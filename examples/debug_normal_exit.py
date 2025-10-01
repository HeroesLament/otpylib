# examples/debug_normal_exit.py
import asyncio
import logging
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime.atoms import NORMAL

logging.basicConfig(level=logging.DEBUG)

async def child_proc():
    print("[child] exiting normally ✅")
    return NORMAL

async def parent_proc(runtime: AsyncIOBackend, child_pid: str):
    print("[parent] running, linking to child...")
    await runtime.link(child_pid)   # now inside a process
    print(f"[parent] linked to child {child_pid}")

    try:
        while True:
            msg = await runtime.receive()
            print(f"[parent] got msg: {msg}")
    except asyncio.CancelledError:
        print("[parent] cancelled (shutdown)")
        raise

async def main():
    runtime = AsyncIOBackend()
    await runtime.initialize()

    print("\n=== Debug: normal exit propagation ===")

    # Spawn child first
    child_pid = await runtime.spawn(child_proc)

    # Spawn parent as a process, giving it the child pid
    parent_pid = await runtime.spawn(parent_proc, args=[runtime, child_pid], name="parent")

    # Wait a moment to let child exit
    await asyncio.sleep(0.2)

    print(f"[main] is_alive(parent)? {runtime.is_alive(parent_pid)}")
    print(f"[main] processes={runtime.processes()}")

    await runtime.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
