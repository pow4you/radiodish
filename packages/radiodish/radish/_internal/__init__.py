"""
radish._internal — private implementation details of the radish package.
Leading underscore means exactly that: not public API, no stability
promise, nothing outside radish itself should import from here (and
nothing does -- radioactor only ever reaches RadioDishError via
`from radish import RadioDishError`, the public re-export).
"""

from radish._internal.errors import RadioDishError, InvalidGroupError
from radish._internal.groups import GroupLike, MAX_GROUP_LEN, normalize_group, groups_as_str

__all__ = [
    "RadioDishError",
    "InvalidGroupError",
    "GroupLike",
    "MAX_GROUP_LEN",
    "normalize_group",
    "groups_as_str",
]
