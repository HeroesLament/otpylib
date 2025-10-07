"""
Process Module

High-level process management API for otpylib.
Provides BEAM-like process operations without exposing runtime details.
"""

from typing import Any, Optional, List, Dict, Callable, Tuple
from otpylib.runtime import get_runtime, set_runtime
from otpylib.runtime.backends.base import NotInProcessError, ProcessNotFoundError


async def spawn(
    func: Callable,
    args: Optional[List[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    name: Optional[str] = None,
    mailbox: bool = True,
    trap_exits: bool = False
) -> str:
    """
    Spawn a new process.
    
    :param func: Function to run as a process
    :param args: Positional arguments for the function
    :param kwargs: Keyword arguments for the function
    :param name: Optional registered name for the process
    :param mailbox: Whether to create a mailbox for this process
    :param trap_exits: Whether to trap exit signals as messages
    :returns: PID of the spawned process
    """
    runtime = get_runtime()
    if not runtime:
        raise RuntimeError("No runtime backend configured")
    
    return await runtime.spawn(
        func, args=args, kwargs=kwargs, 
        name=name, mailbox=mailbox, trap_exits=trap_exits
    )


async def spawn_link(
    func: Callable,
    args: Optional[List[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    name: Optional[str] = None,
    mailbox: bool = True,
    trap_exits: bool = False
) -> str:
    """
    Spawn a process and link it to the current process.
    
    If either process dies, the other receives an exit signal.
    
    :param func: Function to run as a process
    :param args: Positional arguments for the function
    :param kwargs: Keyword arguments for the function
    :param name: Optional registered name for the process
    :param mailbox: Whether to create a mailbox for this process
    :returns: PID of the spawned process
    """
    runtime = get_runtime()
    if not runtime:
        raise RuntimeError("No runtime backend configured")
    
    return await runtime.spawn_link(
        func, args=args, kwargs=kwargs,
        name=name, mailbox=mailbox, trap_exits=trap_exits
    )


async def spawn_monitor(
    func: Callable,
    args: Optional[List[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    name: Optional[str] = None,
    mailbox: bool = True
) -> Tuple[str, str]:
    """
    Spawn a process and monitor it from the current process.
    
    When the spawned process dies, the current process receives a DOWN message.
    
    :param func: Function to run as a process
    :param args: Positional arguments for the function
    :param kwargs: Keyword arguments for the function
    :param name: Optional registered name for the process
    :param mailbox: Whether to create a mailbox for this process
    :returns: Tuple of (PID, monitor_ref)
    """
    runtime = get_runtime()
    if not runtime:
        raise RuntimeError("No runtime backend configured")
    
    return await runtime.spawn_monitor(
        func, args=args, kwargs=kwargs,
        name=name, mailbox=mailbox
    )


async def send(target: str, message: Any) -> None:
    """
    Send a message to a process.
    
    :param target: Process PID or registered name
    :param message: Message to send
    """
    runtime = get_runtime()
    if not runtime:
        raise RuntimeError("No runtime backend configured")
    
    await runtime.send(target, message)


async def receive(
    timeout: Optional[float] = None,
    match: Optional[Callable[[Any], bool]] = None
) -> Any:
    """
    Receive a message in the current process.
    
    :param timeout: Optional timeout in seconds
    :param match: Optional function to match specific messages
    :returns: The received message
    :raises NotInProcessError: If not called from within a process
    :raises TimeoutError: If timeout expires
    """
    runtime = get_runtime()
    if not runtime:
        raise RuntimeError("No runtime backend configured")
    
    return await runtime.receive(timeout=timeout, match=match)


async def register(name: str, pid: Optional[str] = None) -> None:
    """
    Register a name for a process.
    
    :param name: Name to register
    :param pid: Process ID (defaults to current process)
    """
    runtime = get_runtime()
    if not runtime:
        raise RuntimeError("No runtime backend configured")
    
    await runtime.register(name, pid)


async def unregister(name: str) -> None:
    """
    Unregister a name.
    
    :param name: Name to unregister
    """
    runtime = get_runtime()
    if not runtime:
        raise RuntimeError("No runtime backend configured")
    
    await runtime.unregister(name)


def whereis(name: str) -> Optional[str]:
    """
    Look up a PID by registered name.
    
    :param name: Registered name
    :returns: PID if found, None otherwise
    """
    runtime = get_runtime()
    if not runtime:
        return None
    
    return runtime.whereis(name)


def whereis_name(name: str) -> Optional[str]:
    """
    Look up the registered name of a PID.
    
    :param pid: The PID to be queried
    :returns: Name if found, None otherwise
    """
    runtime = get_runtime()
    if not runtime:
        return None
    
    return runtime.whereis_name()


def self() -> Optional[str]:
    """
    Get the PID of the current process.
    
    :returns: Current process PID, or None if not in a process context
    """
    runtime = get_runtime()
    if not runtime:
        return None
    
    return runtime.self()


async def link(pid: str) -> None:
    """
    Link the current process to another process.
    
    Creates bidirectional link - if either dies, the other is notified.
    
    :param pid: Process to link to
    :raises NotInProcessError: If not called from within a process
    """
    runtime = get_runtime()
    if not runtime:
        raise RuntimeError("No runtime backend configured")
    
    await runtime.link(pid)


async def unlink(pid: str) -> None:
    """
    Remove link between current process and another process.
    
    :param pid: Process to unlink from
    :raises NotInProcessError: If not called from within a process
    """
    runtime = get_runtime()
    if not runtime:
        raise RuntimeError("No runtime backend configured")
    
    await runtime.unlink(pid)


async def monitor(pid: str) -> str:
    """
    Monitor another process from the current process.
    
    When target dies, current process receives a DOWN message.
    
    :param pid: Process to monitor
    :returns: Monitor reference
    :raises NotInProcessError: If not called from within a process
    """
    runtime = get_runtime()
    if not runtime:
        raise RuntimeError("No runtime backend configured")
    
    return await runtime.monitor(pid)


async def demonitor(ref: str, flush: bool = False) -> None:
    """
    Remove a monitor.
    
    :param ref: Monitor reference to remove
    :param flush: If True, remove any pending DOWN messages
    """
    runtime = get_runtime()
    if not runtime:
        raise RuntimeError("No runtime backend configured")
    
    await runtime.demonitor(ref, flush)


async def exit(pid: str, reason: Any) -> None:
    """
    Send an exit signal to a process.
    
    :param pid: Process to send exit signal to
    :param reason: Exit reason (usually an atom or exception)
    """
    runtime = get_runtime()
    if not runtime:
        raise RuntimeError("No runtime backend configured")
    
    await runtime.exit(pid, reason)


def is_alive(pid: str) -> bool:
    """
    Check if a process is alive.
    
    :param pid: Process ID to check
    :returns: True if process is alive, False otherwise
    """
    runtime = get_runtime()
    if not runtime:
        return False
    
    return runtime.is_alive(pid)


def processes() -> List[str]:
    """
    Get all process IDs.
    
    :returns: List of all PIDs
    """
    runtime = get_runtime()
    if not runtime:
        return []
    
    return runtime.processes()


def registered() -> List[str]:
    """
    Get all registered names.
    
    :returns: List of all registered names
    """
    runtime = get_runtime()
    if not runtime:
        return []
    
    return runtime.registered()


def use_runtime(runtime) -> None:
    """
    Install a runtime backend globally for the process API.

    :param runtime: RuntimeBackend instance (e.g., AsyncIOBackend)
    """
    set_runtime(runtime)


async def _reset_for_testing():
    """
    Clear all registered processes and mailboxes.
    Internal use only: called by pytest fixtures.
    """
    runtime = get_runtime()
    if not runtime:
        return

    await runtime.reset()
