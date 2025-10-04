"""
gen_server.atoms

Canonical set of Atoms used for GenServer lifecycle, events, actions, 
message types, and contract errors. This vocabulary is used consistently 
across otpylib to enforce OTP-style semantics and provide introspection.

These atoms are not user-facing messages — they are internal markers for 
logging, supervision, metrics, and error reasons.
"""

from otpylib.atom import ensure

# ============================================================================
# Lifecycle State Atoms
# ============================================================================
# Track the internal lifecycle of a GenServer process.
# BEAM itself does not expose all of these explicitly, but they are useful
# for tracing and introspection.

INITIALIZING         = ensure("initializing")
RUNNING              = ensure("running")
WAITING_FOR_MESSAGE  = ensure("waiting_for_message")
PROCESSING_MESSAGE   = ensure("processing_message")
STOPPING             = ensure("stopping")
CRASHED              = ensure("crashed")
TERMINATED           = ensure("terminated")


# ============================================================================
# Event Atoms
# ============================================================================
# Represent significant internal events in a GenServer lifecycle.
# Useful for telemetry, logging, or external monitoring.

INIT_SUCCESS         = ensure("init_success")
INIT_FAILED          = ensure("init_failed")
MESSAGE_RECEIVED     = ensure("message_received")
MESSAGE_PROCESSED    = ensure("message_processed")
STOP_REQUESTED       = ensure("stop_requested")
HANDLER_STOP         = ensure("handler_stop")
EXCEPTION_OCCURRED   = ensure("exception_occurred")
MAILBOX_CLOSED       = ensure("mailbox_closed")
TIMEOUT_OCCURRED     = ensure("timeout_occurred")
LINK_DOWN            = ensure("link_down")
MONITOR_DOWN         = ensure("monitor_down")


# ============================================================================
# Action Atoms
# ============================================================================
# Actions that a GenServer handler may request, or that supervision
# may take in response to failure.

CONTINUE             = ensure("continue")
STOP_ACTION          = ensure("stop")
CRASH                = ensure("crash")
RESTART              = ensure("restart")
IGNORE               = ensure("ignore")


# ============================================================================
# Message Type Atoms
# ============================================================================
# Classify the three primary kinds of GenServer messages.
# BEAM uses internal tuples ('$gen_call', '$gen_cast'), we normalize to atoms.

CALL                 = ensure("call")
CAST                 = ensure("cast")
INFO                 = ensure("info")


# ============================================================================
# Contract Violation Atoms
# ============================================================================
# Used as exit reasons when a GenServer handler breaks the OTP contract.
# Mirrors Erlang/BEAM crash reasons like `badarg`, `bad_return_value`.

BADARITY             = ensure("badarity")    # Handler has wrong number of args
BADRETURN            = ensure("badreturn")   # Handler returned invalid value
BADMESSAGE           = ensure("badmessage")  # Unexpected internal message leak


# ============================================================================
# Exit Reasons
# ============================================================================
# Standardized exit reasons for supervised processes.
DOWN                 = ensure("down")
EXIT                 = ensure("exit")
TIMEOUT              = ensure("timeout")


# ============================================================================
# Exit Reason Aliases
# ============================================================================
# Standardized exit reason aliases for supervised processes.

NORMAL               = ensure("normal")      # Normal exit
SHUTDOWN             = ensure("shutdown")    # Graceful supervisor shutdown
KILLED               = ensure("killed")      # Untrappable kill
