"""
radish/autowire/compose.py — autowired_radish(): "on the creation of a
radish, autowire its peers." One call that finds ports, binds, joins
groups, and starts discovery + autowiring together.
"""

from __future__ import annotations

import uuid
from typing import Iterable, Optional

from radish.unified import RadishSocket
from radish.autowire.network import find_free_port_pair, detect_local_addresses
from radish.autowire.discovery import Discoverer, DEFAULT_DISCOVERY_PORT
from radish.autowire.wiring import AutoWirer


async def autowired_radish(
    host: Optional[str] = None,
    groups: Iterable = (),
    interest_groups: Optional[Iterable] = None,
    port_range: tuple[int, int] = (20000, 40000),
    discovery_port: int = DEFAULT_DISCOVERY_PORT,
    seeds: Iterable[tuple[str, int]] = (),
    node_id: Optional[str] = None,
    autowire_poll_interval: float = 0.3,
) -> tuple[RadishSocket, Discoverer, AutoWirer]:
    """
    One call, "on the creation of a radish": finds a free port pair, binds a
    RadishSocket on it, joins `groups`, starts announcing/listening for
    peers, and continuously connects to any discovered peer whose groups
    overlap `interest_groups` (defaults to the same as `groups` — "only wire
    me to peers who care about what I care about").

    Leave `host` unset for the normal case: binds on "0.0.0.0" (every local
    interface at once, loopback included -- always bindable, no guessing
    needed) and announces every address this machine actually has
    (detect_local_addresses(): loopback first, then whatever LAN-facing
    addresses this machine's own hostname resolves to). Peers connect back
    over whichever of those is actually reachable from where they sit --
    loopback for a same-machine peer, a LAN address for one elsewhere on
    the network. Pass an explicit `host` only to override both bind and
    announce with one specific address (e.g. pairing a container-internal
    address with `seeds=` on the other end).

    Returns (radish, discoverer, autowirer). Hold onto discoverer/autowirer
    if you want to inspect known/wired peers later; to tear everything down,
    stop() the autowirer and discoverer, then close() the radish (see
    example_autowire.py).
    """
    if host is not None:
        bind_host = host
        announce_addresses = [host]
        try:
            port, radio_sock, dish_sock = find_free_port_pair(bind_host, *port_range)
        except RuntimeError:
            if bind_host == "127.0.0.1":
                raise
            # an explicitly-given host turned out not to be bindable --
            # fall back to localhost rather than failing outright.
            bind_host = "127.0.0.1"
            announce_addresses = [bind_host]
            port, radio_sock, dish_sock = find_free_port_pair(bind_host, *port_range)
    else:
        bind_host = "0.0.0.0"
        announce_addresses = detect_local_addresses()
        port, radio_sock, dish_sock = find_free_port_pair(bind_host, *port_range)

    radish = RadishSocket()
    await radish.bind(bind_host, port, radio_sock=radio_sock, dish_sock=dish_sock)
    for g in groups:
        radish.join(g)

    node_id = node_id or uuid.uuid4().hex[:12]
    interest = groups if interest_groups is None else interest_groups
    discoverer = await Discoverer(
        node_id=node_id,
        addresses=announce_addresses,
        port=port,
        groups=groups,
        interest=interest,
        discovery_port=discovery_port,
        seeds=seeds,
        auto_refresh_addresses=(host is None),
    ).start()

    wirer = await AutoWirer(radish, discoverer, interest_groups=interest).start(
        poll_interval=autowire_poll_interval
    )

    return radish, discoverer, wirer
