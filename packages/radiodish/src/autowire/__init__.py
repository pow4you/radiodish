"""
radiodish.autowire — automatic port assignment, peer discovery, and peer
connection on top of radiodish.RadishSocket.

    radiodish.autowire.network             find_free_port_pair, detect_local_addresses
    radiodish.autowire.local_discovery      the "my machine" file-based tier
    radiodish.autowire.discovery             the "my LAN" multicast tier, and Discoverer
    radiodish.autowire.wiring                  AutoWirer -- the actual autowiring
    radiodish.autowire.compose                  autowired_radish() -- one-call entrypoint

For most uses:

    from radiodish.autowire import autowired_radish
    radish, discoverer, wirer = await autowired_radish(groups=["sensors"])
"""

from radiodish.autowire.network import find_free_port_pair, detect_local_addresses
from radiodish.autowire.discovery import Discoverer, PeerInfo, MULTICAST_GROUP, DEFAULT_DISCOVERY_PORT
from radiodish.autowire.wiring import AutoWirer
from radiodish.autowire.compose import autowired_radish

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
