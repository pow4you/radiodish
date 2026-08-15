"""
radish/protocol.py — the RFC 48 wire format: frame encoding/decoding.

Every UDP datagram is a single frame:

    +--------+-----------+------------------+-------------------+
    | type   | group_len | group (0-255 B)  | payload (rest)    |
    | 1 byte | 1 byte    | group_len bytes  | remaining bytes   |
    +--------+-----------+------------------+-------------------+

type is one of:
    0x01  DATA   — an application message, always carries a group
    0x02  JOIN   — a DISH announcing it wants a group   (control frame)
    0x03  LEAVE  — a DISH announcing it no longer wants a group (control frame)

DATA frames flow RADIO -> DISH. JOIN/LEAVE frames flow DISH -> RADIO.
A single UDP packet is one frame; there is no framing/multipart concept,
matching the RFC's "MUST NOT allow multipart messages" requirement --
UDP datagrams are already atomic "one send = one receive" units, which is
exactly the delivery guarantee the thread-safe socket family requires.
"""

from __future__ import annotations

import struct

from radish.errors import RadioDishError
from utils.groups import GroupLike, MAX_GROUP_LEN, normalize_group

MSG_DATA = 0x01
MSG_JOIN = 0x02
MSG_LEAVE = 0x03

_HEADER = struct.Struct("!BB")  # type, group_len

Address = tuple  # (host: str, port: int)

# Re-exported here too so existing `from radish.protocol import normalize_group`
# style imports (and MAX_GROUP_LEN / GroupLike) keep working without every
# caller needing to know these actually live in utils.groups.
__all__ = [
    "MSG_DATA", "MSG_JOIN", "MSG_LEAVE", "MAX_GROUP_LEN", "GroupLike",
    "Address", "normalize_group", "encode_frame", "decode_frame",
]


def encode_frame(msg_type: int, group: bytes, payload: bytes = b"") -> bytes:
    return _HEADER.pack(msg_type, len(group)) + group + payload


def decode_frame(data: bytes) -> tuple[int, bytes, bytes]:
    if len(data) < _HEADER.size:
        raise RadioDishError("datagram too short to contain a valid frame header")
    msg_type, group_len = _HEADER.unpack_from(data)
    offset = _HEADER.size
    group = data[offset:offset + group_len]
    if len(group) != group_len:
        raise RadioDishError("truncated frame: group shorter than declared length")
    payload = data[offset + group_len:]
    return msg_type, group, payload
