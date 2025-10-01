# examples/hello_otp_http.py
"""
Example: OTP Hello World HTTP server (wrapper-child, stable)

What this demonstrates:
- Static supervisor: supervisor.start(children, options(...), name=...)
- GenServer started via a *wrapper child* that stays alive
  (prevents normal-return restarts and name clashes)
- Ephemeral port bind (host, 0), with log of the chosen port
"""

import asyncio
import logging
from typing import Tuple

from otpylib import process, supervisor, gen_server
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime.registry import set_runtime


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

print("\n=== Example: OTP Hello World HTTP server ===")


# -----------------------------------------------------------------------------
# Connection worker (one per accepted connection)
# -----------------------------------------------------------------------------
async def connection_worker(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        data = await reader.read(1024)
        first = data.decode(errors="ignore").splitlines()[0] if data else "-"
        logger.info(f"[conn:{process.self()}] got: {first}")

        body = b"Hello World"
        resp = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"\r\n" + body
        )
        writer.write(resp)
        await writer.drain()
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logger.info("[conn] closed")


# -----------------------------------------------------------------------------
# HttpListener GenServer (module-style)
# -----------------------------------------------------------------------------
class HttpListenerModule:
    __name__ = "HttpListenerModule"

    @staticmethod
    async def init(init_arg: Tuple[str, int]):
        host, port = init_arg
        logger.info(f"[HttpListener] requested bind on {host}:{port}")

        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            # Spawn a lightweight otpylib process per connection
            await process.spawn(connection_worker, args=[reader, writer])

        server = await asyncio.start_server(handle_client, host, port)
        # Discover the ephemeral port actually chosen (when port==0)
        sock = server.sockets[0].getsockname() if server.sockets else (host, port)
        logger.info(f"[HttpListener] listening on {sock[0]}:{sock[1]}")
        return {"server": server, "sock": sock}

    @staticmethod
    async def handle_info(message, state):
        # No special info handling; keep state
        return gen_server.NoReply(), state

    @staticmethod
    async def terminate(reason, state):
        server = state.get("server") if state else None
        if server:
            server.close()
            await server.wait_closed()
            logger.info("[HttpListener] server closed")


# -----------------------------------------------------------------------------
# Wrapper child process for the listener
#   - Starts the GenServer via start_link (linked to this wrapper)
#   - Keeps running (so the supervisor doesn't see a normal exit)
# -----------------------------------------------------------------------------
async def http_listener_child():
    server_name = "http_listener_server"  # distinct from wrapper name
    # Bind to ephemeral port 0 to avoid conflicts
    await gen_server.start_link(HttpListenerModule, ("127.0.0.1", 0), name=server_name)
    logger.info(f"[http_listener_child] GenServer started (name={server_name})")

    # Keep this wrapper alive; supervisor now sees it as healthy
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        # Supervisor shutdown will cancel this; linked GenServer will be taken down too
        logger.info("[http_listener_child] cancelled")
        raise


# -----------------------------------------------------------------------------
# HTTP supervisor bootstrap (child of http_app)
# -----------------------------------------------------------------------------
async def start_http_sup():
    children = [
        supervisor.child_spec(
            id="http_listener",
            func=http_listener_child,           # wrapper that stays alive
            args=[],
            restart=supervisor.PERMANENT,
            name="http_listener",               # wrapper's registered name (distinct from server_name)
        ),
    ]
    opts = supervisor.options(strategy=supervisor.ONE_FOR_ONE)
    sup_pid = await supervisor.start(children, opts, name="http_super")
    logger.info(f"[http_sup] started as {sup_pid}")
    return sup_pid


# -----------------------------------------------------------------------------
# Application process (roots the supervision tree)
# -----------------------------------------------------------------------------
async def http_app():
    logger.info(f"[http_app] running in {process.self()}")
    sup_pid = await process.spawn(start_http_sup)
    logger.info(f"[http_app] supervisor started as {sup_pid}")

    # Keep the app alive (simple run loop)
    try:
        while True:
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        logger.info("[http_app] cancelled; exiting")
        raise


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
async def main():
    # Backend init & registration
    backend = AsyncIOBackend()
    await backend.initialize()
    set_runtime(backend)

    # Spawn root app
    app_pid = await process.spawn(http_app)
    print(f"[main] spawned http_app process {app_pid}")

    # Run until Ctrl+C
    try:
        while True:
            await asyncio.sleep(1.0)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("[main] shutting down")
    finally:
        # Best-effort nudge to the app (optional; app doesn't receive)
        try:
            if process.is_alive(app_pid):
                await process.send(app_pid, supervisor.SHUTDOWN)
        except Exception:
            pass
        await backend.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
