"""
radiodish/errors.py — re-exports the shared exception hierarchy under the
radiodish namespace, so `from radiodish import RadioDishError` (and code
throughout this package that does `from radiodish.errors import ...`) keeps
working. The actual definitions live in radiodish._internal.errors -- a
private subpackage (leading underscore, not part of the public API) since
nothing outside radiodish itself, not even radioactor, needs to import it
directly. See that module's docstring for the reasoning.
"""

from radiodish._internal.errors import RadioDishError, InvalidGroupError, SocketClosedError

__all__ = ["RadioDishError", "InvalidGroupError", "SocketClosedError"]
