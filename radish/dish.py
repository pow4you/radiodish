"""
radish/dish.py — the DISH socket type from RFC 48: one-way listener,
MAY connect to any number of RADIO sockets, SHALL only receive.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Optional

from radish.protocol import Address, GroupLike, MSG_DATA, MSG_JOIN, MSG_LEAVE, encode_frame, decode_frame
from radish.errors import RadioDishError
from radish.transport import _BoundedDropQueue, _UDPProtocol, _Peer
from utils.groups import normalize_group


class DishSocket:
    """
    One-way listener. MAY be connected to any number of RADIO sockets.
    SHALL only receive application messages, delivered fairly across peers.
    """

    def __init__(self, queue_size: int = 1000, rejoin_interval: Optional[float] = 2.0):
        """
        rejoin_interval: UDP gives no delivery guarantee, so a JOIN command
        sent before the radio is up (or dropped in transit) would otherwise
        leave a dish silently deaf forever. If set, JOIN commands for all
        currently-joined groups are periodically re-sent to all connected
        radios so a dish self-heals after a lost packet or a radio restart.
        Set to None to disable and send JOIN exactly once per join() call.
        """
        self._queue_size = queue_size
        self._rejoin_interval = rejoin_interval
        self._protocol: Optional[_UDPProtocol] = None
        self._peers: dict[Address, _Peer] = {}
        self._joined: set = set()
        self._wake = asyncio.Event()
        self._recv_lock = asyncio.Lock()
        self._rr_cursor = 0  # round-robin cursor into self._peers.keys()
        self._rejoin_task: Optional[asyncio.Task] = None
        self._closed = False

    async def bind(
        self, host: str = "", port: int = 0, *, sock: Optional[socket.socket] = None
    ) -> "DishSocket":
        """See RadioSocket.bind — same port=0 / sock= behavior."""
        loop = asyncio.get_running_loop()
        if sock is not None:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: _UDPProtocol(self._on_datagram), sock=sock,
            )
        else:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: _UDPProtocol(self._on_datagram),
                local_addr=(host, port),
            )
        self._protocol = protocol
        if self._rejoin_interval:
            self._rejoin_task = asyncio.ensure_future(self._rejoin_loop())
        return self

    async def _rejoin_loop(self):
        try:
            while True:
                await asyncio.sleep(self._rejoin_interval)
                for addr in list(self._peers.keys()):
                    for group in self._joined:
                        self._send_control(MSG_JOIN, group, addr)
        except asyncio.CancelledError:
            pass

    def connect(self, host: str, port: int) -> "DishSocket":
        """Register a RADIO endpoint. Re-sends any already-JOINed groups to
        the new peer so join order relative to connect order doesn't matter."""
        addr = (host, port)
        if addr not in self._peers:
            peer = _Peer(addr=addr, queue=_BoundedDropQueue(self._queue_size))
            self._peers[addr] = peer
            for group in self._joined:
                self._send_control(MSG_JOIN, group, addr)
        return self

    def disconnect(self, host: str, port: int) -> None:
        self._peers.pop((host, port), None)

    def join(self, group: GroupLike) -> None:
        """Start receiving messages published under `group` (exact match).
        A dish only receives messages for groups it has explicitly joined —
        this includes the empty group b"" if you want ungrouped traffic."""
        group_b = normalize_group(group)
        if group_b in self._joined:
            return
        self._joined.add(group_b)
        for addr in self._peers:
            self._send_control(MSG_JOIN, group_b, addr)

    def leave(self, group: GroupLike) -> None:
        group_b = normalize_group(group)
        if group_b not in self._joined:
            return
        self._joined.discard(group_b)
        for addr in self._peers:
            self._send_control(MSG_LEAVE, group_b, addr)

    def _send_control(self, msg_type: int, group: bytes, addr: Address) -> None:
        if self._protocol and self._protocol.transport:
            self._protocol.transport.sendto(encode_frame(msg_type, group), addr)

    async def recv(self) -> tuple[bytes, bytes]:
        """Await the next (group, payload) pair, fairly across all connected
        radios: each call advances a round-robin cursor over peers so no
        single busy radio can starve the others. Items sit in their peer's
        bounded queue (and thus provide real backpressure/dropping) until a
        recv() call actually consumes them."""
        while True:
            async with self._recv_lock:
                addrs = list(self._peers.keys())
                n = len(addrs)
                for i in range(n):
                    idx = (self._rr_cursor + i) % n
                    addr = addrs[idx]
                    peer = self._peers.get(addr)
                    if peer is None:
                        continue
                    item = peer.queue.try_pop()
                    if item is not None:
                        self._rr_cursor = (idx + 1) % n
                        return item
            self._wake.clear()
            await self._wake.wait()

    def _on_datagram(self, data: bytes, addr: Address):
        try:
            msg_type, group, payload = decode_frame(data)
        except RadioDishError:
            return
        if msg_type != MSG_DATA:
            # A dish never receives JOIN/LEAVE itself in normal operation;
            # ignore anything unexpected rather than crash the app.
            return
        if group not in self._joined:
            # DISH-side belt-and-suspenders filtering in case a radio (e.g.
            # a non-conformant one) sends a group we never joined.
            return
        peer = self._peers.get(addr)
        if peer is None:
            peer = _Peer(addr=addr, queue=_BoundedDropQueue(self._queue_size))
            self._peers[addr] = peer
        peer.queue.try_put((group, payload))  # silently dropped if full
        self._wake.set()

    async def close(self) -> None:
        self._closed = True
        if self._rejoin_task:
            self._rejoin_task.cancel()
        self._wake.set()  # unblock any pending recv()
        self._peers.clear()
        if self._protocol and self._protocol.transport:
            self._protocol.transport.close()

