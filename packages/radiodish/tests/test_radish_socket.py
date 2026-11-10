import asyncio
import socket

import pytest

from radiodish import RadishSocket
from radiodish.autowire import find_free_port_pair


async def test_mesh_broadcast_and_recv():
    a = await RadishSocket().bind("127.0.0.1", 20000)
    b = await RadishSocket().bind("127.0.0.1", 20010)
    c = await RadishSocket().bind("127.0.0.1", 20020)

    # full mesh: everyone connects to everyone
    for x in (a, b, c):
        for y, base in ((a, 20000), (b, 20010), (c, 20020)):
            if x is not y:
                x.connect("127.0.0.1", base)

    for x in (a, b, c):
        x.join("chat")

    await asyncio.sleep(0.1)  # let JOINs land

    a.broadcast("hi from a", group="chat")
    b.broadcast("hi from b", group="chat")

    got_by_c = set()
    for _ in range(2):
        group, payload = await asyncio.wait_for(c.recv(), timeout=1.0)
        assert group == b"chat"
        got_by_c.add(payload)

    assert got_by_c == {b"hi from a", b"hi from b"}, got_by_c

    for x in (a, b, c):
        await x.close()
    print("test_mesh_broadcast_and_recv: PASS")


async def test_default_bind_picks_an_adjacent_port_pair():
    """bind() with no port used to bind RADIO to an OS-assigned port and DISH
    to port 1 (privileged; fails for ordinary users). It must pick a real
    adjacent pair instead, and the result must actually work."""
    a = await RadishSocket().bind("127.0.0.1")
    b = await RadishSocket().bind("127.0.0.1")
    try:
        assert a.port and b.port and a.port != b.port
        assert a._dish_port == a.port + 1
        # the halves really are listening where the socket says they are
        radio_port = a.radio._protocol.transport.get_extra_info("sockname")[1]
        dish_port = a.dish._protocol.transport.get_extra_info("sockname")[1]
        assert (radio_port, dish_port) == (a.port, a.port + 1)

        a.connect("127.0.0.1", b.port)
        b.connect("127.0.0.1", a.port)
        a.join("chat")
        await asyncio.sleep(0.1)  # let the JOIN land
        b.broadcast("hello", group="chat")
        group, payload = await asyncio.wait_for(a.recv(), timeout=1.0)
        assert (group, payload) == (b"chat", b"hello")
    finally:
        await a.close()
        await b.close()


async def test_bind_needs_both_sockets_or_neither():
    port, radio_sock, dish_sock = find_free_port_pair("127.0.0.1")
    try:
        with pytest.raises(ValueError):
            await RadishSocket().bind("127.0.0.1", radio_sock=radio_sock)
        with pytest.raises(ValueError):
            await RadishSocket().bind("127.0.0.1", dish_sock=dish_sock)
    finally:
        radio_sock.close()
        dish_sock.close()


async def test_failed_dish_bind_does_not_leave_the_radio_bound():
    """If the DISH half can't bind, bind() must not leave the RADIO half
    holding its port."""
    port, radio_sock, dish_sock = find_free_port_pair("127.0.0.1")
    radio_sock.close()  # radio's port is free again; dish's stays taken
    r = RadishSocket()
    try:
        with pytest.raises(OSError):
            await r.bind("127.0.0.1", port)
        await asyncio.sleep(0.05)  # transport.close() releases the socket on the next iteration
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.bind(("127.0.0.1", port))  # raises if the radio half leaked
        finally:
            probe.close()
    finally:
        dish_sock.close()


if __name__ == "__main__":
    asyncio.run(test_mesh_broadcast_and_recv())
