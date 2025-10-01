# otpylib/atom/table.py
"""Thread-safe atom table implementation."""

import threading
from typing import Dict, List, Optional, Iterable
from .data import AtomNotFound, Atom


class AtomTable:
    """Thread-safe atom table - atoms are immutable once created."""
    
    def __init__(self):
        self._atoms: Dict[str, Atom] = {}       # name -> Atom object
        self._by_id: Dict[int, Atom] = {}       # id -> Atom object
        self._counter = 0
        
        # Only need lock for the creation path
        self._creation_lock = threading.Lock()
    
    def ensure(self, name: str) -> Atom:
        """Get or create an atom by name."""
        # Fast path: lockless read (safe because atoms never change)
        if name in self._atoms:
            return self._atoms[name]
        
        # Slow path: creation (only path that needs locking)
        with self._creation_lock:
            # Double-check pattern
            if name in self._atoms:
                return self._atoms[name]
            
            # Create new atom
            atom_id = self._counter
            atom_obj = Atom(atom_id, name)
            
            self._by_id[atom_id] = atom_obj     # Write by_id first
            self._atoms[name] = atom_obj        # Write by_name second (makes atom "visible")
            self._counter += 1
            
            return atom_obj
    
    def get_by_name(self, name: str) -> Optional[Atom]:
        """Get atom by name, None if not exists."""
        return self._atoms.get(name)
    
    def get_by_id(self, atom_id: int) -> Atom:
        """Get atom by ID."""
        if atom_id not in self._by_id:
            raise AtomNotFound(atom_id)
        return self._by_id[atom_id]
    
    def exists(self, name: str) -> bool:
        """Check if atom exists."""
        return name in self._atoms
    
    def ensure_many(self, names: Iterable[str]) -> List[Atom]:
        """Efficiently create multiple atoms."""
        result = []
        missing = []
        
        # First pass: collect existing atoms (lockless)
        for name in names:
            if name in self._atoms:
                result.append(self._atoms[name])
            else:
                missing.append(name)
        
        # Second pass: create missing atoms (locked)
        if missing:
            with self._creation_lock:
                for name in missing:
                    if name in self._atoms:  # Double-check
                        result.append(self._atoms[name])
                    else:
                        atom_id = self._counter
                        atom_obj = Atom(atom_id, name)
                        self._by_id[atom_id] = atom_obj
                        self._atoms[name] = atom_obj
                        self._counter += 1
                        result.append(atom_obj)
        
        return result
    
    def all_atoms(self) -> Dict[str, Atom]:
        """Get all atoms (copy for safety)."""
        return self._atoms.copy()
    
    def count(self) -> int:
        """Get total atom count (lockless)."""
        return len(self._atoms)
    
    def clear(self) -> None:
        """Clear all atoms - primarily for testing."""
        with self._creation_lock:
            self._atoms.clear()
            self._by_id.clear()
            self._counter = 0
