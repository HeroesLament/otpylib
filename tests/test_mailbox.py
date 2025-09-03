import pytest
import anyio

from otpylib import mailbox


pytestmark = pytest.mark.anyio


class Producer:
    def __init__(self, mbox):
        self.mbox = mbox

    async def __call__(self, message):
        await mailbox.send(self.mbox, message)


class Consumer:
    def __init__(self, mbox, timeout=None, with_on_timeout=True):
        self.mbox = mbox
        self.timeout = timeout
        self.with_on_timeout = with_on_timeout

        self.received_message = None
        self.timed_out = False
        self.mid = None

    async def on_timeout(self):
        self.timed_out = True
        return None

    async def __call__(self):
        async with mailbox.open(self.mbox) as mid:
            self.mid = mid
            
            cb = self.on_timeout if self.with_on_timeout else None
            self.received_message = await mailbox.receive(
                mid,
                timeout=self.timeout,
                on_timeout=cb,
            )


async def test_receive_no_timeout(mailbox_env):
    producer = Producer("pytest")
    consumer = Consumer("pytest")

    async with anyio.create_task_group() as tg:
        # Start consumer first
        tg.start_soon(consumer)
        await anyio.sleep(0.01)  # Give consumer time to open mailbox
        tg.start_soon(producer, "foo")

    assert not consumer.timed_out
    assert consumer.received_message == "foo"


async def test_receive_on_timeout(mailbox_env):
    consumer = Consumer("pytest", timeout=0.01)

    async with anyio.create_task_group() as tg:
        tg.start_soon(consumer)

    assert consumer.timed_out
    assert consumer.received_message is None


async def test_receive_too_slow(mailbox_env):
    consumer = Consumer("pytest", timeout=0.01, with_on_timeout=False)

    with pytest.raises(TimeoutError):
        async with anyio.create_task_group() as tg:
            tg.start_soon(consumer)


async def test_no_mailbox(mailbox_env):
    producer = Producer("pytest")

    with pytest.raises(mailbox.MailboxDoesNotExist):
        await producer("foo")

    with pytest.raises(mailbox.MailboxDoesNotExist):
        await mailbox.receive("pytest")


async def test_direct(mailbox_env):
    consumer = Consumer(None)

    async with anyio.create_task_group() as tg:
        # Start consumer and wait for it to set up
        tg.start_soon(consumer)
        await anyio.sleep(0.01)  # Give consumer time to open mailbox
        
        # Use the mailbox ID directly
        producer = Producer(consumer.mid)
        tg.start_soon(producer, "foo")

    assert not consumer.timed_out
    assert consumer.received_message == "foo"


async def test_register(mailbox_env):
    consumer = Consumer("pytest")

    with pytest.raises(mailbox.MailboxDoesNotExist):
        mailbox.register("not-found", "pytest")

    with pytest.raises(mailbox.NameAlreadyExist):
        async with anyio.create_task_group() as tg:
            # Start first consumer
            tg.start_soon(consumer)
            await anyio.sleep(0.01)  # Give it time to register
            
            # Try to start second consumer with same name
            consumer2 = Consumer("pytest")
            tg.start_soon(consumer2)
            await anyio.sleep(0.01)  # Wait for the error to occur


async def test_unregister(mailbox_env):
    consumer = Consumer("pytest")
    producer = Producer("pytest")

    with pytest.raises(mailbox.MailboxDoesNotExist):
        async with anyio.create_task_group() as tg:
            tg.start_soon(consumer)
            await anyio.sleep(0.01)  # Give consumer time to register

            mailbox.unregister("pytest")

            with pytest.raises(mailbox.NameDoesNotExist):
                mailbox.unregister("pytest")

            # This should fail since mailbox was unregistered
            await producer("foo")


async def test_destroy_unknown(mailbox_env):
    with pytest.raises(mailbox.MailboxDoesNotExist):
        await mailbox.destroy("not-found")