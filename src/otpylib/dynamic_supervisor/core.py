"""
A dynamic supervisor is almost identical to a normal supervisor.

The only difference is that a dynamic supervisor creates a mailbox in order to
receive requests to start new children from other tasks.

.. code-block:: python
   :caption: Example

   # app.py

   from otpylib import supervisor, dynamic_supervisor
   import anyio

   from . import worker


   async def start():
       opts = supervisor.options()
       children = [
           supervisor.child_spec(
               id='worker_pool',
               task=dynamic_supervisor.start,
               args=[opts, 'worker-pool'],
           ),
       ]

       async with anyio.create_task_group() as tg:
           tg.start_soon(supervisor.start, children, opts)

           await dynamic_supervisor.start_child(
               'worker-pool',
               supervisor.child_spec(
                   id='worker-0',
                   task=worker.start,
                   args=[],
                   restart=supervisor.restart_strategy.TRANSIENT,
               ),
           )
"""

from typing import Optional, Union, Dict
import anyio
from anyio.abc import TaskGroup

from otpylib import supervisor
from otpylib import mailbox
from otpylib.types import StartupSync


class _DynamicSupervisorState:
    """Internal state for managing dynamic child supervision."""
    
    def __init__(self, opts: supervisor.options):
        self.opts = opts
        self.children: Dict[str, anyio.CancelScope] = {}
        self.task_group: Optional[TaskGroup] = None
    
    async def add_child(self, child_spec: supervisor.child_spec):
        """Add a new child to the supervisor."""
        if self.task_group is None:
            return
            
        # Cancel existing child with same ID
        if child_spec.id in self.children:
            self.children[child_spec.id].cancel()
            
        # Create new cancel scope for this child
        cancel_scope = anyio.CancelScope()
        self.children[child_spec.id] = cancel_scope
        
        # Start child in its own scope
        self.task_group.start_soon(self._run_child, child_spec, cancel_scope)
    
    async def _run_child(self, child_spec: supervisor.child_spec, cancel_scope: anyio.CancelScope):
        """Run a single child under supervision within its own cancel scope."""
        with cancel_scope:
            # Create a single-child supervisor for this task
            await supervisor.start([child_spec], self.opts)


# Global registry to track dynamic supervisor states
_supervisor_registry: Dict[mailbox.MailboxID, _DynamicSupervisorState] = {}


async def start(
    opts: supervisor.options,
    name: Optional[str] = None,
    startup_sync: Optional[StartupSync] = None,
) -> mailbox.MailboxID:
    """
    Starts a new dynamic supervisor.

    This function creates a new mailbox to receive request for new children.

    :param opts: Supervisor options
    :param name: Optional name to use to register the supervisor's mailbox
    :param startup_sync: Optional startup synchronization object
    :raises otpylib.mailbox.NameAlreadyExist: If the `name` was already registered

    .. code-block:: python
       :caption: Example

       from otpylib import dynamic_supervisor, supervisor
       import anyio


       async def example():
           opts = supervisor.options()
           child_spec = # ...

           async with anyio.create_task_group() as tg:
               # Start dynamic supervisor
               sync = supervisor._StartupSync() 
               tg.start_soon(dynamic_supervisor.start, opts, 'worker-pool', sync)
               mid = await sync.wait()
               
               # Add child
               await dynamic_supervisor.start_child(mid, child_spec)
    """

    async with mailbox.open(name) as mid:
        # Signal startup complete
        if startup_sync:
            startup_sync.started(mid)
        
        # Create supervisor state
        state = _DynamicSupervisorState(opts)
        _supervisor_registry[mid] = state
        
        try:
            async with anyio.create_task_group() as tg:
                state.task_group = tg
                
                # Start child listener
                listener_sync = StartupSync()
                tg.start_soon(_child_listener, mid, state, listener_sync)
                await listener_sync.wait()
                
                # Keep running until cancelled
                await anyio.sleep_forever()
                
        finally:
            # Cleanup
            _supervisor_registry.pop(mid, None)
            state.task_group = None
        
        return mid


async def start_child(
    name_or_mid: Union[str, mailbox.MailboxID],
    child_spec: supervisor.child_spec,
) -> None:
    """
    Start a new task in the specified supervisor.

    :param name_or_mid: Dynamic supervisor's mailbox identifier
    :param child_spec: Child specification to start
    """

    await mailbox.send(name_or_mid, child_spec)


async def terminate_child(
    name_or_mid: Union[str, mailbox.MailboxID], 
    child_id: str
) -> None:
    """
    Terminate a specific child in the dynamic supervisor.
    
    :param name_or_mid: Dynamic supervisor's mailbox identifier
    :param child_id: ID of the child to terminate
    """
    
    await mailbox.send(name_or_mid, {"action": "terminate", "child_id": child_id})


async def _child_listener(
    mid: mailbox.MailboxID,
    state: _DynamicSupervisorState,
    startup_sync: StartupSync,
) -> None:
    """Listen for child management requests."""
    
    startup_sync.started(None)

    while True:
        try:
            request = await mailbox.receive(mid)

            match request:
                case supervisor.child_spec() as spec:
                    await state.add_child(spec)

                case {"action": "terminate", "child_id": child_id}:
                    if child_id in state.children:
                        state.children[child_id].cancel()
                        state.children.pop(child_id)

                case _:
                    # Ignore unknown messages
                    pass
                    
        except Exception as e:
            # Log error but continue listening
            import logging
            logger = logging.getLogger("otpylib.dynamic_supervisor")
            logger.error(f"Error in child listener: {e}")
            continue