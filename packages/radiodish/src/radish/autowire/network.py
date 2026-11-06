"""
radish/autowire/network.py — automatic port assignment and local address
detection: the pieces that figure out "what port pair is free" and "what
address(es) can this machine be reached at," with no dependency on
whether a network is even connected.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Optional


def _try_bind_udp(host: str, port: int) -> Optional[socket.socket]:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind((host, port))
        return s
    except OSError:
        s.close()
        return None


def find_free_port_pair(
    host: str = "0.0.0.0", start: int = 20000, end: int = 40000
) -> tuple[int, socket.socket, socket.socket]:
    """
    Find a free (port, port + 1) pair for a RadishSocket's RADIO/DISH halves
    and return the port along with both *already-bound* sockets.

    Returning live sockets rather than just an int matters: if this only
    returned a number, there'd be a gap between "we confirmed it's free" and
    "RadishSocket actually binds it" where another process could grab the
    port first (a classic check-then-act race). Handing back sockets that
    are already bound — for RadishSocket.bind(radio_sock=, dish_sock=) to
    take over directly — closes that gap; the port is ours the moment this
    function returns.

    Only even base ports are tried, so two nodes on the same host can never
    be assigned overlapping pairs (node A on (9000,9001) and node B on
    (9001,9002) would both think they own 9001).
    """
    first = start + (start % 2)  # round up to the nearest even number
    for candidate in range(first, end, 2):
        radio_sock = _try_bind_udp(host, candidate)
        if radio_sock is None:
            continue
        dish_sock = _try_bind_udp(host, candidate + 1)
        if dish_sock is None:
            radio_sock.close()
            continue
        return candidate, radio_sock, dish_sock
    raise RuntimeError(f"no free UDP port pair found in [{start}, {end}) on {host!r}")


def detect_local_addresses() -> list[str]:
    """
    Every address this machine could plausibly be reached at, ordered
    "most local first": loopback, then whatever LAN-facing addresses can
    be found. Deliberately makes no outbound contact with anything -- not
    even the harmless connect()-only trick this used to use against
    8.8.8.8, since that still asks the OS to resolve a route toward the
    public internet specifically, and what that resolves to when there's
    no real internet route is genuinely inconsistent across OSes and
    network states (confirmed in practice, not just in theory: it was
    producing addresses that couldn't actually reach a same-machine peer
    on some setups).

    Two independent techniques are combined, since each covers cases the
    other misses:

    1. socket.gethostbyname_ex(socket.gethostname()) -- pure local
       resolver/hosts-file/NSS lookup, no network round-trip at all. Can
       be stale or just not configured to reflect the current LAN address
       on some systems (notably common on laptops that roam between
       networks).
    2. A UDP connect()-then-getsockname() route lookup aimed at a
       PRIVATE address (10.255.255.255) rather than a public one. Still
       zero packets sent -- UDP connect() is purely a local routing-table
       lookup, nothing is transmitted -- but asking "what's my LAN route"
       instead of "what's my internet route" matters: a LAN-only setup
       with no default gateway configured at all can still have a
       specific route to a private subnet, so this can succeed in cases
       where the old public-address version would just fail outright.

    Every candidate from either technique is verified with a real bind
    attempt before being trusted -- a route lookup succeeding doesn't
    guarantee the resulting address is actually bindable on this host.
    "127.0.0.1" is always first and always present regardless of whether
    either technique finds anything, so same-machine discovery never
    depends on either one succeeding.
    """
    addresses = ["127.0.0.1"]

    def _try_add(candidate: str) -> None:
        if candidate in addresses:
            return
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.bind((candidate, 0))
            addresses.append(candidate)
        except OSError:
            pass  # a technique found it, but it's not actually bindable here -- skip it
        finally:
            probe.close()

    # technique 1: local hostname resolution (no network round-trip)
    try:
        _hostname, _aliases, ip_list = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        ip_list = []
    for candidate in ip_list:
        _try_add(candidate)

    # technique 2: LAN-facing route lookup -- still zero packets sent, see
    # docstring above for why a private target specifically matters here
    route_probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        route_probe.connect(("10.255.255.255", 1))
        _try_add(route_probe.getsockname()[0])
    except OSError:
        pass
    finally:
        route_probe.close()

    return addresses

def _is_local_scope_address(host: str) -> bool:
    """True for loopback / private-LAN / link-local addresses; False for
    anything that looks like a real public IP. Used only to decide whether
    to warn about a seed -- not a security boundary, just a nudge toward
    "did you mean to point this at the open internet?" Hostnames (not IP
    literals) are assumed intentional and never warned about, since
    resolving them here would mean doing DNS just to decide on a warning."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return True  # not an IP literal (a hostname) -- don't warn
    return addr.is_private or addr.is_loopback or addr.is_link_local


