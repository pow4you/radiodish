"""
radish/_internal/errors.py — the exception hierarchy for the radish
package. Private subpackage (leading underscore) -- not part of the
public API, and nothing outside radish itself needs it, including
radioactor, which only ever imports RadioDishError via `from radish
import RadioDishError` (radish.errors re-exports these under the public
namespace for that purpose).
"""


class RadioDishError(Exception):
    """Base error for the whole project."""


class InvalidGroupError(RadioDishError):
    """Raised when a group name violates RFC 48's length constraint (0-255 bytes)."""
