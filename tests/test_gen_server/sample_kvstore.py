import anyio
import types
import pytest

from otpylib.helpers import current_module
from otpylib import gen_server, mailbox

__module__ = current_module()


pytestmark = pytest.mark.anyio


async def start(test_state, *, task_status):
    try:
        callbacks = create_callbacks()
        await gen_server.start(callbacks, test_state, name=__name__, task_status=task_status)

    except Exception as err:
        test_state.did_raise = err

    finally:
        test_state.stopped.set()


def create_callbacks():
    """Create gen_server callbacks namespace."""
    callbacks = types.SimpleNamespace()
    
    async def init(test_state):
        test_state.ready.set()
        return test_state

    async def terminate(reason, test_state):
        test_state.terminated_with = reason

    async def handle_call(message, caller, test_state):
        match message:
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

            case ("special_call_delayed", task_group):
                async def slow_task():
                    await anyio.sleep(0.1)
                    await gen_server.reply(caller, "done")

                task_group.start_soon(slow_task)
                return (gen_server.NoReply(), test_state)

            case "special_call_timedout":
                return (gen_server.NoReply(), test_state)

            case "special_call_stopped":
                return (gen_server.Stop(), test_state)

            case "special_call_failure":
                exc = RuntimeError("pytest")
                return (gen_server.Stop(exc), test_state)

            case _:
                exc = NotImplementedError("wrong call")
                return (gen_server.Reply(payload=exc), test_state)

    async def handle_cast(message, test_state):
        match message:
            case "special_cast_normal":
                test_state.casted.set()
                return (gen_server.NoReply(), test_state)

            case "special_cast_stop":
                return (gen_server.Stop(), test_state)

            case _:
                exc = NotImplementedError("wrong cast")
                return (gen_server.Stop(exc), test_state)

    async def handle_info(message, test_state):
        match message:
            case ("special_info_matched", val):
                test_state.info_val = val
                test_state.info.set()
                return (gen_server.NoReply(), test_state)

            case "special_info_stop":
                return (gen_server.Stop(), test_state)

            case "special_info_fail":
                exc = RuntimeError("pytest")
                return (gen_server.Stop(exc), test_state)

            case _:
                test_state.unknown_info.append(message)
                test_state.info.set()
                return (gen_server.NoReply(), test_state)

    callbacks.init = init
    callbacks.terminate = terminate
    callbacks.handle_call = handle_call
    callbacks.handle_cast = handle_cast
    callbacks.handle_info = handle_info
    
    return callbacks


class api:
    """
    Normal KVStore API
    """

    @staticmethod
    async def get(key):
        return await gen_server.call(__name__, ("api_get", key))

    @staticmethod
    async def set(key, val):
        return await gen_server.call(__name__, ("api_set", key, val))

    @staticmethod
    async def clear():
        return await gen_server.call(__name__, "api_clear")


class special_call:
    """
    Special edge cases for gen_server.call
    """

    @staticmethod
    async def delayed(task_group):
        return await gen_server.call(__name__, ("special_call_delayed", task_group))

    @staticmethod
    async def timedout(timeout):
        return await gen_server.call(__name__, "special_call_timedout", timeout=timeout)

    @staticmethod
    async def stopped():
        return await gen_server.call(__name__, "special_call_stopped")

    @staticmethod
    async def failure():
        return await gen_server.call(__name__, "special_call_failure")


class special_cast:
    """
    Special edge cases for gen_server.cast
    """

    @staticmethod
    async def normal():
        await gen_server.cast(__name__, "special_cast_normal")

    @staticmethod
    async def stop():
        await gen_server.cast(__name__, "special_cast_stop")

    @staticmethod
    async def fail():
        await gen_server.cast(__name__, "special_cast_fail")


class special_info:
    """
    Special edge cases for direct messages
    """

    @staticmethod
    async def matched(val):
        await mailbox.send(__name__, ("special_info_matched", val))

    @staticmethod
    async def no_match(val):
        await mailbox.send(__name__, ("special_info_no_match", val))

    @staticmethod
    async def stop():
        await mailbox.send(__name__, "special_info_stop")

    @staticmethod
    async def fail():
        await mailbox.send(__name__, "special_info_fail")