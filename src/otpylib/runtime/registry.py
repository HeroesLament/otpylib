"""
Runtime Backend Registry

Manages the global runtime backend state and provides coordination for switching
between different runtime implementations (AnyIO, SPAM, etc.).
"""

import threading
import logging
from typing import Any, Optional, List, Callable
from weakref import WeakSet

from otpylib.runtime.backends.base import RuntimeBackend
from otpylib.distribution import DistributionProtocol

logger = logging.getLogger(__name__)

# Global state - protected by lock
_current_backend: Optional[RuntimeBackend] = None
_backend_lock = threading.RLock()

_current_distribution: Optional[DistributionProtocol] = None
_distribution_lock = threading.RLock()

# Cache invalidation system
_change_listeners: WeakSet[Callable[[], None]] = WeakSet()


def get_distribution() -> Optional[DistributionProtocol]:
    """Get the currently active distribution layer."""
    with _distribution_lock:
        return _current_distribution


def get_runtime() -> Optional[RuntimeBackend]:
    """
    Get the currently active runtime backend.
    
    :returns: Current RuntimeBackend instance, or None if no backend is set
    """
    with _backend_lock:
        return _current_backend


def set_distribution(distribution: DistributionProtocol) -> None:
    """
    Set the active distribution layer.
    
    :param distribution: Distribution implementation (e.g., AsyncIODistribution)
    """
    global _current_distribution
    
    with _backend_lock:
        _current_distribution = distribution
        logger.debug(f"Distribution layer set: {type(distribution).__name__}")


def set_runtime(backend: RuntimeBackend) -> None:
    """
    Set the active runtime backend.
    
    This replaces the current backend with the provided one. The caller is
    responsible for properly shutting down the previous backend if needed.
    
    :param backend: RuntimeBackend implementation to activate
    :raises TypeError: If backend doesn't implement RuntimeBackend interface
    :raises RuntimeError: If backend setup fails
    """
    global _current_backend
    
    # Validate backend
    if not isinstance(backend, RuntimeBackend):
        raise TypeError(f"Backend must implement RuntimeBackend interface, got {type(backend)}")
    
    with _backend_lock:
        previous_backend = _current_backend
        _current_backend = backend
        
        logger.debug(f"Runtime backend changed: {type(previous_backend).__name__ if previous_backend else 'None'} -> {type(backend).__name__}")
        
        # Notify cache invalidation listeners
        _notify_change_listeners()


def reset_distribution() -> None:
    """Reset distribution to None."""
    global _current_distribution
    
    with _backend_lock:
        if _current_distribution:
            logger.debug("Distribution layer reset")
        _current_distribution = None


def reset_runtime() -> Optional[RuntimeBackend]:
    """
    Reset the runtime to no backend (fallback to native implementations).
    
    :returns: The previous backend that was reset, or None if no backend was set
    """
    global _current_backend
    
    with _backend_lock:
        previous_backend = _current_backend
        _current_backend = None
        
        if previous_backend:
            logger.debug(f"Runtime backend reset from {type(previous_backend).__name__}")
            
            # Notify cache invalidation listeners
            _notify_change_listeners()
        
        return previous_backend


def is_runtime_active() -> bool:
    """
    Check if a runtime backend is currently active.
    
    :returns: True if a backend is set, False otherwise
    """
    with _backend_lock:
        return _current_backend is not None


def get_backend_type() -> Optional[str]:
    """
    Get the type name of the current backend.
    
    :returns: Backend type name, or None if no backend is set
    """
    with _backend_lock:
        return type(_current_backend).__name__ if _current_backend else None


def add_change_listener(callback: Callable[[], None]) -> None:
    """
    Add a callback to be notified when the runtime backend changes.
    
    This is used for cache invalidation - modules like gen_server can register
    callbacks to clear their cached runtime references when the backend changes.
    
    Uses weak references so callbacks don't need explicit cleanup.
    
    :param callback: Function to call when backend changes (no arguments)
    """
    _change_listeners.add(callback)


def _notify_change_listeners() -> None:
    """Notify all registered change listeners."""
    
    # Create a list to avoid issues with set modification during iteration
    listeners = list(_change_listeners)
    
    for callback in listeners:
        try:
            callback()
        except Exception as e:
            logger.warning(f"Runtime change listener failed: {e}")


def with_runtime(backend: RuntimeBackend):
    """
    Context manager for temporarily setting a runtime backend.
    
    Automatically restores the previous backend when exiting the context.
    Useful for testing or temporary runtime switches.
    
    :param backend: Backend to use within the context
    
    Example:
        with with_runtime(my_backend):
            # Use my_backend for this block
            pid = await spawn_gen_server(module)
        # Previous backend restored here
    """
    return _RuntimeContext(backend)


class _RuntimeContext:
    """Context manager implementation for with_runtime()."""
    
    def __init__(self, backend: RuntimeBackend):
        self.backend = backend
        self.previous_backend = None
    
    def __enter__(self) -> RuntimeBackend:
        self.previous_backend = get_runtime()
        set_runtime(self.backend)
        return self.backend
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.previous_backend:
            set_runtime(self.previous_backend)
        else:
            reset_runtime()


# Integration helpers for other modules

def register_for_cache_invalidation(invalidate_func: Callable[[], None]) -> None:
    """
    Register a cache invalidation function to be called when backend changes.
    
    This is specifically for integration with gen_server, supervisor, etc.
    modules that cache the current runtime for performance.
    
    :param invalidate_func: Function that invalidates the module's runtime cache
    """
    add_change_listener(invalidate_func)


def ensure_runtime_available() -> RuntimeBackend:
    """
    Ensure a runtime backend is available, raising an error if not.
    
    :returns: Current RuntimeBackend
    :raises RuntimeError: If no backend is active
    """
    backend = get_runtime()
    if backend is None:
        raise RuntimeError(
            "No runtime backend is active. Set a backend using set_runtime() "
            "or ensure otpylib.runtime is properly initialized."
        )
    return backend


def get_runtime_info() -> dict:
    """
    Get information about the current runtime state.
    
    :returns: Dictionary with runtime information
    """
    with _backend_lock:
        if _current_backend:
            try:
                stats = _current_backend.statistics()
                return {
                    'backend_type': type(_current_backend).__name__,
                    'backend_active': True,
                    'uptime_seconds': stats.uptime_seconds,
                    'total_processes': stats.total_processes,
                    'active_processes': stats.active_processes,
                }
            except Exception as e:
                return {
                    'backend_type': type(_current_backend).__name__,
                    'backend_active': True,
                    'error': f"Failed to get statistics: {e}"
                }
        else:
            return {
                'backend_type': None,
                'backend_active': False,
                'fallback_mode': True
            }
