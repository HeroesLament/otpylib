"""
hello_supervisor.py - Supervisor Module Demo

Demonstrates:
- Defining supervisors as OTPModule with SUPERVISOR behavior
- Using child_spec for type-safe child specifications
- Nested supervision trees (RootSupervisor -> AppSupervisor -> Workers)
- Fault tolerance and automatic restarts
- Supervision isolation
"""

import asyncio
from otpylib import process
from otpylib.runtime import set_runtime
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.module import OTPModule, GEN_SERVER, SUPERVISOR
from otpylib.gen_server.data import Reply, NoReply
from otpylib.supervisor.atoms import PERMANENT, ONE_FOR_ONE
from otpylib.supervisor import options
from otpylib import gen_server
from otpylib.supervisor import child_spec
import otpylib.supervisor as supervisor


# ============================================================================
# Worker 1: Counter Server
# ============================================================================

class CounterServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Simple counter that can crash on command."""
    
    async def init(self, initial_value):
        return {'count': initial_value}
    
    async def handle_call(self, request, from_pid, state):
        match request:
            case 'get':
                return (Reply(state['count']), state)
            
            case 'increment':
                new_count = state['count'] + 1
                return (Reply(new_count), {'count': new_count})
            
            case 'crash':
                # Intentional crash for testing supervision
                raise RuntimeError("Intentional crash!")
            
            case _:
                return (Reply({'error': 'unknown'}), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


# ============================================================================
# Worker 2: Logger Server
# ============================================================================

class LoggerServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
    """Simple logger that records messages."""
    
    async def init(self, config):
        return {'logs': [], 'max_logs': config.get('max_logs', 100)}
    
    async def handle_call(self, request, from_pid, state):
        match request:
            case ('log', message):
                state['logs'].append(message)
                if len(state['logs']) > state['max_logs']:
                    state['logs'] = state['logs'][-state['max_logs']:]
                return (Reply('ok'), state)
            
            case 'get_logs':
                return (Reply(state['logs']), state)
            
            case 'count':
                return (Reply(len(state['logs'])), state)
            
            case _:
                return (Reply({'error': 'unknown'}), state)
    
    async def handle_cast(self, message, state):
        return (NoReply(), state)
    
    async def handle_info(self, message, state):
        return (NoReply(), state)
    
    async def terminate(self, reason, state):
        pass


# ============================================================================
# Mid-Level Supervisor: App Supervisor
# ============================================================================

class AppSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
    """Manages counter and logger workers."""
    
    async def init(self, args):
        children = [
            child_spec(
                id='counter',
                module=CounterServer,
                args=10,
                restart=PERMANENT,
                name='counter'
            ),
            child_spec(
                id='logger',
                module=LoggerServer,
                args={'max_logs': 50},
                restart=PERMANENT,
                name='logger'
            )
        ]
        
        opts = options(
            strategy=ONE_FOR_ONE,
            max_restarts=5,
            max_seconds=10
        )
        
        return (children, opts)
    
    async def terminate(self, reason, state):
        pass


# ============================================================================
# Root Supervisor
# ============================================================================

class RootSupervisor(metaclass=OTPModule, behavior=SUPERVISOR, version="1.0.0"):
    """
    Root supervisor managing the AppSupervisor.
    Provides isolation between demo process and worker supervision tree.
    """
    
    async def init(self, args):
        children = [
            child_spec(
                id='app_supervisor',
                module=AppSupervisor,
                args=None,
                restart=PERMANENT,
                name='app_sup'
            )
        ]
        
        opts = options(
            strategy=ONE_FOR_ONE,
            max_restarts=3,
            max_seconds=10
        )
        
        return (children, opts)
    
    async def terminate(self, reason, state):
        pass


# ============================================================================
# Demo Application
# ============================================================================

async def run_demo():
    """Run the supervision tree demo."""
    
    print("=" * 70)
    print("Starting Supervision Tree Demo")
    print("=" * 70)
    
    # Start root supervisor - it will start everything else
    print("\n[1] Starting supervision tree...")
    root_pid = await supervisor.start_link(RootSupervisor, init_arg=None, name='root_sup')
    print(f"    ✓ Root supervisor started: {root_pid}")
    
    # Give children time to start
    await asyncio.sleep(0.5)
    
    # Test counter operations
    print("\n[2] Testing counter operations...")
    count = await gen_server.call('counter', 'get')
    print(f"    Initial count: {count}")
    
    await gen_server.call('counter', 'increment')
    await gen_server.call('counter', 'increment')
    
    count = await gen_server.call('counter', 'get')
    print(f"    After 2 increments: {count}")
    
    # Test logger operations
    print("\n[3] Testing logger operations...")
    await gen_server.call('logger', ('log', 'First message'))
    await gen_server.call('logger', ('log', 'Second message'))
    await gen_server.call('logger', ('log', 'Third message'))
    
    log_count = await gen_server.call('logger', 'count')
    print(f"    Total logs recorded: {log_count}")
    
    # Crash the counter to test supervision
    print("\n[4] Testing fault tolerance (crashing counter)...")
    count_before = await gen_server.call('counter', 'get')
    print(f"    Count before crash: {count_before}")
    
    try:
        await gen_server.call('counter', 'crash', timeout=1.0)
    except (TimeoutError, Exception):
        print(f"    Counter crashed (as expected)")
    
    # Give supervisor time to restart
    await asyncio.sleep(0.5)
    
    # Verify counter was restarted
    print("\n[5] Verifying automatic restart...")
    try:
        count_after = await gen_server.call('counter', 'get')
        print(f"    Count after restart: {count_after}")
        print(f"    ✓ Counter restarted with fresh state!")
    except Exception as e:
        print(f"    ✗ Counter not available: {e}")
    
    # Verify logger is still running (one_for_one strategy)
    print("\n[6] Verifying one_for_one isolation...")
    try:
        log_count = await gen_server.call('logger', 'count')
        print(f"    Logger still has {log_count} logs")
        print(f"    ✓ Logger unaffected by counter crash!")
    except Exception as e:
        print(f"    ✗ Logger error: {e}")
    
    print("\n" + "=" * 70)
    print("Demo Summary")
    print("=" * 70)
    print("\nSuccessfully demonstrated:")
    print("  ✓ Three-level supervision tree (Root → App → Workers)")
    print("  ✓ Type-safe child specifications")
    print("  ✓ Automatic child restart on failure")
    print("  ✓ One-for-one restart strategy isolation")
    print("  ✓ Fresh state on restart (count reset)")
    print()


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
    await asyncio.sleep(5)
    await backend.shutdown()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("OTPylib Supervision Tree Demo")
    print("=" * 70)
    asyncio.run(main())
