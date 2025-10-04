"""
Data types and helper classes for otpylib.gen_server.

Includes CallbackNS for user-facing callback grouping.
"""

from dataclasses import dataclass
from typing import Any


# ============================================================================
# Return Wrappers (OTP-style return tuples)
# ============================================================================

@dataclass
class Reply:
    payload: Any


@dataclass
class NoReply:
    pass


@dataclass
class Stop:
    reason: Any = "stop"


# ============================================================================
# Callback Namespace
# ============================================================================

class CallbackNS:
    """
    OTP-style Callback Namespace.

    A structured container for GenServer callbacks:
      - init
      - handle_call
      - handle_cast
      - handle_info
      - terminate

    Keeps callbacks together and lets user code live inline
    in one file, similar to an Erlang module with -behaviour(gen_server).

    Example:

        from otpylib import gen_server

        async def init(config):
            return {"state": config}

        async def handle_call(message, from_, state):
            return (gen_server.Reply("ok"), state)

        callbacks = gen_server.CallbackNS("ConfigManager")
        callbacks.init = init
        callbacks.handle_call = handle_call
    """

    __slots__ = ("name", "init", "handle_call", "handle_cast", "handle_info", "terminate")

    def __init__(self, name: str = "GenServer"):
        self.name = name
        self.init = None
        self.handle_call = None
        self.handle_cast = None
        self.handle_info = None
        self.terminate = None

    @property
    def __name__(self) -> str:
        return self.name

    def __repr__(self):
        return (
            f"<CallbackNS {self.name} "
            f"init={self.init} "
            f"call={self.handle_call} "
            f"cast={self.handle_cast} "
            f"info={self.handle_info} "
            f"term={self.terminate}>"
        )
