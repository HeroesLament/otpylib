from otpylib.atom import ensure

# GenServer Lifecycle State Atoms
INITIALIZING = ensure("initializing")
RUNNING = ensure("running")
WAITING_FOR_MESSAGE = ensure("waiting_for_message")
PROCESSING_MESSAGE = ensure("processing_message")
STOPPING = ensure("stopping")
CRASHED = ensure("crashed")
TERMINATED = ensure("terminated")

# GenServer Event Atoms
INIT_SUCCESS = ensure("init_success")
INIT_FAILED = ensure("init_failed")
MESSAGE_RECEIVED = ensure("message_received")
MESSAGE_PROCESSED = ensure("message_processed")
STOP_REQUESTED = ensure("stop_requested")
HANDLER_STOP = ensure("handler_stop")
EXCEPTION_OCCURRED = ensure("exception_occurred")
MAILBOX_CLOSED = ensure("mailbox_closed")
TIMEOUT_OCCURRED = ensure("timeout_occurred")

# GenServer Action Atoms
CONTINUE = ensure("continue")
STOP_ACTION = ensure("stop")
CRASH = ensure("crash")
RESTART = ensure("restart")
IGNORE = ensure("ignore")

# Message Type Atoms
CALL = ensure("call")
CAST = ensure("cast")
INFO = ensure("info")