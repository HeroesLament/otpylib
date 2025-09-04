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


async def test_receive_no_timeout():
    """Test normal message sending and receiving."""
    mailbox.init_mailbox_registry()
    
    producer = Producer("pytest")
    consumer = Consumer("pytest")

    async with anyio.create_task_group() as tg:
        # Start consumer first
        tg.start_soon(consumer)
        await anyio.sleep(0.01)  # Give consumer time to open mailbox
        tg.start_soon(producer, "foo")

    assert not consumer.timed_out
    assert consumer.received_message == "foo"


async def test_receive_on_timeout():
    """Test receive with timeout and on_timeout callback."""
    mailbox.init_mailbox_registry()
    
    consumer = Consumer("pytest", timeout=0.01)

    async with anyio.create_task_group() as tg:
        tg.start_soon(consumer)

    assert consumer.timed_out
    assert consumer.received_message is None


async def test_receive_too_slow():
    """Test receive timeout without callback raises TimeoutError."""
    mailbox.init_mailbox_registry()
    
    consumer = Consumer("pytest", timeout=0.01, with_on_timeout=False)

    with pytest.raises(ExceptionGroup) as exc_info:
        async with anyio.create_task_group() as tg:
            tg.start_soon(consumer)
    
    # Check that the ExceptionGroup contains a TimeoutError
    assert any(isinstance(e, TimeoutError) and "Mailbox receive timed out" in str(e) 
               for e in exc_info.value.exceptions)


async def test_no_mailbox():
    """Test operations on non-existent mailboxes."""
    mailbox.init_mailbox_registry()
    
    producer = Producer("pytest")

    with pytest.raises(mailbox.MailboxDoesNotExist):
        await producer("foo")

    with pytest.raises(mailbox.MailboxDoesNotExist):
        await mailbox.receive("pytest")


async def test_direct():
    """Test direct communication using mailbox ID."""
    mailbox.init_mailbox_registry()
    
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


async def test_register():
    """Test mailbox registration and name collision handling."""
    mailbox.init_mailbox_registry()
    
    # Test registering non-existent mailbox
    with pytest.raises(mailbox.MailboxDoesNotExist):
        mailbox.register("not-found", "pytest")

    # Test name collision
    async with mailbox.open("pytest") as mid1:
        # Try to register the same name again
        with pytest.raises(mailbox.NameAlreadyExist):
            async with mailbox.open("pytest") as mid2:
                pass  # This should fail in mailbox.open()


async def test_unregister():
    """Test mailbox unregistration."""
    mailbox.init_mailbox_registry()
    
    # First create and register a mailbox
    async with mailbox.open("pytest") as mid:
        # Unregister the name
        mailbox.unregister("pytest")
        
        # Try to unregister again - should fail
        with pytest.raises(mailbox.NameDoesNotExist):
            mailbox.unregister("pytest")
        
        # Try to send to unregistered name - should fail
        with pytest.raises(mailbox.MailboxDoesNotExist):
            await mailbox.send("pytest", "foo")


async def test_destroy_unknown():
    """Test destroying non-existent mailbox."""
    mailbox.init_mailbox_registry()
    
    with pytest.raises(mailbox.MailboxDoesNotExist):
        await mailbox.destroy("not-found")