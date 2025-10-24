"""
Timing Wheel Implementation

Efficient timer management for otpylib AsyncIO backend, inspired by BEAM's
hierarchical timing wheel algorithm.

Architecture:
- Single-level wheel for most use cases (10ms ticks, 5.12s coverage)
- O(1) insertion and cancellation
- O(k) tick complexity where k = timers in current slot
- ~100 bytes per timer vs ~10KB for asyncio.Task

References:
- Varghese & Lauck (1987): "Hashed and Hierarchical Timing Wheels"
- BEAM VM erts_time.c: Erlang's timer implementation
"""

import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass(slots=True)
class Timer:
    """
    A timer entry in the timing wheel.
    
    Attributes:
        ref: Unique reference for this timer
        expiry_ms: Absolute expiry time in milliseconds (monotonic)
        target: Target process PID or name (unused if callback provided)
        message: Message to send when timer fires (unused if callback provided)
        callback: Optional callback to invoke instead of sending message
        cancelled: Flag indicating if timer has been cancelled
    """
    ref: str
    expiry_ms: int
    target: str
    message: Any
    callback: Optional[Callable] = None
    cancelled: bool = False
    
    def __lt__(self, other: 'Timer') -> bool:
        """For potential heap operations."""
        return self.expiry_ms < other.expiry_ms


@dataclass(slots=True)
class TimerLocation:
    """
    Tracks where a timer is located in the wheel.
    
    Used for O(1) cancellation lookups.
    """
    slot: int
    index: int


class TimingWheel:
    """
    Single-level timing wheel for efficient timer management.
    
    Design:
    - Fixed number of slots (circular buffer)
    - Each slot represents a time interval (tick_ms)
    - Coverage = num_slots × tick_ms
    - Timers beyond coverage wrap around with exact expiry tracking
    
    Performance:
    - Insert: O(1) - append to slot list
    - Cancel: O(1) - mark cancelled via index lookup
    - Tick: O(k) - where k = timers in current slot
    - Space: ~100 bytes per timer
    
    Example:
        wheel = TimingWheel(tick_ms=10, num_slots=512)
        # Coverage: 10ms × 512 = 5120ms = 5.12 seconds
        # Precision: ±10ms
        
        wheel.insert("timer1", 1000, "pid_123", ("timeout",))
        # Timer fires after ~1000ms (±10ms)
    """
    
    __slots__ = (
        'tick_ms', 'num_slots', 'wheel', 'current_slot',
        'current_time_ms', 'timer_index', 'stats'
    )
    
    def __init__(self, tick_ms: int = 10, num_slots: int = 512):
        """
        Initialize timing wheel.
        
        Args:
            tick_ms: Duration of each tick in milliseconds (default 10ms)
            num_slots: Number of slots in the wheel (default 512)
        
        Note:
            Coverage = tick_ms × num_slots
            With defaults: 10ms × 512 = 5.12 seconds
        """
        self.tick_ms = tick_ms
        self.num_slots = num_slots
        
        # The wheel: each slot is a list of timers
        self.wheel: List[List[Timer]] = [[] for _ in range(num_slots)]
        
        # Current position in wheel (0 to num_slots-1)
        self.current_slot = 0
        
        # Current time in milliseconds (monotonic clock)
        self.current_time_ms = self._get_time_ms()
        
        # Index for O(1) cancellation: ref -> location
        self.timer_index: Dict[str, TimerLocation] = {}
        
        # Statistics
        self.stats = {
            "total_inserted": 0,
            "total_fired": 0,
            "total_cancelled": 0,
            "current_active": 0,
        }
    
    def insert(
        self,
        ref: str,
        delay_ms: int,
        target: str,
        message: Any,
        callback: Optional[Callable] = None
    ) -> None:
        """
        Insert a timer into the wheel.
        
        Args:
            ref: Unique reference for this timer (for cancellation)
            delay_ms: Delay in milliseconds before firing
            target: Target process PID or registered name (ignored if callback provided)
            message: Message to send when timer fires (ignored if callback provided)
            callback: Optional callback to invoke instead of sending message
        
        Time Complexity: O(1)
        
        Example:
            # Message-based timer (for send_after)
            wheel.insert("timer1", 5000, "pid_abc", ("timeout", "reason"))
            
            # Callback-based timer (for sleep)
            wheel.insert("sleep1", 1000, "", None, callback=lambda: event.set())
        """
        # Calculate target slot
        ticks = delay_ms // self.tick_ms
        target_slot = (self.current_slot + ticks) % self.num_slots
        
        # Calculate exact expiry time for sub-tick precision
        expiry_ms = self.current_time_ms + delay_ms
        
        # Create timer
        timer = Timer(
            ref=ref,
            expiry_ms=expiry_ms,
            target=target,
            message=message,
            callback=callback,
            cancelled=False
        )
        
        # Add to wheel
        slot = self.wheel[target_slot]
        slot.append(timer)
        
        # Track location for fast cancellation
        self.timer_index[ref] = TimerLocation(
            slot=target_slot,
            index=len(slot) - 1
        )
        
        # Update stats
        self.stats["total_inserted"] += 1
        self.stats["current_active"] += 1
    
    def cancel(self, ref: str) -> bool:
        """
        Cancel a timer by reference.
        
        Args:
            ref: Timer reference to cancel
        
        Returns:
            True if timer was found and cancelled, False otherwise
        
        Time Complexity: O(1)
        
        Note:
            The timer is marked as cancelled but not removed immediately.
            Actual removal happens during tick() to maintain O(1) complexity.
        """
        location = self.timer_index.get(ref)
        if not location:
            return False
        
        # Get the timer and mark as cancelled
        slot = self.wheel[location.slot]
        if location.index < len(slot):
            timer = slot[location.index]
            timer.cancelled = True
        
        # Remove from index
        del self.timer_index[ref]
        
        # Update stats
        self.stats["total_cancelled"] += 1
        self.stats["current_active"] -= 1
        
        return True
    
    def tick(self) -> List[Timer]:
        """
        Advance the wheel by one tick and return expired timers.
        
        Returns:
            List of expired (non-cancelled) timers ready to fire
        
        Time Complexity: O(k) where k = timers in current slot
        
        Note:
            This should be called every tick_ms milliseconds by a
            background task to maintain timing accuracy.
        """
        # Update current time
        self.current_time_ms = self._get_time_ms()
        
        # Get timers in current slot
        slot = self.wheel[self.current_slot]
        
        expired: List[Timer] = []
        remaining: List[Timer] = []
        
        # Process each timer in this slot
        for timer in slot:
            # Skip cancelled timers
            if timer.cancelled:
                continue
            
            # Check if timer has actually expired
            # (needed for wrapped timers that exceed wheel coverage)
            if timer.expiry_ms <= self.current_time_ms:
                # Timer expired - add to result
                expired.append(timer)
                
                # Remove from index
                self.timer_index.pop(timer.ref, None)
                
                # Update stats
                self.stats["total_fired"] += 1
                self.stats["current_active"] -= 1
            else:
                # Timer wrapped around, not ready yet
                remaining.append(timer)
        
        # Clear slot and restore remaining timers
        self.wheel[self.current_slot] = remaining
        
        # Update indices for remaining timers
        for idx, timer in enumerate(remaining):
            if timer.ref in self.timer_index:
                self.timer_index[timer.ref].index = idx
        
        # Advance to next slot
        self.current_slot = (self.current_slot + 1) % self.num_slots
        
        return expired
    
    def peek_next(self) -> Optional[Tuple[str, int]]:
        """
        Peek at the next timer to expire (for debugging/monitoring).
        
        Returns:
            Tuple of (timer_ref, milliseconds_until_expiry) or None
        
        Time Complexity: O(n) where n = total active timers
        
        Note:
            This is not optimized for performance. Use only for debugging.
        """
        min_expiry: Optional[int] = None
        min_ref: Optional[str] = None
        
        for slot in self.wheel:
            for timer in slot:
                if timer.cancelled:
                    continue
                
                if min_expiry is None or timer.expiry_ms < min_expiry:
                    min_expiry = timer.expiry_ms
                    min_ref = timer.ref
        
        if min_expiry is None:
            return None
        
        ms_until = max(0, min_expiry - self.current_time_ms)
        return (min_ref, ms_until)
    
    def read_timer(self, ref: str) -> Optional[int]:
        """
        Read remaining time on a timer.
        
        Args:
            ref: Timer reference
        
        Returns:
            Remaining time in milliseconds, or None if not found
        
        Time Complexity: O(1)
        """
        location = self.timer_index.get(ref)
        if not location:
            return None
        
        slot = self.wheel[location.slot]
        if location.index >= len(slot):
            return None
        
        timer = slot[location.index]
        if timer.cancelled:
            return None
        
        remaining_ms = timer.expiry_ms - self.current_time_ms
        return max(0, remaining_ms)
    
    def get_active_count(self) -> int:
        """Return the number of active (non-cancelled) timers."""
        return self.stats["current_active"]
    
    def clear(self) -> None:
        """Clear all timers from the wheel (for testing/reset)."""
        self.wheel = [[] for _ in range(self.num_slots)]
        self.timer_index.clear()
        self.stats["current_active"] = 0
    
    def _get_time_ms(self) -> int:
        """Get current monotonic time in milliseconds."""
        return int(time.monotonic() * 1000)
    
    def __repr__(self) -> str:
        return (
            f"TimingWheel(tick_ms={self.tick_ms}, num_slots={self.num_slots}, "
            f"active={self.stats['current_active']}, "
            f"coverage={self.tick_ms * self.num_slots}ms)"
        )
