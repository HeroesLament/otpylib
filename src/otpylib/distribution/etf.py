# otpylib/distribution/etf.py
"""
External Term Format (ETF) codec for Erlang interoperability.
Integrates with otpylib.atom for native atom support.

Spec: https://www.erlang.org/doc/apps/erts/erl_ext_dist.html
"""

import struct
from typing import Any, Tuple
from dataclasses import dataclass

from otpylib import atom

# ETF Version
VERSION = 131

# Type tags
SMALL_INTEGER_EXT = 97   # 0..255
INTEGER_EXT = 98         # 32-bit signed
FLOAT_EXT = 99           # Old float format (deprecated)
ATOM_EXT = 100           # Latin-1 atom (deprecated, but still supported)
SMALL_TUPLE_EXT = 104    # Arity < 256
LARGE_TUPLE_EXT = 105    # Arity >= 256
NIL_EXT = 106            # Empty list []
STRING_EXT = 107         # List of bytes (deprecated for strings)
LIST_EXT = 108           # Proper list
BINARY_EXT = 109         # Binary data
SMALL_BIG_EXT = 110      # Bignum
LARGE_BIG_EXT = 111      # Larger bignum
NEW_FLOAT_EXT = 70       # IEEE 754 float
ATOM_UTF8_EXT = 118      # UTF-8 atom
SMALL_ATOM_UTF8_EXT = 119  # UTF-8 atom (length < 256)
MAP_EXT = 116            # Map
PID_EXT = 103            # Process identifier
NEW_PID_EXT = 88         # New PID format (OTP 23+)
REFERENCE_EXT = 101      # Old reference (deprecated)
NEW_REFERENCE_EXT = 114  # New reference format
NEWER_REFERENCE_EXT = 90 # Newer reference format (OTP 23+)
PORT_EXT = 102           # Port identifier
NEW_PORT_EXT = 89        # New port format


@dataclass
class Pid:
    """
    Erlang process identifier.
    Maps to OTPYLIB process ids, but maintains ETF format for wire protocol.
    """
    node: Any  # atom.Atom
    id: int
    serial: int
    creation: int
    
    def __str__(self):
        return f"<{self.id}.{self.serial}.{self.creation}@{self.node.name}>"
    
    def __repr__(self):
        return f"Pid(node={self.node!r}, id={self.id}, serial={self.serial}, creation={self.creation})"


@dataclass
class Reference:
    """Erlang reference"""
    node: Any  # atom.Atom
    creation: int
    ids: Tuple[int, ...]
    
    def __str__(self):
        return f"#Ref<{self.creation}.{'.'.join(map(str, self.ids))}>"
    
    def __repr__(self):
        return f"Reference(node={self.node!r}, creation={self.creation}, ids={self.ids})"


@dataclass
class Port:
    """Erlang port identifier"""
    node: Any  # atom.Atom
    id: int
    creation: int
    
    def __str__(self):
        return f"#Port<{self.id}.{self.creation}@{self.node.name}>"


class ETFDecoder:
    """Decode ETF binary to Python objects with OTPYLIB atom integration"""
    
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
    
    def decode(self) -> Any:
        """Decode ETF data"""
        version = self.read_byte()
        if version != VERSION:
            raise ValueError(f"Invalid ETF version: {version} (expected {VERSION})")
        return self.decode_term()
    
    def read_byte(self) -> int:
        if self.pos >= len(self.data):
            raise ValueError("Unexpected end of ETF data")
        b = self.data[self.pos]
        self.pos += 1
        return b
    
    def read_bytes(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise ValueError("Unexpected end of ETF data")
        data = self.data[self.pos:self.pos + n]
        self.pos += n
        return data
    
    def read_u8(self) -> int:
        return self.read_byte()
    
    def read_u16(self) -> int:
        return struct.unpack('>H', self.read_bytes(2))[0]
    
    def read_u32(self) -> int:
        return struct.unpack('>I', self.read_bytes(4))[0]
    
    def read_i32(self) -> int:
        return struct.unpack('>i', self.read_bytes(4))[0]
    
    def decode_term(self) -> Any:
        tag = self.read_byte()
        
        if tag == SMALL_INTEGER_EXT:
            return self.read_u8()
        
        elif tag == INTEGER_EXT:
            return self.read_i32()
        
        elif tag == FLOAT_EXT:
            # Old format: 31 bytes string representation
            float_str = self.read_bytes(31).split(b'\x00')[0].decode('ascii')
            return float(float_str)
        
        elif tag == NEW_FLOAT_EXT:
            return struct.unpack('>d', self.read_bytes(8))[0]
        
        elif tag in (ATOM_EXT, ATOM_UTF8_EXT):
            length = self.read_u16()
            name = self.read_bytes(length).decode('utf-8' if tag == ATOM_UTF8_EXT else 'latin-1')
            # Convert to OTPYLIB atom!
            return atom.ensure(name)
        
        elif tag == SMALL_ATOM_UTF8_EXT:
            length = self.read_u8()
            name = self.read_bytes(length).decode('utf-8')
            # Convert to OTPYLIB atom!
            return atom.ensure(name)
        
        elif tag == SMALL_TUPLE_EXT:
            arity = self.read_u8()
            return tuple(self.decode_term() for _ in range(arity))
        
        elif tag == LARGE_TUPLE_EXT:
            arity = self.read_u32()
            return tuple(self.decode_term() for _ in range(arity))
        
        elif tag == NIL_EXT:
            return []
        
        elif tag == STRING_EXT:
            # This is actually a list of bytes, not a string
            length = self.read_u16()
            return list(self.read_bytes(length))
        
        elif tag == LIST_EXT:
            length = self.read_u32()
            items = [self.decode_term() for _ in range(length)]
            tail = self.decode_term()
            if tail != []:  # Improper list
                items.append(tail)
            return items
        
        elif tag == BINARY_EXT:
            length = self.read_u32()
            return self.read_bytes(length)
        
        elif tag == SMALL_BIG_EXT:
            n = self.read_u8()
            sign = self.read_u8()
            digits = self.read_bytes(n)
            value = int.from_bytes(digits, byteorder='little')
            return -value if sign else value
        
        elif tag == LARGE_BIG_EXT:
            n = self.read_u32()
            sign = self.read_u8()
            digits = self.read_bytes(n)
            value = int.from_bytes(digits, byteorder='little')
            return -value if sign else value
        
        elif tag == MAP_EXT:
            arity = self.read_u32()
            return {self.decode_term(): self.decode_term() for _ in range(arity)}
        
        elif tag == PID_EXT:
            node = self.decode_term()
            id = self.read_u32()
            serial = self.read_u32()
            creation = self.read_u8()
            return Pid(node, id, serial, creation)
        
        elif tag == NEW_PID_EXT:
            node = self.decode_term()
            id = self.read_u32()
            serial = self.read_u32()
            creation = self.read_u32()
            return Pid(node, id, serial, creation)
        
        elif tag == NEW_REFERENCE_EXT:
            length = self.read_u16()
            node = self.decode_term()
            creation = self.read_u8()
            ids = tuple(self.read_u32() for _ in range(length))
            return Reference(node, creation, ids)
        
        elif tag == NEWER_REFERENCE_EXT:
            length = self.read_u16()
            node = self.decode_term()
            creation = self.read_u32()
            ids = tuple(self.read_u32() for _ in range(length))
            return Reference(node, creation, ids)
        
        elif tag == PORT_EXT:
            node = self.decode_term()
            id = self.read_u32()
            creation = self.read_u8()
            return Port(node, id, creation)
        
        elif tag == NEW_PORT_EXT:
            node = self.decode_term()
            id = self.read_u32()
            creation = self.read_u32()
            return Port(node, id, creation)
        
        else:
            raise NotImplementedError(f"ETF tag {tag} not implemented")


class ETFEncoder:
    """Encode Python objects to ETF binary with OTPYLIB atom support"""
    
    def __init__(self):
        self.buffer = bytearray()
    
    def encode(self, term: Any) -> bytes:
        """Encode term to ETF"""
        self.buffer = bytearray([VERSION])
        self.encode_term(term)
        return bytes(self.buffer)
    
    def write_byte(self, b: int):
        self.buffer.append(b)
    
    def write_bytes(self, data: bytes):
        self.buffer.extend(data)
    
    def write_u8(self, value: int):
        self.buffer.append(value)
    
    def write_u16(self, value: int):
        self.buffer.extend(struct.pack('>H', value))
    
    def write_u32(self, value: int):
        self.buffer.extend(struct.pack('>I', value))
    
    def write_i32(self, value: int):
        self.buffer.extend(struct.pack('>i', value))
    
    def encode_term(self, term: Any):
        # Check for OTPYLIB atom first!
        if (hasattr(term, '__class__') and 
            term.__class__.__name__ == 'Atom' and
            hasattr(term, 'name')):
            # This is an otpylib.atom.Atom
            name_bytes = term.name.encode('utf-8')
            if len(name_bytes) < 256:
                self.write_byte(SMALL_ATOM_UTF8_EXT)
                self.write_u8(len(name_bytes))
            else:
                self.write_byte(ATOM_UTF8_EXT)
                self.write_u16(len(name_bytes))
            self.write_bytes(name_bytes)
        
        elif term is None:
            # Encode as atom 'nil'
            self.encode_term(atom.ensure('nil'))
        
        elif isinstance(term, bool):
            # Encode as atoms 'true' / 'false'
            self.encode_term(atom.ensure('true' if term else 'false'))
        
        elif isinstance(term, int):
            if 0 <= term <= 255:
                self.write_byte(SMALL_INTEGER_EXT)
                self.write_u8(term)
            elif -2147483648 <= term <= 2147483647:
                self.write_byte(INTEGER_EXT)
                self.write_i32(term)
            else:
                # Bignum
                sign = 1 if term < 0 else 0
                value = abs(term)
                bytes_val = value.to_bytes((value.bit_length() + 7) // 8, 'little')
                if len(bytes_val) < 256:
                    self.write_byte(SMALL_BIG_EXT)
                    self.write_u8(len(bytes_val))
                else:
                    self.write_byte(LARGE_BIG_EXT)
                    self.write_u32(len(bytes_val))
                self.write_u8(sign)
                self.write_bytes(bytes_val)
        
        elif isinstance(term, float):
            self.write_byte(NEW_FLOAT_EXT)
            self.buffer.extend(struct.pack('>d', term))
        
        elif isinstance(term, bytes):
            self.write_byte(BINARY_EXT)
            self.write_u32(len(term))
            self.write_bytes(term)
        
        elif isinstance(term, str):
            # Encode strings as binaries (Elixir/Erlang modern convention)
            self.encode_term(term.encode('utf-8'))
        
        elif isinstance(term, tuple):
            if len(term) < 256:
                self.write_byte(SMALL_TUPLE_EXT)
                self.write_u8(len(term))
            else:
                self.write_byte(LARGE_TUPLE_EXT)
                self.write_u32(len(term))
            for item in term:
                self.encode_term(item)
        
        elif isinstance(term, list):
            if len(term) == 0:
                self.write_byte(NIL_EXT)
            else:
                self.write_byte(LIST_EXT)
                self.write_u32(len(term))
                for item in term:
                    self.encode_term(item)
                self.write_byte(NIL_EXT)  # Proper list tail
        
        elif isinstance(term, dict):
            self.write_byte(MAP_EXT)
            self.write_u32(len(term))
            for key, value in term.items():
                self.encode_term(key)
                self.encode_term(value)
        
        elif isinstance(term, Pid):
            self.write_byte(NEW_PID_EXT)
            self.encode_term(term.node)
            self.write_u32(term.id)
            self.write_u32(term.serial)
            self.write_u32(term.creation)
        
        elif isinstance(term, Reference):
            self.write_byte(NEWER_REFERENCE_EXT)
            self.write_u16(len(term.ids))
            self.encode_term(term.node)
            self.write_u32(term.creation)
            for id_val in term.ids:
                self.write_u32(id_val)
        
        elif isinstance(term, Port):
            self.write_byte(NEW_PORT_EXT)
            self.encode_term(term.node)
            self.write_u32(term.id)
            self.write_u32(term.creation)
        
        else:
            raise TypeError(f"Cannot encode type {type(term).__name__}: {term!r}")


# Convenience functions
def encode(term: Any) -> bytes:
    """Encode a Python term to ETF binary"""
    return ETFEncoder().encode(term)


def decode(data: bytes) -> Any:
    """Decode ETF binary to Python term"""
    return ETFDecoder(data).decode()


# Helper for converting OTPYLIB pids to ETF Pids
def otpylib_pid_to_etf(pid_str: str, node_name: str = "otpylib@nohost") -> Pid:
    """
    Convert OTPYLIB pid string (e.g., "pid_abc123") to ETF Pid.
    
    Args:
        pid_str: OTPYLIB process id string
        node_name: Node name for this OTPYLIB instance
    
    Returns:
        ETF Pid suitable for wire protocol
    """
    # Extract numeric portion from pid string
    # "pid_abc123" -> hash to id/serial
    pid_hash = hash(pid_str)
    id_part = abs(pid_hash) & 0x7FFFFFFF  # 31 bits
    serial_part = (abs(pid_hash) >> 31) & 0x1FFF  # 13 bits
    
    node_atom = atom.ensure(node_name)
    return Pid(node_atom, id_part, serial_part, creation=1)


def etf_pid_to_otpylib(etf_pid: Pid) -> str:
    """
    Convert ETF Pid back to OTPYLIB pid string.
    This is lossy - we create a synthetic pid string.
    
    For true bidirectional mapping, maintain a pid translation table.
    """
    return f"pid_{etf_pid.node.name}_{etf_pid.id}_{etf_pid.serial}"
