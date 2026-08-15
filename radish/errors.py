"""
radish/errors.py — re-exports the shared exception hierarchy under the
radish namespace, so `from radish import RadioDishError` (and code
throughout this package that does `from radish.errors import ...`) keeps
working. The actual definitions live in utils.errors; see that module's
docstring for why.
"""

from utils.errors import RadioDishError, InvalidGroupError

__all__ = ["RadioDishError", "InvalidGroupError"]
