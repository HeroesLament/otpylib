"""
Runtime Atoms

Pure atom definitions for the otpylib runtime system.
No logic, no validation, just atom creation.
"""

from otpylib import atom

# =============================================================================
# Process Types
# =============================================================================

GEN_SERVER = atom.ensure("gen_server")
SUPERVISOR = atom.ensure("supervisor")
DYNAMIC_SUPERVISOR = atom.ensure("dynamic_supervisor")
WORKER = atom.ensure("worker")
TASK = atom.ensure("task")
APPLICATION = atom.ensure("application")

# =============================================================================
# Process States
# =============================================================================

STARTING = atom.ensure("starting")
RUNNING = atom.ensure("running")
WAITING = atom.ensure("waiting")
SUSPENDED = atom.ensure("suspended")
TERMINATING = atom.ensure("terminating")
TERMINATED = atom.ensure("terminated")

# =============================================================================
# Exit Reasons
# =============================================================================

NORMAL = atom.ensure("normal")
SHUTDOWN = atom.ensure("shutdown")
SUPERVISOR_SHUTDOWN = atom.ensure("supervisor_shutdown")
KILLED = atom.ensure("killed")
ABNORMAL = atom.ensure("abnormal")
NOPROC = atom.ensure("noproc")
TIMEOUT = atom.ensure("timeout")
BADARITH = atom.ensure("badarith")
BADARG = atom.ensure("badarg")
UNDEF = atom.ensure("undef")
BADFUN = atom.ensure("badfun")
BADMATCH = atom.ensure("badmatch")
FUNCTION_CLAUSE = atom.ensure("function_clause")
CASE_CLAUSE = atom.ensure("case_clause")
IF_CLAUSE = atom.ensure("if_clause")
SYSTEM_LIMIT = atom.ensure("system_limit")
MAX_RESTART_INTENSITY = atom.ensure("max_restart_intensity")
SHUTDOWN_ERROR = atom.ensure("shutdown_error")
CHILD_UNDEFINED = atom.ensure("child_undefined")
ALREADY_PRESENT = atom.ensure("already_present")
ALREADY_STARTED = atom.ensure("already_started")
NOT_FOUND = atom.ensure("not_found")
SIMPLE_ONE_FOR_ONE = atom.ensure("simple_one_for_one")
NOT_STARTED = atom.ensure("not_started")

# =============================================================================
# Monitor & Link Messages
# =============================================================================

DOWN = atom.ensure("DOWN")
PROCESS = atom.ensure("process")
NOCONNECTION = atom.ensure("noconnection")
EXIT = atom.ensure("EXIT")
EXIT_SIGNAL = atom.ensure("exit_signal")
PROCESS_INFO = atom.ensure("process_info")
UNDEFINED = atom.ensure("undefined")

# =============================================================================
# Supervisor Strategies
# =============================================================================

ONE_FOR_ONE = atom.ensure("one_for_one")
ONE_FOR_ALL = atom.ensure("one_for_all")
REST_FOR_ONE = atom.ensure("rest_for_one")

# =============================================================================
# Child Restart Types
# =============================================================================

PERMANENT = atom.ensure("permanent")
TEMPORARY = atom.ensure("temporary")
TRANSIENT = atom.ensure("transient")

# =============================================================================
# Child Shutdown Types
# =============================================================================

BRUTAL_KILL = atom.ensure("brutal_kill")
INFINITY = atom.ensure("infinity")

# =============================================================================
# Gen_Server Response Types
# =============================================================================

REPLY = atom.ensure("reply")
NOREPLY = atom.ensure("noreply")
STOP = atom.ensure("stop")
CONTINUE = atom.ensure("continue")
HIBERNATE = atom.ensure("hibernate")

# =============================================================================
# Call/Cast/Info Types
# =============================================================================

CALL = atom.ensure("call")
CAST = atom.ensure("cast")
INFO = atom.ensure("info")
TIMEOUT_ATOM = atom.ensure("timeout")
HIBERNATE_AFTER = atom.ensure("hibernate_after")

# =============================================================================
# System Messages
# =============================================================================

SYSTEM = atom.ensure("system")
GET_STATE = atom.ensure("get_state")
GET_STATUS = atom.ensure("get_status")
SUSPEND = atom.ensure("suspend")
RESUME = atom.ensure("resume")
CHANGE_CODE = atom.ensure("change_code")
TERMINATE = atom.ensure("terminate")
DEBUG = atom.ensure("debug")
TRACE = atom.ensure("trace")
STATISTICS = atom.ensure("statistics")
LOG = atom.ensure("log")
NO_DEBUG = atom.ensure("no_debug")

# =============================================================================
# Name Registration
# =============================================================================

LOCAL = atom.ensure("local")
GLOBAL = atom.ensure("global")
VIA = atom.ensure("via")
YES = atom.ensure("yes")
NO = atom.ensure("no")
OK = atom.ensure("ok")
ERROR = atom.ensure("error")

# =============================================================================
# Application & Node Status
# =============================================================================

LOADED = atom.ensure("loaded")
STARTED = atom.ensure("started")
STOPPED = atom.ensure("stopped")
UNLOADED = atom.ensure("unloaded")
ALIVE = atom.ensure("alive")
VISIBLE = atom.ensure("visible")
HIDDEN = atom.ensure("hidden")
THIS = atom.ensure("this")
KNOWN = atom.ensure("known")
CONNECTED = atom.ensure("connected")
DISCONNECTED = atom.ensure("disconnected")

# =============================================================================
# Runtime-Specific
# =============================================================================

BACKEND_ANYIO = atom.ensure("backend_anyio")
BACKEND_SPAM = atom.ensure("backend_spam")
BACKEND_NATIVE = atom.ensure("backend_native")

SPAWN = atom.ensure("spawn")
SPAWN_LINK = atom.ensure("spawn_link")
SPAWN_MONITOR = atom.ensure("spawn_monitor")
LINK = atom.ensure("link")
UNLINK = atom.ensure("unlink")
MONITOR = atom.ensure("monitor")
DEMONITOR = atom.ensure("demonitor")
TRAP_EXIT = atom.ensure("trap_exit")

MAILBOX_CREATE = atom.ensure("mailbox_create")
MAILBOX_DESTROY = atom.ensure("mailbox_destroy")
MAILBOX_SEND = atom.ensure("mailbox_send")
MAILBOX_RECEIVE = atom.ensure("mailbox_receive")
MAILBOX_REGISTER = atom.ensure("mailbox_register")
MAILBOX_UNREGISTER = atom.ensure("mailbox_unregister")

# =============================================================================
# Priority Levels
# =============================================================================

HIGH = atom.ensure("high")
NORMAL_PRIORITY = atom.ensure("normal_priority")
LOW = atom.ensure("low")
MAX = atom.ensure("max")
MAX_PRIORITY = atom.ensure("max_priority")
HIGH_PRIORITY = atom.ensure("high_priority")
NORMAL_PROCESS = atom.ensure("normal_process")
LOW_PRIORITY = atom.ensure("low_priority")
