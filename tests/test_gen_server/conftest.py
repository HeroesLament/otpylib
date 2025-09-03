import pytest
import anyio
from otpylib.mailbox.core import _init


class GenServerTestState:
    def __init__(self):
        self.ready = anyio.Event()
        self.stopped = anyio.Event()
        self.info = anyio.Event()
        self.casted = anyio.Event()

        self.data = {}
        self.did_raise = None
        self.terminated_with = None

        self.info_val = None
        self.unknown_info = []


@pytest.fixture
async def mailbox_env():
    """Initialize mailbox system for tests."""
    _init()
    yield
    # Cleanup if needed


@pytest.fixture
async def test_state(mailbox_env):
    """Provide test state for gen_server tests."""
    from . import sample_kvstore
    
    test_state = GenServerTestState()

    async with anyio.create_task_group() as tg:
        tg.start_soon(sample_kvstore.start, test_state)

        with anyio.move_on_after(1.0) as cancel_scope:
            await test_state.ready.wait()
        
        if cancel_scope.cancelled_caught:
            pytest.fail("GenServer failed to start within timeout")

        yield test_state

        # Cleanup
        try:
            await sample_kvstore.special_cast.stop()
            await anyio.sleep(0.1)
        except Exception:
            pass