"""
utils — dependency-free helpers shared across radish, radish.autowire, and
actor. Nothing in this package imports from any of those, on purpose: this
sits at the bottom of the project's dependency graph.
"""

from utils.errors import RadioDishError, InvalidGroupError
from utils.groups import GroupLike, MAX_GROUP_LEN, normalize_group, groups_as_str

__all__ = [
    "RadioDishError",
    "InvalidGroupError",
    "GroupLike",
    "MAX_GROUP_LEN",
    "normalize_group",
    "groups_as_str",
]
