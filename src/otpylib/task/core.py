"""
otpylib/task/core.py

TASK behavior - for running fire-and-forget async functions.

Similar to Elixir's Task behavior - spawns a process that runs a single
async function and exits when done.

Tasks are simple:
- Run a single async function (the `run` callback)
- Exit when the function completes
- Can be supervised like any other process
"""

from typing import Any, Optional
from otpylib import atom, process
from otpylib.module import (
    is_otp_module,
    get_behavior,
    ModuleError
)

# Task behavior atom
TASK = atom.ensure("task")

LOGGER = atom.ensure("logger")


# ============================================================================
# Exceptions
# ============================================================================

class NotATaskError(ModuleError):
    """Module is not a task behavior."""
    def __init__(self, module_class: type):
        behavior = get_behavior(module_class) if is_otp_module(module_class) else None
        super().__init__(
            f"Module {module_class.__name__} is not a task "
            f"(behavior: {behavior.name if behavior else 'unknown'})"
        )


# ============================================================================
# Validation
# ============================================================================

def _validate_task_module(module_class: type) -> None:
    """Validate that a class is an OTPModule with task behavior."""
    if not is_otp_module(module_class):
        raise NotATaskError(module_class)
    
    behavior = get_behavior(module_class)
    if behavior != TASK:
        raise NotATaskError(module_class)


# ============================================================================
# Public API
# ============================================================================

async def start_link(
    module_class: type,
    init_arg: Any = None,
    name: Optional[str] = None
) -> str:
    """
    Start a task process (linked to caller).
    
    Args:
        module_class: OTPModule class with TASK behavior
        init_arg: Argument passed to run callback
        name: Optional registered name
    
    Returns:
        Task PID
    """
    _validate_task_module(module_class)
    
    parent = process.self()
    if not parent:
        raise RuntimeError("task.start_link() must be called from within a process")
    
    task_pid = await process.spawn_link(
        _task_loop,
        args=[module_class, init_arg, parent],
        name=name,
        mailbox=True,
    )
    
    # Wait for init handshake
    msg = await process.receive(timeout=5.0)
    
    match msg:
        case ("task_init_ok", pid) if pid == task_pid:
            return task_pid
        case ("task_init_error", pid, reason) if pid == task_pid:
            raise RuntimeError(f"[task] {module_class.__mod_id__} init failed: {reason}")
        case _:
            raise RuntimeError(f"[task] Unexpected init reply: {msg}")


async def start(
    module_class: type,
    init_arg: Any = None,
    name: Optional[str] = None
) -> str:
    """
    Start a task process (not linked).
    
    Args:
        module_class: OTPModule class with TASK behavior
        init_arg: Argument passed to run callback
        name: Optional registered name
    
    Returns:
        Task PID
    """
    _validate_task_module(module_class)
    
    parent = process.self()
    if not parent:
        raise RuntimeError("task.start() must be called from within a process")
    
    task_pid = await process.spawn(
        _task_loop,
        args=[module_class, init_arg, parent],
        name=name,
        mailbox=True,
    )
    
    # Wait for init handshake
    msg = await process.receive(timeout=5.0)
    
    match msg:
        case ("task_init_ok", pid) if pid == task_pid:
            return task_pid
        case ("task_init_error", pid, reason) if pid == task_pid:
            raise RuntimeError(f"[task] {module_class.__mod_id__} init failed: {reason}")
        case _:
            raise RuntimeError(f"[task] Unexpected init reply: {msg}")


# ============================================================================
# Task Loop
# ============================================================================

async def _task_loop(module_class: type, init_arg: Any, parent_pid: str):
    """
    Simple task loop - creates instance, runs the task, exits.
    
    Unlike gen_server which has a message loop, tasks just run once and exit.
    """
    pid = process.self()
    modname = module_class.__mod_id__
    
    try:
        # Create task instance
        task_instance = module_class()
        
        # Verify run callback exists
        if not hasattr(task_instance, 'run'):
            await process.send(parent_pid, ("task_init_error", pid, "no run callback"))
            return
        
        # Send init success immediately
        await process.send(parent_pid, ("task_init_ok", pid))
        await process.send(LOGGER, ("log", "DEBUG",
            f"[task.init] module={modname}, pid={pid} starting",
            {"module": modname, "pid": pid}))
        
        # Run the task
        result = await task_instance.run(init_arg)
        
        await process.send(LOGGER, ("log", "DEBUG",
            f"[task.run] module={modname}, pid={pid} completed normally",
            {"module": modname, "pid": pid}))
        
        # Task completes - process exits normally
        
    except Exception as e:
        await process.send(LOGGER, ("log", "ERROR",
            f"[task.run] module={modname}, pid={pid} failed: {repr(e)}",
            {"module": modname, "pid": pid, "exception": repr(e)}))
        raise
