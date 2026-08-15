"""
Run a DISH that joins the "temp" group only (try changing it to "humidity"
or both, in a second instance, to see group filtering in action).

Usage:
    python3 example_dish.py [--bind-port 9001] [--radio host:port ...] [--group temp]
"""
import argparse
import asyncio

from radish import DishSocket


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind-port", type=int, default=9001)
    parser.add_argument("--radio", action="append", default=[],
                         help="host:port of a radio to connect() to, repeatable")
    parser.add_argument("--group", action="append", default=[],
                         help="group to join, repeatable (default: temp)")
    args = parser.parse_args()

    radios = args.radio or ["127.0.0.1:9000"]
    groups = args.group or ["temp"]

    dish = await DishSocket().bind("127.0.0.1", args.bind_port)
    for r in radios:
        host, port = r.split(":")
        dish.connect(host, int(port))
    for g in groups:
        dish.join(g)

    print(f"[dish] bound on 127.0.0.1:{args.bind_port}, connected to {radios}, "
          f"joined groups {groups}")

    try:
        while True:
            group, payload = await dish.recv()
            print(f"[dish] group={group.decode()!r} payload={payload.decode()!r}")
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await dish.close()


if __name__ == "__main__":
    asyncio.run(main())
