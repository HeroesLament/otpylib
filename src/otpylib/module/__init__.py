"""
otpylib.module

OTP module system for Python - metaclass-based module definitions with
behavior contracts, validation, and hot code reloading support.

Public API exports for creating and introspecting OTP modules.
"""

# Core metaclass
from .core import OTPModule

# Introspection functions
from .core import (
    is_otp_module,
    get_module_info,
    list_callbacks,
    get_behavior,
    get_version
)

# Behavior atoms
from .atoms import (
    GEN_SERVER,
    SUPERVISOR,
    DYNAMIC_SUPERVISOR,
    APPLICATION,
    GEN_STATEM,
    GEN_EVENT,
    TASK
)

# Exception types
from .data import (
    ModuleError,
    BehaviorContractError,
    MissingCallbackError,
    InvalidCallbackError,
    CallbackArityError,
    UnknownBehaviorError,
    NoBehaviorSpecifiedError,
    NoVersionSpecifiedError,
    RegistrationError,
    ModuleAlreadyExistsError,
    ModuleNotFoundError,
    InvalidModuleClassError,
    VersionError,
    VersionConflictError,
    InvalidVersionFormatError,
    PurgeError,
    ModuleInUseError,
    LoadError,
    FileLoadError,
    CodeExecutionError,
    DependencyError,
    MissingDependencyError,
    CircularDependencyError
)

# Data structures
from .data import (
    BehaviorContract,
    CallbackSignature,
    ModuleMetadata,
    ModuleInfo,
    LoadRequest,
    ReloadResult,
    SystemReport,
    BEHAVIOR_CONTRACTS,
    CALLBACK_SIGNATURES
)


__all__ = [
    # Core metaclass
    'OTPModule',
    
    # Introspection
    'is_otp_module',
    'get_module_info',
    'list_callbacks',
    'get_behavior',
    'get_version',
    
    # Behavior atoms
    'GEN_SERVER',
    'SUPERVISOR',
    'DYNAMIC_SUPERVISOR',
    'APPLICATION',
    'GEN_STATEM',
    'GEN_EVENT',
    'TASK',
    
    # Exceptions
    'ModuleError',
    'BehaviorContractError',
    'MissingCallbackError',
    'InvalidCallbackError',
    'CallbackArityError',
    'UnknownBehaviorError',
    'NoBehaviorSpecifiedError',
    'NoVersionSpecifiedError',
    'RegistrationError',
    'ModuleAlreadyExistsError',
    'ModuleNotFoundError',
    'InvalidModuleClassError',
    'VersionError',
    'VersionConflictError',
    'InvalidVersionFormatError',
    'PurgeError',
    'ModuleInUseError',
    'LoadError',
    'FileLoadError',
    'CodeExecutionError',
    'DependencyError',
    'MissingDependencyError',
    'CircularDependencyError',
    
    # Data structures
    'BehaviorContract',
    'CallbackSignature',
    'ModuleMetadata',
    'ModuleInfo',
    'LoadRequest',
    'ReloadResult',
    'SystemReport',
    'BEHAVIOR_CONTRACTS',
    'CALLBACK_SIGNATURES',
]