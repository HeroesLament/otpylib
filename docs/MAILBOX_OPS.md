# Mailbox Theory and Operation: Complete Registry Management

## Overview

The Mailbox system provides inter-process communication for async tasks using anyio memory object streams. The core challenge is maintaining **dual registry consistency** - mailboxes are identified by UUIDs but accessed by human-readable names, requiring perfect synchronization between two separate registries.

## Fundamental Architecture

### Dual Registry System

1. **Mailbox Registry**: `Dict[MailboxID, Tuple[SendStream, ReceiveStream]]`
   - Maps UUID → actual communication channels
   - Contains the real anyio memory object streams
   - Primary source of truth for mailbox existence

2. **Name Registry**: `Dict[str, MailboxID]` 
   - Maps human names → UUIDs
   - Convenience layer for named access
   - **Secondary index that must stay synchronized**

### Storage Strategies

```python
# ContextVar (task-isolated)
context_mailbox_registry = ContextVar[MailboxRegistry]("mailbox_registry")
context_name_registry = ContextVar[NameRegistry]("name_registry")

# Global (cross-task shared)  
_global_mailbox_registry: MailboxRegistry = {}
_global_name_registry: NameRegistry = {}
```

## Complete Mailbox Lifecycle

### Phase 1: Creation

```
1. create() called with buffer_size
2. Generate UUID: mid = str(uuid4())
3. Create anyio streams: send_stream, receive_stream = anyio.create_memory_object_stream(buffer_size)
4. Store in mailbox registry: mailbox_registry[mid] = (send_stream, receive_stream)
5. Return mid to caller
```

**Critical Point**: At this stage, mailbox exists but has no name. Only UUID access works.

### Phase 2: Name Registration

```
1. register(mid, name) called
2. Validate mailbox exists: mid in mailbox_registry
3. Validate name available: name not in name_registry  
4. Create name mapping: name_registry[name] = mid
5. Now both UUID and name access work
```

**Failure Points**:
- Mailbox doesn't exist → `MailboxDoesNotExist`
- Name already taken → `NameAlreadyExist`
- Registry corruption → Silent mapping loss

### Phase 3: Message Operations

#### Send Operation Flow
```
1. send(name_or_mid, message) called
2. Resolve name to UUID:
   if isinstance(name_or_mid, str):
       mid = _resolve(name_or_mid)  # name_registry.get(name_or_mid)
       if mid is None:
           mid = name_or_mid  # Fallback: treat string as UUID
   else:
       mid = name_or_mid
3. Validate mailbox exists: mid in mailbox_registry
4. Get send stream: send_stream, _ = mailbox_registry[mid]
5. Send message: await send_stream.send(message)
```

#### Receive Operation Flow
```
1. receive(mid, timeout, on_timeout) called
2. Validate mailbox exists: mid in mailbox_registry
3. Get receive stream: _, receive_stream = mailbox_registry[mid]
4. Receive message: await receive_stream.receive()
```

### Phase 4: Cleanup

```
1. destroy(mid) called
2. Validate mailbox exists: mid in mailbox_registry
3. Remove all name mappings: unregister_all(mid)
4. Close streams: await send_stream.aclose(), await receive_stream.aclose()
5. Remove from mailbox registry: mailbox_registry.pop(mid)
```

## Registry Consistency Rules

### Invariants That Must Hold

1. **Mailbox Registry Primacy**: A mailbox exists iff it's in mailbox_registry
2. **Name Registry Subset**: Every name_registry entry must point to existing mailbox
3. **Bidirectional Consistency**: If name → mid, then mid must exist in mailbox_registry
4. **Unique Names**: Each name maps to exactly one mailbox
5. **No Orphaned Names**: No name can point to non-existent mailbox

### Consistency Validation

```python
def validate_registry_consistency():
    mailbox_registry = _get_mailbox_registry()
    name_registry = _get_name_registry()
    
    # Check for orphaned names (point to non-existent mailboxes)
    orphaned_names = []
    for name, mid in name_registry.items():
        if mid not in mailbox_registry:
            orphaned_names.append((name, mid))
    
    # Check for unnamed mailboxes (not necessarily an error)
    named_mids = set(name_registry.values())
    unnamed_mailboxes = []
    for mid in mailbox_registry:
        if mid not in named_mids:
            unnamed_mailboxes.append(mid)
    
    return {
        'consistent': len(orphaned_names) == 0,
        'orphaned_names': orphaned_names,
        'unnamed_mailboxes': unnamed_mailboxes
    }
```

## Context vs Global Registry Behavior

### ContextVar Mode (Default)

- **Isolation**: Each task gets its own registry
- **Lifecycle**: Registry dies with task context
- **Problem**: Cross-task communication impossible
- **Use Case**: Testing, isolated components

### Global Mode

- **Sharing**: All tasks share single registry
- **Lifecycle**: Registry persists across task boundaries  
- **Problem**: No automatic cleanup
- **Use Case**: Production systems with cross-task communication

## Critical Failure Modes

### 1. Registry Corruption

**Symptom**: Mailbox exists but name resolution fails
```
Registry has 8 mailboxes, 6 names
Available names: ['tc_mgr', 'usr_mgr', 'shaping_mgr', 'config_manager', 'csv_mgr', 'leaf_mgr']
Missing: provisioning_mgr
```

**Causes**:
- Name registry cleared while mailbox registry preserved
- Context switching with partial registry updates
- Exception during registration leaving partial state

### 2. Context Isolation Issues

**Symptom**: Mailbox created in one context, accessed from another
```
Task A: Creates mailbox, registers name in Task A's context
Task B: Tries to resolve name, gets None (different context)
```

**Root Cause**: ContextVar registries are task-local

### 3. Async Cleanup Race Conditions

**Symptom**: Mailbox disappears during receive operations
```
GenServer calls mailbox.receive(mid)
Concurrent cleanup destroys mailbox
receive() fails with MailboxDoesNotExist
```

## Debugging Strategy

### Registry State Logging

```python
def _log_registry_operation(operation, name=None, mid=None, extra_info=None):
    # Log every registry mutation with:
    # - Operation type (CREATE, REGISTER, DESTROY, etc.)
    # - Affected name/mid
    # - Registry sizes before/after
    # - Stack trace for mutation source
```

### Critical Checkpoints

1. **After create()**: Log mailbox registry size increase
2. **After register()**: Log name registry size increase + mapping
3. **Before resolve()**: Log name registry contents if resolution fails
4. **Before send()**: Log both registry states on failure
5. **During destroy()**: Log cleanup sequence

### Failure Investigation

When `MailboxDoesNotExist` occurs:

1. **Check registry sizes**: Are they what you expect?
2. **Compare registry contents**: What names are available?
3. **Trace operation history**: What was the last successful registration?
4. **Validate context**: Are you in the right ContextVar context?
5. **Check for race conditions**: Concurrent cleanup or creation?

## Resilience Patterns

### Defensive Resolution

```python
def _resolve_with_fallback(name_or_mid):
    # Try normal resolution
    mid = _resolve(name_or_mid)
    if mid is not None:
        return mid
    
    # Check if it's already a valid UUID
    mailbox_registry = _get_mailbox_registry()
    if name_or_mid in mailbox_registry:
        return name_or_mid
    
    # Last resort: scan for mapping inconsistencies
    name_registry = _get_name_registry()
    for n, m in name_registry.items():
        if n == name_or_mid and m in mailbox_registry:
            logger.warning(f"Found {name_or_mid} via registry scan")
            return m
    
    return None
```

### Atomic Operations

```python
def register_atomic(mid, name):
    # Validate preconditions
    mailbox_registry = _get_mailbox_registry()
    name_registry = _get_name_registry()
    
    if mid not in mailbox_registry:
        raise MailboxDoesNotExist(mid)
    if name in name_registry:
        raise NameAlreadyExist(name)
    
    # Atomic update
    name_registry[name] = mid
    
    # Verify postcondition
    assert name_registry[name] == mid
    assert mid in mailbox_registry
```

## Performance Considerations

### Registry Access Patterns

- **O(1) mailbox lookup**: Direct UUID access
- **O(1) name resolution**: Hash table lookup
- **O(n) consistency check**: Must scan both registries
- **Memory overhead**: Dual storage of relationships

### Optimization Opportunities

1. **Registry compaction**: Remove unused entries periodically
2. **Weak references**: Allow automatic cleanup of unused mailboxes
3. **Registry snapshots**: Faster consistency validation
4. **Event-driven updates**: Notify on registry changes

## Key Design Principles

1. **Mailbox Registry is Truth**: All validation against mailbox existence
2. **Name Registry is Index**: Convenience layer, can be rebuilt
3. **Fail Fast**: Detect inconsistencies immediately
4. **Log Everything**: Every registry mutation must be traceable
5. **Atomic Updates**: Registry changes must be all-or-nothing
6. **Context Awareness**: Understand ContextVar vs Global implications

This design ensures reliable inter-process communication with proper failure detection and recovery mechanisms for distributed async systems.
