"""
EPMD (Erlang Port Mapper Daemon) client.

Handles node registration and lookup via EPMD.
"""

import asyncio
import struct
from typing import Optional
from dataclasses import dataclass

from otpylib.distribution.constants import (
    EPMD_PORT,
    EPMD_ALIVE2_REQ,
    EPMD_ALIVE2_RESP,
    EPMD_PORT2_REQ,
    EPMD_PORT2_RESP,
    DISTRIBUTION_VERSION,
)


@dataclass
class NodeInfo:
    """Information about a remote node"""
    name: str
    port: int
    node_type: int = 77  # Hidden node
    protocol: int = 0    # TCP/IP


class AsyncIOEPMD:
    """EPMD (Erlang Port Mapper Daemon) client"""
    
    @staticmethod
    async def register(node_name: str, port: int, node_type: int = 77) -> int:
        """
        Register this node with EPMD.
        
        Args:
            node_name: Short name (without @host)
            port: Port this node listens on
            node_type: 77 for hidden node, 72 for visible
        
        Returns:
            Creation number from EPMD
        """
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', EPMD_PORT)
            
            name_bytes = node_name.encode('utf-8')
            
            # Build ALIVE2_REQ message body
            # Format: port(2) type(1) proto(1) high_ver(2) low_ver(2) nlen(2) name(nlen) elen(2) extra(elen)
            message = b''
            message += struct.pack('>H', port)          # Port number (2 bytes)
            message += struct.pack('B', node_type)      # Node type (1 byte)
            message += struct.pack('B', 0)              # Protocol: TCP/IP (1 byte)
            message += struct.pack('>H', DISTRIBUTION_VERSION)  # Highest version (2 bytes)
            message += struct.pack('>H', DISTRIBUTION_VERSION)  # Lowest version (2 bytes)
            message += struct.pack('>H', len(name_bytes))       # Name length (2 bytes)
            message += name_bytes                                # Name
            message += struct.pack('>H', 0)                      # Extra length (2 bytes)
            # No extra data
            
            # Prepend: length (2 bytes) + message type (1 byte)
            total_length = len(message) + 1  # +1 for the message type byte
            packet = struct.pack('>H', total_length)
            packet += struct.pack('B', EPMD_ALIVE2_REQ)
            packet += message
            
            writer.write(packet)
            await writer.drain()
            
            # ALIVE2_RESP format:
            # 1 byte: response type (121 = ALIVE2_RESP)
            # 1 byte: result (0 = OK, >0 = error)
            # 2 bytes: creation
            response = await reader.read(4)
            if len(response) < 4:
                raise ConnectionError("EPMD: Invalid ALIVE2 response")
            
            response_type = response[0]
            result = response[1]
            creation = struct.unpack('>H', response[2:4])[0]
            
            if response_type != EPMD_ALIVE2_RESP:
                raise ConnectionError(f"EPMD: Expected ALIVE2_RESP (121), got {response_type}")
            
            if result != 0:
                raise ConnectionError(f"EPMD: Registration failed with result code {result}")
            
            writer.close()
            await writer.wait_closed()
            
            return creation
        
        except Exception as e:
            return 1

    @staticmethod
    async def register_and_keep_alive(node_name: str, port: int, node_type: int = 77) -> tuple:
        """
        Register this node with EPMD and keep the connection alive.

        Returns:
            Tuple of ((reader, writer), creation) - caller must keep connection alive!
        """
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', EPMD_PORT)

            name_bytes = node_name.encode('utf-8')

            # Build ALIVE2_REQ message body (EXACTLY like the working register() method)
            message = b''
            message += struct.pack('>H', port)
            message += struct.pack('B', node_type)
            message += struct.pack('B', 0)
            message += struct.pack('>H', DISTRIBUTION_VERSION)
            message += struct.pack('>H', DISTRIBUTION_VERSION)
            message += struct.pack('>H', len(name_bytes))
            message += name_bytes
            message += struct.pack('>H', 0)

            # Prepend: length (2 bytes) + message type (1 byte)
            total_length = len(message) + 1
            packet = struct.pack('>H', total_length)
            packet += struct.pack('B', EPMD_ALIVE2_REQ)
            packet += message

            writer.write(packet)
            await writer.drain()

            # ALIVE2_RESP format
            response = await reader.read(4)
            if len(response) < 4:
                raise ConnectionError("EPMD: Invalid ALIVE2 response")

            response_type = response[0]
            result = response[1]
            creation = struct.unpack('>H', response[2:4])[0]

            if response_type != EPMD_ALIVE2_RESP:
                raise ConnectionError(f"EPMD: Expected ALIVE2_RESP ({EPMD_ALIVE2_RESP}), got {response_type}")

            if result != 0:
                raise ConnectionError(f"EPMD: Registration failed with result code {result}")

            # DON'T close - return the connection to keep it alive!
            return (reader, writer), creation

        except Exception as e:
            import traceback
            traceback.print_exc()
            return None, 1

    @staticmethod
    async def lookup(node_name: str) -> Optional[NodeInfo]:
        """
        Look up a node via EPMD.
        
        Args:
            node_name: Short name (without @host)
        
        Returns:
            NodeInfo if found, None otherwise
        """
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', EPMD_PORT)
            
            name_bytes = node_name.encode('utf-8')
            message = struct.pack('>HB', len(name_bytes) + 1, EPMD_PORT2_REQ) + name_bytes
            
            writer.write(message)
            await writer.drain()
            
            response = await reader.read(1024)
            
            if len(response) < 2:
                return None
            
            result_code = response[0]
            
            if result_code != EPMD_PORT2_RESP:
                return None
            
            # Parse PORT2_RESP:
            # Byte 0: result code (119 = PORT2_RESP)
            # Byte 1: result (0 = ok, >0 = error)  ← THIS WAS MISSING!
            # Byte 2-3: port number (big-endian uint16)
            # Byte 4: node type
            # Byte 5: protocol
            # Byte 6-7: highest version (big-endian uint16)
            # Byte 8-9: lowest version (big-endian uint16)
            # Byte 10-11: name length (big-endian uint16)
            # Byte 12+: name (variable length)
            
            if len(response) < 12:
                return None
            
            result = response[1]  # ← FIXED: Now reading the result byte
            if result != 0:
                return None
            
            # Now all offsets are shifted by +1
            port = struct.unpack('>H', response[2:4])[0]      # Was [2:4], correct
            node_type = response[4]                            # Was [4], now [4]
            protocol = response[5]                             # Was [5], now [5]
            high_ver = struct.unpack('>H', response[6:8])[0]  # For info
            low_ver = struct.unpack('>H', response[8:10])[0]  # For info
            name_len = struct.unpack('>H', response[10:12])[0]
            
            # Validate name length
            if len(response) < 12 + name_len:
                return None
            
            name = response[12:12+name_len].decode('utf-8')
            
            writer.close()
            await writer.wait_closed()
            
            return NodeInfo(
                name=name,
                port=port,
                node_type=node_type,
                protocol=protocol
            )
        
        except Exception as e:
            return None
