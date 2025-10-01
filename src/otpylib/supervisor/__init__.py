"""
Supervisor module for OTPyLib.

Provides process supervision with restart strategies.
"""

from otpylib.supervisor.core import (
    start,
    start_link,
    get_child_status,
    list_children,
    child_spec,
    options,
    SupervisorHandle
)

from otpylib.supervisor.atoms import (
    # Restart strategies
    PERMANENT,
    TRANSIENT,
    TEMPORARY,
    
    # Supervisor strategies
    ONE_FOR_ONE,
    ONE_FOR_ALL,
    REST_FOR_ONE,
    
    # Exit reasons
    NORMAL,
    SHUTDOWN,
    KILLED,
    SUPERVISOR_SHUTDOWN,
    SIBLING_RESTART_LIMIT
)

__all__ = [
    # Functions
    'start',
    'start_link',
    'get_child_status',
    'list_children',
    
    # Classes
    'child_spec',
    'options',
    'SupervisorHandle',
    
    # Atoms - Restart strategies
    'PERMANENT',
    'TRANSIENT', 
    'TEMPORARY',
    
    # Atoms - Supervisor strategies
    'ONE_FOR_ONE',
    'ONE_FOR_ALL',
    'REST_FOR_ONE',
    
    # Atoms - Exit reasons
    'NORMAL',
    'SHUTDOWN',
    'KILLED',
    'SUPERVISOR_SHUTDOWN',
    'SIBLING_RESTART_LIMIT'
]
