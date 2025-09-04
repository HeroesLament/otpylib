"""
An otpylib node encapsulates the call to `anyio.run` and allows you to specify a
list of application to start.

   **NB:** There is no dependency management between applications, it's up to
   you to start the correct applications in the right order.

.. code-block:: python
   :caption: Example

   from otpylib import node, application

   from myproject import myapp1, myapp2

   node.run(
       apps=[
           application.app_spec(
               module=myapp1,
               start_arg=[],
           ),
           application.app_spec(
               module=myapp2,
               start_arg=[],
               permanent=False,
           ),
       ],
   )
"""

from typing import Optional, List

import anyio

from otpylib import application, logging, mailbox


def run(
    apps: List[application.app_spec],
    loglevel: logging.LogLevel = logging.LogLevel.INFO,
    logformat: Optional[str] = None,
    backend: str = "asyncio",
) -> None:
    """
    Start a new node by calling `anyio.run`.

    :param apps: List of application to start
    :param loglevel: Logging Level of the node
    :param logformat: Format of log messages produced by the node
    :param backend: Async backend to use ('asyncio', 'trio', or 'auto')
    """
    
    # Configure logging with loguru
    if loglevel != logging.LogLevel.NONE:
        logging.configure_logging(level=loglevel, format_string=logformat)
    
    # Run the node with specified backend
    anyio.run(_start, apps, backend=backend)


async def _start(apps: List[application.app_spec]) -> None:
    """Internal function to start all applications within the node."""
    
    # Initialize mailbox system
    mailbox.init_mailbox_registry()

    async with anyio.create_task_group() as tg:
        # Initialize application management
        application._init(tg)

        # Start all applications
        for app_spec in apps:
            await application.start(app_spec)
        
        # Keep the node running until cancelled
        await anyio.sleep_forever()