"""
Dynamic supervisor module for runtime child management with OTPModule support.

This is the module-aware version of dynamic_supervisor that works exclusively
with OTPModule classes. For function-based children, use the standard
dynamic_supervisor module instead.
"""

from otpylib.dynamic_supervisor.core import (
    # Main functions
    start,
    start_link,
    start_child,
    terminate_child,
    list_children,
    which_children,
    count_children,
    
    # Configuration classes
    child_spec,
    options,
)

from otpylib.dynamic_supervisor.atoms import (
    # Restart Strategy Atoms
    PERMANENT,
    TRANSIENT,
    TEMPORARY,
    
    # Supervisor Strategy Atoms
    ONE_FOR_ONE,
    ONE_FOR_ALL,
    REST_FOR_ONE,
    
    # Exit Reason Atoms
    NORMAL,
    SHUTDOWN,
    KILLED,
    SUPERVISOR_SHUTDOWN,
    SIBLING_RESTART_LIMIT,
    
    # Supervisor State Atoms
    STARTING,
    RUNNING,
    SHUTTING_DOWN,
    TERMINATED,
    
    # Dynamic Supervisor Message Atoms
    GET_CHILD_STATUS,
    LIST_CHILDREN,
    WHICH_CHILDREN,
    COUNT_CHILDREN,
    ADD_CHILD,
    TERMINATE_CHILD,
    RESTART_CHILD,
    
    # Process Message Atoms
    EXIT,
    DOWN,
    PROCESS,
    
    # Child Types
    WORKER,
    SUPERVISOR,
    
    # Dynamic Supervisor Specific
    DYNAMIC,
    STATIC,
)

__all__ = [
    # Main functions
    "start",
    "start_link",
    "start_child",
    "terminate_child",
    "list_children",
    "which_children",
    "count_children",
    
    # Configuration classes
    "module_child_spec",
    "options",
    
    # Restart Strategy Atoms
    "PERMANENT",
    "TRANSIENT",
    "TEMPORARY",
    
    # Supervisor Strategy Atoms
    "ONE_FOR_ONE",
    "ONE_FOR_ALL",
    "REST_FOR_ONE",
    
    # Exit Reason Atoms
    "NORMAL",
    "SHUTDOWN",
    "KILLED",
    "SUPERVISOR_SHUTDOWN",
    "SIBLING_RESTART_LIMIT",
    
    # Supervisor State Atoms
    "STARTING",
    "RUNNING",
    "SHUTTING_DOWN",
    "TERMINATED",
    
    # Dynamic Supervisor Message Atoms
    "GET_CHILD_STATUS",
    "LIST_CHILDREN",
    "WHICH_CHILDREN",
    "COUNT_CHILDREN",
    "ADD_CHILD",
    "TERMINATE_CHILD",
    "RESTART_CHILD",
    
    # Process Message Atoms
    "EXIT",
    "DOWN",
    "PROCESS",
    
    # Child Types
    "WORKER",
    "SUPERVISOR",
    
    # Dynamic Supervisor Specific
    "DYNAMIC",
    "STATIC",
]
