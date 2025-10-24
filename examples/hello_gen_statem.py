"""
hello_gen_statem.py - Generic State Machine Demo

Demonstrates:
- Module-based gen_statem with GEN_STATEM behavior
- State machine with explicit state names (atoms)
- State-specific callback functions
- State transitions with actions
- State timeouts for automatic transitions
- Reply actions for synchronous calls
- Different event types (call, cast, info, timeout)
"""

import asyncio
from otpylib import atom, gen_statem, process
from otpylib.runtime import set_runtime
from otpylib.runtime.backends.asyncio_backend.backend import AsyncIOBackend
from otpylib.module import OTPModule, GEN_STATEM
from otpylib.gen_statem import (
    CallbackMode,
    EventType,
    NextState,
    KeepState,
    RepeatState,
    StopState,
    ReplyAction,
    StateTimeoutAction,
)

# Define state atoms
LOCKED = atom.ensure("locked")
UNLOCKED = atom.ensure("unlocked")
OPENED = atom.ensure("opened")


# ============================================================================
# Door Lock State Machine Module
# ============================================================================

class DoorLock(metaclass=OTPModule, behavior=GEN_STATEM, version="1.0.0"):
    """
    A door lock state machine.
    
    States:
    - locked: Door is locked, waiting for unlock code
    - unlocked: Door is unlocked, can be opened or re-locked
    - opened: Door is open, will auto-close after timeout
    
    State data: {"code": str, "attempts": int, "max_attempts": int}
    """
    
    async def callback_mode(self):
        """Use state-specific callback functions."""
        print("[DoorLock] callback_mode() -> STATE_FUNCTIONS")
        return CallbackMode.STATE_FUNCTIONS
    
    async def init(self, unlock_code: str):
        """Initialize in locked state with unlock code."""
        print(f"[DoorLock] init(unlock_code={unlock_code})")
        state_name = LOCKED
        state_data = {
            "code": unlock_code,
            "attempts": 0,
            "max_attempts": 3,
        }
        print(f"[DoorLock] init() -> state={state_name.name}, data={state_data}")
        return state_name, state_data
    
    # ========================================================================
    # State: locked
    # ========================================================================
    
    async def state_locked(self, event_type: EventType, event_content, data: dict):
        """Handle events in locked state."""
        print(f"[DoorLock] state_locked({event_type}, {event_content})")
        
        match event_type:
            case EventType.CALL:
                # For CALL events, event_content is (payload, from_)
                payload, from_ = event_content
                match payload:
                    case ("unlock", code):
                        if code == data["code"]:
                            # Correct code - unlock!
                            print(f"[DoorLock] Correct code! Unlocking...")
                            new_data = {**data, "attempts": 0}
                            return NextState(
                                state_name=UNLOCKED,
                                state_data=new_data,
                                actions=[ReplyAction(from_=from_, reply="unlocked")]
                            )
                        else:
                            # Wrong code
                            attempts = data["attempts"] + 1
                            new_data = {**data, "attempts": attempts}
                            print(f"[DoorLock] Wrong code! Attempts: {attempts}/{data['max_attempts']}")
                            
                            if attempts >= data["max_attempts"]:
                                # Too many attempts - lock down
                                print(f"[DoorLock] Max attempts exceeded! Locking down...")
                                return StopState(reason="max_attempts_exceeded", state_data=new_data)
                            
                            return KeepState(
                                state_data=new_data,
                                actions=[ReplyAction(from_=from_, reply="invalid_code")]
                            )
                    
                    case ("status",):
                        return KeepState(
                            state_data=data,
                            actions=[ReplyAction(from_=from_, reply=LOCKED.name)]
                        )
            
            case EventType.CAST:
                match event_content:
                    case ("reset_attempts",):
                        print(f"[DoorLock] Resetting attempts counter")
                        new_data = {**data, "attempts": 0}
                        return KeepState(state_data=new_data)
        
        # Default: ignore unknown events
        print(f"[DoorLock] Ignoring unknown event in locked state")
        return KeepState(state_data=data)
    
    # ========================================================================
    # State: unlocked
    # ========================================================================
    
    async def state_unlocked(self, event_type: EventType, event_content, data: dict):
        """Handle events in unlocked state."""
        print(f"[DoorLock] state_unlocked({event_type}, {event_content})")
        
        match event_type:
            case EventType.CALL:
                # For CALL events, event_content is (payload, from_)
                payload, from_ = event_content
                match payload:
                    case ("open",) | "open":
                        # Open the door, set timeout to auto-close
                        print(f"[DoorLock] Opening door, setting 5s auto-close timer")
                        return NextState(
                            state_name=OPENED,
                            state_data=data,
                            actions=[
                                ReplyAction(from_=from_, reply="opened"),
                                StateTimeoutAction(timeout=5.0, event_content="auto_close"),
                            ]
                        )
                    
                    case ("lock",) | "lock":
                        print(f"[DoorLock] Manually locking door")
                        return NextState(
                            state_name=LOCKED,
                            state_data=data,
                            actions=[ReplyAction(from_=from_, reply="locked")]
                        )
                    
                    case ("status",) | "status":
                        return KeepState(
                            state_data=data,
                            actions=[ReplyAction(from_=from_, reply=UNLOCKED.name)]
                        )
            
            case EventType.INFO:
                match event_content:
                    case ("emergency_lock",):
                        # External trigger to lock
                        print(f"[DoorLock] EMERGENCY LOCK triggered!")
                        return NextState(state_name=LOCKED, state_data=data)
        
        print(f"[DoorLock] Ignoring unknown event in unlocked state")
        return KeepState(state_data=data)
    
    # ========================================================================
    # State: opened
    # ========================================================================
    
    async def state_opened(self, event_type: EventType, event_content, data: dict):
        """Handle events in opened state."""
        print(f"[DoorLock] state_opened({event_type}, {event_content})")
        
        match event_type:
            case EventType.CALL:
                # For CALL events, event_content is (payload, from_)
                payload, from_ = event_content
                match payload:
                    case ("close",):
                        # Manually close (will lock)
                        print(f"[DoorLock] Manually closing and locking door")
                        return NextState(
                            state_name=LOCKED,
                            state_data=data,
                            actions=[ReplyAction(from_=from_, reply="closed_and_locked")]
                        )
                    
                    case ("status",):
                        return KeepState(
                            state_data=data,
                            actions=[ReplyAction(from_=from_, reply=OPENED.name)]
                        )
            
            case EventType.STATE_TIMEOUT:
                # Auto-close timeout expired
                match event_content:
                    case "auto_close":
                        # Close and lock automatically
                        print(f"[DoorLock] Auto-close timeout! Closing and locking door")
                        return NextState(
                            state_name=LOCKED,
                            state_data=data
                        )
        
        print(f"[DoorLock] Ignoring unknown event in opened state")
        return KeepState(state_data=data)
    
    # ========================================================================
    # Cleanup
    # ========================================================================
    
    async def terminate(self, reason, state_name, state_data):
        """Called when state machine stops."""
        print(f"[DoorLock] terminate(reason={reason}, state={state_name.name}, data={state_data})")


# ============================================================================
# Demo Application
# ============================================================================

async def run_demo():
    """Run the door lock state machine demo."""
    
    print("=" * 70)
    print("Generic State Machine Demo (gen_statem)")
    print("=" * 70)
    
    # Start the door lock state machine
    print("\n[1] Starting door lock state machine...")
    print("[DEBUG] About to call DoorLock.start_link()")
    lock_pid = await gen_statem.start_link(
        DoorLock,
        init_arg="1234",  # Unlock code
        name="front_door"
    )
    print(f"[DEBUG] start_link returned: {lock_pid}")
    print(f"    ✓ Door lock started: {lock_pid}")
    print(f"    ✓ Using OTPModule: DoorLock")
    print(f"    ✓ Unlock code: 1234")
    
    await asyncio.sleep(0.3)
    
    # Check initial status
    print("\n[2] Checking initial status...")
    status = await gen_statem.call("front_door", ("status",))
    print(f"    Status: {status}")
    
    # Try wrong code
    print("\n[3] Trying wrong unlock code (9999)...")
    result = await gen_statem.call("front_door", ("unlock", "9999"))
    print(f"    Result: {result}")
    
    # Try correct code
    print("\n[4] Trying correct unlock code (1234)...")
    result = await gen_statem.call("front_door", ("unlock", "1234"))
    print(f"    Result: {result}")
    
    await asyncio.sleep(0.2)
    
    # Check status (should be unlocked)
    print("\n[5] Checking status after unlock...")
    status = await gen_statem.call("front_door", ("status",))
    print(f"    Status: {status}")
    
    # Open the door
    print("\n[6] Opening the door...")
    result = await gen_statem.call("front_door", ("open",))
    print(f"    Result: {result}")
    print(f"    (Auto-close timer started: 5 seconds)")
    
    await asyncio.sleep(1.0)
    
    # Check status while open
    print("\n[7] Checking status while door is open...")
    status = await gen_statem.call("front_door", ("status",))
    print(f"    Status: {status}")
    
    # Wait for auto-close
    print("\n[8] Waiting for auto-close (4 more seconds)...")
    await asyncio.sleep(4.5)
    
    # Check final status
    print("\n[9] Checking status after auto-close...")
    status = await gen_statem.call("front_door", ("status",))
    print(f"    Status: {status}")
    
    print("\n[DEMO] Demo complete!")
    print("\nState transitions observed:")
    print("  1. locked (initial state)")
    print("  2. locked -> unlocked (correct code)")
    print("  3. unlocked -> opened (open command)")
    print("  4. opened -> locked (auto-close timeout)")


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
    await asyncio.sleep(10)
    await backend.shutdown()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("OTPylib Generic State Machine Demo")
    print("=" * 70)
    asyncio.run(main())
