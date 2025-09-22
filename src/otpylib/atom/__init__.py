# otpylib/atom/__init__.py
"""
Atom system for OTPyLib - provides efficient symbolic constants
similar to Erlang atoms for message passing and state management.
"""

from .data import Atom, AtomError, AtomNotFound
from .core import (
    ensure, 
    exists,
    name,
    id,
    ensure_many,
    all_atoms,
    atom_count,
    clear
)

__all__ = [
    # Protocol and exceptions
    'Atom',
    'AtomError', 
    'AtomNotFound',
    
    # Core functions
    'ensure',
    'exists', 
    'name',
    'id',
    'ensure_many',
    'all_atoms',
    'atom_count',
    'clear',
]
