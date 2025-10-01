#!/usr/bin/env python3
"""
Simple ETF Demo - Just encoding and decoding

Demonstrates External Term Format (ETF) working with OTPYLIB atoms.
No networking, no distribution protocol - just the codec.
"""

from otpylib import atom
from otpylib.distribution.etf import encode, decode


def demo_basic_types():
    """Demo encoding/decoding basic Erlang types"""
    print("=" * 60)
    print("ETF Demo: Basic Types")
    print("=" * 60)
    
    # Integers
    print("\n1. Integer:")
    data = encode(42)
    print(f"   Encoded 42: {data.hex()}")
    print(f"   Decoded: {decode(data)}")
    
    # Floats
    print("\n2. Float:")
    data = encode(3.14159)
    print(f"   Encoded 3.14159: {data.hex()}")
    print(f"   Decoded: {decode(data)}")
    
    # Strings (become binaries in ETF)
    print("\n3. String:")
    data = encode("hello")
    print(f"   Encoded 'hello': {data.hex()}")
    print(f"   Decoded: {decode(data)}")
    
    # Bytes
    print("\n4. Bytes:")
    data = encode(b"world")
    print(f"   Encoded b'world': {data.hex()}")
    print(f"   Decoded: {decode(data)}")


def demo_atoms():
    """Demo encoding/decoding atoms"""
    print("\n" + "=" * 60)
    print("ETF Demo: Atoms")
    print("=" * 60)
    
    # Single atom
    print("\n1. Single atom:")
    ok = atom.ensure("ok")
    print(f"   OTPYLIB atom: {ok}")
    data = encode(ok)
    print(f"   Encoded: {data.hex()}")
    decoded = decode(data)
    print(f"   Decoded: {decoded}")
    print(f"   Same atom? {decoded is ok}")
    
    # Booleans (atoms in Erlang)
    print("\n2. Booleans:")
    data = encode(True)
    print(f"   Encoded True: {data.hex()}")
    decoded = decode(data)
    print(f"   Decoded: {decoded} (atom '{decoded.name}')")


def demo_collections():
    """Demo encoding/decoding collections"""
    print("\n" + "=" * 60)
    print("ETF Demo: Collections")
    print("=" * 60)
    
    # Lists
    print("\n1. List:")
    lst = [1, 2, 3]
    data = encode(lst)
    print(f"   Original: {lst}")
    print(f"   Encoded: {data.hex()}")
    print(f"   Decoded: {decode(data)}")
    
    # Tuples
    print("\n2. Tuple:")
    tpl = (atom.ensure("ok"), 42, "result")
    data = encode(tpl)
    print(f"   Original: {tpl}")
    print(f"   Encoded: {data.hex()}")
    print(f"   Decoded: {decode(data)}")
    
    # Maps (dicts)
    print("\n3. Map:")
    mp = {
        atom.ensure("name"): "Alice",
        atom.ensure("age"): 30
    }
    data = encode(mp)
    print(f"   Original: {mp}")
    print(f"   Encoded: {data.hex()}")
    print(f"   Decoded: {decode(data)}")


def demo_genserver_messages():
    """Demo realistic GenServer message patterns"""
    print("\n" + "=" * 60)
    print("ETF Demo: GenServer Messages")
    print("=" * 60)
    
    # GET request
    print("\n1. GET request:")
    msg = (atom.ensure("get"), "user_123")
    data = encode(msg)
    print(f"   Message: {msg}")
    print(f"   Encoded: {data.hex()}")
    decoded = decode(data)
    print(f"   Decoded: {decoded}")
    
    # PUT request
    print("\n2. PUT request:")
    msg = (atom.ensure("put"), "user_123", {"name": "Bob", "age": 25})
    data = encode(msg)
    print(f"   Message: {msg}")
    print(f"   Encoded: {data.hex()}")
    decoded = decode(data)
    print(f"   Decoded: {decoded}")
    
    # Response
    print("\n3. OK response:")
    msg = (atom.ensure("ok"), "success")
    data = encode(msg)
    print(f"   Message: {msg}")
    print(f"   Encoded: {data.hex()}")
    decoded = decode(data)
    print(f"   Decoded: {decoded}")
    
    # Error response
    print("\n4. Error response:")
    msg = (atom.ensure("error"), atom.ensure("not_found"))
    data = encode(msg)
    print(f"   Message: {msg}")
    print(f"   Encoded: {data.hex()}")
    decoded = decode(data)
    print(f"   Decoded: {decoded}")


def demo_roundtrip():
    """Demo that encode -> decode is lossless"""
    print("\n" + "=" * 60)
    print("ETF Demo: Round-trip Test")
    print("=" * 60)
    
    test_cases = [
        42,
        3.14,
        "hello",
        atom.ensure("test"),
        [1, 2, 3],
        (atom.ensure("ok"), "data"),
        {atom.ensure("key"): "value"},
        True,
        False,
    ]
    
    print("\nTesting encode -> decode round-trip:")
    for i, original in enumerate(test_cases, 1):
        encoded = encode(original)
        decoded = decode(encoded)
        match = original == decoded or (hasattr(original, 'name') and hasattr(decoded, 'name') and original.name == decoded.name)
        status = "✓" if match else "✗"
        print(f"   {status} Test {i}: {type(original).__name__} -> {match}")


def main():
    print("\n")
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║  OTPYLIB ETF (External Term Format) Demo                 ║")
    print("║  Erlang serialization format for distributed systems     ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    
    demo_basic_types()
    demo_atoms()
    demo_collections()
    demo_genserver_messages()
    demo_roundtrip()
    
    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)
    print("\nWhat this means:")
    print("- OTPYLIB can serialize/deserialize Erlang data")
    print("- Atoms are preserved across encode/decode")
    print("- GenServer messages can be sent to Erlang nodes")
    print("- Ready for distribution protocol implementation")
    print()


if __name__ == "__main__":
    main()