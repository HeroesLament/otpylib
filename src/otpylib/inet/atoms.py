#!/usr/bin/env python3
"""
Networking Atoms

Pre-defined atoms for networking operations.
"""

from otpylib import atom

# =============================================================================
# Protocol Types
# =============================================================================

TCP = atom.ensure("tcp")
UDP = atom.ensure("udp")
SSL = atom.ensure("ssl")

# =============================================================================
# Address Families
# =============================================================================

INET = atom.ensure("inet")      # IPv4
INET6 = atom.ensure("inet6")    # IPv6

# =============================================================================
# Socket Modes
# =============================================================================

ACTIVE = atom.ensure("active")      # Messages delivered to mailbox
PASSIVE = atom.ensure("passive")    # Must call recv() explicitly
ONCE = atom.ensure("once")          # One message then switch to passive

# =============================================================================
# Data Modes
# =============================================================================

BINARY = atom.ensure("binary")      # Data as bytes
LIST = atom.ensure("list")          # Data as string/list

# =============================================================================
# Packet Modes
# =============================================================================

PACKET = atom.ensure("packet")
RAW = atom.ensure("raw")            # No framing
LINE = atom.ensure("line")          # Line-delimited
HTTP = atom.ensure("http")          # HTTP packet mode
HTTP_BIN = atom.ensure("http_bin")  # HTTP binary mode

# =============================================================================
# Socket Options
# =============================================================================

NODELAY = atom.ensure("nodelay")        # TCP_NODELAY
KEEPALIVE = atom.ensure("keepalive")    # SO_KEEPALIVE
REUSEADDR = atom.ensure("reuseaddr")    # SO_REUSEADDR
REUSEPORT = atom.ensure("reuseport")    # SO_REUSEPORT
BUFFER = atom.ensure("buffer")          # Buffer size
SNDBUF = atom.ensure("sndbuf")          # Send buffer size
RCVBUF = atom.ensure("rcvbuf")          # Receive buffer size
PRIORITY = atom.ensure("priority")      # SO_PRIORITY
TOS = atom.ensure("tos")                # IP_TOS

# =============================================================================
# Socket States
# =============================================================================

CONNECTED = atom.ensure("connected")
CLOSED = atom.ensure("closed")
LISTENING = atom.ensure("listening")

# =============================================================================
# Error Reasons
# =============================================================================

ECONNREFUSED = atom.ensure("econnrefused")
ETIMEDOUT = atom.ensure("etimedout")
EHOSTUNREACH = atom.ensure("ehostunreach")
ENETUNREACH = atom.ensure("enetunreach")
EADDRINUSE = atom.ensure("eaddrinuse")
EADDRNOTAVAIL = atom.ensure("eaddrnotavail")
CLOSED_ERROR = atom.ensure("closed")
TIMEOUT = atom.ensure("timeout")

# =============================================================================
# Messages (for active mode)
# =============================================================================

TCP_MSG = atom.ensure("tcp")            # {tcp, Socket, Data}
TCP_CLOSED = atom.ensure("tcp_closed")  # {tcp_closed, Socket}
TCP_ERROR = atom.ensure("tcp_error")    # {tcp_error, Socket, Reason}
UDP_MSG = atom.ensure("udp")            # {udp, Socket, Address, Data}
UDP_ERROR = atom.ensure("udp_error")    # {udp_error, Socket, Reason}