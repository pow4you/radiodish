"""
A fully autowired RadishSocket node: no --peer list, no manual connect()
anywhere. It finds its own free ports, joins its groups, announces itself
over multicast, listens for other nodes doing the same, and auto-connects to
anyone whose groups overlap its own -- then broadcasts and prints whatever
it receives. Compare against example_radish.py's manual wiring.

Usage (three terminals, same machine or same LAN segment):
    python3 example_autowire.py --name alice --group sensors
    python3 example_autowire.py --name bob   --group sensors --group logs
    python3 example_autowire.py --name carol --group logs

alice and carol never connect to each other directly (no shared group) --
bob bridges both. Watch the "[wired]" lines to see AutoWirer working.

If multicast doesn't reach across your network (common in Docker/cloud),
add --seed host:port pointing discovery at specific peers directly:
    python3 example_autowire.py --name remote --group sensors --seed 10.0.0.5:9999
"""
import argparse
import asyncio

from radish.autowire import autowired_radish, DEFAULT_DISCOVERY_PORT


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="node")
    parser.add_argument("--group", action="append", default=[], help="repeatable")
    parser.add_argument("--host", default=None, help="advertise/bind address; auto-detected if omitted")
    parser.add_argument("--discovery-port", type=int, default=DEFAULT_DISCOVERY_PORT)
    parser.add_argument("--seed", action="append", default=[], help="host:port, repeatable; unicast fallback when multicast can't reach")
    args = parser.parse_args()

    groups = args.group or ["chat"]
    seeds = []
    for s in args.seed:
        host, port = s.split(":")
        seeds.append((host, int(port)))

    radish, discoverer, wirer = await autowired_radish(
        host=args.host,
        groups=groups,
        discovery_port=args.discovery_port,
        seeds=seeds,
        node_id=args.name,
    )
    print(f"[{args.name}] autowired on {radish._host}:{radish._radio_port}/{radish._dish_port}, "
          f"groups={groups}, discovery_port={args.discovery_port}")

    known_printed = set()

    async def status_loop():
        while True:
            await asyncio.sleep(1.0)
            for peer in discoverer.peers():
                if peer.node_id in wirer.wired_peers and peer.node_id not in known_printed:
                    known_printed.add(peer.node_id)
                    print(f"[{args.name}] [wired] -> {peer.node_id} "
                          f"({peer.addresses}:{peer.port}, groups={list(peer.groups)})")

    async def broadcaster():
        i = 0
        while True:
            await asyncio.sleep(2.0)
            i += 1
            msg = f"{args.name}#{i}"
            radish.broadcast(msg, group=groups[0])
            print(f"[{args.name}] -> {msg} (group={groups[0]!r})")

    async def receiver():
        while True:
            group, payload = await radish.recv()
            print(f"[{args.name}] <- {payload.decode()!r} (group={group.decode()!r})")

    try:
        await asyncio.gather(status_loop(), broadcaster(), receiver())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await wirer.stop()
        await discoverer.stop()
        await radish.close()


if __name__ == "__main__":
    asyncio.run(main())
