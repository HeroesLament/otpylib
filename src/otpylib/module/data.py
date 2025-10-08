"""
otpylib.module.data

Data structures, exceptions, and behavior contracts for the OTP module system.
Defines all dataclasses, exception types, and validation contracts used by
the OTPModule metaclass and code_server.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Callable, Any
from datetime import datetime

from otpylib.atom import Atom
from .atoms import (
    GEN_SERVER, SUPERVISOR, DYNAMIC_SUPERVISOR, APPLICATION, GEN_STATEM, GEN_EVENT, TASK,
    INIT, TERMINATE, CODE_CHANGE,
    HANDLE_CALL, HANDLE_CAST, HANDLE_INFO,
    HANDLE_CHILD_EXIT,
    START, STOP, CONFIG_CHANGE,
    CALLBACK_MODE
)


# ============================================================================
# Exception Hierarchy
# ============================================================================

class ModuleError(Exception):
    """Base exception for all module-related errors."""
    pass


# --- Contract Validation Exceptions ---

class BehaviorContractError(ModuleError):
    """Base exception for behavior contract violations."""
    pass


class MissingCallbackError(BehaviorContractError):
    """Required callback is not defined in module."""
    
    def __init__(self, module_name: str, behavior: Atom, callback_name: str):
        self.module_name = module_name
        self.behavior = behavior
        self.callback_name = callback_name
        super().__init__(
            f"Module {module_name} (behavior: {behavior.name}) "
            f"missing required callback: {callback_name}"
        )


class InvalidCallbackError(BehaviorContractError):
    """Callback exists but does not meet requirements."""
    
    def __init__(self, module_name: str, callback_name: str, reason: str):
        self.module_name = module_name
        self.callback_name = callback_name
        self.reason = reason
        super().__init__(
            f"Callback {callback_name} in {module_name} is invalid: {reason}"
        )


class CallbackArityError(BehaviorContractError):
    """Callback has wrong number of parameters."""
    
    def __init__(self, module_name: str, callback_name: str, expected: int, actual: int):
        self.module_name = module_name
        self.callback_name = callback_name
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Callback {callback_name} in {module_name} "
            f"expects {expected} parameters, got {actual}"
        )


class UnknownBehaviorError(BehaviorContractError):
    """Behavior atom is not recognized."""
    
    def __init__(self, behavior: Atom):
        self.behavior = behavior
        super().__init__(f"Unknown behavior: {behavior.name}")


class NoBehaviorSpecifiedError(BehaviorContractError):
    """Module created without specifying a behavior."""
    
    def __init__(self, module_name: str):
        self.module_name = module_name
        super().__init__(
            f"Module {module_name} must specify behavior= in metaclass"
        )


class NoVersionSpecifiedError(ModuleError):
    """Module created without specifying a version."""
    
    def __init__(self, module_name: str):
        self.module_name = module_name
        super().__init__(
            f"Module {module_name} must specify version= in metaclass"
        )


# --- Registration Exceptions ---

class RegistrationError(ModuleError):
    """Base exception for registration failures."""
    pass


class ModuleAlreadyExistsError(RegistrationError):
    """Module with same mod_id already registered."""
    
    def __init__(self, mod_id: str):
        self.mod_id = mod_id
        super().__init__(f"Module {mod_id} is already registered")


class ModuleNotFoundError(RegistrationError):
    """Module lookup failed - not found in registry."""
    
    def __init__(self, identifier: str):
        self.identifier = identifier
        super().__init__(f"Module not found: {identifier}")


class InvalidModuleClassError(RegistrationError):
    """Attempted to register something that is not an OTPModule."""
    
    def __init__(self, obj: Any):
        self.obj = obj
        super().__init__(
            f"Cannot register {type(obj).__name__} - must be OTPModule class"
        )


# --- Version Management Exceptions ---

class VersionError(ModuleError):
    """Base exception for version-related errors."""
    pass


class VersionConflictError(VersionError):
    """Version conflict during reload or registration."""
    
    def __init__(self, mod_id: str, reason: str):
        self.mod_id = mod_id
        self.reason = reason
        super().__init__(f"Version conflict for {mod_id}: {reason}")


class InvalidVersionFormatError(VersionError):
    """Version string format is invalid."""
    
    def __init__(self, version: str, reason: str):
        self.version = version
        self.reason = reason
        super().__init__(f"Invalid version format '{version}': {reason}")


# --- Purge Exceptions ---

class PurgeError(ModuleError):
    """Base exception for purge operation failures."""
    pass


class ModuleInUseError(PurgeError):
    """Cannot purge module - still referenced by processes."""
    
    def __init__(self, mod_id: str, refcount: int):
        self.mod_id = mod_id
        self.refcount = refcount
        super().__init__(
            f"Cannot purge {mod_id} - still in use by {refcount} process(es)"
        )


# --- Loading Exceptions ---

class LoadError(ModuleError):
    """Base exception for code loading failures."""
    pass


class FileLoadError(LoadError):
    """Failed to load module from file."""
    
    def __init__(self, filepath: str, reason: str):
        self.filepath = filepath
        self.reason = reason
        super().__init__(f"Failed to load {filepath}: {reason}")


class CodeExecutionError(LoadError):
    """Error executing module code."""
    
    def __init__(self, code_snippet: str, error: Exception):
        self.code_snippet = code_snippet
        self.error = error
        super().__init__(f"Code execution failed: {error}")


# --- Dependency Exceptions ---

class DependencyError(ModuleError):
    """Base exception for dependency-related errors."""
    pass


class MissingDependencyError(DependencyError):
    """Required dependency module not found."""
    
    def __init__(self, module_name: str, dependency: str):
        self.module_name = module_name
        self.dependency = dependency
        super().__init__(
            f"Module {module_name} depends on {dependency} which is not available"
        )


class CircularDependencyError(DependencyError):
    """Circular dependency detected in module graph."""
    
    def __init__(self, cycle: List[str]):
        self.cycle = cycle
        super().__init__(
            f"Circular dependency detected: {' -> '.join(cycle)}"
        )


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class BehaviorContract:
    """
    Defines the callback contract for an OTP behavior.
    
    Each behavior (gen_server, supervisor, etc.) has a contract specifying
    which callbacks are required and which are optional.
    """
    behavior: Atom
    required_callbacks: List[str]
    optional_callbacks: List[str] = field(default_factory=list)
    validator: Optional[Callable] = None  # Custom validation function
    
    def validate(self, callbacks: Dict[str, Callable]) -> List[str]:
        """
        Validate that callbacks satisfy this contract.
        Returns list of missing required callbacks.
        """
        missing = []
        for callback_name in self.required_callbacks:
            if callback_name not in callbacks:
                missing.append(callback_name)
        return missing
    
    def all_callbacks(self) -> Set[str]:
        """Get set of all callbacks (required + optional)."""
        return set(self.required_callbacks + self.optional_callbacks)


@dataclass
class CallbackSignature:
    """
    Expected signature for a callback function.
    Used for strict signature validation.
    """
    name: str
    arity: int  # Number of parameters (including self)
    param_names: Optional[List[str]] = None
    returns: Optional[str] = None  # Expected return type description
    
    def matches(self, func: Callable) -> bool:
        """Check if function matches this signature."""
        import inspect
        sig = inspect.signature(func)
        return len(sig.parameters) == self.arity


@dataclass
class ModuleMetadata:
    """
    Complete metadata for a registered module.
    This is what code_server stores for each module.
    """
    mod_id: str
    name: str
    version: str
    behavior: Atom
    module_class: type
    callbacks: Dict[str, Callable]
    atoms: Dict[str, Atom]
    registered_at: float
    dependencies: List[str] = field(default_factory=list)
    refcount: int = 0
    is_current: bool = True
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization/introspection."""
        return {
            'mod_id': self.mod_id,
            'name': self.name,
            'version': self.version,
            'behavior': self.behavior.name,
            'callbacks': list(self.callbacks.keys()),
            'registered_at': self.registered_at,
            'dependencies': self.dependencies,
            'refcount': self.refcount,
            'is_current': self.is_current
        }


@dataclass
class ModuleInfo:
    """
    Rich information about a module for introspection.
    Returned by code_server info queries.
    """
    mod_id: str
    name: str
    version: str
    behavior: str
    callbacks: List[str]
    registered_at: float
    is_current: bool
    refcount: int
    dependencies: List[str]
    state: str  # 'current', 'old', 'purged', etc.
    
    @classmethod
    def from_metadata(cls, metadata: ModuleMetadata, state: str) -> 'ModuleInfo':
        """Create ModuleInfo from ModuleMetadata."""
        return cls(
            mod_id=metadata.mod_id,
            name=metadata.name,
            version=metadata.version,
            behavior=metadata.behavior.name,
            callbacks=list(metadata.callbacks.keys()),
            registered_at=metadata.registered_at,
            is_current=metadata.is_current,
            refcount=metadata.refcount,
            dependencies=metadata.dependencies,
            state=state
        )


@dataclass
class LoadRequest:
    """
    Request to load module code.
    Used in code_server load operations.
    """
    source_type: str  # 'file', 'code', 'import'
    source: str       # filepath, code string, or module name
    force_reload: bool = False
    register_immediately: bool = True
    
    def __repr__(self):
        return f"LoadRequest(type={self.source_type}, source={self.source[:50]}...)"


@dataclass
class ReloadResult:
    """
    Result of a module reload operation.
    """
    success: bool
    old_mod_id: Optional[str]
    new_mod_id: Optional[str]
    error: Optional[Exception] = None
    message: str = ""
    
    def to_dict(self) -> dict:
        return {
            'success': self.success,
            'old_mod_id': self.old_mod_id,
            'new_mod_id': self.new_mod_id,
            'error': str(self.error) if self.error else None,
            'message': self.message
        }


@dataclass
class SystemReport:
    """
    Comprehensive report of code_server state.
    """
    total_modules: int
    unique_modules: int
    behaviors: Dict[str, int]
    total_references: int
    modules_in_use: int
    purgeable_modules: int
    current_versions: Dict[str, str]
    old_versions: List[str]
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    
    def to_dict(self) -> dict:
        return {
            'total_modules': self.total_modules,
            'unique_modules': self.unique_modules,
            'behaviors': self.behaviors,
            'total_references': self.total_references,
            'modules_in_use': self.modules_in_use,
            'purgeable_modules': self.purgeable_modules,
            'current_versions': self.current_versions,
            'old_versions': self.old_versions,
            'timestamp': self.timestamp
        }


# ============================================================================
# Behavior Contracts Registry
# ============================================================================

BEHAVIOR_CONTRACTS: Dict[Atom, BehaviorContract] = {
    GEN_SERVER: BehaviorContract(
        behavior=GEN_SERVER,
        required_callbacks=[
            'init',
            'handle_call',
            'handle_cast',
            'handle_info',
            'terminate'
        ],
        optional_callbacks=['code_change']
    ),
    
    SUPERVISOR: BehaviorContract(
        behavior=SUPERVISOR,
        required_callbacks=[
            'init',
            'terminate'
        ],
        optional_callbacks=['handle_child_exit']
    ),
    
    DYNAMIC_SUPERVISOR: BehaviorContract(
        behavior=DYNAMIC_SUPERVISOR,
        required_callbacks=[
            'init',
            'terminate'
        ],
        optional_callbacks=[]
    ),
    
    APPLICATION: BehaviorContract(
        behavior=APPLICATION,
        required_callbacks=[
            'start',
            'stop'
        ],
        optional_callbacks=['config_change']
    ),
    
    GEN_STATEM: BehaviorContract(
        behavior=GEN_STATEM,
        required_callbacks=[
            'init',
            'callback_mode',
            'terminate'
        ],
        optional_callbacks=['code_change']
        # Note: State function names are dynamic, validated differently
    ),
    
    GEN_EVENT: BehaviorContract(
        behavior=GEN_EVENT,
        required_callbacks=[
            'init',
            'handle_event',
            'terminate'
        ],
        optional_callbacks=['code_change']
    ),
    
    TASK: BehaviorContract(
        behavior=TASK,
        required_callbacks=[
            'run'
        ],
        optional_callbacks=[]
    )
}


# ============================================================================
# Callback Signatures (Optional Strict Validation)
# ============================================================================

CALLBACK_SIGNATURES: Dict[Atom, Dict[str, CallbackSignature]] = {
    GEN_SERVER: {
        'init': CallbackSignature(
            name='init',
            arity=2,  # self, args
            param_names=['self', 'args'],
            returns="state"
        ),
        'handle_call': CallbackSignature(
            name='handle_call',
            arity=4,  # self, request, from_pid, state
            param_names=['self', 'request', 'from_pid', 'state'],
            returns="(Reply | NoReply | Stop, state)"
        ),
        'handle_cast': CallbackSignature(
            name='handle_cast',
            arity=3,  # self, message, state
            param_names=['self', 'message', 'state'],
            returns="(NoReply | Stop, state)"
        ),
        'handle_info': CallbackSignature(
            name='handle_info',
            arity=3,  # self, message, state
            param_names=['self', 'message', 'state'],
            returns="(NoReply | Stop, state)"
        ),
        'terminate': CallbackSignature(
            name='terminate',
            arity=3,  # self, reason, state
            param_names=['self', 'reason', 'state'],
            returns="None"
        )
    },
    
    SUPERVISOR: {
        'init': CallbackSignature(
            name='init',
            arity=2,  # self, args
            param_names=['self', 'args'],
            returns="(children: List[child_spec], opts: options)"
        ),
        'terminate': CallbackSignature(
            name='terminate',
            arity=3,  # self, reason, state
            param_names=['self', 'reason', 'state'],
            returns="None"
        )
    },
    
    DYNAMIC_SUPERVISOR: {
        'init': CallbackSignature(
            name='init',
            arity=2,  # self, args
            param_names=['self', 'args'],
            returns="(children: List[child_spec], opts: options)"
        ),
        'terminate': CallbackSignature(
            name='terminate',
            arity=3,  # self, reason, state
            param_names=['self', 'reason', 'state'],
            returns="None"
        )
    },
    
    APPLICATION: {
        'start': CallbackSignature(
            name='start',
            arity=3,  # self, start_type, args
            param_names=['self', 'start_type', 'args'],
            returns="pid"
        ),
        'stop': CallbackSignature(
            name='stop',
            arity=2,  # self, state
            param_names=['self', 'state'],
            returns="None"
        )
    },
    
    GEN_STATEM: {
        'init': CallbackSignature(
            name='init',
            arity=2,  # self, args
            param_names=['self', 'args'],
            returns="(state_name, state_data) or (state_name, state_data, actions)"
        ),
        'callback_mode': CallbackSignature(
            name='callback_mode',
            arity=1,  # self
            param_names=['self'],
            returns="CallbackMode.STATE_FUNCTIONS or CallbackMode.HANDLE_EVENT_FUNCTION"
        ),
        'terminate': CallbackSignature(
            name='terminate',
            arity=4,  # self, reason, state_name, state_data
            param_names=['self', 'reason', 'state_name', 'state_data'],
            returns="None"
        ),
        # Note: State functions (state_<name>) are dynamic and validated at runtime
        # handle_event is only required if callback_mode returns HANDLE_EVENT_FUNCTION
        'handle_event': CallbackSignature(
            name='handle_event',
            arity=5,  # self, event_type, event_content, state_name, state_data
            param_names=['self', 'event_type', 'event_content', 'state_name', 'state_data'],
            returns="NextState | KeepState | RepeatState | StopState"
        )
    }
}


# ============================================================================
# Utility Functions
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


def parse_mod_id(mod_id: str) -> tuple[str, str]:
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
