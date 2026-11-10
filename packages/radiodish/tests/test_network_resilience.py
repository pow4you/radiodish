import asyncio

from radiodish.autowire import Discoverer, AutoWirer
from radiodish import RadishSocket


class _SocketSpy:
    """Wraps discovery's OS-level socket factory so lifecycle tests can see
    what really happens to sockets. Everything above the factory (the
    Discoverer, its revalidation, its transports) is the real code; the
    sockets themselves are real too. The spy only (a) records every socket
    created, so a test can count how many are still open, and (b) can make
    multicast, or everything, fail on demand.

    pretend_multicast_works=True hands out a plain socket whenever a
    multicast join is requested, so "multicast is up" is deterministic
    regardless of whether this machine's real multicast works -- a test
    that needs the real thing to succeed would be testing the environment
    rather than the code."""

    def __init__(self, pretend_multicast_works=True):
        import radiodish.autowire.discovery as aw

        self._aw = aw
        self._real = aw._make_discovery_socket
        self.pretend_multicast_works = pretend_multicast_works
        self.block_multicast = False
        self.block_all = False
        self.created = []

    def __enter__(self):
        def fake(port, join_multicast=True, multicast_interface=None):
            if self.block_all or (join_multicast and self.block_multicast):
                raise OSError("simulated: no socket available")
            if join_multicast and self.pretend_multicast_works:
                sock = self._real(port, join_multicast=False)
            else:
                sock = self._real(
                    port, join_multicast=join_multicast, multicast_interface=multicast_interface
                )
            self.created.append(sock)
            return sock

        self._aw._make_discovery_socket = fake
        return self

    def __exit__(self, *exc):
        self._aw._make_discovery_socket = self._real

    def open_count(self):
        return sum(1 for s in self.created if s.fileno() != -1)


async def _let_transports_close():
    # transport.close() releases the socket on the next loop iteration
    await asyncio.sleep(0.05)


async def test_start_never_raises_when_multicast_is_blocked():
    """Simulate an environment where multicast join fails on every
    interface (both the any-interface and loopback-scoped attempts) but
    plain UDP bind works -- Discoverer.start() should come up in degraded
    mode, not raise."""
    import radiodish.autowire.discovery as aw

    real_make_socket = aw._make_discovery_socket

    def fake_make_socket(port, join_multicast=True, multicast_interface=None):
        if join_multicast:
            raise OSError("simulated: no multicast-capable interface")
        return real_make_socket(port, join_multicast=False)

    aw._make_discovery_socket = fake_make_socket
    try:
        d = await Discoverer(
            node_id="restricted-node", addresses=["127.0.0.1"], port=40001,
            groups=["chat"], discovery_port=28500,
        ).start()
        assert d._multicast_active is False, "should have come up in degraded mode"
        assert d._protocol is not None, "should still have SOME working socket"
        await d.stop()
        print("test_start_never_raises_when_multicast_is_blocked: PASS")
    finally:
        aw._make_discovery_socket = real_make_socket


async def test_revalidation_does_not_leak_sockets():
    """Revalidating over and over on a stable network must not accumulate
    discovery sockets: exactly one stays open, however many cycles run."""
    with _SocketSpy() as spy:
        d = await Discoverer(
            node_id="leak-test-node", addresses=["127.0.0.1"], port=40070,
            groups=["chat"], discovery_port=28550,
        ).start()
        for _ in range(25):
            await d._revalidate_once()
        await _let_transports_close()

        assert len(spy.created) >= 26, "each cycle should have opened a fresh socket"
        assert spy.open_count() == 1, (
            f"{spy.open_count()} discovery sockets still open after 25 "
            "revalidations of an unchanged network -- old ones are leaking"
        )
        await d.stop()
        await _let_transports_close()
        assert spy.open_count() == 0, "stop() should release the last socket"
    print("test_revalidation_does_not_leak_sockets: PASS")


async def test_upgrade_replaces_and_closes_old_socket():
    """Degraded start, then multicast becomes available: the next
    revalidation upgrades the tier AND releases the plain socket it
    replaced."""
    with _SocketSpy() as spy:
        spy.block_multicast = True
        d = await Discoverer(
            node_id="upgrade-test-node", addresses=["127.0.0.1"], port=40071,
            groups=["chat"], discovery_port=28551,
        ).start()
        assert d._multicast_active is False
        first = spy.created[0]
        assert spy.open_count() == 1

        spy.block_multicast = False
        await d._revalidate_once()
        await _let_transports_close()

        assert d._multicast_active is True, "revalidation never picked up the upgrade"
        assert first.fileno() == -1, "the socket replaced by the upgrade was never closed"
        assert spy.open_count() == 1
        await d.stop()
    print("test_upgrade_replaces_and_closes_old_socket: PASS")


async def test_downgrade_replaces_and_closes_old_socket():
    """The other direction: multicast works at start, then stops. The next
    revalidation falls back to a plain socket and releases the multicast
    one."""
    with _SocketSpy() as spy:
        d = await Discoverer(
            node_id="downgrade-test-node", addresses=["127.0.0.1"], port=40072,
            groups=["chat"], discovery_port=28552,
        ).start()
        assert d._multicast_active is True
        first = spy.created[0]

        spy.block_multicast = True
        await d._revalidate_once()
        await _let_transports_close()

        assert d._multicast_active is False, "revalidation never noticed multicast went away"
        assert first.fileno() == -1, "the multicast socket was never closed after the downgrade"
        assert spy.open_count() == 1
        await d.stop()
    print("test_downgrade_replaces_and_closes_old_socket: PASS")


async def test_failed_revalidation_keeps_the_working_socket():
    """If a revalidation cycle can't open ANY socket (transient failure),
    the socket that was working must stay open and active, not be torn
    down -- and a later cycle that succeeds must recover cleanly."""
    with _SocketSpy() as spy:
        d = await Discoverer(
            node_id="keep-old-node", addresses=["127.0.0.1"], port=40073,
            groups=["chat"], discovery_port=28553,
        ).start()
        before = d._protocol
        state = (d._multicast_active, d._multicast_scope)

        spy.block_all = True
        await d._revalidate_once()
        await _let_transports_close()
        assert d._protocol is before
        assert not before.transport.is_closing(), "a working socket was closed over a failed attempt"
        assert (d._multicast_active, d._multicast_scope) == state
        assert spy.open_count() == 1

        spy.block_all = False
        await d._revalidate_once()
        await _let_transports_close()
        assert d._protocol is not before
        assert spy.open_count() == 1
        await d.stop()
    print("test_failed_revalidation_keeps_the_working_socket: PASS")


async def test_same_machine_discovery_independent_of_multicast():
    """The property that actually matters most in practice: two real,
    unmocked Discoverers on the same machine, same discovery_port, find
    each other regardless of whether real multicast happens to work in
    this environment at all -- because the local-file tier doesn't
    involve the network stack in any way."""
    a = await Discoverer(
        node_id="local-a", addresses=["127.0.0.1"], port=40020,
        groups=["chat"], discovery_port=28520,
    ).start()
    b = await Discoverer(
        node_id="local-b", addresses=["127.0.0.1"], port=40021,
        groups=["chat"], discovery_port=28520,
    ).start()

    deadline = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < deadline:
        if any(p.node_id == "local-b" for p in a.peers()) and any(
            p.node_id == "local-a" for p in b.peers()
        ):
            break
        await asyncio.sleep(0.1)

    assert any(p.node_id == "local-b" for p in a.peers()), "a never found b"
    assert any(p.node_id == "local-a" for p in b.peers()), "b never found a"

    await a.stop()
    await b.stop()
    print("test_same_machine_discovery_independent_of_multicast: PASS")


async def test_discoverer_refreshes_own_addresses_when_they_change():
    """The exact scenario reported: a node starts with a limited address
    list (standing in for 'started before WiFi came on'), and should pick
    up a richer one later on its own, without needing a restart -- this is
    what makes it possible for such a node to ever be reachable via
    anything but loopback."""
    import radiodish.autowire.discovery as aw

    d = Discoverer(
        node_id="was-offline", addresses=["127.0.0.1"], port=40030,
        groups=["chat"], discovery_port=28530,
    )
    # force it to look like it started with nothing but loopback, then
    # simulate "WiFi came on" by having the next detect_local_addresses()
    # call return more than that
    call_count = {"n": 0}
    real_detect = aw.detect_local_addresses

    def fake_detect():
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ["127.0.0.1"]
        return ["127.0.0.1", "192.168.50.50"]  # "WiFi just connected"

    aw.detect_local_addresses = fake_detect
    try:
        await d.start()
        assert d.addresses == ["127.0.0.1"]

        # cancel the slow default revalidate loop, replace with a fast one
        for t in d._tasks:
            t.cancel()
        d._tasks = [asyncio.ensure_future(d._revalidate_loop(interval=0.1))]

        deadline = asyncio.get_event_loop().time() + 2.0
        while asyncio.get_event_loop().time() < deadline and d.addresses == ["127.0.0.1"]:
            await asyncio.sleep(0.05)

        assert "192.168.50.50" in d.addresses, (
            f"node never picked up its new address after 'WiFi came on', "
            f"still announcing {d.addresses}"
        )
        await d.stop()
        print("test_discoverer_refreshes_own_addresses_when_they_change: PASS")
    finally:
        aw.detect_local_addresses = real_detect


async def test_autowirer_connects_new_address_for_already_wired_peer():
    """The other half: even a peer AutoWirer already wired to should get
    connect() called again if that peer's announced address list grows
    later -- otherwise a node that only had loopback at first contact
    stays stuck on loopback forever, even after it gains a real address
    other machines on the LAN could actually use."""
    radish = await RadishSocket().bind("127.0.0.1", 40040)
    discoverer = await Discoverer(
        node_id="watcher", addresses=["127.0.0.1"], port=40040,
        groups=["chat"], discovery_port=28531,
    ).start()
    wirer = await AutoWirer(radish, discoverer, interest_groups=["chat"]).start(
        poll_interval=0.1
    )

    # simulate discovering a peer that, at first, only knows about loopback
    from radiodish.autowire import PeerInfo
    import time

    discoverer._peers["peer-1"] = PeerInfo(
        node_id="peer-1", addresses=("127.0.0.1",), port=40041,
        groups=("chat",), interest=("chat",), last_seen=time.monotonic(),
    )

    await asyncio.sleep(0.3)
    assert wirer.wired_peers == {"peer-1"}
    assert radish.radio._peers.get(("127.0.0.1", 40042)) is not None  # dish port = radio port + 1

    # now the peer "gains WiFi" -- its address list grows
    discoverer._peers["peer-1"] = PeerInfo(
        node_id="peer-1", addresses=("127.0.0.1", "192.168.50.60"), port=40041,
        groups=("chat",), interest=("chat",), last_seen=time.monotonic(),
    )

    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline:
        if radish.radio._peers.get(("192.168.50.60", 40042)) is not None:
            break
        await asyncio.sleep(0.05)

    assert radish.radio._peers.get(("192.168.50.60", 40042)) is not None, (
        "AutoWirer never connect()'d the peer's new address after it "
        "was already wired via the old one"
    )

    await wirer.stop()
    await discoverer.stop()
    await radish.close()
    print("test_autowirer_connects_new_address_for_already_wired_peer: PASS")


async def test_falls_back_to_loopback_scoped_multicast():
    """When any-interface multicast fails but loopback-scoped multicast
    would succeed, _try_open_socket should land on the loopback tier
    rather than dropping straight to no-multicast-at-all. Simulates the
    any-interface failure (the WiFi-off case); the loopback attempt itself
    is real, not mocked, since that's the actual mechanism being tested."""
    import radiodish.autowire.discovery as aw

    real_make_socket = aw._make_discovery_socket

    def fake_make_socket(port, join_multicast=True, multicast_interface=None):
        if join_multicast and multicast_interface is None:
            raise OSError("simulated: any-interface join fails (the WiFi-off case)")
        return real_make_socket(port, join_multicast=join_multicast, multicast_interface=multicast_interface)

    aw._make_discovery_socket = fake_make_socket
    try:
        d = await Discoverer(
            node_id="loopback-scoped-node", addresses=["127.0.0.1"], port=40050,
            groups=["chat"], discovery_port=28540,
        ).start()
        assert d._multicast_active is True, "should have landed on SOME multicast tier"
        assert d._multicast_scope == "loopback", f"expected loopback tier, got {d._multicast_scope!r}"
        await d.stop()
        print("test_falls_back_to_loopback_scoped_multicast: PASS")
    finally:
        aw._make_discovery_socket = real_make_socket


async def test_loopback_scoped_multicast_actually_delivers():
    """Not just a state-flag check -- two Discoverers, both forced onto the
    loopback tier (simulating any-interface being unavailable on both),
    should still genuinely find each other over real (loopback-scoped)
    multicast, not just fall through to the file tier by coincidence."""
    import radiodish.autowire.discovery as aw

    real_make_socket = aw._make_discovery_socket

    def fake_make_socket(port, join_multicast=True, multicast_interface=None):
        if join_multicast and multicast_interface is None:
            raise OSError("simulated: any-interface join fails")
        return real_make_socket(port, join_multicast=join_multicast, multicast_interface=multicast_interface)

    aw._make_discovery_socket = fake_make_socket
    try:
        a = await Discoverer(
            node_id="lb-a", addresses=["127.0.0.1"], port=40060,
            groups=["chat"], discovery_port=28541, announce_interval=0.3,
        ).start()
        b = await Discoverer(
            node_id="lb-b", addresses=["127.0.0.1"], port=40061,
            groups=["chat"], discovery_port=28541, announce_interval=0.3,
        ).start()
        assert a._multicast_scope == "loopback" and b._multicast_scope == "loopback"

        deadline = asyncio.get_event_loop().time() + 3.0
        while asyncio.get_event_loop().time() < deadline:
            if any(p.node_id == "lb-b" for p in a.peers()) and any(
                p.node_id == "lb-a" for p in b.peers()
            ):
                break
            await asyncio.sleep(0.1)

        assert any(p.node_id == "lb-b" for p in a.peers()), "a never heard b over loopback multicast"
        assert any(p.node_id == "lb-a" for p in b.peers()), "b never heard a over loopback multicast"

        await a.stop()
        await b.stop()
        print("test_loopback_scoped_multicast_actually_delivers: PASS")
    finally:
        aw._make_discovery_socket = real_make_socket


async def main():
    await test_start_never_raises_when_multicast_is_blocked()
    await test_revalidation_does_not_leak_sockets()
    await test_upgrade_replaces_and_closes_old_socket()
    await test_downgrade_replaces_and_closes_old_socket()
    await test_failed_revalidation_keeps_the_working_socket()
    await test_same_machine_discovery_independent_of_multicast()
    await test_discoverer_refreshes_own_addresses_when_they_change()
    await test_autowirer_connects_new_address_for_already_wired_peer()
    await test_falls_back_to_loopback_scoped_multicast()
    await test_loopback_scoped_multicast_actually_delivers()


if __name__ == "__main__":
    asyncio.run(main())
