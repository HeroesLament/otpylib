# Supervision Trees in OTPylib

A supervision tree is a hierarchical structure of supervisors and workers that provides fault tolerance and organized process management. This guide covers how to design and implement supervision trees using OTPylib's supervisor and dynamic supervisor components.

## Core Concepts

### Supervisor Types

**Static Supervisor**
- Fixed set of children defined at startup
- Children restart according to configured strategies
- Best for core system services that don't change

**Dynamic Supervisor**
- Children can be added/removed at runtime via mailbox messages
- Combines static supervision logic with dynamic management
- Ideal for worker pools and scalable services

### Restart Strategies

- **Permanent**: Always restart on failure (critical services)
- **Transient**: Only restart on abnormal exit (batch jobs)
- **Temporary**: Never restart (one-time tasks)

### Supervision Strategies

- **OneForOne**: Only restart failed child
- **OneForAll**: Restart all children if one fails
- **RestForOne**: Restart failed child and all started after it

## Basic Supervision Tree

```python
import anyio
from otpylib import supervisor, dynamic_supervisor
from otpylib.types import Permanent, Transient, OneForOne

# Core application services (static)
async def database_connection():
    """Critical database service."""
    # Database connection logic
    await anyio.sleep_forever()

async def cache_service():
    """Redis cache service."""
    # Cache service logic
    await anyio.sleep_forever()

async def main():
    """Start the supervision tree."""
    
    # Core system supervisor
    core_children = [
        supervisor.child_spec(
            id="database",
            task=database_connection,
            args=[],
            restart=Permanent()  # Critical - always restart
        ),
        supervisor.child_spec(
            id="cache", 
            task=cache_service,
            args=[],
            restart=Permanent()  # Critical - always restart
        )
    ]
    
    core_opts = supervisor.options(
        max_restarts=3,
        max_seconds=10,
        strategy=OneForAll()  # All services depend on each other
    )
    
    async with anyio.create_task_group() as tg:
        # Start core supervisor
        core_handle = await tg.start(supervisor.start, core_children, core_opts)
        
        # Keep running
        await anyio.sleep_forever()

if __name__ == "__main__":
    anyio.run(main)
```

## Nested Supervision Tree

```python
import anyio
from otpylib import supervisor, dynamic_supervisor, mailbox
from otpylib.types import Permanent, Transient, OneForOne, OneForAll

# Worker tasks
async def http_worker(worker_id: str):
    """HTTP request handler."""
    while True:
        # Process HTTP requests
        await anyio.sleep(1.0)
        print(f"HTTP worker {worker_id} processed request")

async def background_job_worker(job_data):
    """Process a background job."""
    print(f"Processing job: {job_data}")
    await anyio.sleep(2.0)  # Simulate work
    print(f"Job completed: {job_data}")

# Core services
async def database_service():
    """Database connection pool."""
    print("Database service started")
    await anyio.sleep_forever()

async def message_queue():
    """Message queue service."""
    print("Message queue started") 
    await anyio.sleep_forever()

async def main():
    """Multi-layer supervision tree."""
    
    mailbox.init_mailbox_registry()
    
    async with anyio.create_task_group() as root_tg:
        
        # Layer 1: Core Infrastructure
        infrastructure_children = [
            supervisor.child_spec(
                id="database",
                task=database_service,
                args=[],
        # Layer 1: Core Infrastructure
        infrastructure_children = [
            supervisor.child_spec(
                id="database",
                task=database_service,
                args=[],
                restart=Permanent()  # Critical - always restart
            ),
            supervisor.child_spec(
                id="message_queue",
                task=message_queue,
                args=[],
                restart=Permanent()  # Critical - always restart
            )
        ]
        
        infrastructure_opts = supervisor.options(
            max_restarts=3,
            max_seconds=10,
            strategy=OneForAll()  # All infrastructure must work together
        )
        
        # Start infrastructure supervisor
        infra_handle = await root_tg.start(
            supervisor.start, 
            infrastructure_children, 
            infrastructure_opts
        )
        
        print("Core infrastructure started")
        
        # Layer 2: HTTP Worker Pool (Dynamic)
        http_pool_opts = dynamic_supervisor.options(
            max_restarts=5,
            max_seconds=30,
            strategy=OneForOne()  # Workers are independent
        )
        
        # Start HTTP worker pool supervisor
        http_handle = await root_tg.start(
            dynamic_supervisor.start,
            [],  # Start empty
            http_pool_opts,
            "http_workers"
        )
        
        # Add HTTP workers dynamically
        for i in range(3):
            worker_spec = dynamic_supervisor.child_spec(
                id=f"http_worker_{i}",
                task=http_worker,
                args=[f"worker_{i}"],
                restart=Permanent(),  # Keep workers running
                health_check_enabled=False
            )
            await dynamic_supervisor.start_child("http_workers", worker_spec)
        
        print("HTTP worker pool started")
        
        # Layer 3: Job Processing Pool (Dynamic)
        job_pool_opts = dynamic_supervisor.options(
            max_restarts=10,
            max_seconds=60,
            strategy=OneForOne()  # Jobs are independent
        )
        
        # Start job processor supervisor
        job_handle = await root_tg.start(
            dynamic_supervisor.start,
            [],  # Start empty
            job_pool_opts,
            "job_processors"
        )
        
        print("Job processing pool started")
        
        # Simulate adding jobs dynamically
        await anyio.sleep(2.0)
        
        jobs = ["email_batch", "data_export", "report_generation"]
        for job in jobs:
            job_spec = dynamic_supervisor.child_spec(
                id=f"job_{job}",
                task=background_job_worker,
                args=[job],
                restart=Transient(),  # Only restart on crash, not normal completion
                health_check_enabled=False
            )
            await dynamic_supervisor.start_child("job_processors", job_spec)
        
        print("Background jobs queued")
        
        # Let the system run
        await anyio.sleep(10.0)
        
        # Graceful shutdown
        print("Shutting down supervision tree...")
        await job_handle.shutdown()
        await http_handle.shutdown()
        await infra_handle.shutdown()
        print("Shutdown complete")

if __name__ == "__main__":
    anyio.run(main)
```

## Design Patterns

### Worker Pool Pattern

Use dynamic supervisors for scalable worker pools:

```python
async def create_worker_pool(pool_name: str, worker_count: int):
    """Create a dynamic worker pool."""
    
    async with anyio.create_task_group() as tg:
        pool_handle = await tg.start(
            dynamic_supervisor.start,
            [],  # Start empty
            dynamic_supervisor.options(strategy=OneForOne()),
            pool_name
        )
        
        # Add workers
        for i in range(worker_count):
            worker_spec = dynamic_supervisor.child_spec(
                id=f"worker_{i}",
                task=worker_function,
                args=[i],
                restart=Permanent(),
                health_check_enabled=True,
                health_check_interval=30.0,
                health_check_fn=health_check_fn
            )
            await dynamic_supervisor.start_child(pool_name, worker_spec)
        
        return pool_handle

# Scale the pool at runtime
await dynamic_supervisor.start_child("workers", new_worker_spec)
await dynamic_supervisor.terminate_child("workers", "worker_5")
```

### Batch Job Pattern

Use transient restart strategy for jobs that should complete:

```python
async def process_batch_jobs(jobs):
    """Process a batch of jobs with fault tolerance."""
    
    async with anyio.create_task_group() as tg:
        batch_handle = await tg.start(
            dynamic_supervisor.start,
            [],
            dynamic_supervisor.options(
                max_restarts=2,  # Allow some retries
                max_seconds=60,
                strategy=OneForOne()  # Jobs are independent
            ),
            "batch_processor"
        )
        
        # Submit all jobs
        for job_id, job_data in jobs.items():
            job_spec = dynamic_supervisor.child_spec(
                id=job_id,
                task=process_job,
                args=[job_data],
                restart=Transient(),  # Don't restart on normal completion
                health_check_enabled=False
            )
            await dynamic_supervisor.start_child("batch_processor", job_spec)
        
        # Monitor progress
        while batch_handle.list_children():
            await anyio.sleep(1.0)
            print(f"Jobs remaining: {len(batch_handle.list_children())}")
        
        await batch_handle.shutdown()
        print("All jobs completed")
```

### Circuit Breaker Pattern

Implement circuit breaker with supervision:

```python
async def circuit_breaker_service():
    """Service with built-in circuit breaker via supervision."""
    
    failure_count = 0
    
    async def monitored_service():
        nonlocal failure_count
        try:
            # Your service logic here
            await external_api_call()
            failure_count = 0  # Reset on success
        except Exception as e:
            failure_count += 1
            if failure_count > 5:
                print("Circuit breaker open - too many failures")
                await anyio.sleep(30)  # Backoff
            raise
    
    # Use supervisor to handle failures and implement backoff
    children = [
        supervisor.child_spec(
            id="api_service",
            task=monitored_service,
            args=[],
            restart=Permanent()
        )
    ]
    
    opts = supervisor.options(
        max_restarts=5,
        max_seconds=60,  # Allow 5 restarts per minute
        strategy=OneForOne()
    )
    
    async with anyio.create_task_group() as tg:
        handle = await tg.start(supervisor.start, children, opts)
        await anyio.sleep_forever()
```

## Best Practices

### Supervision Tree Design

1. **Layer by Criticality**: Place most critical services at the top
2. **Isolate Failures**: Use OneForOne for independent services
3. **Group Dependencies**: Use OneForAll for tightly coupled services
4. **Design for Restart**: Services should be stateless or handle restart gracefully

### Restart Strategy Selection

- **Permanent**: Database connections, web servers, message queues
- **Transient**: Batch jobs, data processing tasks, API calls

### Health Monitoring

```python
from result import Ok, Err

async def database_health_check(child_id: str, child_process) -> Result[None, str]:
    """Custom health check for database connection."""
    try:
        # Test database connectivity
        await test_db_query()
        return Ok(None)
    except Exception as e:
        return Err(f"Database health check failed: {e}")

# Use in child spec
db_spec = dynamic_supervisor.child_spec(
    id="database",
    task=database_service,
    args=[],
    restart=Permanent(),
    health_check_enabled=True,
    health_check_interval=30.0,
    health_check_fn=database_health_check
)
```

### Error Handling

```python
try:
    async with anyio.create_task_group() as tg:
        handle = await tg.start(supervisor.start, children, opts)
        await anyio.sleep_forever()
        
except* Exception as eg:
    # Handle supervisor shutdown
    for exc in eg.exceptions:
        if "restart limit exceeded" in str(exc):
            print("Supervisor failed - restart limit exceeded")
            # Implement recovery logic
        else:
            print(f"Supervisor error: {exc}")
```

## Monitoring and Observability

### Supervisor Status

```python
async def monitor_supervision_tree(handles):
    """Monitor multiple supervisors."""
    while True:
        for name, handle in handles.items():
            children = handle.list_children()
            print(f"{name}: {len(children)} children running")
            
            for child_id in children:
                restart_count = handle.get_restart_count(child_id)
                health = handle.get_health_status(child_id)
                print(f"  {child_id}: restarts={restart_count}, health={health}")
        
        await anyio.sleep(10.0)
```

### Logging Integration

```python
import logging

# Configure logging for supervisors
logging.basicConfig(level=logging.INFO)
supervisor_logger = logging.getLogger("otpylib.supervisor")
dynamic_logger = logging.getLogger("otpylib.dynamic_supervisor")

# Supervisors will automatically log:
# - Child starts and stops
# - Restart attempts
# - Health check failures
# - Supervision strategy actions
```

This supervision tree approach provides robust fault tolerance and organized process management for complex applications. The combination of static and dynamic supervisors allows you to build systems that are both stable and flexible.