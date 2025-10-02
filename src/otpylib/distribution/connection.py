"""
Connection to a remote Erlang/OTP node.

Handles the distribution handshake and message sending.
"""

import asyncio
import struct
import hashlib
import random
from typing import Optional, Callable, Awaitable, Any

from otpylib import atom
from otpylib.distribution.etf import encode, decode, Pid
from otpylib.distribution.constants import (
    DEFAULT_FLAGS,
    CTRL_REG_SEND,
    CTRL_SEND,
)


class Connection:
    """A connection to a remote node"""
    
    def __init__(self, local_node: str, remote_node: str, cookie: str, creation: int = 1):
        self.local_node = local_node
        self.remote_node = remote_node
        self.cookie = cookie
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.connected = False
        self.creation = creation
        self.flags = DEFAULT_FLAGS
        self.message_handler: Optional[Callable[[Any], Awaitable[None]]] = None
    
    async def connect(self, host: str, port: int):
        """Connect and handshake with remote node"""
        self.reader, self.writer = await asyncio.open_connection(host, port)
        await self._handshake()
        self.connected = True
        
        # Start receive loop
        asyncio.create_task(self._receive_loop())
    
    async def _handshake(self):
        """Perform distribution handshake"""
        # Step 1: Send our name (send_name message)
        name_bytes = self.local_node.encode('utf-8')
        
        # Use version 6 format ('N' with 8-byte flags and 4-byte creation)
        message = struct.pack('>cQI', b'N', self.flags, self.creation)
        message += struct.pack('>H', len(name_bytes)) + name_bytes
        
        # Send with 2-byte length header
        packet = struct.pack('>H', len(message)) + message
        
        self.writer.write(packet)
        await self.writer.drain()
        
        # Step 2: Receive status (send_status message)
        length_bytes = await self.reader.read(2)
        length = struct.unpack('>H', length_bytes)[0]
        data = await self.reader.read(length)
        
        # Status message format: 's' + status_string (no length field)
        if len(data) < 1 or chr(data[0]) != 's':
            raise ConnectionError(f"Expected status 's', got {chr(data[0]) if data else 'nothing'}")
        
        status = data[1:]
        
        # Check status
        if status == b'ok' or status == b'ok_simultaneous':
            pass  # Success
        elif status == b'alive':
            raise ConnectionError("Node is alive but we can't connect (simultaneous connect)")
        elif status == b'nok' or status == b'not_allowed':
            raise ConnectionError(f"Handshake rejected: {status.decode('utf-8')} (check cookie)")
        else:
            raise ConnectionError(f"Unknown status: {status}")
        
        # Step 3: Receive challenge (send_challenge message)
        length_bytes = await self.reader.read(2)
        length = struct.unpack('>H', length_bytes)[0]
        data = await self.reader.read(length)
        
        # Challenge format for version 6: 'N' + flags(8) + challenge(4) + creation(4) + nlen(2) + name(nlen)
        if len(data) < 1:
            raise ConnectionError("Empty challenge message")
        
        challenge_type = chr(data[0])
        if challenge_type not in ['N', 'n']:
            raise ConnectionError(f"Expected challenge 'N' or 'n', got '{challenge_type}'")
        
        # Parse challenge (version 6 format)
        flags = struct.unpack('>Q', data[1:9])[0]
        their_challenge = struct.unpack('>I', data[9:13])[0]
        their_creation = struct.unpack('>I', data[13:17])[0]
        nlen = struct.unpack('>H', data[17:19])[0]
        their_name = data[19:19+nlen].decode('utf-8')
        
        # Negotiate flags
        negotiated_flags = self.flags & flags
        
        # Step 4: Send challenge reply (send_challenge_reply message)
        our_challenge = random.randint(0, 0xFFFFFFFF)
        
        # Calculate digest of THEIR challenge: MD5(cookie + their_challenge)
        digest_input = f"{self.cookie}{their_challenge}".encode('utf-8')
        digest = hashlib.md5(digest_input).digest()
        
        # Message format: 'r' + our_challenge(4) + digest(16)
        message = struct.pack('>cI', b'r', our_challenge) + digest
        packet = struct.pack('>H', len(message)) + message
        
        self.writer.write(packet)
        await self.writer.drain()
        
        # Step 5: Receive ack (send_challenge_ack message)
        length_bytes = await self.reader.read(2)
        if len(length_bytes) < 2:
            raise ConnectionError(f"Connection closed while reading ack length (got {len(length_bytes)} bytes)")
        
        length = struct.unpack('>H', length_bytes)[0]
        data = await self.reader.read(length)
        
        # Ack format: 'a' + digest(16)
        if len(data) < 1 or chr(data[0]) != 'a':
            raise ConnectionError(f"Expected ack 'a', got '{chr(data[0]) if data else 'nothing'}'")
        
        their_digest = data[1:17]
        
        # Verify their digest: MD5(cookie + our_challenge)
        expected_input = f"{self.cookie}{our_challenge}".encode('utf-8')
        expected_digest = hashlib.md5(expected_input).digest()
        
        if their_digest != expected_digest:
            raise ConnectionError("Challenge verification failed - cookie mismatch!")
    
    async def send_reg_send(self, to_name: str, message: Any):
        """Send message to registered process"""
        if not self.connected:
            raise ConnectionError("Not connected")
        
        from_pid = Pid(atom.ensure(self.local_node), 0, 0, self.creation)
        to_name_atom = atom.ensure(to_name)
        
        control = (CTRL_REG_SEND, from_pid, atom.ensure(''), to_name_atom)
        
        control_data = encode(control)
        message_data = encode(message)
        
        # Strip the ETF version byte (131) from encoded data
        # The distribution header already specifies the version
        if control_data[0] == 131:
            control_data = control_data[1:]
        if message_data[0] == 131:
            message_data = message_data[1:]
        
        # Distribution header (no atom cache)
        # Format: 131 (version) + 68 (DIST_HEADER) + 0 (no cache entries)
        dist_header = bytes([131, 68, 0])
        
        packet = dist_header + control_data + message_data
        header = struct.pack('>I', len(packet))
        
        self.writer.write(header + packet)
        await self.writer.drain()
    
    async def send_to_pid(self, to_pid: Pid, message: Any):
        """Send message to specific PID"""
        if not self.connected:
            raise ConnectionError("Not connected")
        
        control = (CTRL_SEND, atom.ensure(''), to_pid)
        
        control_data = encode(control)
        message_data = encode(message)
        
        # Strip ETF version bytes
        if control_data[0] == 131:
            control_data = control_data[1:]
        if message_data[0] == 131:
            message_data = message_data[1:]
        
        dist_header = bytes([131, 68, 0])
        packet = dist_header + control_data + message_data
        header = struct.pack('>I', len(packet))
        
        self.writer.write(header + packet)
        await self.writer.drain()
    
    async def _receive_loop(self):
        """Receive messages from remote node"""
        while self.connected:
            try:
                header = await self.reader.read(4)
                if not header:
                    break
                
                length = struct.unpack('>I', header)[0]
                packet = await self.reader.read(length)
                
                # Check for distribution header
                if len(packet) < 3:
                    continue
                
                if packet[0] == 131 and packet[1] == 68:  # DIST_HEADER
                    # Parse distribution header format
                    num_atom_refs = packet[2]
                    offset = 3
                    # Skip atom cache refs for now
                    
                    # Parse control and message
                    if self.message_handler:
                        await self.message_handler(packet[offset:])
            
            except Exception as e:
                break
        
        self.connected = False
    
    def close(self):
        """Close connection"""
        self.connected = False
        if self.writer:
            self.writer.close()