# Process Operations

## Overview

The process module provides BEAM-style lightweight processes for Python, enabling isolated concurrent execution with message passing. It serves as the foundation for all OTP patterns in otpylib, abstracting the underlying runtime while providing a familiar Erlang/Elixir-like API.

## Core Concepts

### What is a Process?

A process in otpylib is:
- **Isolated execution unit**: No shared memory with other processes
- **Lightweight**: Just a Python coroutine + minimal overhead
- **Communicating**: Interacts only via message passing
- **Identifiable**: Has a unique PID (Process ID)
- **Named**: Can be registered with a global name
- **Mortal**: Can fail independently without crashing the system

### Process vs Thread vs Coroutine

| Aspect | Process (otpylib) | Thread (Python) | Coroutine (asyncio) |
|--------|------------------|-----------------|---------------------|
| Memory | Isolated | Shared | Shared |
| Communication | Message passing | Locks/queues | Direct calls |
| Failure | Isolated | Can corrupt | Can corrupt |
| Weight | Light (~KB) | Heavy (~MB) | Minimal |
| Scheduling | Cooperative | Preemptive* | Cooperative |
| GIL Impact | Single thread | GIL-bound | Single thread |

*Python threads are preemptive but limited by GIL

## Architecture

### System Stack

```
┌─────────────────────────────────────┐
│         User Process Code            │
│     (your functions/coroutines)      │
├─────────────────────────────────────┤
│          Process API                 │
│  (spawn, send, receive, link, etc)   │
├─────────────────────────────────────┤
│       Runtime Backend                │
│    (AsyncIOBackend or others)        │
├─────────────────────────────────────┤
│      Python Event Loop               │
│         (asyncio)                    │
└─────────────────────────────────────┘
```

### Process Structure

Each process consists of:
```python
Process {
    pid: str                    # Unique identifier
    task: asyncio.Task         # Underlying coroutine
    mailbox: Queue             # Message queue (optional)
    name: Optional[str]        # Global name
    links: Set[str]           # Bidirectional failure links
    monitors: Dict[str, str]  # Unidirectional watchers
    trap_exits: bool          # Convert exit signals to messages
}
```

## Operations

### Process Creation

#### spawn()
```python
pid = await process.spawn(func, args=None, kwargs=None, name=None, mailbox=True)
```

Creates a new process:
1. Generates unique PID
2. Creates mailbox queue if requested
3. Wraps function with process context
4. Starts asyncio.Task
5. Returns PID immediately

#### spawn_link()
```python
pid = await process.spawn_link(func, args=None, kwargs=None, name=None)
```

Atomically spawns and links process to current process.

#### spawn_monitor()
```python
pid, ref = await process.spawn_monitor(func, args=None, kwargs=None, name=None)
```

Atomically spawns and monitors process from current process.

### Message Passing

#### send()
```python
await process.send(target, message)
```

Sends message to target process:
- Target can be PID or registered name
- Message can be any Python object
- Non-blocking (returns after queue)
- Raises if target doesn't exist

#### receive()
```python
msg = await process.receive(timeout=None, match=None)
```

Receives message in current process:
- Blocks until message available
- Optional timeout (raises TimeoutError)
- Future: selective receive with match function
- Must be called from within a process

### Process Relationships

#### link()
```python
await process.link(pid)
```

Creates bidirectional link:
- If either process dies abnormally, the other is killed
- Used for dependent processes
- Forms supervision trees

#### unlink()
```python
await process.unlink(pid)
```

Removes existing link.

#### monitor()
```python
ref = await process.monitor(pid)
```

Creates unidirectional monitor:
- When target dies, watcher receives DOWN message
- Returns unique monitor reference
- Used for supervisors and request tracking

#### demonitor()
```python
await process.demonitor(ref, flush=False)
```

Removes monitor by reference.

### Process Registry

#### register()
```python
await process.register(name, pid=None)
```

Associates name with process:
- Name must be unique
- Defaults to current process
- Enables send by name
- Automatically cleaned on exit

#### unregister()
```python
await process.unregister(name)
```

Removes name registration.

#### whereis()
```python
pid = process.whereis(name)
```

Looks up PID by name.

#### registered()
```python
names = process.registered()
```

Returns all registered names.

### Process Inspection

#### self()
```python
pid = process.self()
```

Returns current process PID or None.

#### is_alive()
```python
alive = process.is_alive(pid)
```

Checks if process is running.

#### processes()
```python
pids = process.processes()
```

Returns all process PIDs.

#### exit()
```python
await process.exit(pid, reason)
```

Sends exit signal to process.

## Message Flow Patterns

### Basic Send/Receive
```
Process A                Process B
    |                        |
    |-------- msg --------->|
    |                        | receive()
    |                        | process msg
    |                        |
```

### Request-Reply
```
Process A                Process B
    |                        |
    |--- request + PID ----->|
    |                        | receive()
    |                        | process
    |<------ reply ---------|
    | receive()              |
    |                        |
```

### Broadcast
```
Process A          Process B, C, D
    |                    |
    |---- msg ---------->|
    |---- msg ---------->|
    |---- msg ---------->|
    |                    |
```

## Process Context

The runtime tracks current process using ContextVar:

```python
# Inside a process
pid = process.self()  # Returns current PID

# Outside a process
pid = process.self()  # Returns None
```

This enables context-aware operations:
- `receive()` - knows which mailbox
- `link()` - knows source process
- `register()` - defaults to current

## Exit Handling

### Normal Exit
Process function returns normally:
- Exit reason: NORMAL
- Links: not triggered
- Monitors: receive ('DOWN', ref, 'process', pid, 'normal')

### Abnormal Exit
Process raises exception:
- Exit reason: exception
- Links: propagate exit (kill linked processes)
- Monitors: receive ('DOWN', ref, 'process', pid, exception)

### Trap Exits
Process with `trap_exits=True`:
- Exit signals become messages: ('EXIT', from_pid, reason)
- Process can handle partner failures
- Used by supervisors

## Mailbox Management

### Queue Behavior
- FIFO message delivery
- Bounded size (default 100)
- Backpressure on send when full
- Closed on process exit

### Message Types
Any Python object can be sent:
- Primitives: int, str, list, dict
- Custom objects
- Atoms for efficient tags
- Tuples for structured messages

### Memory Considerations
Messages are references (not copied):
- Fast for immutable objects
- Careful with mutable state
- No serialization overhead locally

## Failure Semantics

### Let It Crash Philosophy
- Processes should fail fast on errors
- Don't defensive code everything
- Supervisors handle restart
- State rebuilt from scratch

### Error Isolation
Failed process cannot:
- Corrupt other process memory
- Leave locks held
- Leak resources (cleaned up)
- Deadlock the system

### Cascading Failures
Links create failure groups:
- One crashes → all linked crash
- Supervisors restart groups
- Maintains consistency

## Performance Profile

### Spawn Performance
- Creation: ~100-1000 microseconds
- Memory: ~10KB base overhead
- Scalability: 10,000s of processes viable

### Message Passing
- Local send: ~1-10 microseconds
- No serialization cost
- Queue operations: O(1)

### Context Switching
- Cooperative: ~1 microsecond
- No kernel involvement
- No thread context switch

## Implementation Details

### AsyncIO Backend

The default backend maps:
- Process → asyncio.Task
- Mailbox → asyncio.Queue
- Context → ContextVar
- Scheduling → asyncio event loop

### PID Generation
```python
pid = f"pid_{uuid.uuid4().hex[:12]}"
```
- Globally unique
- No coordination required
- Embedded type hint

### Registry Implementation
```python
_name_registry: Dict[str, str] = {}  # name -> pid
_processes: Dict[str, Process] = {}  # pid -> process
```
- O(1) lookup by name or PID
- Automatic cleanup on exit
- Thread-safe with locks

## Common Patterns

### Worker Pool
```python
# Spawn worker pool
workers = []
for i in range(10):
    pid = await process.spawn(worker_func, name=f"worker_{i}")
    workers.append(pid)

# Distribute work
for i, work_item in enumerate(work):
    worker = workers[i % len(workers)]
    await process.send(worker, work_item)
```

### Monitor Pattern
```python
async def monitored_operation():
    pid, ref = await process.spawn_monitor(risky_operation)
    
    while True:
        msg = await process.receive(timeout=30)
        if msg[0] == 'DOWN' and msg[1] == ref:
            # Process died
            return handle_failure(msg[4])  # reason
        elif msg[0] == 'result':
            return msg[1]
```

### Link for Cleanup
```python
async def with_resource():
    # Spawn resource manager
    resource_pid = await process.spawn_link(resource_manager)
    
    try:
        # Use resource
        await process.send(resource_pid, ('query', data))
        result = await process.receive()
    finally:
        # If we die, resource_manager dies too (linked)
        pass
```

## Best Practices

1. **One process, one concern**: Keep processes focused
2. **Fail fast**: Don't catch exceptions you can't handle
3. **Message contracts**: Define clear message formats
4. **Name processes**: Use descriptive names for debugging
5. **Monitor for reliability**: Track critical processes
6. **Link for consistency**: Group related processes

## Debugging

### Process Discovery
```python
# List all processes
for pid in process.processes():
    print(f"Process: {pid}")
    
# Find specific process
db_pid = process.whereis("database")
if db_pid and process.is_alive(db_pid):
    print(f"Database running: {db_pid}")
```

### Message Tracing
```python
async def traced_process():
    while True:
        msg = await process.receive()
        print(f"[{process.self()}] Received: {msg}")
        # Process message
```

### Monitoring Health
```python
async def health_monitor(targets):
    refs = {}
    for target in targets:
        refs[await process.monitor(target)] = target
    
    while True:
        msg = await process.receive()
        if msg[0] == 'DOWN':
            failed = refs[msg[1]]
            print(f"Process {failed} died: {msg[4]}")
```

## Limitations

1. **Single event loop**: All processes on one thread
2. **Python GIL**: CPU-bound work blocks all processes
3. **Local only**: No network distribution (yet)
4. **No persistence**: State lost on shutdown
5. **No selective receive**: Messages processed in order

## Comparison with BEAM

### Similarities
- Process isolation
- Message passing only
- Link/monitor primitives
- Let it crash philosophy
- Lightweight processes

### Differences
- Single-threaded vs multi-scheduler
- Python objects vs Erlang terms
- Asyncio vs BEAM scheduler
- No distribution vs distributed by default
- Thousands vs millions of processes

## Future Directions

- Network distribution
- Multiple event loops
- Persistent mailboxes
- Selective receive
- Process migration
- Built-in debugging tools

## Summary

The process module brings BEAM's actor model to Python, enabling thousands of isolated, communicating processes on a single thread. By providing spawn, send, receive, link, and monitor primitives, it creates a foundation for building fault-tolerant systems without traditional concurrency headaches. The integration with Python's asyncio makes it natural for Python developers while maintaining the robustness of Erlang's process model.
