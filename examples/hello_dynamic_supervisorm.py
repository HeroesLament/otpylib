"""
hello_dynamic_supervisor.py - Dynamic Supervisor Demo (0.5.0) - DEBUG VERSION

Demonstrates:
- Module-based dynamic supervisor with DYNAMIC_SUPERVISOR behavior
- Starting with initial static children
- Adding dynamic children at runtime
- Removing dynamic children
- Querying supervisor state
- Fault tolerance with automatic restarts
- Different restart strategies
"""

import asyncio
from otpylib import dynamic_supervisor, process
from otpylib.runtime import set_runtime
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.module import OTPModule, GEN_SERVER, DYNAMIC_SUPERVISOR
from otpylib.gen_server.data import Reply, NoReply
from otpylib import gen_server
from otpylib.dynamic_supervisor import child_spec, options, ONE_FOR_ONE, PERMANENT


# ============================================================================
# Worker Module: Simple Worker
# ============================================================================

class Worker(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """A simple worker that can be dynamically added/removed."""
    
    async def init(self, config):
        worker_id = config.get('id', 'unknown')
        print(f"[DEBUG] Worker {worker_id} initializing")
        return {'id': worker_id, 'work_done': 0}
    
    async def handle_call(self, request, from_pid, state):
        print(f"[DEBUG] Worker {state['id']} got call: {request}")
        match request:
            case 'get_id':
                return (Reply(state['id']), state)
            
            case 'get_work':
                return (Reply(state['work_done']), state)
            
            case 'do_work':
                new_work = state['work_done'] + 1
                return (Reply(new_work), {**state, 'work_done': new_work})
            
            case 'crash':
                raise RuntimeError(f"Worker {state['id']} crashed!")
            
            case _:
                return (Reply({'error': 'unknown'}), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        print(f"[DEBUG] Worker {state['id']} terminating: {reason}")


# ============================================================================
# Dynamic Supervisor Module
# ============================================================================

class WorkerSupervisor(metaclass=OTPModule, behavior=DYNAMIC_SUPERVISOR, version="1.0.0"):
    """
    Dynamic supervisor for workers.
    
    Demonstrates the 0.5.0 module-based pattern for dynamic supervision.
    """
    
    async def init(self, args):
        """Initialize with two static worker children."""
        print("[DEBUG] WorkerSupervisor.init() called")
        children = [
            child_spec(
                id='worker_1',
                module=Worker,
                args={'id': 'worker_1'},
                restart=PERMANENT,
                name='worker_1'
            ),
            child_spec(
                id='worker_2',
                module=Worker,
                args={'id': 'worker_2'},
                restart=PERMANENT,
                name='worker_2'
            )
        ]
        
        opts = options(
            strategy=ONE_FOR_ONE,
            max_restarts=5,
            max_seconds=10
        )
        
        print(f"[DEBUG] WorkerSupervisor.init() returning {len(children)} children")
        return (children, opts)
    
    async def terminate(self, reason, state):
        """Called when supervisor terminates."""
        print(f"[DEBUG] WorkerSupervisor.terminate() reason={reason}")
        if reason:
            print(f"[WorkerSupervisor] Terminated with reason: {reason}")


# ============================================================================
# Demo Application
# ============================================================================

async def run_demo():
    """Run the dynamic supervisor demo."""
    
    print("=" * 70)
    print("Dynamic Supervisor Demo (0.5.0 Module-Based)")
    print("=" * 70)
    
    # Start module-based dynamic supervisor
    print("\n[1] Starting module-based dynamic supervisor with 2 static workers...")
    print("[DEBUG] About to call dynamic_supervisor.start_link()")
    sup_pid = await dynamic_supervisor.start_link(
        WorkerSupervisor,
        init_arg=None,
        name='my_supervisor'
    )
    print(f"[DEBUG] start_link returned: {sup_pid}")
    print(f"    ✓ Supervisor started: {sup_pid}")
    print(f"    ✓ Using OTPModule: WorkerSupervisor")
    
    await asyncio.sleep(0.5)
    
    # Query initial state
    print("\n[2] Querying supervisor state...")
    print("[DEBUG] About to call list_children()")
    children = await dynamic_supervisor.list_children(sup_pid)
    print(f"[DEBUG] list_children returned: {children}")
    print(f"    Children: {children}")
    
    print("[DEBUG] About to call count_children()")
    counts = await dynamic_supervisor.count_children(sup_pid)
    print(f"[DEBUG] count_children returned: {counts}")
    print(f"    Counts: {counts}")
    
    # Test static workers
    print("\n[3] Testing static workers...")
    print("[DEBUG] About to call worker_1.do_work()")
    work1 = await gen_server.call('worker_1', 'do_work')
    print(f"[DEBUG] worker_1 returned: {work1}")
    
    print("[DEBUG] About to call worker_2.do_work()")
    work2 = await gen_server.call('worker_2', 'do_work')
    print(f"[DEBUG] worker_2 returned: {work2}")
    
    print(f"    worker_1 completed: {work1} tasks")
    print(f"    worker_2 completed: {work2} tasks")
    
    # Add a dynamic worker
    print("\n[4] Adding dynamic worker at runtime...")
    success, msg = await dynamic_supervisor.start_child(
        sup_pid,
        child_spec(
            id='worker_3',
            module=Worker,
            args={'id': 'worker_3'},
            restart=PERMANENT,
            name='worker_3'
        )
    )
    print(f"    Success: {success}, Message: {msg}")
    
    await asyncio.sleep(0.3)
    
    # Verify dynamic worker
    print("\n[5] Testing dynamic worker...")
    work3 = await gen_server.call('worker_3', 'do_work')
    print(f"    worker_3 completed: {work3} tasks")
    
    # Query updated state
    print("\n[6] Querying updated state...")
    children = await dynamic_supervisor.list_children(sup_pid)
    print(f"    Children: {children}")
    
    which = await dynamic_supervisor.which_children(sup_pid)
    print(f"    Detailed info:")
    for child in which:
        print(f"      - {child['id']}: pid={child['pid']}, dynamic={child['is_dynamic']}")
    
    print("\n[DEMO] Demo complete!")


# ============================================================================
# Main Entry Point
# ============================================================================

async def main():
    """Main entry point - initialize backend and run demo."""
    
    backend = AsyncIOBackend()
    await backend.initialize()
    set_runtime(backend)
    
    async def demo_process():
        try:
            await run_demo()
        except Exception as e:
            print(f"\n✗ Demo failed: {e}")
            import traceback
            traceback.print_exc()
    
    await process.spawn(demo_process, mailbox=True)
    
    # Keep running for demo duration
    await asyncio.sleep(8)
    await backend.shutdown()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("OTPylib Dynamic Supervisor Demo (0.5.0)")
    print("=" * 70)
    asyncio.run(main())
