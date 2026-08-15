"""
utils/errors.py — the exception hierarchy shared across the whole project.

Lives in utils (not radish) because actor depends on it directly too, and
utils is meant to sit at the bottom of the dependency graph: nothing here
imports from radish, radish.autowire, or actor, so any of those can import
from here without creating a cycle. radish.errors re-exports these under
the radish package's own namespace for convenience (`from radish import
RadioDishError` keeps working), but this is the canonical definition.
"""


class RadioDishError(Exception):
    """Base error for the whole project."""


class InvalidGroupError(RadioDishError):
    """Raised when a group name violates RFC 48's length constraint (0-255 bytes)."""
