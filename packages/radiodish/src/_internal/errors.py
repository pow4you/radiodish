"""
radiodish/_internal/errors.py — the exception hierarchy for the radiodish
package. Private subpackage (leading underscore) -- not part of the
public API, and nothing outside radiodish itself needs it, including
radioactor, which only ever imports RadioDishError via `from radiodish
import RadioDishError` (radiodish.errors re-exports these under the public
namespace for that purpose).
"""


class RadioDishError(Exception):
    """Base error for the whole project."""

class SocketClosedError(RadioDishError):
    """Throw when the socket is closed"""

class InvalidGroupError(RadioDishError):
    """Raised when a group name violates RFC 48's length constraint (0-255 bytes)."""
