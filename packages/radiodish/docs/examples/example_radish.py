"""
A single RadishSocket node: broadcasts on --group every second AND prints
anything it receives, all from one object. Peers are wired by hand with
--peer, so you can see what manual mesh-building looks like before
comparing it to example_autowire.py, which does the wiring for you.

Usage (three terminals, forming a triangle mesh):
    python3 example_radish.py --port 20000 --name alice --group chat --peer 127.0.0.1:20010 --peer 127.0.0.1:20020
    python3 example_radish.py --port 20010 --name bob   --group chat --peer 127.0.0.1:20000 --peer 127.0.0.1:20020
    python3 example_radish.py --port 20020 --name carol --group chat --peer 127.0.0.1:20000 --peer 127.0.0.1:20010

Remember each RadishSocket reserves TWO ports: --port (RADIO) and
--port + 1 (DISH) -- so give each node's --port a gap of at least 2.
"""
import argparse
import asyncio

from radish import RadishSocket


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True, help="base port (uses port and port+1)")
    parser.add_argument("--name", default="node")
    parser.add_argument("--group", action="append", default=[], help="group to join+broadcast on, repeatable")
    parser.add_argument("--peer", action="append", default=[], help="host:base_port to connect to, repeatable")
    args = parser.parse_args()

    groups = args.group or ["chat"]

    node = await RadishSocket().bind(args.host, args.port)
    for g in groups:
        node.join(g)
    for p in args.peer:
        host, port = p.split(":")
        node.connect(host, int(port))

    print(f"[{args.name}] bound on {args.host}:{args.port}/{args.port+1}, "
          f"groups={groups}, peers={args.peer}")

    async def broadcaster():
        i = 0
        while True:
            await asyncio.sleep(1.0)
            i += 1
            msg = f"{args.name}#{i}"
            node.broadcast(msg, group=groups[0])
            print(f"[{args.name}] -> {msg} (group={groups[0]!r})")

    async def receiver():
        while True:
            group, payload = await node.recv()
            print(f"[{args.name}] <- {payload.decode()!r} (group={group.decode()!r})")

    try:
        await asyncio.gather(broadcaster(), receiver())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await node.close()


if __name__ == "__main__":
    asyncio.run(main())
