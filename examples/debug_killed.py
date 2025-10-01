# examples/debug_killed.py
import asyncio
import logging

from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime.atoms import EXIT, DOWN, KILLED

logging.basicConfig(level=logging.DEBUG)

# Define runtime globally so child procs can access it
runtime = AsyncIOBackend()

async def trapped_proc():
    """Process that traps exits (should still die if killed)."""
    pid = runtime.self()
    print(f"[trapped_proc] started pid={pid}, trap_exits=True")
    try:
        while True:
            msg = await runtime.receive(timeout=0.2)
            print(f"[trapped_proc] got message: {msg}")
    except asyncio.CancelledError:
        print(f"[trapped_proc] cancelled (KILLED should bypass trap_exits)")
        raise

async def main():
    print("\n=== Debug: KILLED bypass trap_exits (BEAM-style) ===")

    # Initialize backend
    await runtime.initialize()

    # Spawn process with trap_exits enabled
    pid = await runtime.spawn(trapped_proc, trap_exits=True)

    print(f"[main] spawned trapped_proc pid={pid}")
    assert runtime.is_alive(pid)

    # Kill it
    print("[main] sending exit(KILLED)")
    await runtime.exit(pid, KILLED)

    # Give time for propagation
    await asyncio.sleep(0.5)

    alive = runtime.is_alive(pid)
    print(f"[main] is_alive({pid})? {alive}")
    if alive:
        print("❌ FAIL: process still alive after KILLED (bug!)")
    else:
        print("✅ PASS: process terminated despite trap_exits")

    await runtime.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
