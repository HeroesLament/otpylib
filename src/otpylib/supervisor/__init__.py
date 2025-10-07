"""
Supervisorm module for OTPyLib - Module-aware supervisor.
"""

from otpylib.supervisor.core import (
    start_link,
    child_spec,
    options,
    NotASupervisorError,
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
    SHUTDOWN,
    SUPERVISOR_SHUTDOWN,
    KILLED,
)

__all__ = [
    # Functions
    'start_link',
    
    # Classes
    'child_spec',
    'options',
    
    # Exceptions
    'NotASupervisorError',
    
    # Atoms - Restart strategies
    'PERMANENT',
    'TRANSIENT', 
    'TEMPORARY',
    
    # Atoms - Supervisor strategies
    'ONE_FOR_ONE',
    'ONE_FOR_ALL',
    'REST_FOR_ONE',
    
    # Atoms - Exit reasons
    'SHUTDOWN',
    'SUPERVISOR_SHUTDOWN',
    'KILLED',
]
