"""
Gen_Server Module
"""

from otpylib.gen_server.core import (
    # Main functions
    start,
    start_link,
    call,
    cast,
    reply,
    
    # Exceptions
    GenServerExited,
)

from otpylib.gen_server.atoms import (
    # Lifecycle states
    INITIALIZING,
    RUNNING,
    WAITING_FOR_MESSAGE,
    PROCESSING_MESSAGE,
    STOPPING,
    CRASHED,
    TERMINATED,
    
    # Event atoms
    INIT_SUCCESS,
    INIT_FAILED,
    MESSAGE_RECEIVED,
    MESSAGE_PROCESSED,
    STOP_REQUESTED,
    HANDLER_STOP,
    EXCEPTION_OCCURRED,
    MAILBOX_CLOSED,
    TIMEOUT_OCCURRED,
    
    # Action atoms
    CONTINUE,
    STOP_ACTION,
    CRASH,
    RESTART,
    IGNORE,
    
    # Message types
    CALL,
    CAST,
    INFO,
)

from otpylib.gen_server.data import (
    Reply,
    NoReply,
    Stop,
    CallbackNS,
)

__all__ = [
    # Functions
    'start',
    'start_link',
    'call', 
    'cast',
    'reply',
    
    # Response types
    'Reply',
    'NoReply',
    'Stop',
    
    # Exceptions
    'GenServerExited',
    
    # Atoms - Lifecycle
    'INITIALIZING',
    'RUNNING',
    'WAITING_FOR_MESSAGE',
    'PROCESSING_MESSAGE',
    'STOPPING',
    'CRASHED',
    'TERMINATED',
    
    # Atoms - Events
    'INIT_SUCCESS',
    'INIT_FAILED',
    'MESSAGE_RECEIVED',
    'MESSAGE_PROCESSED',
    'STOP_REQUESTED',
    'HANDLER_STOP',
    'EXCEPTION_OCCURRED',
    'MAILBOX_CLOSED',
    'TIMEOUT_OCCURRED',
    
    # Atoms - Actions
    'CONTINUE',
    'STOP_ACTION',
    'CRASH',
    'RESTART',
    'IGNORE',
    
    # Atoms - Message types
    'CALL',
    'CAST',
    'INFO',

    # Data helpers
    'CallbackNS',
]
