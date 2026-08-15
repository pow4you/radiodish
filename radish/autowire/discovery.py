"""
radish/autowire/discovery.py — the "LAN" discovery tier (UDP multicast,
a small homemade mDNS) plus the loopback-scoped fallback within it, and
the Discoverer class that ties this together with the local-file tier
from radish.autowire.local_discovery.

Two tiers active by default, matching "local machine or my LAN, not the
internet unless you explicitly say so":

- "my machine": radish.autowire.local_discovery -- pure filesystem, no
  sockets, works identically whether or not any network interface is up.
- "my LAN": UDP multicast here, three tiers tried in order each time --
  any interface, then loopback-scoped specifically (for when the OS
  won't auto-select loopback as a multicast interface on its own, which
  is confirmed real on macOS with no non-loopback interface active), then
  a plain non-multicast bind as the last resort before giving up on
  sockets entirely and relying on the file tier alone.

Reaching beyond machine + LAN is explicit only: pass `seeds` to unicast
announcements directly at specific (host, port) addresses.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import struct
import time
import warnings
from dataclasses import dataclass
from typing import Iterable, Optional

from radish.errors import RadioDishError
from radish.autowire.network import detect_local_addresses, _is_local_scope_address
from radish.autowire.local_discovery import _local_discovery_dir, _safe_filename
from utils.groups import groups_as_str

MULTICAST_GROUP = "239.255.42.99"  # organization-local scope, RFC 2365
DEFAULT_DISCOVERY_PORT = 9999


def _make_discovery_socket(
    port: int, join_multicast: bool = True, multicast_interface: Optional[str] = None
) -> socket.socket:
    """
    multicast_interface: which interface to join the multicast group ON.
    None means INADDR_ANY -- "let the OS pick a sensible interface for
    multicast," which is where the WiFi-off failure actually comes from:
    some OSes (confirmed: macOS) don't consider loopback a valid choice
    when nothing else is up, and the join fails outright even though
    loopback would happily carry the traffic if asked directly. Passing
    "127.0.0.1" here bypasses that guesswork entirely -- explicitly join
    (and, for sends, explicitly set IP_MULTICAST_IF to) loopback itself,
    which doesn't depend on the OS's auto-selection logic at all.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    s.bind(("", port))
    if join_multicast:
        interface_bytes = (
            socket.inet_aton(multicast_interface)
            if multicast_interface
            else struct.pack("=I", socket.INADDR_ANY)
        )
        mreq = struct.pack("4s4s", socket.inet_aton(MULTICAST_GROUP), interface_bytes)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        if multicast_interface:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(multicast_interface))
    return s


@dataclass
class PeerInfo:
    node_id: str
    addresses: tuple[str, ...]
    port: int
    groups: tuple[str, ...]
    interest: tuple[str, ...]
    last_seen: float


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_datagram):
        self._on_datagram = on_datagram
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr):
        self._on_datagram(data, addr)

    def error_received(self, exc):
        pass


class Discoverer:
    """
    Zero-config peer discovery for RadishSocket nodes, with two tiers active
    by default, matching "local machine or LAN, not the open internet unless
    you explicitly say so":

    - "my machine": every Discoverer sharing a discovery_port writes its own
      announcement to a shared temp-directory file and reads everyone
      else's. Pure filesystem, no sockets involved, so it works identically
      whether or not any network interface is up at all -- the case that
      actually matters on a laptop with WiFi off, which is where this tier
      came from: UDP multicast group-join can fail outright with no active
      route (confirmed empirically, not hypothetically -- see autowire.py's
      test suite), and when it does, it fails the SAME way for every local
      process, so none of them can hear each other even though they're all
      on one machine.
    - "LAN": UDP multicast (239.255.42.99 by default) -- a small homemade
      mDNS. Each node periodically announces (node_id, host, port, groups,
      interest); every node on the same multicast group + port hears every
      announcement, including its own (filtered out by node_id). Comes up
      automatically when a real network interface is available, and
      self-upgrades into working if one appears after startup.

    `interest` matters for a reason that isn't obvious until you hit it:
    connection-forming has to be decided from BOTH sides, not just "do I
    want them." If only a consumer's interest is checked against a
    provider's groups, the consumer connects to the provider — but the
    provider's own AutoWirer, checking only ITS interest against the
    consumer's (usually empty, provide-nothing) groups, never independently
    decides to connect back. Without that second connection, the provider's
    DISH never tells the consumer's RADIO what it's joined, and calls from
    consumer to provider silently never transmit even though "wired_peers"
    looks satisfied. Announcing `interest` alongside `groups` lets a
    provider's AutoWirer see "this peer's interest overlaps what I provide"
    and connect back on its own, closing the loop symmetrically.

    Reaching beyond local machine + LAN is explicit, not automatic: pass
    `seeds` to unicast the same announcements directly at specific
    (host, port) addresses -- the escape hatch for Docker overlays, cloud
    VPCs, or genuinely remote peers. A seed that looks like a public IP
    (not loopback/private/link-local) triggers a warning at construction
    time, since that's usually either a mistake or a case that wants a
    real tunnel/VPN in front of it rather than bare UDP discovery trusting
    whatever shows up on the open internet.
    """

    def __init__(
        self,
        node_id: str,
        addresses: Iterable[str],
        port: int,
        groups: Iterable = (),
        interest: Optional[Iterable] = None,
        discovery_port: int = DEFAULT_DISCOVERY_PORT,
        announce_interval: float = 2.0,
        ttl: float = 8.0,
        seeds: Iterable[tuple[str, int]] = (),
        auto_refresh_addresses: bool = True,
    ):
        self.node_id = node_id
        self.addresses = list(addresses)
        self.port = port
        self.groups = groups_as_str(groups)
        # default interest = groups: "I connect to anyone who overlaps what
        # I provide" is a safe, sensible baseline even for pure providers
        self.interest = groups_as_str(interest) if interest is not None else self.groups
        self._discovery_port = discovery_port
        self._announce_interval = announce_interval
        self._ttl = ttl
        self._seeds = list(seeds)
        # Whether _revalidate_loop should periodically re-run
        # detect_local_addresses() and pick up changes -- set to False by
        # autowired_radish() when the caller passed an explicit host, since
        # that's a deliberate override this shouldn't second-guess.
        self._auto_refresh_addresses = auto_refresh_addresses
        for seed_host, _seed_port in self._seeds:
            if not _is_local_scope_address(seed_host):
                warnings.warn(
                    f"radiodish: seed {seed_host!r} doesn't look like a "
                    f"loopback/private-LAN/link-local address -- if this is "
                    f"really a public-internet peer, consider putting a "
                    f"proper tunnel/VPN in front of it rather than relying "
                    f"on bare UDP discovery to reach across the open "
                    f"internet.",
                    stacklevel=2,
                )
        self._peers: dict[str, PeerInfo] = {}
        self._protocol: Optional[_DiscoveryProtocol] = None
        self._multicast_active = False
        self._multicast_scope: Optional[str] = None  # "any", "loopback", or None
        self._local_dir = _local_discovery_dir(discovery_port)
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> "Discoverer":
        """
        Never raises for network-availability reasons alone. Tries full
        multicast first; if that specifically fails (no active interface
        capable of it -- the WiFi-off case), falls back to a plain bound
        socket so explicit `seeds=` unicast still works. The "my machine"
        file-based tier starts regardless, independent of whether either
        socket attempt worked. Only raises if NEITHER tier is usable at
        all (no socket, and no writable temp directory either) -- at that
        point it's a genuine, unusual misconfiguration rather than a
        networking limitation. A background task periodically re-attempts
        full multicast setup for as long as this Discoverer runs -- not
        just once at startup -- so it upgrades automatically if a real
        network appears later, and downgrades automatically (falls back to
        the file/seeds-only tiers without crashing) if that network goes
        away again. No restart needed either direction.
        """
        socket_ok = await self._try_open_socket()
        if not socket_ok and self._local_dir is None:
            raise RadioDishError(
                f"couldn't set up any discovery channel at all: no usable "
                f"socket on port {self._discovery_port}, and no writable "
                f"temp directory for local discovery either. That's an "
                f"unusually restricted environment -- pass seeds= to "
                f"discover peers directly, or skip Discoverer/AutoWirer "
                f"and call RadishSocket.connect() manually."
            )
        self._tasks.append(asyncio.ensure_future(self._announce_loop()))
        self._tasks.append(asyncio.ensure_future(self._prune_loop()))
        if self._local_dir is not None:
            self._tasks.append(asyncio.ensure_future(self._local_discovery_loop()))
        self._tasks.append(asyncio.ensure_future(self._revalidate_loop()))
        return self

    async def _try_open_socket(self) -> bool:
        """
        Three tiers, tried in order, each a fallback for the previous
        one's failure:

        1. Full multicast, any interface (INADDR_ANY) -- the normal LAN
           case, reaches other machines on the network.
        2. Multicast scoped explicitly to loopback -- same-machine-only,
           but doesn't depend on the OS successfully auto-selecting an
           interface the way tier 1 does. This is specifically what fixes
           the WiFi-off case: tier 1 fails there on some OSes (confirmed:
           macOS) because there's no non-loopback interface for the OS to
           pick, even though loopback itself would work fine if asked
           directly instead of left to auto-selection.
        3. A plain bound socket, no multicast at all -- seeds-only /
           file-tier-only discovery.

        Returns whether ANY socket was obtained (True even in the fully
        degraded tier-3 case). self._multicast_active tells you whether
        SOME form of multicast landed (tier 1 or 2); self._multicast_scope
        tells you which one ("any", "loopback", or None).
        """
        loop = asyncio.get_running_loop()
        for scope in ("any", "loopback"):
            try:
                interface = "127.0.0.1" if scope == "loopback" else None
                sock = _make_discovery_socket(
                    self._discovery_port, join_multicast=True, multicast_interface=interface
                )
                self._multicast_active = True
                self._multicast_scope = scope
                break
            except OSError:
                continue
        else:
            try:
                sock = _make_discovery_socket(self._discovery_port, join_multicast=False)
                self._multicast_active = False
                self._multicast_scope = None
            except OSError:
                return False
        _transport, protocol = await loop.create_datagram_endpoint(
            lambda: _DiscoveryProtocol(self._on_datagram), sock=sock,
        )
        self._protocol = protocol
        return True

    async def _revalidate_loop(self, interval: float = 8.0):
        """Periodically re-attempts full multicast setup from scratch, for
        the entire lifetime of this Discoverer, and swaps the active
        socket whenever the outcome differs from the current state --
        upgrading a degraded node the moment a real network shows up, and
        just as importantly downgrading gracefully (falling back to
        file/seeds discovery, not crashing or going silent) if a network
        that was working stops being available mid-session. A brief
        multicast-only gap during the swap is the accepted cost of not
        needing any separate "is this socket still healthy" introspection,
        which UDP doesn't make easy to answer any more directly than this.

        Also re-detects this node's OWN addresses each cycle (unless
        auto_refresh_addresses was turned off, e.g. an explicit host= was
        given to autowired_radish()) -- self.addresses used to be computed
        exactly once, at construction. That's a real bug on its own, not
        just incomplete: a node started before WiFi came on would stay
        stuck announcing only "127.0.0.1" forever, even long after a real
        address became available, because nothing ever asked again. Worth
        being explicit about what this does and doesn't fix: it makes THIS
        node's own announcement stay current. A PEER that already finished
        wiring to this node before the refresh doesn't automatically learn
        about the new address either -- that's AutoWirer's job (see its
        docstring: it re-checks already-known peers for new addresses on
        its own poll cycle), not this loop's.

        DEBUGGING NOTE for the "reconnect after some nodes already running"
        case: a node that started degraded doesn't notice a network coming
        back until its OWN next tick of this loop fires -- up to
        `interval` seconds after reconnection, not instantly. A node
        started fresh AFTER reconnection tries real multicast immediately
        at startup and usually succeeds right away, which is exactly the
        asymmetry "freshly-started nodes autowire fine, ones running since
        before the reconnect take longer" would look like from outside. If
        you're chasing that, the fastest way to confirm it's this and not
        something else: check `discoverer._multicast_active` and
        `discoverer._multicast_scope` ("any" / "loopback" / None) AND
        `discoverer.addresses` on the long-running node right after
        reconnecting -- if multicast is still False or addresses still
        only shows loopback, it just hasn't hit its next tick yet, not
        stuck. This is completely independent of the local-file tier,
        which doesn't care about network state changes at all -- if
        same-machine peers still aren't finding each other even accounting
        for this delay, the local-file tier (not this loop) is where to
        look next.
        """
        try:
            while True:
                await asyncio.sleep(interval)

                if self._auto_refresh_addresses:
                    fresh = detect_local_addresses()
                    if fresh != self.addresses:
                        self.addresses = fresh
                        self._send_announce()  # don't wait for the next tick

                was_active = self._multicast_active
                was_scope = self._multicast_scope
                old_protocol = self._protocol
                ok = await self._try_open_socket()
                if ok and (self._multicast_active, self._multicast_scope) != (was_active, was_scope):
                    if old_protocol and old_protocol.transport:
                        old_protocol.transport.close()
                    self._send_announce()  # don't wait for the next tick
                elif not ok:
                    # neither multicast nor even a plain bind worked this
                    # time around -- keep the OLD socket (if any) rather
                    # than tearing down a working one over a transient hiccup
                    self._multicast_active = was_active
                    self._multicast_scope = was_scope
        except asyncio.CancelledError:
            pass

    def _payload(self) -> bytes:
        return json.dumps(
            {
                "id": self.node_id,
                "addresses": self.addresses,
                "port": self.port,
                "groups": self.groups,
                "interest": self.interest,
            }
        ).encode("utf-8")

    def _send_announce(self) -> None:
        payload = self._payload()
        if self._protocol is not None and self._protocol.transport is not None:
            self._protocol.transport.sendto(payload, (MULTICAST_GROUP, self._discovery_port))
            for seed_host, seed_port in self._seeds:
                self._protocol.transport.sendto(payload, (seed_host, seed_port))
        self._write_local_announce(payload)

    def _write_local_announce(self, payload: bytes) -> None:
        """Write our announcement into the shared local-discovery directory.
        Atomic (write to a temp file, then os.replace) so another node
        scanning the directory mid-write never sees a torn file.

        DEBUGGING NOTE: if same-machine peers still aren't finding each
        other after the /tmp fix, the single most useful thing to check is
        whether `self._local_dir` actually matches between the two
        processes -- print it (or `ls` the directory it points at) from
        both. If it matches and files ARE appearing there for both nodes,
        the write/scan mechanism itself is working and the bug is
        downstream (e.g. in what address got announced, or in AutoWirer's
        matching); if the directories DON'T match, something is still
        making them disagree on _local_discovery_root(), which would be a
        new report worth its own investigation."""
        if self._local_dir is None:
            return
        try:
            path = os.path.join(self._local_dir, _safe_filename(self.node_id))
            tmp_path = path + f".tmp{os.getpid()}"
            with open(tmp_path, "wb") as f:
                f.write(payload)
            os.replace(tmp_path, path)
        except OSError:
            pass  # e.g. temp dir got removed out from under us -- skip a beat

    def _scan_local_peers(self) -> None:
        if self._local_dir is None:
            return
        try:
            entries = os.listdir(self._local_dir)
        except OSError:
            return
        my_filename = _safe_filename(self.node_id)
        now_wall = time.time()
        for name in entries:
            if name == my_filename or not name.endswith(".json"):
                continue
            path = os.path.join(self._local_dir, name)
            try:
                if now_wall - os.path.getmtime(path) > self._ttl:
                    continue  # stale -- writer probably isn't running anymore
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                continue  # e.g. the writer deleted it between listdir and read
            self._on_datagram(data, addr=None)

    async def _local_discovery_loop(self):
        """Polls fairly often (unlike the LAN tier, this one's pure local
        disk I/O, so a tight interval costs almost nothing). This matters
        more than it looks: whichever of two nodes registers second finds
        the first node's file immediately (it's already sitting there),
        but the FIRST node only notices the second one on its NEXT
        scheduled scan -- a slow interval here means one specific side of
        every pair stacks up nearly a full cycle of pure, avoidable
        latency on top of AutoWirer's own poll cycle, right when a test
        (or a real caller) is waiting on the round trip to complete."""
        try:
            while True:
                self._scan_local_peers()
                await asyncio.sleep(0.3)
        except asyncio.CancelledError:
            pass

    async def _announce_loop(self):
        try:
            while True:
                self._send_announce()
                await asyncio.sleep(self._announce_interval)
        except asyncio.CancelledError:
            pass

    async def _prune_loop(self):
        try:
            while True:
                await asyncio.sleep(max(self._ttl / 2, 0.5))
                now = time.monotonic()
                stale = [nid for nid, p in self._peers.items() if now - p.last_seen > self._ttl]
                for nid in stale:
                    del self._peers[nid]
        except asyncio.CancelledError:
            pass

    def _on_datagram(self, data: bytes, addr):
        try:
            msg = json.loads(data.decode("utf-8"))
            node_id = msg["id"]
            if node_id == self.node_id:
                return  # heard our own multicast loopback; ignore
            addresses = msg.get("addresses")
            if not addresses:
                addresses = [msg["host"]] if "host" in msg else []
            self._peers[node_id] = PeerInfo(
                node_id=node_id,
                addresses=tuple(addresses),
                port=int(msg["port"]),
                groups=groups_as_str(msg.get("groups", ())),
                interest=groups_as_str(msg.get("interest", ())),
                last_seen=time.monotonic(),
            )
        except (ValueError, KeyError, UnicodeDecodeError):
            return  # not a discovery packet we understand

    def peers(self) -> list[PeerInfo]:
        return list(self._peers.values())

    def update_groups(self, groups: Iterable) -> None:
        """Change what this node advertises to newly-discovered peers, and
        send an announcement immediately rather than waiting for the next
        scheduled tick (up to announce_interval seconds away). That matters
        for dynamic updates specifically: two nodes deciding to wire up
        after the fact each depend on the OTHER side's next announcement
        landing (see AutoWirer's docstring on why both directions matter),
        and those are on independent, uncoordinated timers -- waiting for
        both natural ticks to line up is a real, if occasional, source of
        flakiness that an immediate send avoids. Already-connected peers
        separately learn about new groups through radiodish's own
        DishSocket rejoin mechanism regardless; this is specifically for
        peers that haven't found us yet."""
        self.groups = groups_as_str(groups)
        self._send_announce()

    def update_interest(self, interest: Iterable) -> None:
        """Change what this node declares interest in, announcing
        immediately for the same reason as update_groups(). Matters for
        peers who provide something we now want but who don't already want
        anything from us -- their AutoWirer only connects back once it
        sees our updated interest."""
        self.interest = groups_as_str(interest)
        self._send_announce()

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        if self._protocol and self._protocol.transport:
            self._protocol.transport.close()
        if self._local_dir is not None:
            try:
                os.remove(os.path.join(self._local_dir, _safe_filename(self.node_id)))
            except OSError:
                pass


# --------------------------------------------------------------------------
# 3. Peer connector — the actual "autowiring"
# --------------------------------------------------------------------------

