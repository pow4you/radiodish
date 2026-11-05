import asyncio
from radish import RadishSocket


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


if __name__ == "__main__":
    asyncio.run(test_mesh_broadcast_and_recv())
