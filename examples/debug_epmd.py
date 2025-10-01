import asyncio
import struct

async def test_epmd():
    reader, writer = await asyncio.open_connection('127.0.0.1', 4369)
    
    # Send PORT2_REQ for 'test'
    name = b'test'
    packet = struct.pack('>H', 1 + len(name))
    packet += struct.pack('B', 122)  # PORT2_REQ
    packet += name
    
    print(f"Sending: {packet.hex()}")
    writer.write(packet)
    await writer.drain()
    
    response = await reader.read(1024)
    print(f"Response length: {len(response)}")
    print(f"Response hex: {response.hex()}")
    print(f"Response bytes: {list(response[:20])}")
    
    writer.close()

asyncio.run(test_epmd())