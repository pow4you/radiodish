"""
radish/autowire/wiring.py — AutoWirer: the actual "autowiring." Watches a
Discoverer's peer table and calls RadishSocket.connect() for peers either
side has a reason to reach.
"""

from __future__ import annotations

import asyncio
from typing import Iterable, Optional

from radish.unified import RadishSocket
from radish.autowire.discovery import Discoverer
from utils.groups import groups_as_str


class AutoWirer:
    """
    Watches a Discoverer's peer table and calls RadishSocket.connect()
    for peers where either side has a reason to: my interest overlaps what
    they provide, OR their interest (which they also announce) overlaps
    what I provide. Checking only one direction is a real bug, not a
    style choice -- see Discoverer's docstring for why a one-sided check
    leaves half the wiring silently missing.

    Connects to EVERY address a peer announces, unconditionally -- no
    guessing about which one is "the right one" for reaching them. This
    was tried the other way (skip loopback if a peer shares a non-loopback
    address with us, on the theory that meant "same machine, so just use
    loopback and avoid double-delivery") and it was a real mistake: that
    heuristic assumes both sides have symmetric, up-to-date address
    knowledge, which breaks exactly when it matters most -- a process that
    started offline and only ever knew about its own loopback address
    would conclude it must be talking to a different machine even when
    it's the same one, and skip the one address that would have actually
    worked. Missing a real connection is a far worse failure than an
    occasional duplicate delivery, and RFC 48 already treats connections
    as cheap and unconditional on purpose -- filtering happens at the
    JOIN/group layer, not by being clever about which address to dial.
    Two addresses that happen to reach the same peer just means that peer
    gets a message twice sometimes; every send() and call() path in this
    codebase already documents itself as at-least-once, not exactly-once,
    so this is consistent with everything else here, not a new problem.

    Never un-wires anyone, since a peer that goes quiet just stops being
    useful to send to. DOES keep re-checking already-known peers for NEW
    addresses, though (see _loop) -- a peer whose address list grows after
    it was first wired (e.g. it started offline and gained a real IP once
    WiFi came on) gets connect() called on the new address too, rather
    than being stuck forever with whatever was known at first contact.
    """

    def __init__(
        self,
        radish: RadishSocket,
        discoverer: Discoverer,
        interest_groups: Optional[Iterable] = None,
    ):
        self._radish = radish
        self._discoverer = discoverer
        self._interest = set(groups_as_str(interest_groups)) if interest_groups is not None else None
        self._wired: dict[str, set[str]] = {}  # node_id -> addresses already connect()'d
        self._task: Optional[asyncio.Task] = None

    async def start(self, poll_interval: float = 0.3) -> "AutoWirer":
        self._task = asyncio.ensure_future(self._loop(poll_interval))
        return self

    async def _loop(self, poll_interval: float):
        try:
            while True:
                my_groups = set(self._discoverer.groups)
                for peer in self._discoverer.peers():
                    i_want_them = self._interest is None or not self._interest.isdisjoint(peer.groups)
                    they_want_me = not set(peer.interest).isdisjoint(my_groups)
                    if not (i_want_them or they_want_me):
                        continue
                    already = self._wired.get(peer.node_id, set())
                    new_addresses = [a for a in peer.addresses if a not in already]
                    if not new_addresses:
                        continue
                    for addr in new_addresses:
                        self._radish.connect(addr, peer.port)
                    self._wired.setdefault(peer.node_id, set()).update(new_addresses)
                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            pass

    @property
    def wired_peers(self) -> set[str]:
        return set(self._wired.keys())

    def add_interest(self, group) -> None:
        """Start treating `group` as worth auto-connecting for. If
        interest_groups was None at construction (connect to everyone),
        this is a no-op -- everyone already qualifies. Peers already known
        to the Discoverer that match are picked up on the AutoWirer's next
        poll tick, not instantly."""
        if self._interest is not None:
            self._interest.add(groups_as_str([group])[0])

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()


# --------------------------------------------------------------------------
# 4. "On the creation of a radish, autowire its peers"
# --------------------------------------------------------------------------

