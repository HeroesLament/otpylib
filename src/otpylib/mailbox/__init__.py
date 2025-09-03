"""Mailbox module for actor communication."""

from .core import (
    MailboxID,
    MailboxDoesNotExist,
    NameAlreadyExist,
    NameDoesNotExist,
    TaskStatus,
    TASK_STATUS_IGNORED,
    configure_global_registry,
    create,
    destroy,
    register,
    unregister,
    unregister_all,
    open,
    send,
    receive,
    init_mailbox_registry,
)

__all__ = [
    "MailboxID",
    "MailboxDoesNotExist", 
    "NameAlreadyExist",
    "NameDoesNotExist",
    "TaskStatus",
    "TASK_STATUS_IGNORED",
    "configure_global_registry",
    "create",
    "destroy", 
    "register",
    "unregister",
    "unregister_all",
    "open",
    "send",
    "receive",
    "init_mailbox_registry",
]