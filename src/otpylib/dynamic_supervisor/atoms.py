"""
Atoms for dynamic supervisor module.

Defines all the atoms needed for dynamic supervisor operations.
"""

from otpylib.atom import ensure

# Restart Strategy Atoms
PERMANENT = ensure("permanent")
TRANSIENT = ensure("transient")
TEMPORARY = ensure("temporary")

# Supervisor Strategy Atoms
ONE_FOR_ONE = ensure("one_for_one")
ONE_FOR_ALL = ensure("one_for_all")
REST_FOR_ONE = ensure("rest_for_one")

# Exit Reason Atoms
NORMAL = ensure("normal")
SHUTDOWN = ensure("shutdown")
KILLED = ensure("killed")
SUPERVISOR_SHUTDOWN = ensure("supervisor_shutdown")
SIBLING_RESTART_LIMIT = ensure("sibling_restart_limit")

# Supervisor State Atoms
STARTING = ensure("starting")
RUNNING = ensure("running")
SHUTTING_DOWN = ensure("shutting_down")
TERMINATED = ensure("terminated")

# Dynamic Supervisor Message Atoms
GET_CHILD_STATUS = ensure("get_child_status")
LIST_CHILDREN = ensure("list_children")
WHICH_CHILDREN = ensure("which_children")
COUNT_CHILDREN = ensure("count_children")
ADD_CHILD = ensure("add_child")
TERMINATE_CHILD = ensure("terminate_child")
RESTART_CHILD = ensure("restart_child")

# Process Message Atoms
EXIT = ensure("EXIT")
DOWN = ensure("DOWN")
PROCESS = ensure("process")

# Child Types
WORKER = ensure("worker")
SUPERVISOR = ensure("supervisor")

# Dynamic Supervisor Specific
DYNAMIC = ensure("dynamic")
STATIC = ensure("static")
