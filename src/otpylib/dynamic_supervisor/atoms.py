"""
Atoms for dynamic supervisor module (OTPModule-aware).

Defines all the atoms needed for dynamic supervisor operations.
"""

from otpylib import atom

# Restart Strategy Atoms
PERMANENT = atom.ensure("permanent")
TRANSIENT = atom.ensure("transient")
TEMPORARY = atom.ensure("temporary")

# Supervisor Strategy Atoms
ONE_FOR_ONE = atom.ensure("one_for_one")
ONE_FOR_ALL = atom.ensure("one_for_all")
REST_FOR_ONE = atom.ensure("rest_for_one")

# Exit Reason Atoms
NORMAL = atom.ensure("normal")
SHUTDOWN = atom.ensure("shutdown")
KILLED = atom.ensure("killed")
SUPERVISOR_SHUTDOWN = atom.ensure("supervisor_shutdown")
SIBLING_RESTART_LIMIT = atom.ensure("sibling_restart_limit")

# Supervisor State Atoms
STARTING = atom.ensure("starting")
RUNNING = atom.ensure("running")
SHUTTING_DOWN = atom.ensure("shutting_down")
TERMINATED = atom.ensure("terminated")

# Dynamic Supervisor Message Atoms
GET_CHILD_STATUS = atom.ensure("get_child_status")
LIST_CHILDREN = atom.ensure("list_children")
WHICH_CHILDREN = atom.ensure("which_children")
COUNT_CHILDREN = atom.ensure("count_children")
ADD_CHILD = atom.ensure("add_child")
TERMINATE_CHILD = atom.ensure("terminate_child")
RESTART_CHILD = atom.ensure("restart_child")

# Process Message Atoms
EXIT = atom.ensure("EXIT")
DOWN = atom.ensure("DOWN")
PROCESS = atom.ensure("process")

# Child Types
WORKER = atom.ensure("worker")
SUPERVISOR = atom.ensure("supervisor")

# Static/Dynamic flags
DYNAMIC = atom.ensure("dynamic")
STATIC = atom.ensure("static")