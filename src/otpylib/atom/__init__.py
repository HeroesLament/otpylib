# otpylib/atom/__init__.py
"""
Atom system for OTPyLib - provides efficient symbolic constants
similar to Erlang atoms for message passing and state management.
"""

from .data import Atom, AtomError, AtomNotFound
from .core import (
    ensure, 
    exists,
    by_name,
    by_id,
    ensure_many,
    from_list,
    all_atoms,
    atom_count,
    clear,
    name,
    id,
)

__all__ = [
    # Protocol and exceptions
    'Atom',
    'AtomError', 
    'AtomNotFound',
    
    # Core functions
    'ensure',
    'exists',
    'by_name',
    'by_id',
    'ensure_many',
    'from_list',
    'all_atoms',
    'atom_count',
    'clear',
    
    # Legacy compatibility
    'name',
    'id',
]
