import pytest
import anyio
from otpylib.mailbox.core import init_mailbox_registry


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
    init_mailbox_registry()
    yield
    # Cleanup if needed



@pytest.fixture
async def test_state(mailbox_env):
    """Provide test state for gen_server tests."""
    from . import sample_kvstore
    
    test_state = GenServerTestState()

    async with anyio.create_task_group() as tg:
        # Use structured concurrency - this will block until task_status.started()
        await tg.start(sample_kvstore.start, test_state)
        yield test_state

        # Cleanup
        try:
            await sample_kvstore.special_cast.stop()
            await anyio.sleep(0.1)
        except Exception:
            pass

@pytest.fixture(autouse=True)
def clean_genserver_state():
    """Clean gen_server global state before and after each test."""
    from otpylib.gen_server import core as gen_server_core
    
    # Clear before test
    gen_server_core._PENDING_CALLS.clear()
    gen_server_core._GENSERVER_STATES.clear()
    gen_server_core._CALL_COUNTER = 0
    
    yield
    
    # Clear after test
    gen_server_core._PENDING_CALLS.clear()
    gen_server_core._GENSERVER_STATES.clear()
    gen_server_core._CALL_COUNTER = 0
