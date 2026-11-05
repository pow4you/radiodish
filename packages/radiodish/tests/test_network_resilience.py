import asyncio

from radish.autowire import Discoverer, AutoWirer
from radish import RadishSocket


async def test_start_never_raises_when_multicast_is_blocked():
    """Simulate an environment where multicast join fails on every
    interface (both the any-interface and loopback-scoped attempts) but
    plain UDP bind works -- Discoverer.start() should come up in degraded
    mode, not raise."""
    import radish.autowire.discovery as aw

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


async def test_upgrade_state_machine():
    """Fully mocked -- proves the revalidate loop's own logic (swap the
    socket, flip _multicast_active) works when the outcome of
    _try_open_socket() changes, WITHOUT depending on whether this
    environment's real OS multicast actually works at all. That's
    deliberate: on a machine where real multicast genuinely never succeeds
    (confirmed possible -- see test_start_never_raises_when_multicast_is_
    blocked's premise), a test that only passes if the real thing
    eventually succeeds would be testing the environment, not the code.
    """
    d = await Discoverer(
        node_id="upgrade-test-node", addresses=["127.0.0.1"], port=40010,
        groups=["chat"], discovery_port=28510,
    ).start()
    d._multicast_active = False  # force degraded, regardless of how it actually started

    async def fake_try_open_succeeds():
        d._multicast_active = True
        return True

    d._try_open_socket = fake_try_open_succeeds
    for t in d._tasks:
        t.cancel()
    d._tasks = [asyncio.ensure_future(d._revalidate_loop(interval=0.1))]

    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline and not d._multicast_active:
        await asyncio.sleep(0.05)

    assert d._multicast_active is True, "revalidate loop never picked up the simulated upgrade"
    await d.stop()
    print("test_upgrade_state_machine: PASS")


async def test_downgrade_state_machine():
    """The other direction, which the first version of this fix didn't
    have at all: a Discoverer that WAS in multicast-active mode should
    detect and gracefully fall back if multicast setup starts failing
    later (network dropped mid-session), not just upgrade from a cold
    degraded start."""
    d = await Discoverer(
        node_id="downgrade-test-node", addresses=["127.0.0.1"], port=40011,
        groups=["chat"], discovery_port=28511,
    ).start()
    d._multicast_active = True  # force active, regardless of how it actually started

    async def fake_try_open_now_fails():
        d._multicast_active = False
        return True  # still got SOME socket (degraded/plain), just not multicast

    d._try_open_socket = fake_try_open_now_fails
    for t in d._tasks:
        t.cancel()
    d._tasks = [asyncio.ensure_future(d._revalidate_loop(interval=0.1))]

    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline and d._multicast_active:
        await asyncio.sleep(0.05)

    assert d._multicast_active is False, "revalidate loop never noticed multicast went away"
    await d.stop()
    print("test_downgrade_state_machine: PASS")


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
    import radish.autowire.discovery as aw

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
    from radish.autowire import PeerInfo
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
    import radish.autowire.discovery as aw

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
    import radish.autowire.discovery as aw

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
    await test_upgrade_state_machine()
    await test_downgrade_state_machine()
    await test_same_machine_discovery_independent_of_multicast()
    await test_discoverer_refreshes_own_addresses_when_they_change()
    await test_autowirer_connects_new_address_for_already_wired_peer()
    await test_falls_back_to_loopback_scoped_multicast()
    await test_loopback_scoped_multicast_actually_delivers()


if __name__ == "__main__":
    asyncio.run(main())
