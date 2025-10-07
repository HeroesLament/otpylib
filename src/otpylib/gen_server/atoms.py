"""
gen_server.atoms

Canonical set of Atoms used for GenServer lifecycle, events, actions, 
message types, and contract errors. This vocabulary is used consistently 
across otpylib to enforce OTP-style semantics and provide introspection.

These atoms are not user-facing messages — they are internal markers for 
logging, supervision, metrics, and error reasons.
"""

from otpylib import atom

# ============================================================================
# Lifecycle State Atoms
# ============================================================================
# Track the internal lifecycle of a GenServer process.
# BEAM itself does not expose all of these explicitly, but they are useful
# for tracing and introspection.

INITIALIZING         = atom.ensure("initializing")
RUNNING              = atom.ensure("running")
WAITING_FOR_MESSAGE  = atom.ensure("waiting_for_message")
PROCESSING_MESSAGE   = atom.ensure("processing_message")
STOPPING             = atom.ensure("stopping")
CRASHED              = atom.ensure("crashed")
TERMINATED           = atom.ensure("terminated")


# ============================================================================
# Event Atoms
# ============================================================================
# Represent significant internal events in a GenServer lifecycle.
# Useful for telemetry, logging, or external monitoring.

INIT_SUCCESS         = atom.ensure("init_success")
INIT_FAILED          = atom.ensure("init_failed")
MESSAGE_RECEIVED     = atom.ensure("message_received")
MESSAGE_PROCESSED    = atom.ensure("message_processed")
STOP_REQUESTED       = atom.ensure("stop_requested")
HANDLER_STOP         = atom.ensure("handler_stop")
EXCEPTION_OCCURRED   = atom.ensure("exception_occurred")
MAILBOX_CLOSED       = atom.ensure("mailbox_closed")
TIMEOUT_OCCURRED     = atom.ensure("timeout_occurred")
LINK_DOWN            = atom.ensure("link_down")
MONITOR_DOWN         = atom.ensure("monitor_down")


# ============================================================================
# Action Atoms
# ============================================================================
# Actions that a GenServer handler may request, or that supervision
# may take in response to failure.

CONTINUE             = atom.ensure("continue")
STOP_ACTION          = atom.ensure("stop")
CRASH                = atom.ensure("crash")
RESTART              = atom.ensure("restart")
IGNORE               = atom.ensure("ignore")


# ============================================================================
# Message Type Atoms
# ============================================================================
# Classify the three primary kinds of GenServer messages.
# BEAM uses internal tuples ('$gen_call', '$gen_cast'), we normalize to atoms.

CALL                 = atom.ensure("call")
CAST                 = atom.ensure("cast")
INFO                 = atom.ensure("info")


# ============================================================================
# Contract Violation Atoms
# ============================================================================
# Used as exit reasons when a GenServer handler breaks the OTP contract.
# Mirrors Erlang/BEAM crash reasons like `badarg`, `bad_return_value`.

BADARITY             = atom.ensure("badarity")    # Handler has wrong number of args
BADRETURN            = atom.ensure("badreturn")   # Handler returned invalid value
BADMESSAGE           = atom.ensure("badmessage")  # Unexpected internal message leak


# ============================================================================
# Exit Reasons
# ============================================================================
# Standardized exit reasons for supervised processes.
DOWN                 = atom.ensure("down")
EXIT                 = atom.ensure("exit")
TIMEOUT              = atom.ensure("timeout")


# ============================================================================
# Exit Reason Aliases
# ============================================================================
# Standardized exit reason aliases for supervised processes.

NORMAL               = atom.ensure("normal")      # Normal exit
SHUTDOWN             = atom.ensure("shutdown")    # Graceful supervisor shutdown
KILLED               = atom.ensure("killed")      # Untrappable kill
