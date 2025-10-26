# otpylib/distribution/reference.py
"""
Erlang Reference - Distribution Layer Type

References are used in the Erlang distribution protocol for monitors and unique identifiers.
They consist of a node name, creation number, and tuple of IDs.

This is purely a distribution/ETF concept - local runtimes can use strings or other types
for monitor references.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from otpylib.atom import Atom


@dataclass
class Reference:
    """
    Erlang reference for distributed operations.
    
    Used primarily for:
    - Process monitors (CTRL_MONITOR_P, CTRL_MONITOR_P_EXIT)
    - Unique identifiers in distributed contexts
    
    Attributes:
        node: Node name as Atom
        creation: Creation number (for node restart detection)
        ids: Tuple of integers uniquely identifying this reference
    """
    node: 'Atom'
    creation: int
    ids: tuple[int, ...]
    
    def __str__(self):
        ids_str = '.'.join(str(i) for i in self.ids)
        return f"#Ref<{self.node}.{ids_str}>"
    
    def __repr__(self):
        return f"Reference({self.node}, {self.creation}, {self.ids})"
    
    def __hash__(self):
        return hash((self.node, self.creation, self.ids))
    
    def __eq__(self, other):
        if not isinstance(other, Reference):
            return False
        return (self.node == other.node and 
                self.creation == other.creation and 
                self.ids == other.ids)
