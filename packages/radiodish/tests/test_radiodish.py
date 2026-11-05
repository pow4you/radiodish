import asyncio
from radish import RadioSocket, DishSocket


async def test_basic_group_filtering():
    radio = await RadioSocket().bind("127.0.0.1", 0)
    radio_addr = radio._protocol.transport.get_extra_info("sockname")

    dish = await DishSocket().bind("127.0.0.1", 0)
    dish.connect(*radio_addr)
    dish.join("temp")

    await asyncio.sleep(0.05)  # let the JOIN control frame arrive

    radio.connect(*dish._protocol.transport.get_extra_info("sockname"))
    await asyncio.sleep(0.05)  # radio auto-registers dish as peer via JOIN anyway

    await radio.send(b"21.5C", group="temp")
    await radio.send(b"55%", group="humidity")  # dish hasn't joined this

    group, payload = await asyncio.wait_for(dish.recv(), timeout=1.0)
    assert group == b"temp" and payload == b"21.5C", (group, payload)

    # confirm the humidity message never arrives
    try:
        await asyncio.wait_for(dish.recv(), timeout=0.2)
        raise AssertionError("should not have received an unjoined group's message")
    except asyncio.TimeoutError:
        pass

    await radio.close()
    await dish.close()
    print("test_basic_group_filtering: PASS")


async def test_fairness_and_multi_radio():
    dish = await DishSocket().bind("127.0.0.1", 0)
    dish.join("evt")

    radios = []
    for _ in range(3):
        r = await RadioSocket().bind("127.0.0.1", 0)
        radios.append(r)
        dish.connect(*r._protocol.transport.get_extra_info("sockname"))

    await asyncio.sleep(0.05)
    for i, r in enumerate(radios):
        r.connect(*dish._protocol.transport.get_extra_info("sockname"))
    await asyncio.sleep(0.05)

    # One radio floods, others send one message each -> fairness should
    # interleave delivery rather than starving the quiet radios.
    for i in range(50):
        await radios[0].send(f"flood-{i}".encode(), group="evt")
    await radios[1].send(b"quiet-1", group="evt")
    await radios[2].send(b"quiet-2", group="evt")

    seen_quiet_within_first_10 = False
    received = []
    for _ in range(10):
        group, payload = await asyncio.wait_for(dish.recv(), timeout=1.0)
        received.append(payload)
    if b"quiet-1" in received or b"quiet-2" in received:
        seen_quiet_within_first_10 = True

    assert seen_quiet_within_first_10, f"fairness failed, first 10: {received}"

    for r in radios:
        await r.close()
    await dish.close()
    print("test_fairness_and_multi_radio: PASS")


async def test_queue_drop_when_full():
    radio = await RadioSocket().bind("127.0.0.1", 0)
    dish = await DishSocket(queue_size=3).bind("127.0.0.1", 0)
    dish.connect(*radio._protocol.transport.get_extra_info("sockname"))
    dish.join("g")
    await asyncio.sleep(0.05)
    radio.connect(*dish._protocol.transport.get_extra_info("sockname"))
    await asyncio.sleep(0.05)

    # Pause the dispatcher's consumption by not calling recv() yet; send more
    # than queue_size messages and confirm we don't get all of them.
    for i in range(20):
        await radio.send(str(i).encode(), group="g")
    await asyncio.sleep(0.1)

    got = []
    try:
        while True:
            group, payload = await asyncio.wait_for(dish.recv(), timeout=0.2)
            got.append(payload)
    except asyncio.TimeoutError:
        pass

    assert len(got) < 20, f"expected drops under a bounded queue, got {len(got)} of 20"
    print(f"test_queue_drop_when_full: PASS ({len(got)}/20 delivered, rest silently dropped)")

    await radio.close()
    await dish.close()


async def main():
    await test_basic_group_filtering()
    await test_fairness_and_multi_radio()
    await test_queue_drop_when_full()


if __name__ == "__main__":
    asyncio.run(main())
