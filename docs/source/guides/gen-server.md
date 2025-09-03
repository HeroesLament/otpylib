# GenServer - Stateful processes with RPC communication

**anyio** provides a mechanism to run concurrent tasks and communicate between them.

The **otpylib** GenServer is an abstraction for building stateful processes with
synchronous and asynchronous message passing. This abstraction can be used without 
the rest of **otpylib**.

In this tutorial, we'll see how it works.

## Initializing the mailbox registry

This step is done automatically when a node starts, but it is required if you
want to use GenServer standalone:

```python
from otpylib import mailbox
import anyio


async def main():
    mailbox._init()


anyio.run(main)
```

## Creating a GenServer

A GenServer requires a set of callback functions that define its behavior:

```python
import types
from otpylib import gen_server


def create_callbacks():
    """Create gen_server callbacks namespace."""
    callbacks = types.SimpleNamespace()
    
    async def init(initial_state):
        # Initialize your state here
        return initial_state
    
    async def handle_call(message, caller, state):
        # Handle synchronous calls
        return (gen_server.Reply(payload="response"), state)
    
    async def handle_cast(message, state):
        # Handle asynchronous casts
        return (gen_server.NoReply(), state)
    
    async def handle_info(message, state):
        # Handle direct mailbox messages
        return (gen_server.NoReply(), state)
    
    async def terminate(reason, state):
        # Cleanup on termination
        pass
    
    callbacks.init = init
    callbacks.handle_call = handle_call
    callbacks.handle_cast = handle_cast
    callbacks.handle_info = handle_info
    callbacks.terminate = terminate
    
    return callbacks
```

## Starting a GenServer

You can start a GenServer with or without a registered name:

```python
async def start_anonymous():
    callbacks = create_callbacks()
    initial_state = {}
    mid = await gen_server.start(callbacks, initial_state)
    return mid
```

Or with a registered name:

```python
async def start_named():
    callbacks = create_callbacks()
    initial_state = {}
    await gen_server.start(callbacks, initial_state, name='my_server')
```

## Sending and receiving messages

### Synchronous calls (call)

Use `call` when you need a response from the GenServer:

```python
from otpylib import gen_server
import anyio


async def counter_server():
    """A simple counter GenServer."""
    callbacks = types.SimpleNamespace()
    
    async def init(start_value):
        return start_value
    
    async def handle_call(message, caller, count):
        match message:
            case "get":
                return (gen_server.Reply(payload=count), count)
            case ("add", n):
                new_count = count + n
                return (gen_server.Reply(payload=new_count), new_count)
            case _:
                return (gen_server.Reply(payload=None), count)
    
    callbacks.init = init
    callbacks.handle_call = handle_call
    callbacks.handle_cast = lambda msg, state: (gen_server.NoReply(), state)
    callbacks.handle_info = lambda msg, state: (gen_server.NoReply(), state)
    callbacks.terminate = lambda reason, state: None
    
    await gen_server.start(callbacks, 0, name='counter')


async def client():
    # Get current value
    value = await gen_server.call('counter', 'get')
    print(f"Current count: {value}")
    
    # Add to counter
    new_value = await gen_server.call('counter', ('add', 5))
    print(f"New count: {new_value}")


async def main():
    mailbox._init()
    
    async with anyio.create_task_group() as tg:
        tg.start_soon(counter_server)
        await anyio.sleep(0.1)  # Let server start
        await client()


anyio.run(main)
```

### Asynchronous casts (cast)

Use `cast` when you don't need a response:

```python
async def logger_server():
    """A simple logging GenServer."""
    callbacks = types.SimpleNamespace()
    
    async def init(_):
        return []  # Store log messages
    
    async def handle_cast(message, logs):
        match message:
            case ("log", text):
                logs.append(text)
                print(f"Logged: {text}")
                return (gen_server.NoReply(), logs)
            case "clear":
                return (gen_server.NoReply(), [])
            case _:
                return (gen_server.NoReply(), logs)
    
    callbacks.init = init
    callbacks.handle_call = lambda msg, caller, state: (gen_server.Reply(payload=state), state)
    callbacks.handle_cast = handle_cast
    callbacks.handle_info = lambda msg, state: (gen_server.NoReply(), state)
    callbacks.terminate = lambda reason, state: None
    
    await gen_server.start(callbacks, None, name='logger')


async def client():
    # Fire and forget logging
    await gen_server.cast('logger', ('log', 'Application started'))
    await gen_server.cast('logger', ('log', 'Processing request'))
    
    # Check logs
    logs = await gen_server.call('logger', 'get_logs')
    print(f"All logs: {logs}")
```

## Complete example

Here's a complete key-value store example:

```python
from otpylib import gen_server, mailbox
import anyio
import types


class KVStore:
    """A key-value store GenServer with clean API."""
    
    @staticmethod
    def create_callbacks():
        callbacks = types.SimpleNamespace()
        
        async def init(_):
            return {}  # Empty dict as initial state
        
        async def handle_call(message, caller, state):
            match message:
                case ("get", key):
                    value = state.get(key)
                    return (gen_server.Reply(payload=value), state)
                case ("set", key, value):
                    old_value = state.get(key)
                    state[key] = value
                    return (gen_server.Reply(payload=old_value), state)
                case "get_all":
                    return (gen_server.Reply(payload=dict(state)), state)
                case _:
                    return (gen_server.Reply(payload=None), state)
        
        async def handle_cast(message, state):
            match message:
                case ("delete", key):
                    state.pop(key, None)
                case "clear":
                    state.clear()
            return (gen_server.NoReply(), state)
        
        callbacks.init = init
        callbacks.handle_call = handle_call
        callbacks.handle_cast = handle_cast
        callbacks.handle_info = lambda msg, state: (gen_server.NoReply(), state)
        callbacks.terminate = lambda reason, state: None
        
        return callbacks
    
    @staticmethod
    async def start(name='kv_store'):
        callbacks = KVStore.create_callbacks()
        await gen_server.start(callbacks, None, name=name)
    
    @staticmethod
    async def get(key, server='kv_store'):
        return await gen_server.call(server, ('get', key))
    
    @staticmethod
    async def set(key, value, server='kv_store'):
        return await gen_server.call(server, ('set', key, value))
    
    @staticmethod
    async def delete(key, server='kv_store'):
        await gen_server.cast(server, ('delete', key))
    
    @staticmethod
    async def get_all(server='kv_store'):
        return await gen_server.call(server, 'get_all')


async def main():
    mailbox._init()
    
    async with anyio.create_task_group() as tg:
        # Start the KV store
        tg.start_soon(KVStore.start)
        await anyio.sleep(0.1)
        
        # Use the KV store
        await KVStore.set('name', 'Alice')
        await KVStore.set('age', 30)
        
        name = await KVStore.get('name')
        print(f"Name: {name}")
        
        all_data = await KVStore.get_all()
        print(f"All data: {all_data}")
        
        await KVStore.delete('age')
        all_data = await KVStore.get_all()
        print(f"After delete: {all_data}")


anyio.run(main)
```

## Advanced features

### Delayed replies

Sometimes you need to reply to a call asynchronously:

```python
async def handle_call(message, caller, state):
    match message:
        case ("slow_operation", task_group):
            async def process_later():
                await anyio.sleep(1)  # Simulate slow work
                result = "completed"
                await gen_server.reply(caller, result)
            
            task_group.start_soon(process_later)
            return (gen_server.NoReply(), state)
```

### Stopping a GenServer

You can stop a GenServer gracefully:

```python
async def handle_call(message, caller, state):
    match message:
        case "stop":
            return (gen_server.Stop(), state)
        case "stop_with_error":
            error = RuntimeError("Intentional stop")
            return (gen_server.Stop(error), state)
```

### Handling timeouts

Calls can have timeouts:

```python
try:
    result = await gen_server.call('my_server', 'slow_request', timeout=1.0)
except TimeoutError:
    print("Request timed out")
```