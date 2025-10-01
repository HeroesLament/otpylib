#!/usr/bin/env python3
"""
Stress Test: Dynamic Supervisor with GenServer Runner
"""

import asyncio
import logging
import time
import types

from otpylib import process, gen_server, supervisor, dynamic_supervisor
from otpylib.dynamic_supervisor import start_link as dynsup_start_link, start_child
from otpylib.runtime import set_runtime
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend
from otpylib.supervisor import child_spec, options as sup_options
from otpylib.supervisor.atoms import PERMANENT, ONE_FOR_ONE

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("stress_dynsup")

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
RUNNER_NAME = "stress_runner"
WORKER_SUP_NAME = "worker_sup"
TOTAL_CHILDREN = 5_000
BATCH_SIZE = 5_000

# -----------------------------------------------------------------------------
# Worker task
# -----------------------------------------------------------------------------
async def worker_task():
    """Dummy worker that just waits forever."""
    try:
        await process.receive()
    except asyncio.CancelledError:
        pass

# -----------------------------------------------------------------------------
# Runner GenServer module
# -----------------------------------------------------------------------------

RunnerServer = types.SimpleNamespace(__name__="RunnerServer")

async def init(_arg):
    logger.info("[RunnerServer.init] ENTER")
    worker_sup_pid = process.whereis(WORKER_SUP_NAME)
    result = {
        "count": 0,
        "total": TOTAL_CHILDREN,
        "batch": BATCH_SIZE,
        "batch_times": [],
        "started": False,
        "worker_sup_pid": worker_sup_pid,
    }
    logger.info(f"[RunnerServer.init] EXIT - returning state: {result}")
    return result

RunnerServer.init = init

async def handle_cast(message, state):
    # unwrap if runtime delivered a _CastMessage
    payload = getattr(message, "payload", message)

    logger.info(f"[RunnerServer.handle_cast] ENTER - payload={payload}, state={state}")
    match payload:
        case "start":
            if not state["started"]:
                state["started"] = True
                logger.info("[RunnerServer] Starting batch spawning...")

            if state["count"] >= state["total"]:
                avg_time = sum(state["batch_times"]) / len(state["batch_times"]) if state["batch_times"] else 0
                logger.info(f"✓ All {state['total']} children spawned. Avg batch time: {avg_time:.4f}s")
                return (gen_server.NoReply(), state)

            batch_size = min(state["batch"], state["total"] - state["count"])
            logger.info(f"[RunnerServer] Spawning batch of {batch_size}")
            t0 = time.perf_counter()

            for i in range(batch_size):
                worker_id = state["count"]
                logger.debug(f"[RunnerServer] Spawning worker {worker_id}")
                spec = child_spec(
                    id=f"worker_{worker_id}",
                    func=worker_task,
                    restart=PERMANENT,
                )
                await start_child(WORKER_SUP_NAME, spec)
                state["count"] += 1

            elapsed = time.perf_counter() - t0
            state["batch_times"].append(elapsed)

            logger.info(
                f"Batch complete: {state['count']}/{state['total']} "
                f"({elapsed:.4f}s, {elapsed/batch_size*1000:.2f}ms/spawn)"
            )

            # Schedule next batch
            logger.info("[RunnerServer] Scheduling next batch")
            await gen_server.cast(RUNNER_NAME, "start")
            return (gen_server.NoReply(), state)

        case _:
            logger.warning(f"[RunnerServer.handle_cast] Unknown payload: {payload}")
            return (gen_server.NoReply(), state)

RunnerServer.handle_cast = handle_cast

# -----------------------------------------------------------------------------
# Application process
# -----------------------------------------------------------------------------
async def app():
    """Main application - must run in a process context."""
    logger.info("[app] ENTER - Starting stress test application")

    # Define children
    children = [
        # Dynamic supervisor for workers
        dynamic_supervisor.child_spec(
            id=WORKER_SUP_NAME,
            func=dynsup_start_link,
            args=[[], sup_options(), WORKER_SUP_NAME],  # no static children, default opts, name
            restart=PERMANENT,
        ),
        # GenServer that spawns workers in batches (registered as RUNNER_NAME)
        child_spec(
            id=RUNNER_NAME,
            func=gen_server.start_link,
            args=[RunnerServer, None],
            kwargs={"name": RUNNER_NAME},   # <-- important fix
            restart=PERMANENT,
        ),
    ]

    logger.info("[app] Starting root supervisor")
    sup_pid = await supervisor.start_link(
        children,
        sup_options(strategy=ONE_FOR_ONE),
        name="root_sup",
    )

    logger.info(f"[app] Root supervisor started: {sup_pid}")

    # Debug: Check if RunnerServer is alive and registered
    await asyncio.sleep(0.5)

    run_pid = process.whereis(RUNNER_NAME)
    match run_pid:
        case p if p is not None:
            exists = True
        case _:
            exists = False
    rpid_alive = process.is_alive(run_pid)
    match_tup = (exists, rpid_alive)
    match match_tup:    
        case (True, True):
            logger.info("[app] Sending cast to RunnerServer")
            await gen_server.cast(RUNNER_NAME, "start")
        case (False, _):
            logger.error("[app] RunnerServer name NOT REGISTERED!")
        case (_, False):
            logger.error("[app] RunnerServer is DEAD!")
        case (_, _):
            logger.error("[app] RunnerServer is SHCROEDINGER!")
    # Keep app alive
    try:
        while True:
            await asyncio.sleep(10)
    except asyncio.CancelledError:
        logger.info("[app] Shutting down")

# -----------------------------------------------------------------------------
# Main entry
# -----------------------------------------------------------------------------
async def main():
    logger.info("=== Dynamic Supervisor Stress Test ===")
    logger.info(f"Target: {TOTAL_CHILDREN} children in batches of {BATCH_SIZE}")

    # Initialize backend
    backend = AsyncIOBackend()
    await backend.initialize()
    set_runtime(backend)

    # Spawn app in process context
    logger.info("[main] Spawning app process")
    app_pid = await process.spawn(app, name="stress_app", mailbox=True)
    logger.info(f"[main] Application process started: {app_pid}")

    # Wait for app to run
    try:
        while process.is_alive(app_pid):
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n[main] KeyboardInterrupt - shutting down...")
        await process.exit(app_pid, "shutdown")
        await asyncio.sleep(0.5)
    finally:
        logger.info("[main] Shutting down backend")
        await backend.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
