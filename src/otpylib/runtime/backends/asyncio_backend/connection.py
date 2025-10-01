"""
Connection to a remote Erlang/OTP node - WITH DEBUG OUTPUT

Handles the distribution handshake and message sending/receiving.
"""

import asyncio
import struct
import hashlib
import random
from typing import Optional, Callable, Awaitable, Any

from otpylib import atom
from otpylib.distribution.etf import encode, decode, Pid, ETFDecoder
from otpylib.distribution.constants import (
    DEFAULT_FLAGS,
    CTRL_REG_SEND,
    CTRL_SEND,
)


class AsyncIOConnection:
    """A connection to a remote node"""
    
    def __init__(self, local_node: str, remote_node: Optional[str], cookie: str, creation: int = 1):
        self.local_node = local_node
        self.remote_node = remote_node
        self.cookie = cookie
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.creation = creation
        self.flags = DEFAULT_FLAGS
        self.message_handler: Optional[Callable[[Any], Awaitable[None]]] = None
        self._send_lock = asyncio.Lock()
        self._recv_lock = asyncio.Lock()
        self._socket_id = id(self)  # Unique ID for this connection object
    
    @property
    def connected(self) -> bool:
        """Check if connection is still active."""
        return (self.reader is not None and 
                self.writer is not None and 
                not self.reader.at_eof())
    
    async def connect(self, host: str, port: int):
        """Connect and handshake with remote node (client side)"""
        self.reader, self.writer = await asyncio.open_connection(host, port)
        await self._client_handshake()
    
    async def accept_connection(
        self, 
        reader: asyncio.StreamReader, 
        writer: asyncio.StreamWriter
    ) -> Optional[str]:
        """Accept incoming connection and perform server-side handshake."""
        self.reader = reader
        self.writer = writer
        
        try:
            remote_node = await self._server_handshake()
            if remote_node:
                self.remote_node = remote_node
                return remote_node
            else:
                return None
        except Exception as e:
            import traceback
            traceback.print_exc()
            return None
    
    async def _client_handshake(self):
        """Perform client-side handshake (version 6 format)"""
        # Step 1: Send our name
        name_bytes = self.local_node.encode('utf-8')
        
        # Use version 6 format ('N' with 8-byte flags and 4-byte creation)
        message = struct.pack('>cQI', b'N', self.flags, self.creation)
        message += struct.pack('>H', len(name_bytes)) + name_bytes
        
        # Send with 2-byte length header
        packet = struct.pack('>H', len(message)) + message
        
        self.writer.write(packet)
        await self.writer.drain()
        
        # Step 2: Receive status
        length_bytes = await self.reader.read(2)
        if len(length_bytes) < 2:
            raise ConnectionError(f"Connection closed reading status length (got {len(length_bytes)} bytes)")
        
        length = struct.unpack('>H', length_bytes)[0]
        data = await self.reader.read(length)
        
        if len(data) < 1 or chr(data[0]) != 's':
            raise ConnectionError(f"Expected status 's', got {chr(data[0]) if data else 'nothing'}")
        
        status = data[1:]
        
        if status == b'ok' or status == b'ok_simultaneous':
            pass  # Success
        elif status == b'alive':
            raise ConnectionError("Node is alive but we can't connect (simultaneous connect)")
        elif status == b'nok' or status == b'not_allowed':
            raise ConnectionError(f"Handshake rejected: {status.decode('utf-8')} (check cookie)")
        else:
            raise ConnectionError(f"Unknown status: {status}")
        
        # Step 3: Receive challenge
        length_bytes = await self.reader.read(2)
        if len(length_bytes) < 2:
            raise ConnectionError(f"Connection closed reading challenge length (got {len(length_bytes)} bytes)")
        
        length = struct.unpack('>H', length_bytes)[0]
        data = await self.reader.read(length)
        
        if len(data) < 1:
            raise ConnectionError("Empty challenge message")
        
        challenge_type = chr(data[0])
        
        if challenge_type not in ['N', 'n']:
            raise ConnectionError(f"Expected challenge 'N' or 'n', got '{challenge_type}'")
        
        # Parse challenge (version 6 format for 'N', version 5 for 'n')
        if challenge_type == 'N':
            flags = struct.unpack('>Q', data[1:9])[0]
            their_challenge = struct.unpack('>I', data[9:13])[0]
            their_creation = struct.unpack('>I', data[13:17])[0]
            nlen = struct.unpack('>H', data[17:19])[0]
            their_name = data[19:19+nlen].decode('utf-8')
        else:  # 'n' - version 5
            flags = struct.unpack('>I', data[1:5])[0]
            their_challenge = struct.unpack('>I', data[5:9])[0]
            their_creation = struct.unpack('>I', data[9:13])[0]
            nlen = struct.unpack('>H', data[13:15])[0]
            their_name = data[15:15+nlen].decode('utf-8')
        
        # Step 4: Send challenge reply
        our_challenge = random.randint(0, 0xFFFFFFFF)
        
        # Calculate digest of THEIR challenge
        digest = self._compute_digest(their_challenge)
        
        # Message format: 'r' + our_challenge(4) + digest(16)
        message = struct.pack('>cI', b'r', our_challenge) + digest
        packet = struct.pack('>H', len(message)) + message
        
        self.writer.write(packet)
        await self.writer.drain()
        
        # Step 5: Receive ack
        length_bytes = await self.reader.read(2)
        if len(length_bytes) < 2:
            raise ConnectionError(f"Connection closed while reading ack length (got {len(length_bytes)} bytes)")
        
        length = struct.unpack('>H', length_bytes)[0]
        data = await self.reader.read(length)
        
        if len(data) < 1 or chr(data[0]) != 'a':
            raise ConnectionError(f"Expected ack 'a', got '{chr(data[0]) if data else 'nothing'}'")
        
        their_digest = data[1:17]
        
        # Verify their digest
        expected_digest = self._compute_digest(our_challenge)
        
        if their_digest != expected_digest:
            raise ConnectionError("Challenge verification failed - cookie mismatch!")
    
    async def _server_handshake(self) -> Optional[str]:
        """Perform server-side handshake."""
        # Receive name message
        name_len = struct.unpack('>H', await self.reader.readexactly(2))[0]
        name_msg = await self.reader.readexactly(name_len)
        
        if name_msg[0:1] != b'N' and name_msg[0:1] != b'n':
            return None
        
        # Parse name message (handle both 'N' and 'n' versions)
        if name_msg[0:1] == b'N':
            flags_remote = struct.unpack('>Q', name_msg[1:9])[0]
            creation_remote = struct.unpack('>I', name_msg[9:13])[0]
            remote_name_len = struct.unpack('>H', name_msg[13:15])[0]
            remote_name = name_msg[15:15+remote_name_len].decode('utf-8')
        else:
            flags_remote = struct.unpack('>I', name_msg[1:5])[0]
            creation_remote = struct.unpack('>I', name_msg[5:9])[0]
            remote_name_len = struct.unpack('>H', name_msg[9:11])[0]
            remote_name = name_msg[11:11+remote_name_len].decode('utf-8')
        
        # Send status "ok"
        status_msg = struct.pack('>H', 3) + b's' + b'ok'
        self.writer.write(status_msg)
        await self.writer.drain()
        
        # Send challenge (match their version)
        our_challenge = random.randint(0, 0xFFFFFFFF)
        name_bytes = self.local_node.encode('utf-8')
        
        challenge_msg = struct.pack('>H', len(name_bytes) + 1 + 8 + 4 + 4 + 2) + b'N'
        challenge_msg += struct.pack('>Q', self.flags)
        challenge_msg += struct.pack('>I', our_challenge)
        challenge_msg += struct.pack('>I', self.creation)
        challenge_msg += struct.pack('>H', len(name_bytes))
        challenge_msg += name_bytes
        
        self.writer.write(challenge_msg)
        await self.writer.drain()
        
        # Receive challenge reply
        reply_len = struct.unpack('>H', await self.reader.readexactly(2))[0]
        reply_msg = await self.reader.readexactly(reply_len)
        
        if reply_msg[0:1] != b'r':
            return None
        
        their_challenge = struct.unpack('>I', reply_msg[1:5])[0]
        their_digest = reply_msg[5:21]
        
        # Verify their digest
        expected_digest = self._compute_digest(our_challenge)
        if their_digest != expected_digest:
            return None
        
        # Send challenge ack
        our_digest = self._compute_digest(their_challenge)
        ack_msg = struct.pack('>H', 17) + b'a' + our_digest
        
        self.writer.write(ack_msg)
        await self.writer.drain()
        return remote_name
    
    def _compute_digest(self, challenge: int) -> bytes:
        """Compute MD5 digest for challenge."""
        m = hashlib.md5()
        # Cookie + challenge as decimal string (not binary!)
        challenge_str = str(challenge)
        digest_input = self.cookie + challenge_str
        m.update(digest_input.encode('utf-8'))
        return m.digest()
    
    async def send_reg_send(self, to_name: str, message: Any):
        """Send message to registered process"""
        if not self.connected:
            raise ConnectionError("Not connected")
        
        async with self._send_lock:
            from_pid = Pid(atom.ensure(self.local_node), 0, 0, self.creation)
            to_name_atom = atom.ensure(to_name)
            
            control = (CTRL_REG_SEND, from_pid, atom.ensure(''), to_name_atom)
            
            control_data = encode(control)
            message_data = encode(message)
            
            # Strip the ETF version byte (131)
            if control_data[0] == 131:
                control_data = control_data[1:]
            if message_data[0] == 131:
                message_data = message_data[1:]
            
            # Distribution header (no atom cache)
            dist_header = bytes([131, 68, 0])
            
            packet = dist_header + control_data + message_data
            header = struct.pack('>I', len(packet))
            self.writer.write(header + packet)
            await self.writer.drain()
    
    async def send_to_pid(self, to_pid: Pid, message: Any):
        """Send message to specific PID"""
        if not self.connected:
            raise ConnectionError("Not connected")
        
        async with self._send_lock:
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
    
    async def receive(self) -> Optional[Any]:
        """Receive next message from the connection."""
        async with self._recv_lock:
            try:
                # Read 4-byte length header
                header = await self.reader.readexactly(4)
                length = struct.unpack('>I', header)[0]

                # Read packet
                try:
                    packet = await self.reader.readexactly(length)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    raise
                
                # Check for distribution header
                if len(packet) < 3:
                    return None
                
                if packet[0] == 131 and packet[1] == 68:  # DIST_HEADER
                    num_atom_refs = packet[2]
                    offset = 3
                    # Skip atom cache refs (we don't use them)
                    
                    # The rest is: control_term + message_term (both without version bytes)
                    # We need to decode them separately
                    remaining_data = packet[offset:]
                    
                    # Decode control term
                    decoder1 = ETFDecoder(bytes([131]) + remaining_data)
                    control = decoder1.decode()
                    
                    # Decode message term (starts where control ended)
                    # decoder1.pos tells us how many bytes were consumed (including the version byte we added)
                    control_length = decoder1.pos - 1  # Subtract the version byte we added
                    
                    message_data = remaining_data[control_length:]
                    if len(message_data) > 0:
                        decoder2 = ETFDecoder(bytes([131]) + message_data)
                        message = decoder2.decode()
                        
                        # Return as tuple: (control, message)
                        return (control, message)
                    else:
                        # No message part, just control
                        return (control, None)
                    
                else:
                    # Fallback: try to decode as plain ETF
                    if packet[0] != 131:
                        packet = bytes([131]) + packet
                    return decode(packet)
                    
            except asyncio.IncompleteReadError:
                return None
            except Exception as e:
                import traceback
                traceback.print_exc()
                return None
    
    def close(self):
        """Close connection"""
        if self.writer:
            try:
                self.writer.close()
            except Exception:
                pass
        
        self.reader = None
        self.writer = None
