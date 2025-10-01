"""
Sample KVStore implemented as a gen_server for testing.
"""

import sys
import asyncio
from otpylib.helpers import current_module
from otpylib import gen_server, process
from otpylib.gen_server.atoms import STOP_ACTION, CRASH, TERMINATED

# Fixed, explicit name for registration
SERVER_NAME = "tests.test_gen_server.sample_kvstore"
__module__ = current_module()

# =====================================================================
# Lifecycle
# =====================================================================

async def init(test_state):
    """Initialize state."""
    test_state.ready.set()
    return test_state


async def terminate(reason, test_state):
    """Run on shutdown."""
    test_state.terminated_with = reason or TERMINATED
    test_state.stopped.set()

# =====================================================================
# Callbacks
# =====================================================================

async def handle_call(message, caller, test_state):
    payload = getattr(message, "payload", message)

    match payload:
        case ("api_get", key):
            val = test_state.data.get(key)
            return (gen_server.Reply(payload=val), test_state)

        case ("api_set", key, val):
            prev = test_state.data.get(key)
            test_state.data[key] = val
            return (gen_server.Reply(payload=prev), test_state)

        case "api_clear":
            test_state.data.clear()
            return (gen_server.Reply(payload=None), test_state)

        # Special calls
        case ("special_call_normal", val):
            return (gen_server.Reply(payload=f"ok:{val}"), test_state)

        case ("special_call_stopped",):
            return (gen_server.Stop(STOP_ACTION), test_state)

        case ("special_call_failure",):
            return (gen_server.Stop(CRASH), test_state)

        case _:
            return (gen_server.Reply(payload=("error", "wrong_call")), test_state)


async def handle_cast(message, test_state):
    payload = getattr(message, "payload", message)

    match payload:
        case "special_cast_normal":
            test_state.casted.set()
            return (gen_server.NoReply(), test_state)

        case "special_cast_stop":
            test_state.stopped.set()
            return (gen_server.Stop("stop"), test_state)

        case "special_cast_fail":
            exc = RuntimeError("pytest")
            return (gen_server.Stop(exc), test_state)

        case ("stop", _):
            test_state.stopped.set()
            return (gen_server.Stop("stop"), test_state)

        case _:
            return (gen_server.NoReply(), test_state)


async def handle_info(message, test_state):
    payload = getattr(message, "payload", message)

    match payload:
        case ("special_info_matched", val):
            test_state.info_val = val
            test_state.info.set()
            return (gen_server.NoReply(), test_state)

        case "special_info_stop":
            return (gen_server.Stop(STOP_ACTION), test_state)

        case "special_info_fail":
            return (gen_server.Stop(CRASH), test_state)

        case _:
            test_state.unknown_info.append(payload)
            test_state.info.set()
            return (gen_server.NoReply(), test_state)

# =====================================================================
# Bind functions into the module object (BEAM semantics)
# =====================================================================

this_module = sys.modules[__name__]
this_module.init = init
this_module.terminate = terminate
this_module.handle_call = handle_call
this_module.handle_cast = handle_cast
this_module.handle_info = handle_info

# =====================================================================
# Entry point
# =====================================================================

async def start(test_state=None) -> str:
    """Start the KVStore server with this module as callbacks."""
    from tests.test_gen_server.conftest import GenServerTestState

    if test_state is None:
        test_state = GenServerTestState()

    pid = await gen_server.start(module=this_module, init_arg=test_state, name=SERVER_NAME)
    return pid

# =====================================================================
# Public API for tests
# =====================================================================

async def call(msg, *, timeout=None):
    return await gen_server.call(SERVER_NAME, msg, timeout=timeout)

async def cast(msg):
    return await gen_server.cast(SERVER_NAME, msg)

async def info(msg):
    return await process.send(SERVER_NAME, msg)


class api:
    @staticmethod
    async def get(key):
        return await gen_server.call(SERVER_NAME, ("api_get", key))

    @staticmethod
    async def set(key, val):
        return await gen_server.call(SERVER_NAME, ("api_set", key, val))

    @staticmethod
    async def clear():
        return await gen_server.call(SERVER_NAME, "api_clear")


class special_call:
    @staticmethod
    async def normal(val):
        return await gen_server.call(SERVER_NAME, ("special_call_normal", val))

    @staticmethod
    async def stop():
        return await gen_server.call(SERVER_NAME, ("special_call_stopped",))

    @staticmethod
    async def fail():
        return await gen_server.call(SERVER_NAME, ("special_call_failure",))


class special_cast:
    @staticmethod
    async def normal():
        await gen_server.cast(SERVER_NAME, "special_cast_normal")

    @staticmethod
    async def stop():
        await gen_server.cast(SERVER_NAME, "special_cast_stop")

    @staticmethod
    async def fail():
        await gen_server.cast(SERVER_NAME, "special_cast_fail")


class special_info:
    @staticmethod
    async def matched(val):
        await process.send(SERVER_NAME, ("special_info_matched", val))

    @staticmethod
    async def stop():
        await process.send(SERVER_NAME, "special_info_stop")

    @staticmethod
    async def fail():
        await process.send(SERVER_NAME, "special_info_fail")
