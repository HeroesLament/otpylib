"""
Process Module

High-level process management API for otpylib.
"""

from otpylib.process.api import (
    spawn,
    spawn_link,
    spawn_monitor,
    send,
    receive,
    register,
    unregister,
    whereis,
    whereis_name,
    self,
    link,
    unlink,
    monitor,
    demonitor,
    exit,
    is_alive,
    processes,
    registered,
    use_runtime,
)

__all__ = [
    'spawn',
    'spawn_link',
    'spawn_monitor',
    'send',
    'receive',
    'register',
    'unregister',
    'whereis',
    'whereis_name',
    'self',
    'link',
    'unlink',
    'monitor',
    'demonitor',
    'exit',
    'is_alive',
    'processes',
    'registered',
    'use_runtime'
]
