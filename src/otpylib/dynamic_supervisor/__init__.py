"""Dynamic supervisor module for runtime child management."""

from .core import (
    # Main functions
    start,
    start_child,
    terminate_child,
    list_children,
    
    # Classes for configuration
    child_spec,
    options,
    
    # Handle for monitoring and control
    DynamicSupervisorHandle,
    
    # Type alias for health probe functions
    HealthProbeFunction,
)

__all__ = [
    # Main functions
    "start",
    "start_child", 
    "terminate_child",
    "list_children",
    
    # Configuration classes
    "child_spec",
    "options",
    
    # Handle class
    "DynamicSupervisorHandle",
    
    # Type alias
    "HealthProbeFunction",
]