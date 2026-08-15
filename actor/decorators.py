"""
actor/decorators.py — @expose: marks a method as network-callable. Pure
metadata; see actor.base.Actor for how the tags get read and dispatched.
"""

from __future__ import annotations

from typing import Iterable, Optional, Union


def expose(groups: Optional[Union[str, Iterable[str]]] = None):
    """
    Mark a method as network-callable. `groups` (a string, an iterable of
    strings, or omitted) lists extra topics this handler should ALSO fire
    on, on top of its two automatic defaults: its own function name, and
    the empty group "" (see module docstring for what each implies).
    Pure metadata -- nothing happens at decoration or call time beyond
    tagging the function; Actor._discover_exposed_methods() reads these
    tags via reflection when an instance registers.
    """
    if groups is None:
        extra: tuple = ()
    elif isinstance(groups, str):
        extra = (groups,)
    else:
        extra = tuple(groups)

    def decorator(func):
        func._exposed = True
        # de-dupe while preserving order, in case someone passes their own
        # name or "" explicitly too
        func._exposed_groups = tuple(dict.fromkeys((*extra, func.__name__, "")))
        return func

    return decorator

