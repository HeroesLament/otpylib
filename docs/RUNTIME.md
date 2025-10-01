# OTPyLib Runtime System

## Overview

The otpylib runtime provides a BEAM-inspired process model for Python, enabling Erlang/Elixir-style concurrent programming patterns without requiring the Erlang VM. It implements lightweight processes, message passing, and fault tolerance primitives on top of Python's asyncio.

## Core Concepts

### Processes vs Tasks

In traditional Python async programming, you work with coroutines and tasks that share memory and state. The otpylib runtime introduces **processes** - isolated units of computation that communicate only through message passing.

```python
# Traditional Python - shared state
shared_data = {}
async def worker():
    shared_data['key'] = 'value'  # Direct memory access

# OTPyLib - isolated processes  
from otpylib import process

async def worker():
    msg = await process.receive()  # Only message passing
    await process.send(sender, response)
```

### The Runtime Backend

The runtime backend is the engine that manages process lifecycle, message delivery, and fault tolerance. It provides:

- **Process spawning**: Create new processes from async functions
- **Message passing**: Send/receive messages between processes
- **Name registration**: Register human-readable names for processes
- **Monitoring & linking**: Detect and respond to process failures
- **Process inspection**: Query process state and statistics

## Architecture

### Layer Structure

```
┌─────────────────────────────────────┐
│         User Code                   │
│  (your gen_servers, supervisors)    │
├─────────────────────────────────────┤
│       Process API                   │
│  (process.spawn, send, receive)     │
├─────────────────────────────────────┤
│      Runtime Backend                │
│  (AsyncIOBackend, future backends)  │
├─────────────────────────────────────┤
│         Python asyncio              │
└─────────────────────────────────────┘
```

### Component Responsibilities

**Process API (`otpylib.process`)**
- High-level, BEAM-like interface
- Hides backend implementation details
- Provides familiar Erlang/Elixir-style functions

**Runtime Backend (`otpylib.runtime`)**
- Manages process lifecycle
- Implements message routing
- Handles process relationships (links/monitors)
- Tracks process registry

**AsyncIO Backend**
- Concrete implementation using asyncio
- Maps processes to asyncio.Task
- Uses asyncio.Queue for mailboxes
- Leverages ContextVar for process identity

## Process Lifecycle

### 1. Process Creation

When you call `process.spawn()`:

```python
pid = await process.spawn(my_function, args=[1, 2, 3])
```

The runtime:
1. Generates a unique process ID (PID)
2. Creates a mailbox (asyncio.Queue) if requested
3. Wraps your function with process context management
4. Spawns an asyncio.Task to run the process
5. Returns the PID immediately (non-blocking)

### 2. Process Execution

Inside the process wrapper:
- Sets the current process context (using ContextVar)
- Updates process state to RUNNING
- Executes your function
- Handles any exceptions
- Triggers exit handlers on completion

### 3. Process Termination

When a process ends (normally or via exception):
1. Exit reason is determined (NORMAL, KILLED, or exception)
2. DOWN messages sent to all monitors
3. Exit signals propagated through links
4. Process resources cleaned up
5. Name registration removed

## Message Passing

### Mailboxes

Each process can have a mailbox - an asyncio.Queue that buffers incoming messages:

```python
# Sender
await process.send("worker_1", {"cmd": "process", "data": [1, 2, 3]})

# Receiver (inside worker_1)
msg = await process.receive()  # Blocks until message available
```

### Selective Receive (Future)

The runtime will support Erlang-style selective receive:

```python
# Only receive messages matching a pattern
msg = await process.receive(match=lambda m: m.get("priority") == "high")
```

## Process Relationships

### Links

Links create bidirectional failure propagation:

```python
pid = await process.spawn_link(worker)  # Spawn and link atomically
# If either process dies abnormally, the other receives exit signal
```

Use cases:
- Dependent processes that should fail together
- Supervisor-child relationships
- Resource cleanup coordination

### Monitors

Monitors provide unidirectional failure notification:

```python
pid, ref = await process.spawn_monitor(worker)
# When worker dies, current process receives:
# ('DOWN', ref, 'process', pid, exit_reason)
```

Use cases:
- Supervisors watching children
- Request-response tracking
- Resource usage monitoring

## Name Registration

Processes can register global names for easy discovery:

```python
# In the process
await process.register("database_connection")

# From anywhere
await process.send("database_connection", query)
pid = process.whereis("database_connection")
```

Names are automatically cleaned up when processes terminate.

## Fault Tolerance

### Exit Trapping

Processes can trap exit signals to handle failures gracefully:

```python
pid = await process.spawn(supervisor, trap_exits=True)
# Now receives ('EXIT', from_pid, reason) messages instead of dying
```

### Process Isolation

Each process failure is isolated:
- No shared memory corruption
- Exceptions don't propagate beyond process boundaries
- Clean restart capability

## Backend Implementation

### AsyncIO Backend

The current implementation uses pure asyncio:

**Process → asyncio.Task mapping**
- Each process becomes an asyncio.Task
- Tasks run independently on the event loop
- No thread overhead

**Mailbox → asyncio.Queue**
- Simple, efficient message buffering
- Backpressure support via maxsize
- Async send/receive operations

**Context tracking → ContextVar**
- Thread-local process identity
- Enables `process.self()` from anywhere
- Clean context isolation

### Future Backends

The runtime protocol allows alternative implementations:
- **SPAM Backend**: For multi-core parallelism
- **Distributed Backend**: For network-distributed processes
- **Debugging Backend**: With enhanced introspection

## Usage Patterns

### Basic Worker

```python
async def worker(name: str):
    await process.register(name)
    while True:
        msg = await process.receive()
        if msg == "stop":
            break
        # Process message
        result = await handle(msg)
        await process.send(msg['reply_to'], result)
```

### Supervisor Pattern

```python
async def supervisor(children):
    # Spawn and monitor children
    monitors = {}
    for child in children:
        pid, ref = await process.spawn_monitor(child)
        monitors[ref] = (pid, child)
    
    # Handle failures
    while True:
        msg = await process.receive()
        if msg[0] == 'DOWN':
            ref = msg[1]
            if ref in monitors:
                pid, child = monitors[ref]
                # Restart child
                new_pid, new_ref = await process.spawn_monitor(child)
                monitors[new_ref] = (new_pid, child)
                del monitors[ref]
```

## Performance Characteristics

### Lightweight Processes
- Just Python objects + asyncio.Task
- Minimal memory overhead
- Fast spawn times (microseconds)

### Message Passing
- Queue-based: O(1) send/receive
- No serialization for local messages
- Bounded buffers prevent memory exhaustion

### Scalability
- Thousands of processes on single thread
- Event-driven, non-blocking I/O
- No thread context switching overhead

## Comparison with Other Systems

### vs. Python multiprocessing
- **otpylib**: Lightweight, in-process, microsecond spawns
- **multiprocessing**: Heavy OS processes, IPC overhead, millisecond spawns

### vs. Python threading
- **otpylib**: No GIL contention, message passing only
- **threading**: GIL limited, shared memory complications

### vs. Actor frameworks (Pykka, Thespian)
- **otpylib**: OTP patterns, BEAM semantics, asyncio native
- **Others**: Custom patterns, various async models

### vs. Erlang/Elixir
- **otpylib**: Python ecosystem, asyncio integration, familiar syntax
- **BEAM**: True parallelism, distributed by default, battle-tested

## Limitations

1. **Single-threaded** (currently): All processes run on one event loop
2. **No selective receive** (yet): Must receive messages in order
3. **No distribution** (yet): Only local processes
4. **Python GIL**: CPU-bound work still GIL-limited

## Future Roadmap

- Selective receive with pattern matching
- Distributed process support
- Multi-core SPAM backend
- Process hibernation
- ETS-like tables
- Hot code reloading

## Summary

The otpylib runtime brings Erlang's proven process model to Python, enabling robust concurrent systems without the complexity of threads or the overhead of OS processes. By building on asyncio, it integrates naturally with Python's async ecosystem while providing the isolation and fault tolerance that make Erlang/Elixir systems so reliable.
