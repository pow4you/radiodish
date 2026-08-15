"""
radish/transport.py — low-level plumbing shared by RadioSocket and
DishSocket: the asyncio protocol wrapper, the bounded/drop-when-full
queue, and the per-peer bookkeeping record. Extracted here rather than
duplicated in radio.py and dish.py, or bolted onto whichever class
happened to need it first.
"""

from __future__ import annotations

import asyncio
import collections
from dataclasses import dataclass, field
from typing import Optional

from radish.protocol import Address


class _BoundedDropQueue:
    """A deque-backed queue that refuses new items (rather than evicting old
    ones) once it reaches its configured maximum size. Newest-message-dropped
    semantics, matching "silently discard/drop the message" in RFC 48
    ("SHOULD constrain queue sizes ... SHALL silently discard/drop when the
    queue is full")."""

    __slots__ = ("_dq", "_maxsize")

    def __init__(self, maxsize: int):
        self._dq: collections.deque = collections.deque()
        self._maxsize = maxsize

    def try_put(self, item) -> bool:
        if len(self._dq) >= self._maxsize:
            return False
        self._dq.append(item)
        return True

    def try_pop(self):
        if self._dq:
            return self._dq.popleft()
        return None

    def __len__(self):
        return len(self._dq)


class _UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_datagram):
        self._on_datagram = on_datagram
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr: Address):
        self._on_datagram(data, addr)

    def error_received(self, exc: Exception):
        # UDP has no connections to reset; log-and-continue is correct here.
        pass


@dataclass
class _Peer:
    addr: Address
    queue: _BoundedDropQueue
    task: Optional[asyncio.Task] = None
    groups: set = field(default_factory=set)  # groups this DISH peer has JOINed (RADIO side)
