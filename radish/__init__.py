"""
radish — a standalone, asyncio-native RADIO/DISH implementation over UDP.

This is an independent implementation of the pattern described in ZeroMQ
RFC 48 (https://rfc.zeromq.org/spec/48/). It does not depend on libzmq or
pyzmq at all — it's built directly on asyncio's UDP transport.

Package layout:
    radish.errors     RadioDishError, InvalidGroupError (re-exported from utils.errors)
    radish.protocol    wire format: encode_frame/decode_frame, MSG_DATA/JOIN/LEAVE
    radish.transport    shared plumbing: _UDPProtocol, _BoundedDropQueue, _Peer
    radish.radio         RadioSocket (RFC 48's RADIO type)
    radish.dish            DishSocket (RFC 48's DISH type)
    radish.unified           RadishSocket (radio+dish combined, one object)
    radish.autowire            automatic port assignment, peer discovery, and
                                 peer connection on top of RadishSocket

For most uses, everything below is enough:

    from radish import RadioSocket, DishSocket, RadishSocket
    from radish.autowire import autowired_radish
"""

from radish.errors import RadioDishError, InvalidGroupError
from radish.protocol import (
    MSG_DATA, MSG_JOIN, MSG_LEAVE, MAX_GROUP_LEN, GroupLike, Address,
    encode_frame, decode_frame,
)
from radish.radio import RadioSocket
from radish.dish import DishSocket
from radish.unified import RadishSocket

__all__ = [
    "RadioSocket", "DishSocket", "RadishSocket",
    "RadioDishError", "InvalidGroupError",
    "MSG_DATA", "MSG_JOIN", "MSG_LEAVE", "MAX_GROUP_LEN", "GroupLike", "Address",
    "encode_frame", "decode_frame",
]
