"""
radiodish._internal — private implementation details of the radiodish package.
Leading underscore means exactly that: not public API, no stability
promise, nothing outside radiodish itself should import from here (and
nothing does -- radioactor only ever reaches RadioDishError via
`from radiodish import RadioDishError`, the public re-export).
"""

from radiodish._internal.errors import RadioDishError, InvalidGroupError
from radiodish._internal.groups import GroupLike, MAX_GROUP_LEN, normalize_group, groups_as_str

__all__ = [
    "RadioDishError",
    "InvalidGroupError",
    "GroupLike",
    "MAX_GROUP_LEN",
    "normalize_group",
    "groups_as_str",
]
