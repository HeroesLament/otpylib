"""
Distribution Module-Level API

High-level distribution functions for otpylib.
Provides Erlang distribution operations without exposing backend details.

Similar to the process module pattern - uses registry to access the
active distribution layer.
"""

from typing import Any, Optional
from otpylib.distribution.etf import Pid


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
