"""
Helper for test_cross_process.py -- NOT a test itself (the leading underscore
keeps pytest from collecting it). Run as its own process:

    python _proc_helper.py provider <discovery_port> [file-tier-only]
    python _proc_helper.py caller   <discovery_port> [file-tier-only]

"file-tier-only" makes multicast unavailable in that process, so peers can
only find each other through the same-machine file tier. Without it, a
machine where multicast happens to work could hide a broken file tier.

provider: registers an actor exposing ping(), prints "READY <tempdir>", then
          runs until its stdin is closed, and shuts down cleanly.
caller:   registers a pure-caller actor, calls ping() once, prints one JSON
          line {"result": ..., "tmp": <tempdir>}, exits 0 (non-zero on failure).
"""
import asyncio
import json
import sys
import tempfile

from radioactor import Actor, expose

PORT_RANGE = (25900, 26000)


def disable_multicast() -> None:
    import radiodish.autowire.discovery as aw

    real = aw._make_discovery_socket

    def no_multicast(port, join_multicast=True, multicast_interface=None):
        if join_multicast:
            raise OSError("simulated: multicast unavailable")
        return real(port, join_multicast=False)

    aw._make_discovery_socket = no_multicast


class Provider(Actor):
    id = "xproc-provider"

    @expose()
    async def ping(self, payload):
        return {"pong": payload}


class Caller(Actor):
    pass


async def run_provider(discovery_port: int) -> None:
    provider = await Provider().register(port_range=PORT_RANGE, discovery_port=discovery_port)
    print(f"READY {tempfile.gettempdir()}", flush=True)
    try:
        # blocks until the parent closes our stdin
        await asyncio.get_running_loop().run_in_executor(None, sys.stdin.read)
    finally:
        await provider.close()


async def run_caller(discovery_port: int) -> None:
    caller = await Caller().register(port_range=PORT_RANGE, discovery_port=discovery_port)
    try:
        result = await caller.call("ping", {"seq": 1}, timeout=15.0)
        print(json.dumps({"result": result, "tmp": tempfile.gettempdir()}), flush=True)
    finally:
        await caller.close()


if __name__ == "__main__":
    role, port = sys.argv[1], int(sys.argv[2])
    if "file-tier-only" in sys.argv[3:]:
        disable_multicast()
    asyncio.run(run_provider(port) if role == "provider" else run_caller(port))
