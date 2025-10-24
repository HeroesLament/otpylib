#!/usr/bin/env python3
"""
Process Identifier (PID) Implementation for OTPYLIB

Provides PID allocation, ETF encoding/decoding, and utility functions.
The Pid class itself is defined in otpylib.runtime.base for use in Protocols.

Erlang PID Structure:
    - node: The node where the process lives (Atom)
    - id: Process identifier (uint32)
    - serial: Generation/reuse counter (uint32)
    - creation: Node incarnation number (uint32)

ETF Encoding Formats:
    - PID_EXT (tag 103): Legacy format with 8-bit creation
    - NEW_PID_EXT (tag 88): Modern format with 32-bit creation (OTP 23+)

Usage:
    # Create a PID allocator for your node
    from otpylib.runtime.pid import PidAllocator
    
    allocator = PidAllocator('otpylib@127.0.0.1', creation=1)
    
    # Allocate PIDs for new processes
    pid = await allocator.allocate()
    
    # Use PIDs in process registry, messages, etc.
    process = Process(pid=pid, ...)
"""

import asyncio
from typing import Optional, Dict, Any
from otpylib import atom
from otpylib.runtime.backends.base import Pid


# ETF Tags for PID encoding
PID_EXT = 103       # Legacy PID format
NEW_PID_EXT = 88    # Modern PID format (OTP 23+)


class PidAllocator:
    """
    Allocates unique PIDs for processes on a node
    
    Manages PID allocation with proper ID and serial number sequencing.
    Thread-safe and async-safe through use of asyncio.Lock.
    
    The allocator maintains counters that wrap around when they reach
    maximum values, similar to Erlang's behavior. The serial number
    increments when the ID wraps around, providing a two-level counter.
    
    Attributes:
        node_atom: The node's atom
        creation: Node creation number from EPMD
    
    Example:
        >>> allocator = PidAllocator('otpylib@127.0.0.1', creation=1)
        >>> pid1 = await allocator.allocate()
        >>> pid2 = await allocator.allocate()
        >>> pid1.id + 1 == pid2.id
        True
        >>> pid1.node == pid2.node
        True
    """
    
    # Maximum values for ID and serial
    MAX_ID = 0x7FFFFFFF      # 2^31 - 1 (keep high bit clear for safety)
    MAX_SERIAL = 0xFFFFFFFF  # 2^32 - 1 (full 32-bit for NEW_PID format)
    
    def __init__(self, node_name: str, creation: int):
        """
        Initialize PID allocator
        
        Args:
            node_name: Full node name (e.g., 'otpylib@127.0.0.1')
            creation: Creation number from EPMD registration (0-3 typically)
        """
        self.node_atom = atom.ensure(node_name)
        self.creation = creation
        
        # Counters start at 1 (Erlang convention, PID 0 is special)
        self._next_id = 1
        self._next_serial = 0
        
        # Lock for thread-safe allocation
        self._lock = asyncio.Lock()
        
        # Statistics
        self._allocated_count = 0
        self._wrap_count = 0
    
    async def allocate(self) -> Pid:
        """
        Allocate a new unique PID
        
        This is the primary way to create PIDs in OTPYLIB. Each call
        returns a unique PID for this node.
        
        Returns:
            A new Pid instance
        
        Thread-safe: Multiple coroutines can safely call this concurrently.
        
        Example:
            >>> pid = await allocator.allocate()
            >>> print(pid)
            #Pid<otpylib@127.0.0.1.1.0>
        """
        async with self._lock:
            # Create PID with current counters
            pid = Pid(
                node=self.node_atom,
                id=self._next_id,
                serial=self._next_serial,
                creation=self.creation
            )
            
            # Increment ID counter
            self._next_id += 1
            
            # Handle ID wraparound
            if self._next_id > self.MAX_ID:
                self._next_id = 1  # Start from 1 again
                self._next_serial += 1
                self._wrap_count += 1
                
                # Handle serial wraparound
                if self._next_serial > self.MAX_SERIAL:
                    self._next_serial = 0
            
            self._allocated_count += 1
            return pid
    
    def stats(self) -> Dict[str, Any]:
        """
        Get allocation statistics
        
        Returns:
            Dictionary with allocation stats
        """
        return {
            'node': self.node_atom.name,
            'creation': self.creation,
            'next_id': self._next_id,
            'next_serial': self._next_serial,
            'allocated_count': self._allocated_count,
            'wrap_count': self._wrap_count,
            'ids_remaining': self.MAX_ID - self._next_id,
        }
    
    def reset(self):
        """
        Reset counters (for testing only)
        
        WARNING: Should only be used in tests. Resetting in production
        could cause PID collisions.
        """
        self._next_id = 1
        self._next_serial = 0
        self._allocated_count = 0
        self._wrap_count = 0


# ETF Encoding/Decoding Functions

def encode_pid(pid: Pid, use_new_format: bool = True) -> bytes:
    """
    Encode a PID in External Term Format
    
    Args:
        pid: The PID to encode
        use_new_format: If True, use NEW_PID_EXT (tag 88), else PID_EXT (tag 103)
    
    Returns:
        Bytes representing the encoded PID
    
    Format (NEW_PID_EXT):
        [88][Node:Atom][ID:uint32][Serial:uint32][Creation:uint32]
    
    Format (PID_EXT):
        [103][Node:Atom][ID:uint32][Serial:uint32][Creation:uint8]
    
    Example:
        >>> from otpylib import atom
        >>> from otpylib.runtime.base import Pid
        >>> pid = Pid(atom.ensure('test@127.0.0.1'), 101, 0, 1)
        >>> data = encode_pid(pid)
        >>> data[0] == 88  # NEW_PID_EXT tag
        True
    """
    from otpylib.distribution.etf import encode_atom
    
    result = bytearray()
    
    if use_new_format:
        # NEW_PID_EXT (tag 88) - OTP 23+
        result.append(NEW_PID_EXT)
        result.extend(encode_atom(pid.node))
        result.extend(pid.id.to_bytes(4, 'big'))
        result.extend(pid.serial.to_bytes(4, 'big'))
        result.extend(pid.creation.to_bytes(4, 'big'))
    else:
        # PID_EXT (tag 103) - Legacy format
        result.append(PID_EXT)
        result.extend(encode_atom(pid.node))
        result.extend(pid.id.to_bytes(4, 'big'))
        result.extend(pid.serial.to_bytes(4, 'big'))
        result.extend((pid.creation & 0xFF).to_bytes(1, 'big'))  # Truncate to 8 bits
    
    return bytes(result)


def decode_pid(data: bytes, pos: int) -> tuple[Pid, int]:
    """
    Decode a PID from External Term Format
    
    Args:
        data: Byte buffer containing ETF data
        pos: Current position in the buffer
    
    Returns:
        Tuple of (decoded Pid, new position)
    
    Raises:
        ValueError: If invalid tag or malformed data
    
    Example:
        >>> encoded = encode_pid(pid)
        >>> decoded, new_pos = decode_pid(encoded, 0)
        >>> decoded == pid
        True
    """
    from otpylib.distribution.etf import decode_atom
    
    if pos >= len(data):
        raise ValueError("Unexpected end of data while decoding PID")
    
    tag = data[pos]
    pos += 1
    
    if tag == NEW_PID_EXT:  # tag 88
        # NEW_PID_EXT: [Node:Atom][ID:uint32][Serial:uint32][Creation:uint32]
        node, pos = decode_atom(data, pos)
        
        if pos + 12 > len(data):
            raise ValueError("Insufficient data for NEW_PID_EXT")
        
        id = int.from_bytes(data[pos:pos+4], 'big')
        pos += 4
        serial = int.from_bytes(data[pos:pos+4], 'big')
        pos += 4
        creation = int.from_bytes(data[pos:pos+4], 'big')
        pos += 4
        
    elif tag == PID_EXT:  # tag 103
        # PID_EXT: [Node:Atom][ID:uint32][Serial:uint32][Creation:uint8]
        node, pos = decode_atom(data, pos)
        
        if pos + 9 > len(data):
            raise ValueError("Insufficient data for PID_EXT")
        
        id = int.from_bytes(data[pos:pos+4], 'big')
        pos += 4
        serial = int.from_bytes(data[pos:pos+4], 'big')
        pos += 4
        creation = data[pos]
        pos += 1
        
    else:
        raise ValueError(f"Invalid PID tag: {tag} (expected {PID_EXT} or {NEW_PID_EXT})")
    
    return Pid(node, id, serial, creation), pos


# Utility functions

def make_pid(node_name: str, id: int, serial: int = 0, creation: int = 0) -> Pid:
    """
    Convenience function to create a PID
    
    Args:
        node_name: Node name as string
        id: Process ID
        serial: Serial number (default 0)
        creation: Creation number (default 0)
    
    Returns:
        A new Pid instance
    
    Example:
        >>> pid = make_pid('otpylib@127.0.0.1', 101)
        >>> print(pid)
        #Pid<otpylib@127.0.0.1.101.0>
    """
    return Pid(
        node=atom.ensure(node_name),
        id=id,
        serial=serial,
        creation=creation
    )


def parse_pid_string(pid_str: str) -> Optional[Pid]:
    """
    Parse a PID from string format like "#Pid<node.101.0>"
    
    Args:
        pid_str: String representation of a PID
    
    Returns:
        Pid instance or None if parsing fails
    
    Note:
        This function cannot determine the creation number from the string,
        so it defaults to 0. Use with caution.
    
    Example:
        >>> pid = parse_pid_string("#Pid<otpylib@127.0.0.1.101.0>")
        >>> pid.id
        101
    """
    import re
    
    # Match #Pid<node.id.serial> format
    match = re.match(r'#Pid<(.+?)\.(\d+)\.(\d+)>', pid_str)
    if not match:
        return None
    
    node_name, id_str, serial_str = match.groups()
    
    try:
        return Pid(
            node=atom.ensure(node_name),
            id=int(id_str),
            serial=int(serial_str),
            creation=0  # Cannot determine from string
        )
    except (ValueError, TypeError):
        return None
