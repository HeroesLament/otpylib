"""
Erlang Distribution Protocol for OTPYLIB

Public API for distribution layer. Provides node discovery, handshake,
and inter-node messaging compatible with Erlang/OTP 26+.

This module contains both:
1. Backend-agnostic transport layer (Node, Connection, EPMD, ETF)
2. Module-level API functions (connect, send, etc.) for use after initialization

Usage pattern:
    from otpylib import distribution
    from otpylib.runtime.backends.asyncio_backend import AsyncIOBackend, AsyncIODistribution
    from otpylib.runtime.registry import set_runtime
    
    # Setup backend
    backend = AsyncIOBackend()
    await backend.initialize()
    set_runtime(backend)
    
    # Setup distribution
    dist = AsyncIODistribution(backend, "myapp@localhost", cookie="secret")
    await dist.start()
    distribution.use_distribution(dist)
    
    # Use module-level API
    await distribution.connect("erlang@localhost")
    await distribution.send("erlang@localhost", "gen_server", message)
"""

from typing import Any, Optional

from otpylib.distribution.protocol import (
    EPMDProtocol,
    NodeProtocol,
    ConnectionProtocol,
    DistributionProtocol,
)
from otpylib.distribution.node import Node
from otpylib.distribution.connection import Connection
from otpylib.distribution.epmd import EPMD, NodeInfo
from otpylib.distribution.etf import Pid, Reference, Port, encode, decode

# Control message constants
from otpylib.distribution.constants import (
    CTRL_LINK,
    CTRL_SEND,
    CTRL_EXIT,
    CTRL_UNLINK,
    CTRL_REG_SEND,
    CTRL_GROUP_LEADER,
    CTRL_EXIT2,
    CTRL_SEND_TT,
    CTRL_EXIT_TT,
    CTRL_REG_SEND_TT,
    CTRL_MONITOR_P,
    CTRL_DEMONITOR_P,
    CTRL_MONITOR_P_EXIT,
)


# ============================================================================
# Module-level API (similar to process module)
# ============================================================================

def _get_distribution():
    """Get current distribution layer from registry."""
    from otpylib.runtime.registry import get_distribution
    dist = get_distribution()
    if not dist:
        raise RuntimeError(
            "Distribution not initialized. Create a distribution instance "
            "(e.g., AsyncIODistribution) and call distribution.use_distribution()"
        )
    return dist


async def connect(remote_node: str) -> None:
    """
    Connect to a remote Erlang/OTP node.
    
    :param remote_node: Full node name (e.g., "erlang@localhost")
    """
    dist = _get_distribution()
    await dist.connect(remote_node)


async def send(remote_node: str, target: str, message: Any) -> None:
    """
    Send message to a registered process on a remote node.
    
    :param remote_node: Full node name
    :param target: Registered name of target process
    :param message: Message to send (will be ETF-encoded)
    """
    dist = _get_distribution()
    await dist.send(remote_node, target, message)


async def send_to_pid(remote_node: str, pid: Pid, message: Any) -> None:
    """
    Send message to a specific PID on a remote node.
    
    :param remote_node: Full node name
    :param pid: ETF Pid of target process
    :param message: Message to send
    """
    dist = _get_distribution()
    await dist.send_to_pid(remote_node, pid, message)


def node_name() -> Optional[str]:
    """
    Get this node's full name.
    
    :returns: Node name (e.g., "myapp@localhost"), or None if not initialized
    """
    from otpylib.runtime.registry import get_distribution
    dist = get_distribution()
    return dist.node_name if dist else None


def port() -> Optional[int]:
    """
    Get the port this node is listening on.
    
    :returns: Port number, or None if not initialized
    """
    from otpylib.runtime.registry import get_distribution
    dist = get_distribution()
    return dist.port if dist else None


def use_distribution(distribution) -> None:
    """
    Install a distribution layer globally.
    
    Similar to process.use_runtime() - sets up the distribution backend
    for use with module-level API functions.
    
    :param distribution: Distribution instance (e.g., AsyncIODistribution)
    
    Example:
        from otpylib import distribution
        from otpylib.runtime.backends.asyncio_backend import AsyncIODistribution
        
        dist = AsyncIODistribution(backend, "myapp@localhost", "secret")
        await dist.start()
        distribution.use_distribution(dist)
    """
    from otpylib.runtime.registry import set_distribution
    set_distribution(distribution)


__all__ = [
    # Protocol
    "DistributionProtocol",
    # Core classes (for backend implementers)
    "Node",
    "Connection",
    "EPMD",
    "NodeInfo",
    # ETF types
    "Pid",
    "Reference",
    "Port",
    "encode",
    "decode",
    # Control message types
    "CTRL_LINK",
    "CTRL_SEND",
    "CTRL_EXIT",
    "CTRL_UNLINK",
    "CTRL_REG_SEND",
    "CTRL_GROUP_LEADER",
    "CTRL_EXIT2",
    "CTRL_SEND_TT",
    "CTRL_EXIT_TT",
    "CTRL_REG_SEND_TT",
    "CTRL_MONITOR_P",
    "CTRL_DEMONITOR_P",
    "CTRL_MONITOR_P_EXIT",
    # Module-level API
    "connect",
    "send",
    "send_to_pid",
    "node_name",
    "port",
    "use_distribution",
]
