"""
An application is a Python module defining an asynchronous function `start`.

.. code-block:: python
   :caption: Example

   async def start(_start_arg):
       print('Hello world')

Usually, the application will start a supervisor containing the child tasks to
run.
"""

from typing import Optional, Any
from types import ModuleType
from contextvars import ContextVar
from dataclasses import dataclass

import anyio
from anyio.abc import TaskGroup

from otpylib import supervisor


context_app_task_group = ContextVar[TaskGroup]("app_task_group")
context_app_registry = ContextVar[dict[str, anyio.CancelScope]]("app_registry")


@dataclass
class app_spec:
    """Describe an application"""

    module: ModuleType  #: Application module
    start_arg: Any  #: Argument to pass to the module's start function
    permanent: bool = (
        True  #: If `False`, the application won't be restarted if it exits
    )
    opts: Optional[supervisor.options] = (
        None  #: Options for the supervisor managing the application task
    )


def _init(task_group: TaskGroup) -> None:
    context_app_task_group.set(task_group)
    context_app_registry.set({})


async def start(app: app_spec) -> None:
    """
    Starts an application on the current node. If the application is already
    started, it does nothing.

       **NB:** This function cannot be called outside a node.

    :param app: The application to start
    """

    task_group = context_app_task_group.get()
    registry = context_app_registry.get()

    if app.module.__name__ not in registry:
        # Start the app scope task and get its cancel scope
        started_event = anyio.Event()
        cancel_scope_holder = {}
        
        async def wrapper():
            await _app_scope(app, started_event, cancel_scope_holder)
        
        task_group.start_soon(wrapper)
        
        # Wait for the app scope to start and provide its cancel scope
        await started_event.wait()
        registry[app.module.__name__] = cancel_scope_holder['scope']


async def stop(app_name: str) -> None:
    """
    Stops an application. If the application was not running, it does nothing.

       **NB:** This function cannot be called outside a node.

    :param app_name: `__name__` of the application module
    """

    registry = context_app_registry.get()

    if app_name in registry:
        cancel_scope = registry.pop(app_name)
        cancel_scope.cancel()


async def _app_scope(
    app: app_spec, 
    started_event: anyio.Event,
    cancel_scope_holder: dict
) -> None:
    if app.permanent:
        restart = supervisor.restart_strategy.PERMANENT

    else:
        restart = supervisor.restart_strategy.TRANSIENT

    async with anyio.create_task_group() as tg:
        # Store the cancel scope and signal that we're started
        cancel_scope_holder['scope'] = tg.cancel_scope
        started_event.set()

        children = [
            supervisor.child_spec(
                id=app.module.__name__,
                task=app.module.start,
                args=[app.start_arg],
                restart=restart,
            )
        ]
        opts = app.opts if app.opts is not None else supervisor.options()

        tg.start_soon(supervisor.start, children, opts)