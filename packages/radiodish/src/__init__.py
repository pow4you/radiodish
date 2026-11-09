"""
radiodish — a standalone, asyncio-native RADIO/DISH implementation over UDP.

This is an independent implementation of the pattern described in ZeroMQ
RFC 48 (https://rfc.zeromq.org/spec/48/). It does not depend on libzmq or
pyzmq at all — it's built directly on asyncio's UDP transport.

Package layout:
    radiodish.errors     RadioDishError, InvalidGroupError (re-exported from radiodish._internal.errors)
    radiodish.protocol    wire format: encode_frame/decode_frame, MSG_DATA/JOIN/LEAVE
    radiodish.transport    shared plumbing: _UDPProtocol, _BoundedDropQueue, _Peer
    radiodish.radio         RadioSocket (RFC 48's RADIO type)
    radiodish.dish            DishSocket (RFC 48's DISH type)
    radiodish.unified           RadishSocket (radio+dish combined, one object)
    radiodish.autowire            automatic port assignment, peer discovery, and
                                 peer connection on top of RadishSocket

For most uses, everything below is enough:

    from radiodish import RadioSocket, DishSocket, RadishSocket
    from radiodish.autowire import autowired_radish
"""

from radiodish.errors import RadioDishError, InvalidGroupError
from radiodish.protocol import (
    MSG_DATA, MSG_JOIN, MSG_LEAVE, MAX_GROUP_LEN, GroupLike, Address,
    encode_frame, decode_frame,
)
from radiodish.radio import RadioSocket
from radiodish.dish import DishSocket
from radiodish.unified import RadishSocket

__all__ = [
    "RadioSocket", "DishSocket", "RadishSocket",
    "RadioDishError", "InvalidGroupError",
    "MSG_DATA", "MSG_JOIN", "MSG_LEAVE", "MAX_GROUP_LEN", "GroupLike", "Address",
    "encode_frame", "decode_frame",
]
