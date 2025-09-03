"""
In Erlang_/Elixir_, each process have a PID that can be used to receive message
from other processes.

.. _erlang: https://erlang.org
.. _elixir: https://elixir-lang.org/

With anyio, there is no such thing as a process. There is only asynchronous tasks
started within a task group.

This module provides an encapsulation of anyio's memory object streams_ which allows
tasks to communicate with each other.

.. _streams: https://anyio.readthedocs.io/en/stable/streams.html#object-streams

.. code-block:: python
   :caption: Example

   from anyiotp import mailbox
   import anyio


   async def task_a(task_status=anyio.TASK_STATUS_IGNORED):
       async with mailbox.open(name='task_a') as mid:
           task_status.started(None)

           msg = await mailbox.receive(mid)
           print(msg)


   async def task_b():
       await mailbox.send('task_a', 'hello world')


   async def main():
       async with anyio.create_task_group() as tg:
           await tg.start(task_a)  # Note: anyio doesn't have nursery.start()
           tg.start_soon(task_b)
"""

from collections.abc import Callable, Awaitable
from typing import Union, Optional, Any, AsyncIterator

from contextlib import asynccontextmanager
from contextvars import ContextVar
from uuid import uuid4

import anyio


from typing import Dict, Tuple

MailboxID = str  #: Mailbox identifier (UUID4)

MailboxRegistry = Dict[
    MailboxID,
    Tuple[anyio.abc.ObjectSendStream, anyio.abc.ObjectReceiveStream],
]

NameRegistry = Dict[str, MailboxID]

# Registry storage - configurable between ContextVar (isolated) and global (distributed)
_USE_GLOBAL_REGISTRY = False

# ContextVar storage (default - maintains triotp compatibility)
context_mailbox_registry = ContextVar[MailboxRegistry]("mailbox_registry")
context_name_registry = ContextVar[NameRegistry]("name_registry")

# Global storage (optional - enables distribution)
_global_mailbox_registry: MailboxRegistry = {}
_global_name_registry: NameRegistry = {}
_registry_lock = anyio.Lock()


class MailboxDoesNotExist(RuntimeError):
    """
    Error thrown when the mailbox identifier was not found.
    """

    def __init__(self, mid: MailboxID):
        super().__init__(f"mailbox {mid} does not exist")


class NameAlreadyExist(RuntimeError):
    """
    Error thrown when trying to register a mailbox to an already registered
    name.
    """

    def __init__(self, name: str):
        super().__init__(f"mailbox {name} already registered")


class NameDoesNotExist(RuntimeError):
    """
    Error thrown when trying to unregister a non-existing name.
    """

    def __init__(self, name: str):
        super().__init__(f"mailbox {name} does not exist")


def configure_global_registry(enabled: bool = True) -> None:
    """
    Configure whether to use global registry (for distribution) or ContextVar (for isolation).
    
    :param enabled: If True, use global registry. If False, use ContextVar (default triotp behavior)
    """
    global _USE_GLOBAL_REGISTRY
    _USE_GLOBAL_REGISTRY = enabled


def _get_mailbox_registry() -> MailboxRegistry:
    """Get the appropriate mailbox registry based on configuration."""
    if _USE_GLOBAL_REGISTRY:
        return _global_mailbox_registry
    else:
        return context_mailbox_registry.get()


def _get_name_registry() -> NameRegistry:
    """Get the appropriate name registry based on configuration."""
    if _USE_GLOBAL_REGISTRY:
        return _global_name_registry
    else:
        return context_name_registry.get()


def init_mailbox_registry() -> None:
    """Initialize the global otpylib mailbox registry system."""
    if _USE_GLOBAL_REGISTRY:
        global _global_mailbox_registry, _global_name_registry
        _global_mailbox_registry.clear()
        _global_name_registry.clear()
    else:
        context_mailbox_registry.set({})
        context_name_registry.set({})


def create(buffer_size: int = 100) -> MailboxID:
    """Create a new mailbox with buffering."""
    mid = str(uuid4())
    
    mailbox_registry = _get_mailbox_registry()
    send_stream, receive_stream = anyio.create_memory_object_stream(buffer_size)
    mailbox_registry[mid] = (send_stream, receive_stream)

    return mid


async def destroy(mid: MailboxID) -> None:
    """
    Close and destroy a mailbox.

    :param mid: The mailbox identifier
    :raises MailboxDoesNotExist: The mailbox identifier was not found
    """
    mailbox_registry = _get_mailbox_registry()

    if mid not in mailbox_registry:
        raise MailboxDoesNotExist(mid)

    unregister_all(mid)

    send_stream, receive_stream = mailbox_registry.pop(mid)
    await send_stream.aclose()
    await receive_stream.aclose()


def register(mid: MailboxID, name: str) -> None:
    """
    Assign a name to a mailbox.

    :param mid: The mailbox identifier
    :param name: The new name

    :raises MailboxDoesNotExist: The mailbox identifier was not found
    :raises NameAlreadyExist: The name was already registered
    """
    mailbox_registry = _get_mailbox_registry()

    if mid not in mailbox_registry:
        raise MailboxDoesNotExist(mid)

    name_registry = _get_name_registry()
    if name in name_registry:
        raise NameAlreadyExist(name)

    name_registry[name] = mid


def unregister(name: str) -> None:
    """
    Unregister a mailbox's name.

    :param name: The name to unregister
    :raises NameDoesNotExist: The name was not found
    """
    name_registry = _get_name_registry()
    if name not in name_registry:
        raise NameDoesNotExist(name)

    name_registry.pop(name)


def unregister_all(mid: MailboxID) -> None:
    """
    Unregister all names associated to a mailbox.

    :param mid: The mailbox identifier
    """
    name_registry = _get_name_registry()

    for name, mailbox_id in list(name_registry.items()):
        if mailbox_id == mid:
            name_registry.pop(name)


@asynccontextmanager
async def open(name: Optional[str] = None) -> AsyncIterator[MailboxID]:
    """
    Shortcut for `create()`, `register()` followed by a `destroy()`.

    :param name: Optional name to register the mailbox
    :returns: Asynchronous context manager for the mailbox
    :raises NameAlreadyExist: If the `name` was already registered

    .. code-block:: python
       :caption: Example

       async with mailbox.open(name='foo') as mid:
           message = await mailbox.receive(mid)
           print(message)
    """
    mid = create()

    try:
        if name is not None:
            register(mid, name)

        yield mid

    finally:
        await destroy(mid)


def _resolve(name: str) -> Optional[MailboxID]:
    """Resolve a name to a mailbox ID."""
    name_registry = _get_name_registry()
    return name_registry.get(name)


async def send(name_or_mid: Union[str, MailboxID], message: Any) -> None:
    """
    Send a message to a mailbox.

    :param name_or_mid: Either a registered name, or the mailbox identifier
    :param message: The message to send
    :raises MailboxDoesNotExist: The mailbox was not found
    """
    mailbox_registry = _get_mailbox_registry()

    mid = _resolve(name_or_mid)
    if mid is None:
        mid = name_or_mid

    if mid not in mailbox_registry:
        raise MailboxDoesNotExist(mid)

    send_stream, _ = mailbox_registry[mid]
    await send_stream.send(message)


async def receive(
    mid: MailboxID,
    timeout: Optional[float] = None,
    on_timeout: Optional[Callable[[], Awaitable[Any]]] = None,
) -> Any:
    """
    Consume a message from a mailbox.

    :param mid: The mailbox identifier
    :param timeout: If set, the call will fail after the timespan set in seconds
    :param on_timeout: If set and `timeout` is set, instead of raising an
                       exception, the result of this async function will be
                       returned

    :raises MailboxDoesNotExist: The mailbox was not found
    :raises TimeoutError: If `timeout` is set, but `on_timeout` isn't, and
                         no message was received during the timespan set
    """
    mailbox_registry = _get_mailbox_registry()

    if mid not in mailbox_registry:
        raise MailboxDoesNotExist(mid)

    _, receive_stream = mailbox_registry[mid]

    if timeout is not None:
        with anyio.move_on_after(timeout) as cancel_scope:
            return await receive_stream.receive()

        # Check if we timed out
        if cancel_scope.cancelled_caught:
            if on_timeout is None:
                raise TimeoutError("Mailbox receive timed out")

            return await on_timeout()

    else:
        return await receive_stream.receive()


# Compatibility function for task status (anyio doesn't have nursery.start equivalent)
class TaskStatus:
    """Mock task status for anyio compatibility."""
    
    def __init__(self):
        self._started_value = None
        self._started_event = anyio.Event()
    
    def started(self, value=None):
        """Signal that task has started."""
        self._started_value = value
        self._started_event.set()
    
    async def wait_started(self):
        """Wait for task to signal started."""
        await self._started_event.wait()
        return self._started_value


# Anyio doesn't have TASK_STATUS_IGNORED, so we create a compatible version
TASK_STATUS_IGNORED = TaskStatus()