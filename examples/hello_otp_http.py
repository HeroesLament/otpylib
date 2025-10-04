# examples/hello_otp_http.py
"""
Example: OTP Hello World HTTP server (wrapper-child, stable)

What this demonstrates:
- Static supervisor: supervisor.start(children, options(...), name=...)
- GenServer started via a *wrapper child* that stays alive
- Ephemeral port bind (host, 0), with log of the chosen port
"""

import asyncio
from typing import Tuple

from otpylib import process, supervisor, gen_server
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.runtime.registry import set_runtime
import otpylib_logger as logger
from otpylib_logger import LOGGER_SUP
from otpylib_logger.data import LoggerSpec, HandlerSpec, LogLevel


# -----------------------------------------------------------------------------
# Connection worker (one per accepted connection)
# -----------------------------------------------------------------------------
async def connection_worker(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        data = await reader.read(1024)
        first = data.decode(errors="ignore").splitlines()[0] if data else "-"
        await logger.info(f"[conn:{process.self()}] got: {first}")

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
        await logger.info("[conn] closed")


# -----------------------------------------------------------------------------
# HttpListener GenServer (module-style)
# -----------------------------------------------------------------------------
class HttpListenerModule:
    __name__ = "HttpListenerModule"

    @staticmethod
    async def init(init_arg: Tuple[str, int]):
        host, port = init_arg
        print(f"[HttpListener] requested bind on {host}:{port}")

        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            await process.spawn(connection_worker, args=[reader, writer])

        server = await asyncio.start_server(handle_client, host, port)
        sock = server.sockets[0].getsockname() if server.sockets else (host, port)
        print(f"[HttpListener] listening on {sock[0]}:{sock[1]}")
        return {"server": server, "sock": sock}

    @staticmethod
    async def handle_info(message, state):
        return gen_server.NoReply(), state

    @staticmethod
    async def terminate(reason, state):
        server = state.get("server") if state else None
        if server:
            server.close()
            await server.wait_closed()
            print("[HttpListener] server closed")


# -----------------------------------------------------------------------------
# Wrapper child - returns a spawned process PID
# -----------------------------------------------------------------------------
async def http_listener_child():
    """Factory that spawns the HTTP listener wrapper process."""
    async def listener_wrapper():
        server_name = "http_listener_server"
        await gen_server.start_link(HttpListenerModule, ("127.0.0.1", 0), name=server_name)
        await logger.info(f"[listener_wrapper] GenServer started (name={server_name})")

        # Keep wrapper alive
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await logger.info("[listener_wrapper] cancelled")
            raise
    
    return await process.spawn(listener_wrapper, mailbox=True)


# -----------------------------------------------------------------------------
# HTTP supervisor setup
# -----------------------------------------------------------------------------
async def start_http_sup():
    """Start HTTP supervisor with logger and listener."""
    logger_spec = LoggerSpec(
        level=LogLevel.INFO,
        handlers=[
            HandlerSpec(
                name="console",
                handler_module="otpylib_logger.handlers.console",
                config={"use_stderr": False, "colorize": True},
                level=LogLevel.INFO,
            ),
        ]
    )

    children = [
        supervisor.child_spec(
            id=LOGGER_SUP,
            func=logger.start_link,
            args=[logger_spec],
            restart=supervisor.PERMANENT,
        ),
        supervisor.child_spec(
            id="http_listener",
            func=http_listener_child,
            restart=supervisor.PERMANENT,
        ),
    ]
    
    opts = supervisor.options(strategy=supervisor.ONE_FOR_ONE)
    
    # supervisor.start() spawns the supervisor and returns after handshake
    sup_pid = await supervisor.start(
        child_specs=children,
        opts=opts,
        name="http_super"
    )
    
    return sup_pid


# -----------------------------------------------------------------------------
# Application process
# -----------------------------------------------------------------------------
async def http_app():
    """Root application process."""
    print(f"[http_app] starting in {process.self()}")
    
    # Start supervisor (returns immediately after handshake)
    sup_pid = await start_http_sup()
    print(f"[http_app] supervisor started as {sup_pid}")
    
    # Wait for logger to be ready
    await asyncio.sleep(0.5)
    await logger.info("[http_app] entering main loop")

    try:
        while True:
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        await logger.info("[http_app] cancelled; exiting")
        raise


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
async def main():
    backend = AsyncIOBackend()
    await backend.initialize()
    set_runtime(backend)

    app_pid = await process.spawn(http_app, mailbox=True)
    print(f"[main] spawned http_app process {app_pid}")

    try:
        while True:
            await asyncio.sleep(1.0)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[main] shutting down")
    finally:
        try:
            if process.is_alive(app_pid):
                await process.send(app_pid, supervisor.SHUTDOWN)
        except Exception:
            pass
        await backend.shutdown()


if __name__ == "__main__":
    asyncio.run(main())