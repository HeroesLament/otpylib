#!/usr/bin/env python3
"""
Instrumented Storage & Notifier Demo

This demonstrates atom performance measurement using monotonic clocks
to measure atom lookup and comparison times in real genserver scenarios.
"""

import anyio
import anyio.abc
import types
import time
from statistics import mean, median
from otpylib import gen_server, mailbox, atom

# Pre-create atoms once at module level - these are actual Atom objects
GET = atom.ensure("get")
PUT = atom.ensure("put")
DELETE = atom.ensure("delete")
CLEAR = atom.ensure("clear")
LIST_KEYS = atom.ensure("list_keys")
EVENT = atom.ensure("event")
GET_COUNT = atom.ensure("get_count")
RESET = atom.ensure("reset")
PING = atom.ensure("ping")
STOP = atom.ensure("stop")
READY = atom.ensure("ready")
BUSY = atom.ensure("busy")
LISTENING = atom.ensure("listening")

# Performance tracking
lookup_times = []
comparison_times = []
creation_times = []

def time_atom_lookup(name: str):
    """Time atom lookup via ensure (cached lookup)."""
    start = time.monotonic_ns()
    atom_obj = atom.ensure(name)  # Should be instant for existing atoms
    end = time.monotonic_ns()
    lookup_times.append(end - start)
    return atom_obj

def time_atom_comparison(atom1, atom2):
    """Time atom comparison."""
    start = time.monotonic_ns()
    result = atom1 == atom2
    end = time.monotonic_ns()
    comparison_times.append(end - start)
    return result

def time_atom_creation(name: str):
    """Time atom creation (should only happen once per name)."""
    start = time.monotonic_ns()
    atom_obj = atom.ensure(name)
    end = time.monotonic_ns()
    creation_times.append(end - start)
    return atom_obj

# =============================================================================
# Storage GenServer (holds key-value pairs) - INSTRUMENTED
# =============================================================================

storage_callbacks = types.SimpleNamespace()

async def storage_init(_init_arg):
    """Initialize the storage."""
    return {
        "data": {},
        "status": READY
    }

storage_callbacks.init = storage_init

async def storage_handle_call(message, _caller, state):
    """Handle storage calls using atom-based dispatch - INSTRUMENTED."""
    match message:
        case msg_type, key if time_atom_comparison(msg_type, GET):
            # Get value by key
            value = state["data"].get(key)
            return (gen_server.Reply(payload=value), state)
        
        case msg_type, (key, value) if time_atom_comparison(msg_type, PUT):
            # Store key-value pair
            old_value = state["data"].get(key)
            state["data"][key] = value
            
            # Notify the notifier of the change
            await mailbox.send("notifier", (
                EVENT,
                {
                    "type": "put",
                    "key": key,
                    "old_value": old_value,
                    "new_value": value
                }
            ))
            
            return (gen_server.Reply(payload=old_value), state)
        
        case msg_type if time_atom_comparison(msg_type, LIST_KEYS):
            # List all keys
            keys = list(state["data"].keys())
            return (gen_server.Reply(payload=keys), state)
        
        case _:
            error = NotImplementedError(f"Unknown call: {message}")
            return (gen_server.Reply(payload=error), state)

storage_callbacks.handle_call = storage_handle_call

async def storage_handle_cast(message, state):
    """Handle storage casts using atoms - INSTRUMENTED."""
    match message:
        case msg_type, key if time_atom_comparison(msg_type, DELETE):
            # Delete a key
            old_value = state["data"].pop(key, None)
            
            if old_value is not None:
                # Notify the notifier
                await mailbox.send("notifier", (
                    EVENT,
                    {
                        "type": "delete",
                        "key": key,
                        "old_value": old_value
                    }
                ))
            
            return (gen_server.NoReply(), state)
        
        case msg_type if time_atom_comparison(msg_type, CLEAR):
            # Clear all data
            old_count = len(state["data"])
            state["data"].clear()
            
            # Notify the notifier
            await mailbox.send("notifier", (
                EVENT,
                {
                    "type": "clear",
                    "count": old_count
                }
            ))
            
            return (gen_server.NoReply(), state)
        
        case msg_type if time_atom_comparison(msg_type, STOP):
            return (gen_server.Stop(), state)
        
        case _:
            print(f"Storage: Unknown cast: {message}")
            return (gen_server.NoReply(), state)

storage_callbacks.handle_cast = storage_handle_cast

async def storage_handle_info(message, state):
    """Handle info messages - INSTRUMENTED."""
    match message:
        case msg_type if time_atom_comparison(msg_type, PING):
            print(f"Storage: Pong! Holding {len(state['data'])} items")
        case _:
            print(f"Storage: Received info: {message}")
    
    return (gen_server.NoReply(), state)

storage_callbacks.handle_info = storage_handle_info

async def storage_terminate(reason, state):
    """Cleanup for storage."""
    print(f"Storage terminated with {len(state['data'])} items")

storage_callbacks.terminate = storage_terminate

# =============================================================================
# Notifier GenServer (tracks events from other services) - INSTRUMENTED
# =============================================================================

notifier_callbacks = types.SimpleNamespace()

async def notifier_init(_init_arg):
    """Initialize the notifier."""
    return {
        "event_count": 0,
        "status": LISTENING
    }

notifier_callbacks.init = notifier_init

async def notifier_handle_call(message, _caller, state):
    """Handle notifier calls - INSTRUMENTED."""
    match message:
        case msg_type if time_atom_comparison(msg_type, GET_COUNT):
            response = {
                "event_count": state["event_count"],
                "status": state["status"].name
            }
            return (gen_server.Reply(payload=response), state)
        
        case _:
            error = NotImplementedError(f"Unknown notifier call: {message}")
            return (gen_server.Reply(payload=error), state)

notifier_callbacks.handle_call = notifier_handle_call

async def notifier_handle_cast(message, state):
    """Handle notifier casts - INSTRUMENTED."""
    match message:
        case msg_type if time_atom_comparison(msg_type, RESET):
            state["event_count"] = 0
            print("Notifier: Event count reset")
            return (gen_server.NoReply(), state)
        
        case msg_type if time_atom_comparison(msg_type, STOP):
            return (gen_server.Stop(), state)
        
        case _:
            print(f"Notifier: Unknown cast: {message}")
            return (gen_server.NoReply(), state)

notifier_callbacks.handle_cast = notifier_handle_cast

async def notifier_handle_info(message, state):
    """Handle info messages - INSTRUMENTED."""
    match message:
        case msg_type, payload if time_atom_comparison(msg_type, EVENT):
            state["event_count"] += 1
            event_type = payload.get("type", "unknown")
            
            if event_type == "put":
                key = payload["key"]
                old = payload["old_value"]
                new = payload["new_value"]
                action = "updated" if old is not None else "created"
                print(f"EVENT #{state['event_count']}: {action} '{key}': {old} -> {new}")
            
            elif event_type == "delete":
                key = payload["key"]
                old = payload["old_value"]
                print(f"EVENT #{state['event_count']}: deleted '{key}' (was: {old})")
            
            elif event_type == "clear":
                count = payload["count"]
                print(f"EVENT #{state['event_count']}: cleared storage ({count} items removed)")
            
            else:
                print(f"EVENT #{state['event_count']}: unknown event: {payload}")
            
            return (gen_server.NoReply(), state)
        
        case msg_type if time_atom_comparison(msg_type, PING):
            print(f"Notifier: Pong! Tracked {state['event_count']} events")
            return (gen_server.NoReply(), state)
        
        case _:
            print(f"Notifier: Received info: {message}")
            return (gen_server.NoReply(), state)

notifier_callbacks.handle_info = notifier_handle_info

async def notifier_terminate(reason, state):
    """Cleanup for notifier."""
    print(f"Notifier terminated (tracked {state['event_count']} events)")

notifier_callbacks.terminate = notifier_terminate

# =============================================================================
# Performance Benchmarks
# =============================================================================

def run_atom_benchmarks():
    """Run dedicated atom performance benchmarks."""
    print("\n=== Atom Performance Benchmarks ===")
    
    # Benchmark 1: Atom lookup speed (cached lookups via ensure)
    print("\nBenchmark 1: Cached atom lookup via ensure (1000 iterations)")
    times = []
    for _ in range(1000):
        start = time.monotonic_ns()
        atom.ensure("get")  # Should hit cache
        end = time.monotonic_ns()
        times.append(end - start)
    
    print(f"  Mean: {mean(times):.1f} ns")
    print(f"  Median: {median(times):.1f} ns")
    print(f"  Min: {min(times)} ns")
    print(f"  Max: {max(times)} ns")
    
    # Benchmark 2: Atom comparison speed
    print("\nBenchmark 2: Atom comparison (1000 iterations)")
    atom1 = atom.ensure("get")
    atom2 = atom.ensure("put")
    atom3 = atom.ensure("get")  # Same as atom1
    
    times_equal = []
    times_different = []
    
    for _ in range(1000):
        # Equal comparison
        start = time.monotonic_ns()
        result = atom1 == atom3
        end = time.monotonic_ns()
        times_equal.append(end - start)
        
        # Different comparison
        start = time.monotonic_ns()
        result = atom1 == atom2
        end = time.monotonic_ns()
        times_different.append(end - start)
    
    print(f"  Equal atoms - Mean: {mean(times_equal):.1f} ns")
    print(f"  Different atoms - Mean: {mean(times_different):.1f} ns")
    
    # Benchmark 3: Atom creation (new atoms)
    print("\nBenchmark 3: New atom creation (100 iterations)")
    times = []
    for i in range(100):
        start = time.monotonic_ns()
        atom.ensure(f"benchmark_atom_{i}")
        end = time.monotonic_ns()
        times.append(end - start)
    
    print(f"  Mean: {mean(times):.1f} ns")
    print(f"  Median: {median(times):.1f} ns")

# =============================================================================
# Demo Client
# =============================================================================

async def demo_client():
    """Demonstrate two gen_servers communicating with atoms - INSTRUMENTED."""
    print("=== Instrumented Storage & Notifier Demo ===")
    
    # Show initial atom table
    print("\nInitial atoms:")
    for name, atom_obj in atom.all_atoms().items():
        print(f"  {atom_obj!r} -> {atom_obj.id}")
    
    # Test some atom lookups with timing
    print("\nTesting cached atom lookups:")
    for name in ["get", "put", "delete", "new_runtime_atom"]:
        result = time_atom_lookup(name)
        if name == "new_runtime_atom":
            print(f"  Lookup '{name}': {result} (newly created)")
        else:
            print(f"  Lookup '{name}': {result} (cached)")
    
    # Test storage operations (these will be timed automatically)
    print("\n1. Storing some data...")
    await gen_server.call("storage", (PUT, ("name", "Alice")))
    await gen_server.call("storage", (PUT, ("age", 30)))
    await gen_server.call("storage", (PUT, ("city", "New York")))
    
    await anyio.sleep(0.1)
    
    print("\n2. Getting stored data...")
    name = await gen_server.call("storage", (GET, "name"))
    age = await gen_server.call("storage", (GET, "age"))
    print(f"   Name: {name}, Age: {age}")
    
    print("\n3. Listing all keys...")
    keys = await gen_server.call("storage", LIST_KEYS)
    print(f"   Keys: {keys}")
    
    print("\n4. Updating existing data...")
    old_age = await gen_server.call("storage", (PUT, ("age", 31)))
    print(f"   Updated age from {old_age} to 31")
    
    await anyio.sleep(0.1)
    
    print("\n5. Deleting data...")
    await gen_server.cast("storage", (DELETE, "city"))
    
    await anyio.sleep(0.1)
    
    print("\n6. Getting notifier stats...")
    stats = await gen_server.call("notifier", GET_COUNT)
    print(f"   Notifier stats: {stats}")
    
    print("\n7. Pinging both servers...")
    await mailbox.send("storage", PING)
    await mailbox.send("notifier", PING)
    
    await anyio.sleep(0.1)
    
    print("\n8. Creating some new atoms during runtime...")
    new_atoms = []
    for i in range(10):
        new_atom = time_atom_creation(f"runtime_atom_{i}")
        new_atoms.append(new_atom)
    
    print(f"   Created {len(new_atoms)} new atoms")
    
    print("\n9. Stopping servers...")
    await gen_server.cast("notifier", STOP)
    await gen_server.cast("storage", STOP)

def print_performance_summary():
    """Print summary of all performance measurements."""
    print("\n" + "=" * 60)
    print("ATOM PERFORMANCE SUMMARY")
    print("=" * 60)
    
    if lookup_times:
        print(f"\nAtom Lookups ({len(lookup_times)} samples):")
        print(f"  Mean: {mean(lookup_times):.1f} ns")
        print(f"  Median: {median(lookup_times):.1f} ns")
        print(f"  Min: {min(lookup_times)} ns")
        print(f"  Max: {max(lookup_times)} ns")
    
    if comparison_times:
        print(f"\nAtom Comparisons ({len(comparison_times)} samples):")
        print(f"  Mean: {mean(comparison_times):.1f} ns")
        print(f"  Median: {median(comparison_times):.1f} ns")
        print(f"  Min: {min(comparison_times)} ns")
        print(f"  Max: {max(comparison_times)} ns")
    
    if creation_times:
        print(f"\nAtom Creations ({len(creation_times)} samples):")
        print(f"  Mean: {mean(creation_times):.1f} ns")
        print(f"  Median: {median(creation_times):.1f} ns")
        print(f"  Min: {min(creation_times)} ns")
        print(f"  Max: {max(creation_times)} ns")
    
    print(f"\nTotal atoms in table: {atom.atom_count()}")

async def main():
    """Main application entry point."""
    async with anyio.create_task_group() as tg:
        # Start both gen_servers
        await tg.start(gen_server.start, notifier_callbacks, None, "notifier")
        await tg.start(gen_server.start, storage_callbacks, None, "storage")
        
        # Run the demo
        await demo_client()

if __name__ == "__main__":
    mailbox.init_mailbox_registry()
    
    # Run the demo
    anyio.run(main)
    
    # Run dedicated benchmarks
    run_atom_benchmarks()
    
    # Print performance summary
    print_performance_summary()
