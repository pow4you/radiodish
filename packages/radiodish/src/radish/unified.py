"""
radish/unified.py — RadishSocket: a RadioSocket and a DishSocket behind
one object, one address pair. "The actor has the radish, the radish has
the queues."
"""

from __future__ import annotations

import asyncio
import socket
from typing import Optional, Union

from radish.errors import RadioDishError
from radish.protocol import GroupLike
from radish.radio import RadioSocket
from radish.dish import DishSocket


class RadishSocket:
    """
    A unified socket combining a RadioSocket and a DishSocket behind a single
    object, so a component can both broadcast and receive without juggling
    two sockets by hand.

    Under the hood it's genuinely just the two RFC-48 sockets: a RadioSocket
    bound on `base_port` and a DishSocket bound on the neighboring port
    `base_port + 1`. Two background asyncio tasks run continuously for the
    lifetime of the socket:

    - a receive loop that awaits DishSocket.recv() and pushes every message
      into `self.recv_queue`
    - a broadcast loop that awaits `self.broadcast_queue` and calls
      RadioSocket.send() for whatever shows up

    `broadcast()` is a plain, non-blocking method: it just enqueues onto
    broadcast_queue and returns immediately (consistent with RADIO's "never
    block on send"; if broadcast_queue is bounded and full, the message is
    dropped silently, same drop policy as everywhere else in this module).
    `recv()` awaits the next item off recv_queue.

    Wiring between peers: connect(host, base_port) points this socket's
    RADIO at the peer's DISH (base_port + 1) and this socket's DISH at the
    peer's RADIO (base_port), so two RadishSockets that connect() to each
    other can freely broadcast to and receive from one another. Any number
    of peers can be connected, forming a mesh — no broker, no central state.
    """

    def __init__(
        self,
        queue_size: int = 1000,
        recv_queue_size: int = 0,
        broadcast_queue_size: int = 0,
    ):
        """
        queue_size: per-peer bounded queue size on the underlying radio/dish
            sockets (see RadioSocket/DishSocket docs).
        recv_queue_size / broadcast_queue_size: size of this socket's own
            asyncio.Queue objects. 0 means unbounded (asyncio.Queue
            convention). If you bound these, a full queue means new items
            are dropped silently rather than blocking the caller.
        """
        self.radio = RadioSocket(queue_size=queue_size)
        self.dish = DishSocket(queue_size=queue_size)
        self.recv_queue: "asyncio.Queue[tuple[bytes, bytes]]" = asyncio.Queue(
            maxsize=recv_queue_size
        )
        self.broadcast_queue: "asyncio.Queue[tuple[bytes, bytes]]" = asyncio.Queue(
            maxsize=broadcast_queue_size
        )
        self._host: Optional[str] = None
        self._radio_port: Optional[int] = None
        self._dish_port: Optional[int] = None
        self._tasks: list[asyncio.Task] = []
        self._closed = False

    async def bind(
        self,
        host: str,
        base_port: int = 0,
        *,
        radio_sock: Optional[socket.socket] = None,
        dish_sock: Optional[socket.socket] = None,
    ) -> "RadishSocket":
        """Binds the RADIO half on base_port and the DISH half on
        base_port + 1, then starts the two background loops. If radio_sock
        and dish_sock are given (already-bound UDP sockets, e.g. from
        autowire.find_free_port_pair()), those are used as-is instead of
        binding fresh ones from (host, base_port)."""
        if radio_sock is not None and dish_sock is not None:
            await self.radio.bind(sock=radio_sock)
            await self.dish.bind(sock=dish_sock)
            self._radio_port = radio_sock.getsockname()[1]
            self._dish_port = dish_sock.getsockname()[1]
        else:
            await self.radio.bind(host, base_port)
            await self.dish.bind(host, base_port + 1)
            self._radio_port, self._dish_port = base_port, base_port + 1
        self._host = host
        self._tasks.append(asyncio.ensure_future(self._recv_loop()))
        self._tasks.append(asyncio.ensure_future(self._broadcast_loop()))
        return self

    def connect(self, host: str, base_port: int) -> "RadishSocket":
        """Connect to a peer RadishSocket bound at (host, base_port). Wires
        this socket's RADIO to the peer's DISH (base_port + 1) and this
        socket's DISH to the peer's RADIO (base_port)."""
        self.radio.connect(host, base_port + 1)
        self.dish.connect(host, base_port)
        return self

    def join(self, group: GroupLike) -> None:
        self.dish.join(group)

    def leave(self, group: GroupLike) -> None:
        self.dish.leave(group)

    def broadcast(self, payload: Union[str, bytes], group: GroupLike = b"") -> None:
        """Enqueue a message for the broadcast loop to send. Non-blocking;
        silently dropped if broadcast_queue is bounded and full."""
        if self._closed:
            raise RadioDishError("broadcast() on a closed RadishSocket")
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        try:
            self.broadcast_queue.put_nowait((payload, group))
        except asyncio.QueueFull:
            pass

    async def recv(self) -> tuple[bytes, bytes]:
        """Await the next (group, payload) received from any connected peer."""
        return await self.recv_queue.get()

    async def _recv_loop(self):
        try:
            while True:
                item = await self.dish.recv()
                try:
                    self.recv_queue.put_nowait(item)
                except asyncio.QueueFull:
                    pass  # consumer isn't keeping up; drop rather than block
        except asyncio.CancelledError:
            pass

    async def _broadcast_loop(self):
        try:
            while True:
                payload, group = await self.broadcast_queue.get()
                await self.radio.send(payload, group=group)
        except asyncio.CancelledError:
            pass

    async def close(self) -> None:
        self._closed = True
        for task in self._tasks:
            task.cancel()
        await self.radio.close()
        await self.dish.close()
