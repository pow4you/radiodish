"""
utils/groups.py — group-name handling shared between two different
representations of the same concept:

- radish.protocol needs a STRICT, wire-format validator: a group is
  0-255 raw bytes, full stop, because that's what RFC 48's ABNF requires
  and what the frame header's single length byte can represent.
- radish.autowire.discovery needs a LOOSE, JSON-safe converter: group
  names have to survive being embedded in a discovery announcement
  payload, so bytes get decoded to str (JSON can't carry raw bytes) and
  anything already a plain string passes through untouched.

Both directions live here instead of being duplicated (or, worse, subtly
diverging) between the two modules that need them.
"""

from __future__ import annotations

from typing import Iterable, Union

from utils.errors import InvalidGroupError

GroupLike = Union[str, bytes]
MAX_GROUP_LEN = 255


def normalize_group(group: GroupLike) -> bytes:
    """Strict validator for the wire protocol: str or bytes in, exactly
    validated bytes out. Raises InvalidGroupError for anything else or
    anything over RFC 48's 255-byte limit."""
    if isinstance(group, str):
        group = group.encode("utf-8")
    if not isinstance(group, (bytes, bytearray)):
        raise InvalidGroupError(f"group must be str or bytes, got {type(group)!r}")
    if len(group) > MAX_GROUP_LEN:
        raise InvalidGroupError(
            f"group is {len(group)} bytes, RFC 48 allows at most {MAX_GROUP_LEN}"
        )
    return bytes(group)


def groups_as_str(groups: Iterable) -> tuple[str, ...]:
    """Loose converter for discovery announcements: decodes any bytes
    entries to str (JSON can't carry raw bytes), passes plain strings
    through untouched. Used for the groups/interest lists that go into a
    Discoverer's JSON payload, not for wire-protocol frame encoding."""
    out = []
    for g in groups:
        out.append(g.decode("utf-8") if isinstance(g, (bytes, bytearray)) else g)
    return tuple(out)
