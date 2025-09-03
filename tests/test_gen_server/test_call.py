import pytest
import anyio

from . import sample_kvstore as kvstore
from otpylib.gen_server import GenServerExited


pytestmark = pytest.mark.anyio

async def test_kvstore_call_delayed(test_state):
    async with anyio.create_task_group() as task_group:
        resp = await kvstore.special_call.delayed(task_group)

    assert resp == "done"


async def test_kvstore_call_timeout(test_state):
    with pytest.raises(TimeoutError):
        await kvstore.special_call.timedout(0.01)


async def test_kvstore_call_stopped(test_state):
    with pytest.raises(GenServerExited):
        await kvstore.special_call.stopped()

    with anyio.fail_after(0.1):
        await test_state.stopped.wait()

    assert test_state.terminated_with is None
    assert test_state.did_raise is None


async def test_kvstore_call_failure(test_state):
    with pytest.raises(GenServerExited):
        await kvstore.special_call.failure()

    with anyio.fail_after(0.1):
        await test_state.stopped.wait()

    assert isinstance(test_state.terminated_with, RuntimeError)
    assert test_state.did_raise is test_state.terminated_with