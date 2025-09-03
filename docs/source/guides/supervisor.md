# OTPyLib Supervisor API Documentation

## Overview

The `otpylib.supervisor` module provides a static supervisor for managing persistent, long-running processes in Python asyncio applications. It implements Erlang/OTP supervision patterns with automatic ping/pong health monitoring for GenServer children.

The supervisor is designed to manage services that should continuously run and be restarted when they fail - things like web servers, database connections, message processors, etc.

## Core Classes and Data Structures

### `child_spec`

Defines the specification for a child process to be supervised.

```python
@dataclass
class child_spec:
    id: str
    task: Callable[..., Awaitable[None]]
    args: List[Any]
    restart: RestartStrategy = Permanent()
    shutdown: ShutdownStrategy = TimedShutdown(5000)
    health_check_enabled: bool = True
    health_check_interval: float = 30.0
    health_check_timeout: float = 5.0
```

**Parameters:**
- `id` (str): Unique identifier for the child process
- `task` (Callable): The async function to run as the child process
- `args` (List[Any]): Arguments to pass to the task function
- `restart` (RestartStrategy): When to restart the child (default: `Permanent()`)
- `shutdown` (ShutdownStrategy): How to shutdown the child (default: `TimedShutdown(5000)`)
- `health_check_enabled` (bool): Enable automatic ping/pong health checks (default: True)
- `health_check_interval` (float): Interval between health checks in seconds (default: 30.0)
- `health_check_timeout` (float): Health check timeout in seconds (default: 5.0)

### `options`

Configuration options for the supervisor.

```python
@dataclass
class options:
    max_restarts: int = 3
    max_seconds: int = 5
    strategy: SupervisorStrategy = OneForOne()
    shutdown_strategy: ShutdownStrategy = TimedShutdown(5000)
```

**Parameters:**
- `max_restarts` (int): Maximum restarts allowed within `max_seconds` (default: 3)
- `max_seconds` (int): Time window for restart limit in seconds (default: 5)
- `strategy` (SupervisorStrategy): Supervision strategy (default: `OneForOne()`)
- `shutdown_strategy` (ShutdownStrategy): How to shutdown the supervisor (default: `TimedShutdown(5000)`)

## Supervision Strategies

### `OneForOne()`
Only the failed child is restarted. Other children continue running normally.

### `OneForAll()`
When any child fails, all children are terminated and restarted.

### `RestForOne()`
When a child fails, that child and all children started after it are terminated and restarted.

## Restart Strategies

### `Permanent()`
Child is always restarted, regardless of how it terminates.

### `Transient()`
Child is restarted only if it terminates abnormally (with an exception). Normal completion does not trigger a restart.

## Main API

### `start(child_specs, opts, *, task_status)`

Start the supervisor with the given children and strategy.

```python
async def start(
    child_specs: List[child_spec],
    opts: options,
    *,
    task_status: anyio.abc.TaskStatus,
) -> None
```

**Parameters:**
- `child_specs` (List[child_spec]): List of child specifications to supervise
- `opts` (options): Supervisor configuration options
- `task_status` (anyio.abc.TaskStatus): Task status for anyio structured concurrency

**Returns:**
- Returns a `SupervisorHandle` via `task_status.started(handle)`

**Example Usage (Internal Worker Supervision):**
```python
import anyio
from otpylib import gen_server, supervisor
from otpylib.supervisor import child_spec, options
from otpylib.types import Permanent, OneForOne

# Worker that uses internal OTP supervision
async def start_worker(*, task_status: anyio.abc.TaskStatus):
    """Start worker with internal GenServer supervision."""
    
    # Define supervised GenServer child
    genserver_spec = child_spec(
        id="worker_genserver",
        task=gen_server.start,
        args=[worker_callbacks, init_state, "worker_server"],
        restart=Permanent(),
        health_check_enabled=True,  # Automatic ping/pong monitoring
        health_check_interval=30.0,
        health_check_timeout=5.0
    )
    
    supervisor_opts = options(
        max_restarts=3,
        max_seconds=60,
        strategy=OneForOne()
    )
    
    # Start internal supervision
    await supervisor.start([genserver_spec], supervisor_opts, task_status=task_status)

# Application level - start the self-supervising worker
async def main():
    async with anyio.create_task_group() as tg:
        worker_handle = await tg.start(start_worker)
        # Worker is now running with internal OTP supervision
```

## SupervisorHandle

Handle for controlling and monitoring a running supervisor.

### Methods

#### `get_child_status(child_id: str) -> Optional[_ChildProcess]`
Get the runtime status of a specific child.

#### `list_children() -> List[str]`
Get list of all child IDs being supervised.

#### `get_restart_count(child_id: str) -> int`
Get the restart count for a specific child.

#### `get_health_status(child_id: str) -> Dict[str, Any]`
Get health check status for a child. Returns a dictionary with:
- `health_check_failures`: Number of consecutive health check failures
- `last_health_check`: Timestamp of last health check
- `health_check_enabled`: Whether health checks are enabled

#### `is_shutting_down() -> bool`
Check if the supervisor is in the process of shutting down.

#### `async shutdown()`
Initiate graceful supervisor shutdown.

## Health Monitoring

The supervisor includes automatic ping/pong health monitoring for GenServer children:

### Automatic Detection
The supervisor automatically detects GenServer children based on:
- Child spec args structure (expects GenServer.start pattern with callbacks, init_arg, name)
- Function signature matching

### Ping/Pong Protocol
For GenServer children with health monitoring enabled:
- Supervisor sends "ping" messages at regular intervals
- GenServer must respond with "pong" 
- 3 consecutive failures trigger child restart
- Health check interval and timeout are configurable per child

### GenServer Requirements
GenServer children must implement the ping/pong protocol:

```python
# In your GenServer callbacks
async def handle_call(self, message, from_pid):
    if message == "ping":
        return "pong"
    # Handle other calls...
```

## Integration with FastAPI Lifespan

The supervisor integrates well with FastAPI's lifespan management:

```python
from contextlib import asynccontextmanager
from anyio import create_task_group

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize your services
    mailbox.configure_global_registry(True)
    mailbox.init_mailbox_registry()
    
    # Define your workers and children specs
    children = [
        child_spec(id="controller", task=controller.run, args=[...]),
        child_spec(id="leaf_manager", task=leaf_manager.run, args=[...]),
        # ... more children
    ]
    
    supervisor_opts = options(strategy=OneForOne())
    
    async with create_task_group() as tg:
        # Start individual workers that don't need supervision
        usr_man_handle = await tg.start(usr_mgr.start)
        
        # Start workers directly if they don't need supervision
        tg.start_soon(controller.run, leaf_tx.clone(), csvman_tx.clone())
        tg.start_soon(leaf_manager.run, leaf_rx)
        tg.start_soon(csvman.start, csvman_rx, csv_file_path)
        
        # Or use supervisor for critical services that need monitoring
        # supervisor_handle = await tg.start(start, children, supervisor_opts)
        
        yield
        
        # Cleanup on shutdown
        logger.info("Shutting down. Cleaning up resources...")
        controller.tc_manager.clear_mq_qdiscs(interface_a)
        controller.tc_manager.clear_mq_qdiscs(interface_b)
        tg.cancel_scope.cancel()
```

## Error Handling and Exit Strategies

### Special Exit Types

#### `NormalExit`
Indicates normal completion. Respects the child's restart strategy.

#### `ShutdownExit`
Forces termination without restart, regardless of restart strategy.

#### `BrutalKill`
Immediate termination without graceful shutdown.

### Restart Intensity
When a child exceeds the maximum restart limit within the time window:
- The supervisor logs an error
- The supervisor itself terminates
- This cascades up to terminate the parent task group

## Best Practices

1. **Use appropriate restart strategies**: 
   - `Permanent()` for critical services that must always run
   - `Transient()` for tasks that may complete normally

2. **Configure health checks wisely**:
   - Enable for GenServer children that support ping/pong
   - Disable for simple worker tasks
   - Adjust intervals based on your service requirements

3. **Set reasonable restart limits**:
   - Don't set limits too low (might cause unnecessary supervisor crashes)
   - Don't set too high (might mask persistent issues)

4. **Choose supervision strategies carefully**:
   - `OneForOne()` for independent services
   - `OneForAll()` when services are interdependent
   - `RestForOne()` for dependency hierarchies

5. **Handle shutdown gracefully**:
   - Use structured concurrency with anyio task groups
   - Implement proper cleanup in lifespan managers
   - Consider shutdown timeouts for long-running cleanup

## Error Cases and Debugging

The supervisor provides detailed logging for debugging:
- Child start/restart events
- Health check failures and recoveries  
- Restart limit exceeded conditions
- Unexpected child completions

Monitor logs at INFO level for normal operations and ERROR level for critical issues that require attention.