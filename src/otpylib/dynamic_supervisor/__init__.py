"""Dynamic supervisor module for runtime child management."""

from .core import (
    # Main functions
    start,
    start_link,
    start_child,
    terminate_child,
    list_children,
    which_children,
    count_children,
    
    # Classes for configuration
    child_spec,
    options,
    
    # Handle for monitoring and control
    DynamicSupervisorHandle,
)

from .atoms import (
    # Restart Strategy Atoms
    PERMANENT, TRANSIENT, TEMPORARY,
    
    # Supervisor Strategy Atoms
    ONE_FOR_ONE, ONE_FOR_ALL, REST_FOR_ONE,
    
    # Exit Reason Atoms
    NORMAL, SHUTDOWN, KILLED,
    SUPERVISOR_SHUTDOWN, SIBLING_RESTART_LIMIT,
    
    # Supervisor State Atoms
    STARTING, RUNNING, SHUTTING_DOWN, TERMINATED,
    
    # Dynamic Supervisor Message Atoms
    GET_CHILD_STATUS, LIST_CHILDREN, WHICH_CHILDREN,
    COUNT_CHILDREN, ADD_CHILD, TERMINATE_CHILD, RESTART_CHILD,
    
    # Process Message Atoms
    EXIT, DOWN, PROCESS,
    
    # Child Types
    WORKER, SUPERVISOR,
    
    # Dynamic Supervisor Specific
    DYNAMIC, STATIC,
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
    "child_spec",
    "options",
    
    # Handle class
    "DynamicSupervisorHandle",

    # Atoms
    "PERMANENT", "TRANSIENT", "TEMPORARY",
    "ONE_FOR_ONE", "ONE_FOR_ALL", "REST_FOR_ONE",
    "NORMAL", "SHUTDOWN", "KILLED",
    "SUPERVISOR_SHUTDOWN", "SIBLING_RESTART_LIMIT",
    "STARTING", "RUNNING", "SHUTTING_DOWN", "TERMINATED",
    "GET_CHILD_STATUS", "LIST_CHILDREN", "WHICH_CHILDREN",
    "COUNT_CHILDREN", "ADD_CHILD", "TERMINATE_CHILD", "RESTART_CHILD",
    "EXIT", "DOWN", "PROCESS",
    "WORKER", "SUPERVISOR",
    "DYNAMIC", "STATIC",
]
