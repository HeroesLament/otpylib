# otpylib/atom/core.py
"""Public API for the atom system."""

from typing import List, Dict, Optional, Iterable
from .table import AtomTable
from .data import Atom

# Global atom table singleton
_table = AtomTable()

# Public API functions
def ensure(name: str) -> Atom:
    """Get or create an atom by name."""
    return _table.ensure(name)

def exists(name: str) -> bool:
    """Check if atom exists."""
    return _table.exists(name)

def by_name(name: str) -> Optional[Atom]:
    """Get atom by name, None if not exists."""
    return _table.get_by_name(name)

def by_id(atom_id: int) -> Atom:
    """Get atom by ID."""
    return _table.get_by_id(atom_id)

def ensure_many(names: Iterable[str]) -> List[Atom]:
    """Create multiple atoms efficiently."""
    return _table.ensure_many(names)

def from_list(names: List[str]) -> List[Atom]:
    """Create atoms from list - alias for ensure_many."""
    return ensure_many(names)

def all_atoms() -> Dict[str, Atom]:
    """Get all atoms."""
    return _table.all_atoms()

def atom_count() -> int:
    """Get total atom count."""
    return _table.count()

def clear() -> None:
    """Clear all atoms - primarily for testing."""
    _table.clear()

# Legacy compatibility functions - these return the underlying values
def name(atom_id: int) -> str:
    """Get atom name from ID (legacy)."""
    return _table.get_by_id(atom_id).name

def id(name: str) -> Optional[int]:
    """Get atom ID from name (legacy)."""
    atom_obj = _table.get_by_name(name)
    return atom_obj.id if atom_obj else None
