"""
radish/radio.py — the RADIO socket type from RFC 48: one-way broadcaster,
MAY connect to any number of DISH sockets, SHALL only send.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Optional

from radish.errors import RadioDishError
from radish.protocol import Address, GroupLike, MSG_DATA, MSG_JOIN, MSG_LEAVE, encode_frame, decode_frame
from radish.transport import _BoundedDropQueue, _UDPProtocol, _Peer
from utils.groups import normalize_group


class RadioSocket:
    """
    One-way broadcaster. MAY be connected to any number of DISH sockets.
    SHALL only send application messages; SHALL NOT block on send.
    """

    def __init__(self, queue_size: int = 1000):
        self._queue_size = queue_size
        self._protocol: Optional[_UDPProtocol] = None
        self._peers: dict[Address, _Peer] = {}
        self._closed = False

    async def bind(
        self, host: str = "", port: int = 0, *, sock: Optional[socket.socket] = None
    ) -> "RadioSocket":
        """Open the local UDP endpoint the radio sends from / listens on for
        JOIN and LEAVE commands from dishes. port=0 asks the OS for any free
        ephemeral port. Pass an already-bound `sock` instead of (host, port)
        to take over a socket obtained elsewhere — e.g. from
        autowire.find_free_port_pair(), which binds two neighboring ports
        up front specifically to avoid the gap a separate "check, then bind"
        step would leave open to another process."""
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
        return self

    def connect(self, host: str, port: int) -> "RadioSocket":
        """Register a DISH endpoint to send to. Creates its outgoing queue
        immediately and keeps it regardless of whether the peer is actually
        reachable ("SHALL create a queue when initiating an outgoing
        connection ... and SHALL maintain the queue whether or not the
        connection is established")."""
        addr = (host, port)
        if addr not in self._peers:
            peer = _Peer(addr=addr, queue=_BoundedDropQueue(self._queue_size))
            peer.task = asyncio.ensure_future(self._sender_loop(peer))
            self._peers[addr] = peer
        return self

    def disconnect(self, host: str, port: int) -> None:
        addr = (host, port)
        peer = self._peers.pop(addr, None)
        if peer is not None:
            if peer.task:
                peer.task.cancel()
            # queue and its contents go out of scope -> discarded, per RFC.

    async def send(self, payload: bytes, group: GroupLike = b"") -> None:
        """
        Enqueue `payload` under `group` for every connected DISH that has
        JOINed that exact group. Never blocks; drops silently per-peer if
        that peer's outgoing queue is full.
        """
        if self._closed:
            raise RadioDishError("send() on a closed RadioSocket")
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        group_b = normalize_group(group)
        frame = encode_frame(MSG_DATA, group_b, payload)

        for peer in self._peers.values():
            if group_b in peer.groups:
                peer.queue.try_put(frame)  # drop silently if full, no exception

    async def _sender_loop(self, peer: _Peer):
        transport = self._protocol.transport
        try:
            while True:
                frame = peer.queue.try_pop()
                if frame is None:
                    await asyncio.sleep(0.001)
                    continue
                transport.sendto(frame, peer.addr)
                # Yield after every send so a burst on one peer's queue can't
                # monopolize the event loop and starve other radios/peers
                # sharing this process from getting their sends out too.
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass

    def _on_datagram(self, data: bytes, addr: Address):
        # RADIO only understands JOIN/LEAVE control frames from dishes;
        # everything else (including any DATA a dish might mistakenly send)
        # is silently discarded, per RFC.
        try:
            msg_type, group, _payload = decode_frame(data)
        except RadioDishError:
            return
        peer = self._peers.get(addr)
        if peer is None:
            # A dish we didn't explicitly connect() to can still reach us
            # (e.g. it called DishSocket.connect() to us). Auto-register it
            # so group filtering / queueing works symmetrically.
            peer = _Peer(addr=addr, queue=_BoundedDropQueue(self._queue_size))
            peer.task = asyncio.ensure_future(self._sender_loop(peer))
            self._peers[addr] = peer
        if msg_type == MSG_JOIN:
            peer.groups.add(group)
        elif msg_type == MSG_LEAVE:
            peer.groups.discard(group)
        # MSG_DATA or anything else from a dish: silently discarded.

    async def close(self) -> None:
        self._closed = True
        for peer in list(self._peers.values()):
            if peer.task:
                peer.task.cancel()
        self._peers.clear()
        if self._protocol and self._protocol.transport:
            self._protocol.transport.close()

