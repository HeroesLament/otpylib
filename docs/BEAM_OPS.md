# OTPyLib Runtime Manual: Working with Raw Processes

## Introduction

This guide shows how to work directly with the OTPyLib runtime backend without using higher-level abstractions like gen_server or supervisors. This is useful for understanding how the runtime works, debugging issues, or building custom process behaviors.

Think of this as working with BEAM's raw processes instead of OTP behaviors - powerful but requiring more manual management.

## Basic Setup

```python
import asyncio
from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend
from otpylib.runtime.atoms import EXIT, DOWN, NORMAL, KILLED
# Note: In actual otpylib code, you'd import these atoms

async def main():
    # Create and initialize the runtime
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    # Your process code here
    
    # Cleanup
    await runtime.shutdown()

# Run the example
asyncio.run(main())
```

## Core Concepts

### What is a Process?

In OTPyLib (like BEAM/Erlang):
- A **process** is a lightweight, isolated unit of computation
- Each process has its own **mailbox** for receiving messages
- Processes communicate only through **message passing**
- Process failure is isolated - one crash doesn't bring down others

### Process Lifecycle

1. **Spawning** - Process is created and starts running
2. **Running** - Process executes its function
3. **Terminating** - Process exits (normally or due to error)
4. **Cleanup** - Runtime removes process and notifies linked/monitoring processes

## Spawning Processes

### Basic Process Spawn

```python
async def simple_process():
    """A basic process that just prints and exits."""
    print(f"Process {runtime.self()} is running!")
    # Process exits normally when function returns

async def main():
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    # Spawn a simple process
    pid = await runtime.spawn(simple_process)
    print(f"Spawned process: {pid}")
    
    # Give it time to run
    await asyncio.sleep(0.1)
    
    await runtime.shutdown()
```

### Process with Arguments

```python
async def worker_process(work_id: int, work_type: str):
    """Process that receives arguments."""
    print(f"Worker {runtime.self()} processing {work_type} job #{work_id}")
    await asyncio.sleep(0.5)  # Simulate work
    print(f"Worker {runtime.self()} completed job #{work_id}")

async def main():
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    # Spawn multiple workers with different arguments
    workers = []
    for i in range(3):
        pid = await runtime.spawn(
            worker_process,
            args=[i],
            kwargs={'work_type': 'analysis'}
        )
        workers.append(pid)
    
    # Wait for all to complete
    await asyncio.sleep(1.0)
    
    # Check which are still alive
    for pid in workers:
        alive = runtime.is_alive(pid)
        print(f"Process {pid} alive: {alive}")
    
    await runtime.shutdown()
```

## Message Passing

### Sending and Receiving Messages

```python
async def echo_server():
    """Process that echoes back messages."""
    print(f"Echo server {runtime.self()} starting...")
    
    while True:
        try:
            # Wait for a message (with timeout to allow shutdown)
            message = await runtime.receive(timeout=1.0)
            print(f"Echo server received: {message}")
            
            # Echo back if it's a tuple with sender
            if isinstance(message, tuple) and len(message) == 2:
                sender, content = message
                await runtime.send(sender, f"echo: {content}")
                
        except asyncio.TimeoutError:
            continue  # Check if we should keep running
        except Exception as e:
            print(f"Echo server error: {e}")
            break

async def client_process(server_pid):
    """Process that sends messages to echo server."""
    my_pid = runtime.self()
    
    # Send a message with our PID for reply
    await runtime.send(server_pid, (my_pid, "Hello, server!"))
    
    # Wait for response
    response = await runtime.receive(timeout=2.0)
    print(f"Client received response: {response}")

async def main():
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    # Start echo server
    server_pid = await runtime.spawn(echo_server)
    await asyncio.sleep(0.1)  # Let server start
    
    # Start client
    await runtime.spawn(client_process, args=[server_pid])
    
    # Let them communicate
    await asyncio.sleep(1.0)
    
    # Stop server
    await runtime.exit(server_pid, 'shutdown')
    
    await runtime.shutdown()
```

## Process Registry

### Registering Named Processes

```python
# Import or create atoms for message protocols
from otpylib.runtime.atoms import atom
PING = atom.ensure("ping")
STOP = atom.ensure("stop")

async def named_service():
    """A process that registers itself with a name."""
    # Register ourselves with a well-known name
    await runtime.register("database")
    print(f"Database service started as {runtime.self()}")
    
    while True:
        try:
            message = await runtime.receive(timeout=1.0)
            
            if message == PING:
                print("Database: pong!")
            elif message == STOP:
                print("Database: shutting down...")
                break
                
        except asyncio.TimeoutError:
            continue

async def client():
    """Client that uses named process."""
    # Find process by name instead of PID
    db_pid = runtime.whereis("database")
    
    if db_pid:
        await runtime.send("database", PING)  # Send atom object
        await asyncio.sleep(0.1)
        await runtime.send("database", STOP)
    else:
        print("Database service not found!")

async def main():
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    # Start service
    await runtime.spawn(named_service)
    await asyncio.sleep(0.1)  # Let it register
    
    # Start client
    await runtime.spawn(client)
    
    await asyncio.sleep(1.0)
    
    # Show all registered names
    print(f"Registered processes: {runtime.registered()}")
    
    await runtime.shutdown()
```

## Process Linking

### Bidirectional Links

When processes are linked, if one exits abnormally, the other is terminated too (unless it's trapping exits).

```python
async def parent_process():
    """Parent that spawns and links to a child."""
    print(f"Parent {runtime.self()} starting...")
    
    # Spawn and link to child
    child_pid = await runtime.spawn_link(child_process)
    print(f"Parent linked to child {child_pid}")
    
    # Wait a bit
    await asyncio.sleep(0.5)
    
    # If child crashes, we'll be terminated too
    print("Parent: still running after child crashed!")
    await asyncio.sleep(1.0)

async def child_process():
    """Child that will crash."""
    print(f"Child {runtime.self()} starting...")
    await asyncio.sleep(0.2)
    
    print("Child: about to crash!")
    raise Exception("Child process error!")

async def main():
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    parent_pid = await runtime.spawn(parent_process)
    
    # Wait to see what happens
    await asyncio.sleep(2.0)
    
    # Check if parent is still alive
    if runtime.is_alive(parent_pid):
        print("Parent survived (unexpected!)")
    else:
        print("Parent was terminated due to linked child crash")
    
    await runtime.shutdown()
```

### Trapping Exits

```python
async def supervisor_process():
    """Process that traps exits to handle failures gracefully."""
    print(f"Supervisor {runtime.self()} starting with trap_exits=True")
    
    # Spawn and link to workers
    worker1 = await runtime.spawn_link(worker, args=["worker1", 0.3])
    worker2 = await runtime.spawn_link(worker, args=["worker2", 0.5])
    
    print(f"Supervisor linked to workers: {worker1}, {worker2}")
    
    # Handle exit signals as messages
    while True:
        try:
            message = await runtime.receive(timeout=2.0)
            print(f"Supervisor received: {message}")
            
            # Exit messages arrive as (EXIT, pid, reason)
            if isinstance(message, tuple) and message[0] == EXIT:
                _, failed_pid, reason = message
                print(f"Supervisor: Worker {failed_pid} exited with: {reason}")
                
                # Could restart the worker here
                
        except asyncio.TimeoutError:
            break

async def worker(name: str, crash_after: float):
    """Worker that crashes after some time."""
    print(f"{name} ({runtime.self()}) starting...")
    await asyncio.sleep(crash_after)
    raise Exception(f"{name} encountered an error!")

async def main():
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    # Spawn supervisor with trap_exits enabled
    await runtime.spawn(supervisor_process, trap_exits=True)
    
    # Let everything run
    await asyncio.sleep(3.0)
    
    await runtime.shutdown()
```

## Process Monitoring

### Unidirectional Monitoring

Unlike links, monitors are one-way and don't cause cascading termination.

```python
async def monitor_process():
    """Process that monitors other processes."""
    print(f"Monitor {runtime.self()} starting...")
    
    # Start some workers to monitor
    workers = {}
    for i in range(3):
        pid = await runtime.spawn(monitored_worker, args=[i])
        ref = await runtime.monitor(pid)
        workers[ref] = pid
        print(f"Monitoring worker {pid} with ref {ref}")
    
    # Wait for DOWN messages
    down_count = 0
    while down_count < 3:
        message = await runtime.receive()
        
        # DOWN messages arrive as (DOWN, ref, pid, reason)
        if isinstance(message, tuple) and message[0] == DOWN:
            _, ref, pid, reason = message
            print(f"Worker {pid} went down: {reason}")
            down_count += 1
    
    print("All workers have terminated")

async def monitored_worker(worker_id: int):
    """Worker that runs for a random time then exits."""
    runtime_ms = (worker_id + 1) * 200
    print(f"Worker {worker_id} running for {runtime_ms}ms...")
    await asyncio.sleep(runtime_ms / 1000)
    
    if worker_id == 1:
        raise Exception(f"Worker {worker_id} error!")
    
    print(f"Worker {worker_id} completed")

async def main():
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    await runtime.spawn(monitor_process)
    
    # Let everything run
    await asyncio.sleep(2.0)
    
    await runtime.shutdown()
```

## Advanced Patterns

### Request-Reply Pattern

```python
# Define atoms for our protocol
from otpylib.runtime.atoms import atom
ADD = atom.ensure("add")
MULTIPLY = atom.ensure("multiply")
DIVIDE = atom.ensure("divide")
REPLY = atom.ensure("reply")
ERROR = atom.ensure("error")

async def server():
    """Server that handles requests and sends replies."""
    await runtime.register("calc_server")
    print("Calculator server ready")
    
    while True:
        message = await runtime.receive()
        
        if isinstance(message, tuple) and len(message) == 3:
            sender, op, args = message
            
            try:
                if op == ADD:
                    result = sum(args)
                elif op == MULTIPLY:
                    result = 1
                    for arg in args:
                        result *= arg
                else:
                    result = (ERROR, f"Unknown operation: {op}")
                
                await runtime.send(sender, (REPLY, result))
                
            except Exception as e:
                await runtime.send(sender, (ERROR, str(e)))

async def client():
    """Client making requests to server."""
    my_pid = runtime.self()
    
    # Make requests using atoms
    requests = [
        (ADD, [1, 2, 3, 4]),
        (MULTIPLY, [2, 3, 4]),
        (DIVIDE, [10, 2])  # This will error (unknown op)
    ]
    
    for op, args in requests:
        await runtime.send("calc_server", (my_pid, op, args))
        
        reply = await runtime.receive(timeout=1.0)
        if reply[0] == REPLY:
            print(f"{op.name}{args} = {reply[1]}")
        else:
            print(f"{op.name}{args} failed: {reply[1]}")

async def main():
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    await runtime.spawn(server)
    await asyncio.sleep(0.1)
    
    await runtime.spawn(client)
    
    await asyncio.sleep(1.0)
    await runtime.shutdown()
```

### Process Pool Pattern

```python
# Define atoms for pool protocol
REQUEST = atom.ensure("request")
WORKER_DONE = atom.ensure("worker_done")

async def pool_manager(pool_size: int):
    """Manages a pool of worker processes."""
    await runtime.register("pool_manager")
    
    # Create worker pool
    workers = []
    available = asyncio.Queue()
    
    for i in range(pool_size):
        pid = await runtime.spawn(pool_worker, args=[i])
        workers.append(pid)
        await available.put(pid)
    
    print(f"Pool manager started with {pool_size} workers")
    
    while True:
        message = await runtime.receive()
        
        if isinstance(message, tuple) and message[0] == REQUEST:
            client_pid, work = message[1], message[2]
            
            # Get available worker
            worker_pid = await available.get()
            
            # Send work to worker
            await runtime.send(worker_pid, (client_pid, work))
            
        elif isinstance(message, tuple) and message[0] == WORKER_DONE:
            worker_pid = message[1]
            # Return worker to available pool
            await available.put(worker_pid)

async def pool_worker(worker_id: int):
    """Worker in the pool."""
    my_pid = runtime.self()
    
    while True:
        client_pid, work = await runtime.receive()
        
        print(f"Worker {worker_id} processing: {work}")
        await asyncio.sleep(0.5)  # Simulate work
        
        # Send result to client
        await runtime.send(client_pid, f"Result of {work} from worker {worker_id}")
        
        # Notify manager we're available
        await runtime.send("pool_manager", (WORKER_DONE, my_pid))

async def pool_client(job_id: int):
    """Client submitting work to pool."""
    my_pid = runtime.self()
    
    # Submit work
    await runtime.send("pool_manager", (REQUEST, my_pid, f"job_{job_id}"))
    
    # Wait for result
    result = await runtime.receive(timeout=2.0)
    print(f"Client received: {result}")

async def main():
    runtime = AsyncIOBackend()
    await runtime.initialize()
    
    # Start pool
    await runtime.spawn(pool_manager, args=[3])
    await asyncio.sleep(0.1)
    
    # Submit multiple jobs
    for i in range(5):
        await runtime.spawn(pool_client, args=[i])
        await asyncio.sleep(0.1)  # Stagger submissions
    
    await asyncio.sleep(3.0)
    await runtime.shutdown()
```

## Best Practices

### 1. Always Handle Timeouts

```python
async def robust_receiver():
    while True:
        try:
            message = await runtime.receive(timeout=1.0)
            # Process message
        except asyncio.TimeoutError:
            # Check if we should continue
            if should_shutdown():
                break
```

### 2. Clean Process Termination

```python
# Define atom for shutdown protocol
SHUTDOWN = atom.ensure("shutdown")

async def graceful_process():
    try:
        while True:
            message = await runtime.receive()
            if message == SHUTDOWN:
                # Cleanup resources
                await cleanup()
                break
            # Handle other messages
    finally:
        # Always runs, even on crash
        print(f"Process {runtime.self()} terminating")
```

### 3. Error Isolation

```python
async def isolated_process():
    """Process that handles errors without crashing."""
    while True:
        try:
            message = await runtime.receive()
            # Dangerous operation
            result = process_message(message)
            
        except SpecificError as e:
            # Log and continue
            print(f"Handled error: {e}")
            
        except Exception as e:
            # Log and possibly exit
            print(f"Unexpected error: {e}")
            raise  # Let supervisor handle
```

### 4. Process Discovery

```python
async def discoverable_service():
    """Service that can be found by name."""
    service_name = "my_service_v1"
    
    # Check if already registered
    if runtime.whereis(service_name):
        print(f"Service {service_name} already running")
        return
    
    await runtime.register(service_name)
    
    # Service loop...
```

## Common Pitfalls

1. **Forgetting mailbox=True**: Processes without mailboxes can't receive messages
2. **Not handling timeouts**: Infinite receive() calls can hang
3. **Ignoring exit signals**: Not using trap_exits when needed
4. **Synchronous thinking**: Remember everything is concurrent
5. **Resource leaks**: Not cleaning up in finally blocks

## Debugging Tips

### Process Inspection

```python
# Get process info
info = runtime.process_info(pid)
print(f"Process {pid}:")
print(f"  State: {info.state}")
print(f"  Name: {info.name}")
print(f"  Created: {info.created_at}")
print(f"  Trap exits: {info.trap_exits}")

# List all processes
all_pids = runtime.processes()
print(f"Active processes: {len(all_pids)}")

# Check registration
registered = runtime.registered()
print(f"Named processes: {registered}")
```

### Runtime Statistics

```python
stats = runtime.statistics()
print(f"Runtime stats:")
print(f"  Uptime: {stats.uptime_seconds}s")
print(f"  Total spawned: {stats.total_spawned}")
print(f"  Active processes: {stats.active_processes}")
print(f"  Messages sent: {stats.messages_processed}")
print(f"  Active monitors: {stats.active_monitors}")
print(f"  Active links: {stats.active_links}")
```

## Conclusion

Working directly with the runtime gives you full control over process behavior, but requires manual management of:

- Message protocols
- Error handling  
- Process supervision
- State management

For production applications, you'll typically want to use higher-level abstractions like gen_server and supervisors, but understanding the runtime layer is essential for:

- Debugging complex issues
- Building custom behaviors
- Performance optimization
- Understanding OTP design principles

The runtime provides the foundation - solid, concurrent, fault-tolerant processes - upon which all of OTP is built.