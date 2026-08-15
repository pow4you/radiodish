"""
Two roles in one script, so you can run them as separate real processes.

Provider (exposes 'ping' and an explicit group 'shout_topic'):
    python3 example_actor.py provider

Caller (calls 'ping' every 2s and prints the reply -- no depends_on needed,
it discovers 'ping' dynamically the first time it's called):
    python3 example_actor.py caller

Run both in separate terminals, same machine or LAN segment -- discovery
finds them, AutoWirer wires them (symmetrically, in both directions -- see
autowire.py's Discoverer docstring for why that matters), and calls flow.
"""
import asyncio
import sys

from actor import Actor, expose


class GreeterProvider(Actor):
    id = "greeter"

    @expose()
    async def ping(self, payload):
        print(f"[provider] got ping({payload!r}), replying")
        return {"pong": payload}

    @expose(groups=["shout_topic"])
    async def shout(self, payload):
        print(f"[provider] got shout({payload!r})")
        return str(payload).upper()


async def run_provider():
    provider = await GreeterProvider().register()
    print(f"[provider] registered as {provider.instance_id()}, "
          f"groups={list(provider._groups_to_handlers.keys())}")
    try:
        while True:
            await asyncio.sleep(1.0)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await provider.close()


class Caller(Actor):
    """No @expose'd methods -- a pure caller. Doesn't need depends_on
    either: call() discovers 'ping' on its own, the first time it's
    actually asked to reach it."""
    pass


async def run_caller():
    caller = await Caller().register()
    print(f"[caller] registered as {caller.instance_id()}")
    i = 0
    try:
        while True:
            await asyncio.sleep(2.0)
            i += 1
            # No wired_peers check before calling -- call()'s built-in
            # retry (see actor/base.py's docstring) is exactly what
            # handles "nothing's wired yet, still discovering" gracefully.
            # Gating on wired_peers here would deadlock with dynamic
            # discovery: nothing gets wired until the first call()
            # actually happens, since that's what registers interest.
            try:
                result = await caller.call("ping", {"seq": i}, timeout=3.0)
                print(f"[caller] ping({i}) -> {result}")
            except asyncio.TimeoutError:
                print(f"[caller] ping({i}) timed out (wired peers so far: {caller.wirer.wired_peers})")
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await caller.close()


if __name__ == "__main__":
    role = sys.argv[1] if len(sys.argv) > 1 else "provider"
    if role == "provider":
        asyncio.run(run_provider())
    elif role == "caller":
        asyncio.run(run_caller())
    else:
        print("usage: example_actor.py [provider|caller]")
