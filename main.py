"""
radiodish in 60 lines: two actors, one process, zero wiring.

    uv sync --all-packages
    uv run python main.py

A `Greeter` exposes two methods, a `Caller` talks to it. Nobody tells either
actor where the other lives: they find free ports, announce themselves over
UDP multicast (or loopback, if multicast is blocked), discover each other and
connect on their own. Calls are addressed to a *group* (by default the
function name), not to a specific actor.

To see the same thing across real processes or machines, run the two roles
separately -- see packages/radiodish-actor/docs/examples/example_actor.py.
"""
import asyncio
import time

from radioactor import Actor, expose

# A private discovery port and port range, so this demo never accidentally
# joins an unrelated radiodish mesh running on the same network.
MESH = dict(discovery_port=27777, port_range=(30000, 30100))


class Greeter(Actor):
    id = "greeter"

    @expose()
    async def ping(self, payload):
        return {"pong": payload}

    @expose(groups=["shout_topic"])
    async def shout(self, payload):
        return str(payload).upper()


class Caller(Actor):
    """A pure caller: no exposed methods, no declared dependencies."""


async def main():
    greeter = await Greeter().register(**MESH)
    caller = await Caller().register(**MESH)
    print(f"greeter up as {greeter.instance_id()}")
    print(f"caller  up as {caller.instance_id()}\n")

    # The first call triggers discovery and wiring; call() retries
    # until the mesh has formed, so there is nothing to wait for by hand.
    start = time.perf_counter()
    reply = await caller.call("ping", {"seq": 1}, timeout=5.0)
    print(f"ping({{'seq': 1}})         -> {reply}   "
          f"({time.perf_counter() - start:.2f}s, includes discovery)")

    start = time.perf_counter()
    reply = await caller.call("ping", {"seq": 2}, timeout=5.0)
    print(f"ping({{'seq': 2}})         -> {reply}   "
          f"({time.perf_counter() - start:.3f}s)")

    # Addressed via the explicit group declared in @expose(groups=[...]).
    reply = await caller.call("shout_topic", "radio dish", timeout=5.0)
    print(f"shout_topic('radio dish') -> {reply!r}")

    # Nobody listens on this group, so this is just a timeout -- there is
    # no "method not found", because a group may legitimately be empty.
    try:
        await caller.call("nobody_home", None, timeout=1.0)
    except asyncio.TimeoutError:
        print("nobody_home()             -> timed out (empty group, as expected)")

    await caller.close()
    await greeter.close()


if __name__ == "__main__":
    asyncio.run(main())
