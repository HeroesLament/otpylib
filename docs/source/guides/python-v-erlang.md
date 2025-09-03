# Python vs Erlang OTP Concepts

This document compares the design of `otpylib`'s Worker-Bee pattern with Erlang/Elixir’s OTP.  
The intent is to highlight where concepts align and where adaptations are required in Python’s coroutine model.  

---

## Overview

- **Objective**: Bring the reliability and supervision model of OTP into Python.  
- **Approach**: Adapt OTP principles to Python’s async runtime with minimal overhead.  
- **Outcome**: Familiar OTP-like semantics expressed in terms of AnyIO tasks and Python constructs.  

---

## Comparison Table

| Concern | Erlang/Elixir OTP | `otpylib` Worker-Bee (Python) | Adaptation Rationale |
|---------|-------------------|-------------------------------|----------------------|
| **Process model** | Lightweight preemptive processes managed by the BEAM VM. | AnyIO coroutine tasks scheduled cooperatively. | Python tasks are cooperative; health checks are added to detect stalled tasks. |
| **State handling** | Immutable state; each callback returns a new state value. | Mutable dataclass mutated in place. | Copying state on each call is inefficient in Python; contained, idempotent mutation provides equivalent semantics. |
| **Liveness semantics** | Process existence implies liveness. | Tasks can block indefinitely; explicit `PING`/`PONG` health checks with timeouts are used. | Ensures the system can detect and recover from stalled tasks. |
| **Supervision** | Supervisor trees with built-in restart intensity and strategies. | `supervisor.start()` with restart strategies defined in Python. | Mirrors OTP behavior at the library level. |
| **Error propagation** | Unhandled crashes bubble to supervisors automatically. | Business logic returns `Ok`/`Err` values; supervisors restart on uncaught exceptions. | Separation of business logic errors (values) from runtime errors (failures). |
| **Message typing** | Atoms and tagged tuples checked at compile/runtime. | `UserMgrRPC` class with typed tuple unions and helper constructors. | Provides structure and type safety with static analysis tools. |
| **Termination cleanup** | `terminate/2` is synchronous and guaranteed. | Async `terminate()` may still `await` core functions. | Matches Python async idioms, but with less determinism in failure cases. |

---

## Key Points

1. **Conceptual alignment**: Core OTP ideas—supervision, isolation, idempotent operations—are preserved.  
2. **Pragmatic mutation**: Python favors in-place state mutation; the design ensures it remains safe and predictable.  
3. **Health monitoring**: Additional liveness checks are necessary in Python due to cooperative scheduling.  
4. **Typed RPC contracts**: Union types and helper functions approximate the role of tagged tuples and atoms.  

---

## Summary

`otpylib` adapts OTP concepts into Python’s coroutine model.  
The result is a system with supervision trees, fault isolation, and reliable state management, expressed in terms natural to Python rather than the BEAM VM.
