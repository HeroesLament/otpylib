# OtpyLib: OTP Framework for Python

An Erlang/Elixir OTP-inspired framework for Python's anyio async ecosystem.

[![License](https://img.shields.io/pypi/l/otpylib.svg?style=flat-square)](https://pypi.python.org/pypi/otpylib/)
[![Development Status](https://img.shields.io/pypi/status/otpylib.svg?style=flat-square)](https://pypi.python.org/pypi/otpylib/)
[![Latest release](https://img.shields.io/pypi/v/otpylib.svg?style=flat-square)](https://pypi.python.org/pypi/otpylib/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/otpylib.svg?style=flat-square)](https://pypi.python.org/pypi/otpylib/)
[![Supported Python implementations](https://img.shields.io/pypi/implementation/otpylib.svg?style=flat-square)](https://pypi.python.org/pypi/otpylib/)
[![Download format](https://img.shields.io/pypi/wheel/otpylib.svg?style=flat-square)](https://pypi.python.org/pypi/otpylib)
[![Downloads](https://img.shields.io/pypi/dm/otpylib.svg?style=flat-square)](https://pypi.python.org/pypi/otpylib/)

## Introduction

OtpyLib brings the proven patterns of Erlang/Elixir OTP to Python's async ecosystem. Built on anyio for cross-async-library compatibility, it provides battle-tested concurrency primitives for building fault-tolerant, distributed systems.

**Stable APIs (v0.2.0):**

- **genserver**: Actor-model processes for stateful, message-passing services
- **supervisor**: Fault-tolerant management of persistent services with restart strategies

**Core Features:**

- **mailboxes**: Message-passing between async tasks
- **applications**: Root of supervision trees
- **restart strategies**: Permanent and Transient policies for service lifecycle management
- **fault tolerance**: Automatic restart and failure isolation

### Built on anyio

Unlike frameworks tied to specific async libraries, OtpyLib is built on [anyio](https://anyio.readthedocs.io), providing compatibility across asyncio, Trio, and other async backends.

## Design Philosophy

OtpyLib follows OTP's "let it crash" philosophy - instead of defensive programming, design systems that can fail safely and recover automatically. Services are organized in supervision trees where failures are isolated and handled at the appropriate level.

**When to use Genserver vs Supervisor:**

- **Genserver**: For stateful services that handle messages (user sessions, caches, worker processes)
- **Static Supervisor**: For managing long-running services that should restart on failure (web servers, database connections, message processors)

## Quick Example

```python
import anyio
from otpylib import genserver, supervisor
from otpylib.types import Permanent

# A simple counter genserver
class Counter:
    def __init__(self):
        self.count = 0
        
    async def handle_call(self, message, _from, state):
        if message == "get":
            return self.count, state
        elif message == "increment":
            self.count += 1
            return "ok", state

async def main():
    # Start a supervised counter service
    counter_spec = supervisor.child_spec(
        id="counter",
        task=genserver.start_link,
        args=[Counter, [], {}],
        restart=Permanent()
    )
    
    async with anyio.create_task_group() as tg:
        opts = supervisor.options()
        tg.start_soon(supervisor.start, [counter_spec], opts)

anyio.run(main)
```

## Installation

```bash
pip install otpylib
```

## Why OtpyLib?

Python's async ecosystem has powerful low-level primitives but lacks higher-level patterns for building reliable, concurrent systems. OtpyLib fills this gap by bringing OTP's proven supervision and actor-model patterns to Python.

**Benefits:**

- **Fault tolerance**: Services that crash don't bring down the entire system
- **Supervision trees**: Hierarchical failure handling and restart policies  
- **Message passing**: Clean, decoupled communication between services
- **Battle-tested patterns**: Based on decades of Erlang/OTP production experience
- **Cross-platform async**: Works with asyncio, Trio, and other anyio-compatible backends

The result is more reliable, maintainable concurrent code that handles failures gracefully and recovers automatically.