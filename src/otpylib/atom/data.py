# otpylib/atom/data.py
"""Data structures, protocols, and exceptions for the atom system."""

from typing import Protocol, runtime_checkable
from abc import ABC


@runtime_checkable
class AtomProtocol(Protocol):
    """Protocol for atom values - efficient symbolic constants.
    
    Atoms are immutable symbolic constants that can be compared by identity
    rather than value, providing efficient message tags and state identifiers
    for actor-model systems.
    """
    
    def __int__(self) -> int:
        """Return the atom's unique integer identifier."""
        ...
    
    def __str__(self) -> str:
        """Return the atom's string name."""
        ...
    
    def __eq__(self, other) -> bool:
        """Compare atoms for equality."""
        ...
    
    def __hash__(self) -> int:
        """Return hash for use as dict keys."""
        ...
    
    @property
    def id(self) -> int:
        """Get the atom's unique integer ID."""
        ...
    
    @property
    def name(self) -> str:
        """Get the atom's string name."""
        ...


class Atom(ABC):
    """Concrete implementation of an atom."""
    
    def __init__(self, atom_id: int, name: str):
        self._id = atom_id
        self._name = name
    
    def __int__(self) -> int:
        return self._id
    
    def __str__(self) -> str:
        return self._name
    
    def __repr__(self) -> str:
        return f"Atom({self._name!r})"
    
    def __eq__(self, other) -> bool:
        if isinstance(other, Atom):
            return self._id == other._id
        return False
    
    def __hash__(self) -> int:
        return hash(self._id)
    
    @property
    def id(self) -> int:
        """Get the atom's ID."""
        return self._id
    
    @property
    def name(self) -> str:
        """Get the atom's name."""
        return self._name


class AtomError(Exception):
    """Base exception for atom-related errors."""
    pass


class AtomNotFound(AtomError):
    """Raised when attempting to look up a non-existent atom."""
    
    def __init__(self, identifier):
        if isinstance(identifier, int):
            super().__init__(f"Atom with ID {identifier} not found")
        else:
            super().__init__(f"Atom '{identifier}' not found")
        self.identifier = identifier


class AtomTableFull(AtomError):
    """Raised when atom table reaches maximum capacity."""
    
    def __init__(self, max_atoms: int):
        super().__init__(f"Atom table full: maximum {max_atoms} atoms exceeded")
        self.max_atoms = max_atoms


class InvalidAtomName(AtomError):
    """Raised when attempting to create an atom with an invalid name."""
    
    def __init__(self, name: str, reason: str = ""):
        msg = f"Invalid atom name: '{name}'"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)
        self.name = name
        self.reason = reason
