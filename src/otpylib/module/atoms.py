"""
otpylib.module.atoms

Complete canonical vocabulary of atoms used by the OTPModule metaclass system,
code_server, and module lifecycle management.

These atoms are used for:
- Module lifecycle states
- Registration events
- Validation results
- Error reasons
- Loading mechanisms
- Version transitions
- Reference counting operations
- Behavior classification
- Contract enforcement
"""

from otpylib.atom import ensure


# ============================================================================
# Behavior Type Atoms
# ============================================================================
# Core OTP behavior patterns that modules can implement

GEN_SERVER          = ensure("gen_server")
SUPERVISOR          = ensure("supervisor")
DYNAMIC_SUPERVISOR  = ensure("dynamic_supervisor")
APPLICATION         = ensure("application")
GEN_STATEM          = ensure("gen_statem")
GEN_EVENT           = ensure("gen_event")
TASK                = ensure("task")


# ============================================================================
# Module Lifecycle State Atoms
# ============================================================================
# Track the state of a module from creation through purge

CREATED             = ensure("created")           # Class created by metaclass
VALIDATED           = ensure("validated")         # Contract validation passed
REGISTERED          = ensure("registered")        # Registered with code_server
CURRENT             = ensure("current")           # Active version for new spawns
OLD                 = ensure("old")               # Superseded by newer version
PURGING             = ensure("purging")           # Being removed from system
PURGED              = ensure("purged")            # Removed from code_server
FAILED              = ensure("failed")            # Creation/validation failed


# ============================================================================
# Registration Event Atoms
# ============================================================================
# Events emitted during module registration process

REGISTRATION_STARTED    = ensure("registration_started")
REGISTRATION_SUCCESS    = ensure("registration_success")
REGISTRATION_FAILED     = ensure("registration_failed")
DUPLICATE_REGISTRATION  = ensure("duplicate_registration")
SUPERSEDED              = ensure("superseded")        # Old version superseded
PROMOTED                = ensure("promoted")          # Version promoted to current


# ============================================================================
# Validation Event Atoms
# ============================================================================
# Events during contract validation

VALIDATION_STARTED      = ensure("validation_started")
VALIDATION_PASSED       = ensure("validation_passed")
VALIDATION_FAILED       = ensure("validation_failed")
CONTRACT_CHECKED        = ensure("contract_checked")
CALLBACKS_COLLECTED     = ensure("callbacks_collected")
SIGNATURE_VERIFIED      = ensure("signature_verified")


# ============================================================================
# Contract Violation Atoms
# ============================================================================
# Specific reasons for contract validation failures

MISSING_CALLBACK        = ensure("missing_callback")
INVALID_CALLBACK        = ensure("invalid_callback")
CALLBACK_NOT_ASYNC      = ensure("callback_not_async")
WRONG_ARITY             = ensure("wrong_arity")
WRONG_SIGNATURE         = ensure("wrong_signature")
UNKNOWN_BEHAVIOR        = ensure("unknown_behavior")
NO_BEHAVIOR_SPECIFIED   = ensure("no_behavior_specified")
NO_VERSION_SPECIFIED    = ensure("no_version_specified")
INVALID_VERSION_FORMAT  = ensure("invalid_version_format")
DUPLICATE_CALLBACK      = ensure("duplicate_callback")


# ============================================================================
# Loading Mechanism Atoms
# ============================================================================
# How modules enter the system

LOADED_VIA_IMPORT       = ensure("loaded_via_import")
LOADED_VIA_FILE         = ensure("loaded_via_file")
LOADED_VIA_CODE_STRING  = ensure("loaded_via_code_string")
LOADED_VIA_EXEC         = ensure("loaded_via_exec")
LOADED_VIA_METACLASS    = ensure("loaded_via_metaclass")
LOAD_REQUESTED          = ensure("load_requested")
LOAD_STARTED            = ensure("load_started")
LOAD_COMPLETED          = ensure("load_completed")
LOAD_FAILED             = ensure("load_failed")


# ============================================================================
# Version Transition Atoms
# ============================================================================
# Hot reload and version management events

RELOAD_REQUESTED        = ensure("reload_requested")
RELOAD_STARTED          = ensure("reload_started")
RELOAD_COMPLETED        = ensure("reload_completed")
RELOAD_FAILED           = ensure("reload_failed")
UPGRADE_STARTED         = ensure("upgrade_started")
UPGRADE_COMPLETED       = ensure("upgrade_completed")
UPGRADE_FAILED          = ensure("upgrade_failed")
DOWNGRADE_STARTED       = ensure("downgrade_started")
DOWNGRADE_COMPLETED     = ensure("downgrade_completed")
VERSION_CONFLICT        = ensure("version_conflict")
CODE_CHANGE             = ensure("code_change")


# ============================================================================
# Reference Counting Atoms
# ============================================================================
# Process reference tracking events

REFCOUNT_INCREMENTED    = ensure("refcount_incremented")
REFCOUNT_DECREMENTED    = ensure("refcount_decremented")
REFCOUNT_ZERO           = ensure("refcount_zero")
REFCOUNT_NONZERO        = ensure("refcount_nonzero")
FIRST_REFERENCE         = ensure("first_reference")
LAST_REFERENCE_DROPPED  = ensure("last_reference_dropped")


# ============================================================================
# Purge Operation Atoms
# ============================================================================
# Module removal events

PURGE_REQUESTED         = ensure("purge_requested")
PURGE_STARTED           = ensure("purge_started")
PURGE_COMPLETED         = ensure("purge_completed")
PURGE_FAILED            = ensure("purge_failed")
PURGE_BLOCKED           = ensure("purge_blocked")      # Module still in use
FORCED_PURGE            = ensure("forced_purge")       # force=True override
AUTO_PURGE              = ensure("auto_purge")         # Automatic cleanup


# ============================================================================
# Lookup Operation Atoms
# ============================================================================
# Module lookup results

LOOKUP_SUCCESS          = ensure("lookup_success")
LOOKUP_FAILED           = ensure("lookup_failed")
MODULE_NOT_FOUND        = ensure("module_not_found")
MODULE_FOUND            = ensure("module_found")
MULTIPLE_VERSIONS_FOUND = ensure("multiple_versions_found")


# ============================================================================
# Code Server Action Atoms
# ============================================================================
# Actions that code_server can take

REGISTER                = ensure("register")
UNREGISTER              = ensure("unregister")
LOOKUP                  = ensure("lookup")
LOOKUP_EXACT            = ensure("lookup_exact")
LOOKUP_BY_BEHAVIOR      = ensure("lookup_by_behavior")
LIST_MODULES            = ensure("list_modules")
LIST_VERSIONS           = ensure("list_versions")
GET_CURRENT             = ensure("get_current")
SET_CURRENT             = ensure("set_current")
PROMOTE_VERSION         = ensure("promote_version")
DEMOTE_VERSION          = ensure("demote_version")
INCREF                  = ensure("incref")
DECREF                  = ensure("decref")
GET_REFCOUNT            = ensure("get_refcount")
PURGE_MODULE            = ensure("purge_module")
PURGE_OLD_VERSIONS      = ensure("purge_old_versions")
LOAD_FILE               = ensure("load_file")
LOAD_CODE               = ensure("load_code")
RELOAD_MODULE           = ensure("reload_module")
MODULE_INFO             = ensure("module_info")
SYSTEM_REPORT           = ensure("system_report")


# ============================================================================
# Error Reason Atoms
# ============================================================================
# Standardized error reasons for module operations

MODULE_ALREADY_EXISTS   = ensure("module_already_exists")
MODULE_IN_USE           = ensure("module_in_use")
INVALID_MOD_ID          = ensure("invalid_mod_id")
INVALID_MODULE_CLASS    = ensure("invalid_module_class")
REGISTRATION_ERROR      = ensure("registration_error")
VALIDATION_ERROR        = ensure("validation_error")
LOAD_ERROR              = ensure("load_error")
RELOAD_ERROR            = ensure("reload_error")
PURGE_ERROR             = ensure("purge_error")
SYNTAX_ERROR            = ensure("syntax_error")
IMPORT_ERROR            = ensure("import_error")
EXECUTION_ERROR         = ensure("execution_error")


# ============================================================================
# Response Status Atoms
# ============================================================================
# Standard response atoms for code_server calls

OK                      = ensure("ok")
ERROR                   = ensure("error")
SUCCESS                 = ensure("success")
FAILURE                 = ensure("failure")
ACCEPTED                = ensure("accepted")
REJECTED                = ensure("rejected")
PENDING                 = ensure("pending")
TIMEOUT                 = ensure("timeout")


# ============================================================================
# Metadata Field Atoms
# ============================================================================
# Keys for module metadata dictionaries

BEHAVIOR                = ensure("behavior")
VERSION                 = ensure("version")
MOD_ID                  = ensure("mod_id")
MODNAME                 = ensure("modname")
CALLBACKS               = ensure("callbacks")
REGISTERED_AT           = ensure("registered_at")
DEPENDENCIES            = ensure("dependencies")
ATOMS                   = ensure("atoms")
RELOAD_HOOK             = ensure("reload_hook")
UPGRADE_HOOK            = ensure("upgrade_hook")
PURGE_HOOK              = ensure("purge_hook")


# ============================================================================
# Callback Name Atoms
# ============================================================================
# Standard callback names across behaviors

INIT                    = ensure("init")
TERMINATE               = ensure("terminate")
CODE_CHANGE             = ensure("code_change")
HANDLE_CALL             = ensure("handle_call")
HANDLE_CAST             = ensure("handle_cast")
HANDLE_INFO             = ensure("handle_info")
HANDLE_CHILD_EXIT       = ensure("handle_child_exit")
START                   = ensure("start")
STOP                    = ensure("stop")
CONFIG_CHANGE           = ensure("config_change")
CALLBACK_MODE           = ensure("callback_mode")


# ============================================================================
# File Operation Atoms
# ============================================================================
# File loading and watching operations

FILE_FOUND              = ensure("file_found")
FILE_NOT_FOUND          = ensure("file_not_found")
FILE_MODIFIED           = ensure("file_modified")
FILE_CREATED            = ensure("file_created")
FILE_DELETED            = ensure("file_deleted")
DIRECTORY_WATCHED       = ensure("directory_watched")
WATCH_STARTED           = ensure("watch_started")
WATCH_STOPPED           = ensure("watch_stopped")


# ============================================================================
# Dependency Management Atoms
# ============================================================================
# Module dependency tracking

DEPENDENCY_SATISFIED    = ensure("dependency_satisfied")
DEPENDENCY_MISSING      = ensure("dependency_missing")
CIRCULAR_DEPENDENCY     = ensure("circular_dependency")
DEPENDENCY_VERSION_MISMATCH = ensure("dependency_version_mismatch")
DEPENDENCY_GRAPH_BUILT  = ensure("dependency_graph_built")


# ============================================================================
# Introspection Atoms
# ============================================================================
# Query and inspection operations

INFO_REQUESTED          = ensure("info_requested")
INFO_PROVIDED           = ensure("info_provided")
REPORT_GENERATED        = ensure("report_generated")
STATS_COLLECTED         = ensure("stats_collected")
MODULE_COUNT            = ensure("module_count")
VERSION_COUNT           = ensure("version_count")
BEHAVIOR_COUNT          = ensure("behavior_count")
TOTAL_REFERENCES        = ensure("total_references")


# ============================================================================
# Telemetry Event Atoms
# ============================================================================
# Events for monitoring and observability

MODULE_CREATED_EVENT    = ensure("module.created")
MODULE_REGISTERED_EVENT = ensure("module.registered")
MODULE_VALIDATED_EVENT  = ensure("module.validated")
MODULE_LOADED_EVENT     = ensure("module.loaded")
MODULE_RELOADED_EVENT   = ensure("module.reloaded")
MODULE_PURGED_EVENT     = ensure("module.purged")
REFCOUNT_CHANGED_EVENT  = ensure("module.refcount_changed")
VERSION_CHANGED_EVENT   = ensure("module.version_changed")


# ============================================================================
# Special Marker Atoms
# ============================================================================
# Special values and markers

UNDEFINED               = ensure("undefined")
NONE_VALUE              = ensure("none")
DEFAULT                 = ensure("default")
ALL                     = ensure("all")
ANY                     = ensure("any")
LATEST                  = ensure("latest")
OLDEST                  = ensure("oldest")