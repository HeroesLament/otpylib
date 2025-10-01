# GenServer Operations

## Overview

GenServer (Generic Server) implements the client-server pattern in otpylib, providing a standardized way to build stateful server processes. Built on top of the process API and runtime system, it abstracts common patterns for request-response (call), fire-and-forget (cast), and general message handling (info).

## Architecture

### System Layers

```
┌─────────────────────────────────────┐
│        User GenServer Module         │
│     (callbacks: init, handle_*)      │
├─────────────────────────────────────┤
│         GenServer Core               │
│  (call/cast/reply, message routing)  │
├─────────────────────────────────────┤
│          Process API                 │
│   (spawn, send, receive, register)   │
├─────────────────────────────────────┤
│       AsyncIO Runtime Backend        │
│  (Task management, mailbox queues)   │
├─────────────────────────────────────┤
│         Python asyncio               │
└─────────────────────────────────────┘
```

## Theory of Operation

### Process Model

Each GenServer runs as an independent process with:
- **Isolated state**: No shared memory with other processes
- **Message queue**: Serialized message processing
- **Lifecycle management**: Clean startup and termination
- **Name registration**: Optional global name for discovery

### Message Types

GenServer distinguishes three message categories:

1. **Call** - Synchronous request/response
   - Client blocks waiting for reply
   - Timeout support
   - Exception propagation

2. **Cast** - Asynchronous notification
   - Fire-and-forget semantics
   - No response expected
   - Non-blocking to sender

3. **Info** - Direct process messages
   - Bypass GenServer protocol
   - System messages (DOWN, EXIT)
   - Custom protocols

## Implementation Details

### Starting a GenServer

```python
async def start(module, init_arg=None, name=None) -> str:
```

When you start a GenServer:

1. **Process spawning**: Creates new process via `process.spawn()`
2. **Initialization**: Calls `module.init(init_arg)` to get initial state
3. **Name registration**: Optional global name via `process.register()`
4. **Message loop**: Enters receive loop waiting for messages
5. **Returns PID**: Immediately returns process ID to caller

### Message Flow

#### Call Flow (Synchronous)

```
Client                GenServer
  |                      |
  |------ Call Msg ----->|
  |    (with call_id)    |
  |                      | handle_call()
  |                      | process message
  |<----- Reply ---------|
  |    (with call_id)    |
  |                      |
```

1. **Client side**:
   - Generates unique call_id
   - Sends `_CallMessage` with payload and reply_to PID
   - Blocks on receive with call_id matching
   
2. **Server side**:
   - Receives `_CallMessage`
   - Calls `handle_call(payload, reply_fn, state)`
   - Sends tagged reply back to caller

3. **Bridge process** (for non-process callers):
   - Spawns temporary process
   - Makes call from process context
   - Returns result via asyncio.Future

#### Cast Flow (Asynchronous)

```
Client                GenServer
  |                      |
  |------ Cast Msg ----->|
  |                      |
  |    (returns)         | handle_cast()
  |                      | process message
  |                      |
```

- Client sends and immediately returns
- Server processes when ready
- No reply mechanism

#### Info Flow (Direct)

```
Sender                GenServer
  |                      |
  |------ Any Msg ------>|
  |                      |
  |                      | handle_info()
  |                      | process message
  |                      |
```

- Any process can send via `process.send()`
- Useful for system messages
- Custom protocols between processes

### State Management

GenServer maintains state across messages:

```python
# Initial state from init
state = await module.init(init_arg)

# Each handler returns new state
result, new_state = await handle_call(msg, caller, state)
state = new_state  # Update for next message
```

State is:
- **Private**: Only this GenServer can access
- **Persistent**: Survives between messages
- **Mutable**: Can be updated by handlers
- **Clean**: No shared memory issues

### Callback Interface

User modules implement callbacks:

```python
async def init(init_arg) -> State:
    """Initialize state."""
    
async def handle_call(message, reply_fn, state) -> (Reply, State):
    """Handle synchronous requests."""
    
async def handle_cast(message, state) -> (NoReply, State):
    """Handle async messages."""
    
async def handle_info(message, state) -> (NoReply, State):
    """Handle other messages."""
    
async def terminate(reason, state) -> None:
    """Cleanup on exit."""
```

Return values control flow:
- `Reply(value)` - Send response and continue
- `NoReply()` - Continue without replying
- `Stop(reason)` - Terminate GenServer

### Error Handling

GenServer provides structured error handling:

1. **Handler exceptions**:
   - Caught and logged
   - terminate() callback invoked
   - Process terminates

2. **Call timeouts**:
   - Caller gets TimeoutError
   - Server continues processing

3. **Process crashes**:
   - Links/monitors notified
   - State lost (unless supervised)

## Bridge Pattern

The bridge pattern enables calling GenServer from non-process contexts:

```python
# Outside process context
result = await gen_server.call("counter", "get")
# Creates temporary bridge process internally

# Inside process context  
result = await gen_server.call("counter", "get")
# Direct process-to-process communication
```

This provides seamless integration between:
- Regular async functions (non-process)
- Process-based code
- Interactive REPL usage

## Atoms in GenServer

GenServer uses atoms for state and event tracking:

### Lifecycle States
- `INITIALIZING` - During init()
- `RUNNING` - Main message loop
- `WAITING_FOR_MESSAGE` - Blocked on receive
- `PROCESSING_MESSAGE` - Handler executing
- `STOPPING` - Termination initiated
- `TERMINATED` - Process ended

### Message Types
- `CALL` - Synchronous request
- `CAST` - Asynchronous message
- `INFO` - Direct message

## Performance Characteristics

### Throughput
- **Message processing**: Sequential (one at a time)
- **Call overhead**: Process context switch + message passing
- **Cast overhead**: Just message send
- **Mailbox**: Bounded queue prevents overflow

### Latency
- **Call**: Round-trip message passing (~microseconds locally)
- **Cast**: One-way message (~microseconds)
- **Spawn**: Process creation (~milliseconds)

### Scalability
- **Process count**: Thousands viable on single thread
- **State size**: Limited by Python memory
- **Message size**: No built-in limits (memory bound)

## Comparison with Erlang/Elixir GenServer

### Similarities
- Same callback structure
- Message type distinction (call/cast/info)
- State management pattern
- Process isolation

### Differences
- **Python types**: Uses dataclasses vs tuples
- **Pattern matching**: Python match/case vs Erlang patterns
- **Error handling**: Exceptions vs error tuples
- **Concurrency**: Single-threaded asyncio vs BEAM scheduler

## Common Patterns

### Request-Response Server

```python
async def handle_call(message, reply_fn, state):
    match message:
        case ("get", key):
            value = state.get(key)
            return (Reply(value), state)
        case ("set", key, value):
            state[key] = value
            return (Reply("ok"), state)
```

### Event Processor

```python
async def handle_cast(message, state):
    match message:
        case ("event", event_type, data):
            state["events"].append((event_type, data))
            if len(state["events"]) > 100:
                await process_batch(state["events"])
                state["events"] = []
    return (NoReply(), state)
```

### Delayed Reply

```python
async def handle_call(message, reply_fn, state):
    match message:
        case ("slow_operation", data):
            # Spawn task for slow work
            asyncio.create_task(slow_work(data, reply_fn))
            return (NoReply(), state)  # Don't reply now
            
async def slow_work(data, reply_fn):
    result = await expensive_computation(data)
    await reply_fn(result)  # Reply when done
```

## Best Practices

1. **Keep handlers fast**: Don't block the message loop
2. **State immutability**: Prefer creating new state over mutation
3. **Error isolation**: Let it crash, supervisor restarts
4. **Timeout calls**: Always use timeouts for remote calls
5. **Clean termination**: Implement terminate() for cleanup

## Debugging

### Process Inspection

```python
# Check if GenServer is alive
if process.is_alive(pid):
    print(f"GenServer {pid} is running")

# Get process list
all_pids = process.processes()

# Find by name
pid = process.whereis("counter")
```

### Message Tracing

Add logging to handlers:
```python
async def handle_call(message, reply_fn, state):
    logger.debug(f"Call: {message}")
    result = process_message(message, state)
    logger.debug(f"Reply: {result}")
    return result
```

## Limitations

1. **No selective receive**: Messages processed in order
2. **Single-threaded**: CPU-bound work blocks process
3. **No distribution**: Local processes only (currently)
4. **Memory state**: State lost on crash without supervisor

## Future Enhancements

- Hot code reloading
- Distributed GenServer (network transparency)
- State persistence hooks
- Built-in telemetry/metrics
- Selective receive patterns

## Summary

GenServer provides a robust abstraction for building stateful server processes in Python. By combining process isolation, message passing, and standardized callbacks, it enables reliable concurrent systems without the complexity of locks and shared memory. The integration with the process API and runtime system creates a BEAM-like environment where thousands of independent servers can coexist efficiently on a single Python thread.
