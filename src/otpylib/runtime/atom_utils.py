"""
Runtime Atom Utilities

Validation and utility functions for working with runtime atoms.
Separated from atom definitions to keep atoms.py pure.
"""

from typing import Set, Tuple, Any, Optional

# Import all atoms we'll be validating/using
from otpylib.runtime.atoms import (
    # Process types
    GEN_SERVER, SUPERVISOR, DYNAMIC_SUPERVISOR, WORKER, TASK, APPLICATION,
    
    # States
    STARTING, RUNNING, WAITING, SUSPENDED, TERMINATING, TERMINATED,
    
    # Exit reasons
    NORMAL, SHUTDOWN, KILLED, ABNORMAL,
    
    # Restart strategies
    ONE_FOR_ONE, ONE_FOR_ALL, REST_FOR_ONE,
    
    # Restart types
    PERMANENT, TEMPORARY, TRANSIENT,
    
    # Messages
    DOWN, EXIT, PROCESS, SYSTEM,
    
    # Responses
    OK, ERROR, YES, NO
)


# =============================================================================
# Exit Reason Checks
# =============================================================================

def is_normal_exit(reason):
    """
    Check if an exit reason is considered normal.
    
    Normal exits are NORMAL and SHUTDOWN atoms.
    """
    return reason == NORMAL or reason == SHUTDOWN


def is_abnormal_exit(reason):
    """Check if an exit reason is considered abnormal."""
    return not is_normal_exit(reason)


def should_restart_permanent(restart_type, reason):
    """
    Check if a permanent child should be restarted.
    
    Permanent children are always restarted regardless of exit reason.
    """
    return restart_type == PERMANENT


def should_restart_transient(restart_type, reason):
    """
    Check if a transient child should be restarted.
    
    Transient children are restarted only on abnormal exits.
    """
    return restart_type == TRANSIENT and is_abnormal_exit(reason)


def should_restart_temporary(restart_type, reason):
    """
    Check if a temporary child should be restarted.
    
    Temporary children are never restarted.
    """
    return False


def should_restart_child(restart_type, reason):
    """
    Determine if a child should be restarted based on its restart type and exit reason.
    
    :param restart_type: PERMANENT, TRANSIENT, or TEMPORARY atom
    :param reason: Exit reason atom
    :returns: True if child should be restarted
    """
    if restart_type == PERMANENT:
        return True
    elif restart_type == TRANSIENT:
        return is_abnormal_exit(reason)
    elif restart_type == TEMPORARY:
        return False
    else:
        raise ValueError(f"Invalid restart type: {restart_type}")


# =============================================================================
# Message Formatting
# =============================================================================

def format_down_message(ref: str, pid: str, reason) -> Tuple:
    """
    Format a DOWN message in Erlang style.
    
    Returns: ('DOWN', ref, 'process', pid, reason)
    """
    return (DOWN, ref, PROCESS, pid, reason)


def format_exit_message(from_pid: str, reason) -> Tuple:
    """
    Format an EXIT message in Erlang style.
    
    Returns: ('EXIT', from_pid, reason)
    """
    return (EXIT, from_pid, reason)


def format_system_message(msg_type, data=None) -> Tuple:
    """
    Format a system message.
    
    Returns: ('system', msg_type) or ('system', msg_type, data)
    """
    if data is None:
        return (SYSTEM, msg_type)
    return (SYSTEM, msg_type, data)


def format_ok_response(value=None) -> Tuple:
    """
    Format an ok response tuple.
    
    Returns: ('ok',) or ('ok', value)
    """
    if value is None:
        return (OK,)
    return (OK, value)


def format_error_response(reason) -> Tuple:
    """
    Format an error response tuple.
    
    Returns: ('error', reason)
    """
    return (ERROR, reason)


# =============================================================================
# Message Pattern Matching
# =============================================================================

def is_down_message(message) -> bool:
    """Check if a message is a DOWN message."""
    return (isinstance(message, tuple) and 
            len(message) == 5 and 
            message[0] == DOWN and
            message[2] == PROCESS)


def is_exit_message(message) -> bool:
    """Check if a message is an EXIT message."""
    return (isinstance(message, tuple) and 
            len(message) == 3 and 
            message[0] == EXIT)


def is_system_message(message) -> bool:
    """Check if a message is a system message."""
    return (isinstance(message, tuple) and 
            len(message) >= 2 and 
            message[0] == SYSTEM)


def parse_down_message(message) -> Optional[dict]:
    """
    Parse a DOWN message into its components.
    
    :param message: Message tuple to parse
    :returns: Dict with 'ref', 'pid', 'reason' keys, or None if not a DOWN message
    """
    if is_down_message(message):
        return {
            'ref': message[1],
            'pid': message[3],
            'reason': message[4]
        }
    return None


def parse_exit_message(message) -> Optional[dict]:
    """
    Parse an EXIT message into its components.
    
    :param message: Message tuple to parse
    :returns: Dict with 'from_pid', 'reason' keys, or None if not an EXIT message
    """
    if is_exit_message(message):
        return {
            'from_pid': message[1],
            'reason': message[2]
        }
    return None


# =============================================================================
# Validation Functions
# =============================================================================

def validate_process_type(process_type):
    """
    Validate that a process type atom is valid.
    
    :param process_type: Atom to validate
    :returns: The process_type if valid
    :raises ValueError: If invalid
    """
    valid_types = {GEN_SERVER, SUPERVISOR, DYNAMIC_SUPERVISOR, WORKER, TASK, APPLICATION}
    if process_type not in valid_types:
        raise ValueError(f"Invalid process type: {process_type}")
    return process_type


def validate_process_state(state):
    """
    Validate that a process state atom is valid.
    
    :param state: Atom to validate
    :returns: The state if valid
    :raises ValueError: If invalid
    """
    valid_states = {STARTING, RUNNING, WAITING, SUSPENDED, TERMINATING, TERMINATED}
    if state not in valid_states:
        raise ValueError(f"Invalid process state: {state}")
    return state


def validate_restart_strategy(strategy):
    """
    Validate a supervisor restart strategy.
    
    :param strategy: Atom to validate
    :returns: The strategy if valid
    :raises ValueError: If invalid
    """
    valid_strategies = {ONE_FOR_ONE, ONE_FOR_ALL, REST_FOR_ONE}
    if strategy not in valid_strategies:
        raise ValueError(f"Invalid restart strategy: {strategy}")
    return strategy


def validate_restart_type(restart_type):
    """
    Validate a child restart type.
    
    :param restart_type: Atom to validate
    :returns: The restart_type if valid
    :raises ValueError: If invalid
    """
    valid_types = {PERMANENT, TEMPORARY, TRANSIENT}
    if restart_type not in valid_types:
        raise ValueError(f"Invalid restart type: {restart_type}")
    return restart_type


def validate_exit_reason(reason):
    """
    Validate that an exit reason is an atom.
    
    Note: We don't restrict to specific atoms since custom exit
    reasons are allowed in BEAM.
    
    :param reason: Value to validate
    :returns: The reason if it's an atom
    :raises ValueError: If not an atom
    """
    from otpylib.atom import Atom
    if not isinstance(reason, Atom):
        raise ValueError(f"Exit reason must be an atom, got {type(reason)}")
    return reason


# =============================================================================
# Sets for Quick Membership Testing
# =============================================================================

# Export sets for efficient membership testing
PROCESS_TYPES = frozenset({
    GEN_SERVER, SUPERVISOR, DYNAMIC_SUPERVISOR, WORKER, TASK, APPLICATION
})

PROCESS_STATES = frozenset({
    STARTING, RUNNING, WAITING, SUSPENDED, TERMINATING, TERMINATED
})

RESTART_STRATEGIES = frozenset({
    ONE_FOR_ONE, ONE_FOR_ALL, REST_FOR_ONE
})

RESTART_TYPES = frozenset({
    PERMANENT, TEMPORARY, TRANSIENT
})

NORMAL_EXIT_REASONS = frozenset({
    NORMAL, SHUTDOWN
})
