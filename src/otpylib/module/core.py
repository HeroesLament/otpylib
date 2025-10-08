"""
otpylib.module.core

The OTPModule metaclass - the foundation of the otpylib module system.

This metaclass transforms Python classes into validated, introspectable OTP modules.
It enforces behavior contracts, collects callbacks, attaches metadata, and ensures
that only well-formed modules are created.
"""

import asyncio
import inspect
import time
import importlib
from typing import Dict, Any, Callable, Set, List, Tuple, Optional

from otpylib.atom import ensure, Atom

from .atoms import (
    CREATED, VALIDATED, REGISTERED,
    VALIDATION_STARTED, VALIDATION_PASSED, VALIDATION_FAILED,
    CALLBACKS_COLLECTED, CONTRACT_CHECKED,
    MODULE_CREATED_EVENT, MODULE_VALIDATED_EVENT,
    MODNAME, BEHAVIOR, VERSION, MOD_ID, CALLBACKS, REGISTERED_AT, ATOMS,
    DEPENDENCIES, RELOAD_HOOK, UPGRADE_HOOK, PURGE_HOOK
)

from .data import (
    BehaviorContractError,
    MissingCallbackError,
    InvalidCallbackError,
    CallbackArityError,
    UnknownBehaviorError,
    NoBehaviorSpecifiedError,
    NoVersionSpecifiedError,
    InvalidVersionFormatError,
    BEHAVIOR_CONTRACTS,
    CALLBACK_SIGNATURES,
    BehaviorContract
)


# ============================================================================
# Helper Functions
# ============================================================================

def validate_version_format(version: str) -> bool:
    """
    Validate version string format.
    Accepts semantic versioning (1.2.3) or simple versioning (v1, 2.0).
    """
    import re
    
    # Semantic versioning pattern
    semver_pattern = r'^\d+\.\d+\.\d+$'
    
    # Simple version pattern
    simple_pattern = r'^v?\d+(\.\d+)?$'
    
    return bool(re.match(semver_pattern, version) or re.match(simple_pattern, version))


def parse_mod_id(mod_id: str) -> Tuple[str, str]:
    """
    Parse mod_id into (name, version) tuple.
    
    Example:
        parse_mod_id("my_server:1.0.0") -> ("my_server", "1.0.0")
    """
    if ':' not in mod_id:
        raise ValueError(f"Invalid mod_id format: {mod_id} (expected 'name:version')")
    
    parts = mod_id.split(':', 1)
    return parts[0], parts[1]


def make_mod_id(name: str, version: str) -> str:
    """
    Construct mod_id from name and version.
    
    Example:
        make_mod_id("my_server", "1.0.0") -> "my_server:1.0.0"
    """
    return f"{name}:{version}"


def format_callback_list(callbacks: List[str], found_callbacks: List[str]) -> str:
    """
    Format callback list for error messages.
    Shows checkmarks for found callbacks, X for missing.
    """
    lines = []
    for callback in callbacks:
        marker = "✓" if callback in found_callbacks else "✗"
        lines.append(f"  {marker} {callback}")
    return "\n".join(lines)


def collect_callbacks(namespace: Dict[str, Any]) -> Dict[str, Callable]:
    """
    Collect all callable methods from class namespace.
    Includes both async and sync functions - validation happens later.
    """
    callbacks = {}
    for name, obj in namespace.items():
        # Skip private/magic methods
        if name.startswith('_'):
            continue
        
        # Collect all callable methods (functions)
        if callable(obj) and (inspect.isfunction(obj) or inspect.ismethod(obj)):
            callbacks[name] = obj
    
    return callbacks


def normalize_module_name(class_name: str) -> str:
    """
    Convert Python class name to OTP-style module name.
    
    Examples:
        MyServer -> my_server
        DatabaseWorker -> database_worker
        HTTPServer -> http_server
    """
    import re
    
    # Insert underscore before uppercase letters
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', class_name)
    s2 = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1)
    
    return s2.lower()


# ============================================================================
# Validation Logic
# ============================================================================

def validate_behavior_contract(
    cls_name: str,
    behavior: Atom,
    callbacks: Dict[str, Callable]
) -> None:
    """
    Validate that the module implements all required callbacks for its behavior.
    
    Raises appropriate BehaviorContractError subclass if validation fails.
    """
    # Check if behavior is known
    if behavior not in BEHAVIOR_CONTRACTS:
        raise UnknownBehaviorError(behavior)
    
    contract = BEHAVIOR_CONTRACTS[behavior]
    
    # Check for missing required callbacks
    missing = contract.validate(callbacks)
    if missing:
        # Create detailed error message
        found_callbacks = list(callbacks.keys())
        callback_status = format_callback_list(
            contract.required_callbacks,
            found_callbacks
        )
        
        error_msg = (
            f"Module {cls_name} (behavior: {behavior.name}) missing required callbacks.\n\n"
            f"Required callbacks for {behavior.name}:\n{callback_status}\n\n"
            f"Found callbacks: {', '.join(found_callbacks) if found_callbacks else '(none)'}\n\n"
            f"Missing: {', '.join(missing)}"
        )
        
        # Raise with first missing callback
        raise MissingCallbackError(cls_name, behavior, missing[0])
    
    # Validate that all callbacks are async
    for callback_name, callback_func in callbacks.items():
        if not asyncio.iscoroutinefunction(callback_func):
            raise InvalidCallbackError(
                cls_name,
                callback_name,
                "Callback must be defined with 'async def'"
            )


def validate_callback_signatures(
    cls_name: str,
    behavior: Atom,
    callbacks: Dict[str, Callable]
) -> None:
    """
    Optional strict signature validation.
    Checks that callbacks have correct arity.
    """
    if behavior not in CALLBACK_SIGNATURES:
        return  # No signature requirements defined
    
    signatures = CALLBACK_SIGNATURES[behavior]
    
    for callback_name, expected_sig in signatures.items():
        if callback_name not in callbacks:
            continue  # Already caught by contract validation
        
        callback_func = callbacks[callback_name]
        sig = inspect.signature(callback_func)
        actual_arity = len(sig.parameters)
        
        if actual_arity != expected_sig.arity:
            raise CallbackArityError(
                cls_name,
                callback_name,
                expected_sig.arity,
                actual_arity
            )


# ============================================================================
# OTPModule Metaclass
# ============================================================================

class OTPModule(type):
    """
    Metaclass for creating OTP-style modules in Python.
    
    This metaclass:
    1. Collects all async callbacks from the class
    2. Validates that the behavior contract is satisfied
    3. Attaches comprehensive metadata to the class
    4. Ensures modules are well-formed before reaching runtime
    5. Provides a universal start_link that routes to the behavior's implementation
    
    Usage:
        class MyServer(metaclass=OTPModule, behavior=GEN_SERVER, version="1.0.0"):
            async def init(self, args):
                return {'ok': {}}
            
            async def handle_call(self, request, from_pid, state):
                return {'reply': 'ok', 'state': state}
            
            # ... other callbacks ...
    """
    
    def __new__(mcs, name: str, bases: tuple, namespace: dict, **kwargs):
        """
        Create a new OTP module class.
        
        This is where all the magic happens:
        - Extract behavior and version from kwargs
        - Collect callbacks from namespace
        - Validate behavior contract
        - Attach metadata attributes
        - Add universal start_link method
        
        Args:
            name: Class name
            bases: Base classes
            namespace: Class namespace (all attributes/methods)
            **kwargs: Metaclass keyword arguments (behavior=, version=, etc.)
        """
        # First, create the class using type's __new__
        cls = super().__new__(mcs, name, bases, namespace)
        
        # Extract required metaclass arguments
        behavior = kwargs.get('behavior')
        version = kwargs.get('version')
        
        # Validate required arguments
        if behavior is None:
            raise NoBehaviorSpecifiedError(name)
        
        if version is None:
            raise NoVersionSpecifiedError(name)
        
        # Validate version format
        if not validate_version_format(version):
            raise InvalidVersionFormatError(
                version,
                "Version must be semantic (1.2.3) or simple (v1, 2.0)"
            )
        
        # Normalize module name
        module_name = normalize_module_name(name)
        
        # Collect all async callbacks
        callbacks = collect_callbacks(namespace)
        
        # Validate behavior contract
        try:
            validate_behavior_contract(name, behavior, callbacks)
        except BehaviorContractError:
            # Re-raise contract errors as-is
            raise
        
        # Optional: Strict signature validation
        # Uncomment to enable strict arity checking
        # validate_callback_signatures(name, behavior, callbacks)
        
        # Build mod_id
        mod_id = make_mod_id(module_name, version)
        
        # Create atoms dictionary
        atoms = {
            'modname': ensure(module_name),
            'behavior': behavior
        }
        
        # Attach all metadata to the class
        cls.__behavior__ = behavior
        cls.__version__ = version
        cls.__callbacks__ = callbacks
        cls.__atoms__ = atoms
        cls.__mod_id__ = mod_id
        cls.__registered_at__ = time.time()
        
        # Optional metadata (may not exist)
        cls.__dependencies__ = kwargs.get('dependencies', [])
        
        # Check for reload hooks
        if hasattr(cls, '__reload__'):
            cls.__reload_hook__ = cls.__reload__
        
        if hasattr(cls, '__upgrade__'):
            cls.__upgrade_hook__ = cls.__upgrade__
        
        if hasattr(cls, '__purge__'):
            cls.__purge_hook__ = cls.__purge__
        
        # Mark as created and validated
        cls.__state__ = VALIDATED
        
        # Add the universal start_link classmethod that routes to behavior implementation
        async def _start_link(init_arg: Any = None, name: Optional[str] = None) -> str:
            """
            Start this OTPModule using its behavior's start_link.
            
            This method dynamically routes to the appropriate behavior module
            based on the module's declared behavior (gen_server, supervisor, etc.)
            
            Args:
                init_arg: Initialization argument passed to the module's init callback
                name: Optional registered name for the process
                
            Returns:
                Process PID
            """
            behavior_name = cls.__behavior__.name
            
            # Convention: behaviors live in otpylib.{behavior_name}
            # e.g., gen_server -> otpylib.gen_server
            #       supervisor -> otpylib.supervisor
            #       dynamic_supervisor -> otpylib.dynamic_supervisor
            try:
                behavior_module = importlib.import_module(f"otpylib.{behavior_name}")
            except ImportError as e:
                raise RuntimeError(
                    f"Cannot import behavior module 'otpylib.{behavior_name}' for {cls.__name__}: {e}"
                )
            
            # Every behavior module must provide a start_link function
            if not hasattr(behavior_module, 'start_link'):
                raise RuntimeError(
                    f"Behavior module 'otpylib.{behavior_name}' does not provide start_link function"
                )
            
            # Call the behavior's start_link with this class
            return await behavior_module.start_link(cls, init_arg=init_arg, name=name)
        
        # Attach as a classmethod so it can be called as: MyModule.start_link(...)
        cls.start_link = classmethod(lambda cls, init_arg=None, name=None: _start_link(init_arg, name))
        
        return cls
    
    def __init__(cls, name: str, bases: tuple, namespace: dict, **kwargs):
        """
        Initialize the module class after creation.
        
        This is where we would register with code_server, but for now
        we just call super().__init__ to complete class initialization.
        
        In a full implementation:
            await code_server.call(pid, {'action': 'register', 'module': cls})
        """
        super().__init__(name, bases, namespace)
        
        # Mark as registered (will be set to REGISTERED after code_server registration)
        # For now, just mark as CREATED since we don't have code_server yet
        cls.__state__ = CREATED
    
    def __repr__(cls):
        """String representation of the module class."""
        return (
            f"<OTPModule {cls.__mod_id__} "
            f"behavior={cls.__behavior__.name} "
            f"callbacks={len(cls.__callbacks__)}>"
        )


# ============================================================================
# Module Introspection Functions
# ============================================================================

def is_otp_module(obj: Any) -> bool:
    """Check if an object is an OTP module class."""
    return isinstance(obj, type) and isinstance(obj, OTPModule)


def get_module_info(cls: type) -> Dict[str, Any]:
    """
    Get comprehensive info about an OTP module.
    
    Returns dictionary with all metadata fields.
    """
    if not is_otp_module(cls):
        raise ValueError(f"{cls} is not an OTP module")
    
    return {
        'name': cls.__atoms__['modname'].name,
        'mod_id': cls.__mod_id__,
        'version': cls.__version__,
        'behavior': cls.__behavior__.name,
        'callbacks': list(cls.__callbacks__.keys()),
        'registered_at': cls.__registered_at__,
        'dependencies': cls.__dependencies__,
        'state': cls.__state__.name if hasattr(cls, '__state__') else 'unknown',
        'has_reload_hook': hasattr(cls, '__reload_hook__'),
        'has_upgrade_hook': hasattr(cls, '__upgrade_hook__'),
        'has_purge_hook': hasattr(cls, '__purge_hook__')
    }


def list_callbacks(cls: type) -> List[str]:
    """Get list of callback names for a module."""
    if not is_otp_module(cls):
        raise ValueError(f"{cls} is not an OTP module")
    
    return list(cls.__callbacks__.keys())


def get_behavior(cls: type) -> Atom:
    """Get the behavior atom for a module."""
    if not is_otp_module(cls):
        raise ValueError(f"{cls} is not an OTP module")
    
    return cls.__behavior__


def get_version(cls: type) -> str:
    """Get the version string for a module."""
    if not is_otp_module(cls):
        raise ValueError(f"{cls} is not an OTP module")
    
    return cls.__version__
