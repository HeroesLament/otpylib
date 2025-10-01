# http_listener_module.py – in same dir as hello_otp_http.py
import asyncio
import logging
from otpylib import process, dynamic_supervisor

async def init(pid, args):
    host, port = args
    logging.info(f"[HttpListener] starting on {host}:{port}")

    conn_sup = process.whereis("conn_dynsup")
    if not conn_sup:
        raise RuntimeError("conn_dynsup not found")

    async def handle_client(reader, writer):
        await dynamic_supervisor.start_child(
            conn_sup,
            dynamic_supervisor.child_spec(
                id=f"conn-{id(writer)}",
                func=connection_worker,
                args=[reader, writer],
                restart=dynamic_supervisor.TEMPORARY,
            ),
        )

    server = await asyncio.start_server(handle_client, host, port)
    logging.info(f"[HttpListener] listening on {host}:{port}")
    return {"server": server}

async def terminate(state):
    server = state.get("server")
    if server:
        server.close()
        await server.wait_closed()
        logging.info("[HttpListener] closed server")

# Make sure otpylib sees this as a “module”
__name__ = "HttpListenerModule"
