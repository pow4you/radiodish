import asyncio
import socket

from radish.autowire import find_free_port_pair, detect_local_addresses, Discoverer, autowired_radish


def test_find_free_port_pair_no_collision():
    # Hold all 5 pairs open simultaneously -- this is the actual property
    # that matters: as long as a previous result's sockets are still held,
    # a later call must never hand out an overlapping port. (Releasing
    # between calls and expecting *those* ports to stay reserved would be
    # testing something find_free_port_pair never promised.)
    held = []
    used_ports = set()
    for _ in range(5):
        port, radio_sock, dish_sock = find_free_port_pair("127.0.0.1", 21000, 21100)
        assert port % 2 == 0, f"expected even base port, got {port}"
        assert port not in used_ports and (port + 1) not in used_ports
        used_ports.add(port)
        used_ports.add(port + 1)
        held.append((radio_sock, dish_sock))

    # and prove the ports are genuinely reserved right now, not just
    # bookkeeping: a fresh bind attempt on one of them must fail while held
    port, radio_sock, dish_sock = held[0][0].getsockname()[1], *held[0]
    clash = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        raised = False
        try:
            clash.bind(("127.0.0.1", port))
        except OSError:
            raised = True
        assert raised, "port was supposedly reserved but a second bind succeeded"
    finally:
        clash.close()

    for radio_sock, dish_sock in held:
        radio_sock.close()
        dish_sock.close()
    print("test_find_free_port_pair_no_collision: PASS")


def test_detect_local_addresses_always_includes_loopback():
    addresses = detect_local_addresses()
    assert addresses[0] == "127.0.0.1", addresses
    for addr in addresses:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind((addr, 0))  # every announced address must genuinely be bindable
        finally:
            s.close()
    print(f"test_detect_local_addresses_always_includes_loopback: PASS ({addresses})")


async def test_discoverer_finds_peer():
    d1 = await Discoverer(
        node_id="node-1", addresses=["127.0.0.1"], port=30001, groups=["chat"],
        discovery_port=29999, announce_interval=0.3, ttl=3.0,
    ).start()
    d2 = await Discoverer(
        node_id="node-2", addresses=["127.0.0.1"], port=30002, groups=["chat", "metrics"],
        discovery_port=29999, announce_interval=0.3, ttl=3.0,
    ).start()

    deadline = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < deadline:
        if any(p.node_id == "node-2" for p in d1.peers()) and \
           any(p.node_id == "node-1" for p in d2.peers()):
            break
        await asyncio.sleep(0.1)

    ids_seen_by_1 = {p.node_id for p in d1.peers()}
    ids_seen_by_2 = {p.node_id for p in d2.peers()}
    assert "node-2" in ids_seen_by_1, f"node-1 never saw node-2: {ids_seen_by_1}"
    assert "node-1" in ids_seen_by_2, f"node-2 never saw node-1: {ids_seen_by_2}"
    assert "node-1" not in ids_seen_by_1, "node-1 should not see its own announcement"

    peer2_as_seen_by_1 = next(p for p in d1.peers() if p.node_id == "node-2")
    assert set(peer2_as_seen_by_1.groups) == {"chat", "metrics"}

    await d1.stop()
    await d2.stop()
    print("test_discoverer_finds_peer: PASS")


async def test_autowired_radish_end_to_end():
    # Three nodes, three different interest sets, all on the same multicast
    # discovery channel. Verifies AutoWirer only wires matching interests,
    # and that messages actually flow with zero manual connect() calls.
    a, da, wa = await autowired_radish(
        host="127.0.0.1", groups=["sensors"], discovery_port=29998,
        port_range=(31000, 31100),
    )
    b, db, wb = await autowired_radish(
        host="127.0.0.1", groups=["sensors", "logs"], discovery_port=29998,
        port_range=(31000, 31100),
    )
    c, dc, wc = await autowired_radish(
        host="127.0.0.1", groups=["logs"], discovery_port=29998,
        port_range=(31000, 31100),
    )

    # a cares about "sensors" only, so it should end up wired to b (shares
    # "sensors") but never to c (only "logs", no overlap with a's interest).
    deadline = asyncio.get_event_loop().time() + 5.0
    while asyncio.get_event_loop().time() < deadline:
        if len(wa.wired_peers) >= 1 and len(wc.wired_peers) >= 1:
            break
        await asyncio.sleep(0.2)

    assert len(wa.wired_peers) == 1, f"a should wire exactly to b, got {wa.wired_peers}"
    assert len(wc.wired_peers) == 1, f"c should wire exactly to b, got {wc.wired_peers}"

    a.broadcast("temp=21C", group="sensors")
    group, payload = await asyncio.wait_for(b.recv(), timeout=2.0)
    assert group == b"sensors" and payload == b"temp=21C"

    # a and c should never have gotten wired to each other at all
    a_node_id = da.node_id
    c_node_id = dc.node_id
    assert c_node_id not in wa.wired_peers
    assert a_node_id not in wc.wired_peers

    for radish, disc, wirer in ((a, da, wa), (b, db, wb), (c, dc, wc)):
        await wirer.stop()
        await disc.stop()
        await radish.close()
    print("test_autowired_radish_end_to_end: PASS")


async def main():
    test_find_free_port_pair_no_collision()
    test_detect_local_addresses_always_includes_loopback()
    await test_discoverer_finds_peer()
    await test_autowired_radish_end_to_end()


if __name__ == "__main__":
    asyncio.run(main())
