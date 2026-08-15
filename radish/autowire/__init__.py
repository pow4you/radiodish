"""
radish.autowire — automatic port assignment, peer discovery, and peer
connection on top of radish.RadishSocket.

    radish.autowire.network             find_free_port_pair, detect_local_addresses
    radish.autowire.local_discovery      the "my machine" file-based tier
    radish.autowire.discovery             the "my LAN" multicast tier, and Discoverer
    radish.autowire.wiring                  AutoWirer -- the actual autowiring
    radish.autowire.compose                  autowired_radish() -- one-call entrypoint

For most uses:

    from radish.autowire import autowired_radish
    radish, discoverer, wirer = await autowired_radish(groups=["sensors"])
"""

from radish.autowire.network import find_free_port_pair, detect_local_addresses
from radish.autowire.discovery import Discoverer, PeerInfo, MULTICAST_GROUP, DEFAULT_DISCOVERY_PORT
from radish.autowire.wiring import AutoWirer
from radish.autowire.compose import autowired_radish

__all__ = [
    "autowired_radish",
    "Discoverer",
    "AutoWirer",
    "PeerInfo",
    "find_free_port_pair",
    "detect_local_addresses",
    "MULTICAST_GROUP",
    "DEFAULT_DISCOVERY_PORT",
]
