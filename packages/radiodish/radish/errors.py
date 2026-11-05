"""
radish/errors.py — re-exports the shared exception hierarchy under the
radish namespace, so `from radish import RadioDishError` (and code
throughout this package that does `from radish.errors import ...`) keeps
working. The actual definitions live in radish._internal.errors -- a
private subpackage (leading underscore, not part of the public API) since
nothing outside radish itself, not even radioactor, needs to import it
directly. See that module's docstring for the reasoning.
"""

from radish._internal.errors import RadioDishError, InvalidGroupError

__all__ = ["RadioDishError", "InvalidGroupError"]
