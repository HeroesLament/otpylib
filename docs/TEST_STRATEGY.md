# OTPYLIB Test Strategy

This document outlines the test coverage strategy for OTPYLIB’s runtime and process layer.
It is modeled after BEAM/OTP semantics and ensures correctness across backends.

---

## 1. Runtime Initialization

- **Goal:** Verify that a runtime can be set and retrieved via `set_runtime` / `get_runtime`.
- **Tests:**
  - Runtime is `None` before initialization.
  - `set_runtime(AsyncIOBackend())` registers globally.
  - Multiple calls overwrite the previous runtime.
  - Reset helper clears all processes and mailboxes.

---

## 2. Message Passing

- **Goal:** Ensure basic mailbox semantics are BEAM-like.
- **Tests:**
  - `send/receive` delivers messages in FIFO order.
  - Timeout raises `TimeoutError`.
  - Named process delivery (`register` + `whereis`).
  - Sending to a dead process is ignored (no crash).
  - Mailbox overflow (bounded queue, oldest dropped).

---

## 3. Links

- **Goal:** Validate bidirectional links and exit cascades.
- **Tests:**
  - `link` creates symmetric links.
  - Abnormal exit cascades to linked processes.
  - Normal exit does **not** cascade.
  - `trap_exits=True` receives `(EXIT, pid, reason)` instead of crashing.
  - `unlink` removes the relationship.
  - Circular links handled without infinite recursion.
  - `KILLED` bypasses `trap_exits`.

---

## 4. Monitors

- **Goal:** Validate unidirectional monitoring semantics.
- **Tests:**
  - `monitor` delivers a `DOWN` 5-tuple:
    ```
    (DOWN, ref, process, pid, reason)
    ```
  - Immediate `DOWN` if target is already dead (`reason = noproc`).
  - Multiple monitors on same target → multiple `DOWN`s.
  - Monitors always fire, even on `normal` exits.
  - `demonitor(ref, flush=False)` removes the monitor but keeps pending messages.
  - `demonitor(ref, flush=True)` removes the monitor **and** drops pending `DOWN`.
  - `spawn_monitor` = `spawn` + `monitor`.

---

## 5. Exit Semantics

- **Goal:** Verify alignment with OTP exit reasons.
- **Tests:**
  - Normal exit reasons: `normal`, `shutdown` → no link cascades.
  - Abnormal reasons: exceptions, arbitrary terms → cascades.
  - `exit(pid, reason)` delivers a kill signal (unless trapping).
  - Monitors always see the original reason.

---

## 6. GenServer Layer

- **Goal:** Validate high-level OTP abstractions.
- **Tests:**
  - `call` roundtrips and returns reply.
  - `call` propagates stop/terminate reason.
  - `call` propagates failure exception.
  - `cast` is fire-and-forget.
  - `info` delivers unmatched messages.
  - `info` with stop/fail reasons propagate properly.
  - State transitions match expected.

---

## 7. Supervisor Strategies

- **Goal:** Cover OTP-style restart logic.
- **Tests:**
  - `one_for_one`: only crashed child restarts.
  - `rest_for_one`: crashed child + later siblings restart.
  - `one_for_all`: all children restart.
  - Max restart intensity enforced (`max_restarts`, `max_seconds`).
  - Child restart type respected (`permanent`, `transient`, `temporary`).

---

## 8. Stress & Edge Cases

- **Goal:** Ensure runtime stability under load.
- **Tests:**
  - Burst spawning (1000+ processes).
  - Rapid crash/restart cycles.
  - Cross-link + cross-monitor storms.
  - Shutdown cleans all processes and clears registry.
  - No dangling tasks after shutdown.

---

## 9. Regression Checklist

Before merging backend/runtime changes, ensure:

- ✅ All `asyncio_backend` tests pass.  
- ✅ All `gen_server` tests pass.  
- ✅ Supervisor strategy tests green.  
- ✅ No warnings about dangling asyncio tasks.  
- ✅ Coverage for monitors & links maintained.

---

**Status:** All current tests (24 backend + 11 gen_server) are passing ✅  
Next: Expand supervisor tests to cover restart intensity and edge cases.
