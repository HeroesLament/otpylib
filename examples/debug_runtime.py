"""
Debug script for AsyncIOBackend link semantics.

Covers:
  1. Normal exit should not propagate
  2. unlink() should break link propagation
  3. Circular links should not cause premature death
"""

import asyncio
import logging
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime.atoms import NORMAL

logging.basicConfig(level=logging.DEBUG)


async def debug_normal_exit_no_propagation():
    print("\n=== Debug: normal exit no propagation ===")
    runtime = AsyncIOBackend()
    await runtime.initialize()

    parent_done = False

    async def parent():
        nonlocal parent_done
        try:
            print(f"Parent {runtime.self()} starting")
            child_pid = await runtime.spawn(child)
            await runtime.link(child_pid)
            print(f"Linked to child: {child_pid}")
            await asyncio.sleep(0.3)
            parent_done = True
            print("Parent finished normally")
        except asyncio.CancelledError:
            print("Parent cancelled (unexpected!)")
            raise

    async def child():
        print(f"Child {runtime.self()} starting")
        await asyncio.sleep(0.1)
        print(f"Child exiting normally with reason={NORMAL}")
        # no return → reason will be NORMAL in Process.run()

    parent_pid = await runtime.spawn(parent)
    await asyncio.sleep(0.5)

    alive = runtime.is_alive(parent_pid)
    print(f"Parent alive after child normal exit? {alive}, parent_done={parent_done}")

    await runtime.shutdown()


async def debug_unlink_behavior():
    print("\n=== Debug: unlink behavior ===")
    runtime = AsyncIOBackend()
    await runtime.initialize()

    async def proc_a():
        print(f"ProcA {runtime.self()} running")
        await asyncio.sleep(0.5)
        print("ProcA survived")
        return  # exits with NORMAL

    async def proc_b():
        print(f"ProcB {runtime.self()} running")
        await asyncio.sleep(0.1)
        print("ProcB crashing")
        raise RuntimeError("boom")

    proc_a_pid = await runtime.spawn(proc_a)
    proc_b_pid = await runtime.spawn(proc_b)

    # Create a process to manage linking/unlinking
    async def linker():
        print(f"Linker {runtime.self()} linking {proc_a_pid} and {proc_b_pid}")
        await runtime.link(proc_a_pid)
        await runtime.link(proc_b_pid)
        # Break the link to proc_b before it crashes
        await runtime.unlink(proc_b_pid)
        print("Unlinked proc_a <-> proc_b")

    await runtime.spawn(linker)

    await asyncio.sleep(0.6)
    alive = runtime.is_alive(proc_a_pid)
    print(f"ProcA alive after unlink? {alive}")

    await runtime.shutdown()


async def debug_circular_links():
    print("\n=== Debug: circular link behavior ===")
    runtime = AsyncIOBackend()
    await runtime.initialize()

    async def proc_a():
        print(f"ProcA {runtime.self()} running")
        await asyncio.sleep(0.5)
        print("ProcA done")

    async def proc_b():
        print(f"ProcB {runtime.self()} running")
        await asyncio.sleep(0.1)
        print("ProcB crashing")
        raise RuntimeError("boom")

    proc_a_pid = await runtime.spawn(proc_a)
    proc_b_pid = await runtime.spawn(proc_b)

    # Linker process makes the circular link
    async def linker():
        print(f"Linker {runtime.self()} creating circular link")
        await runtime.link(proc_a_pid)
        await runtime.link(proc_b_pid)
        print(f"Created circular link between {proc_a_pid} and {proc_b_pid}")

    await runtime.spawn(linker)

    await asyncio.sleep(0.3)
    print(f"ProcA alive? {runtime.is_alive(proc_a_pid)}")
    print(f"ProcB alive? {runtime.is_alive(proc_b_pid)}")

    await runtime.shutdown()


async def main():
    await debug_normal_exit_no_propagation()
    await debug_unlink_behavior()
    await debug_circular_links()


if __name__ == "__main__":
    asyncio.run(main())
