"""
radish/autowire/local_discovery.py — the "my machine" discovery tier: a
shared directory every same-machine Discoverer reads and writes, with zero
dependence on networking. See Discoverer's docstring for the full
reasoning; the short version is that UDP multicast can fail outright with
no active network route (confirmed, not hypothesized), and when it does,
it fails identically for every process on the machine, so none of them
can hear each other even standing right next to one another. This module
exists so same-machine discovery never depends on that.
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import Optional


def _local_discovery_root() -> str:
    """
    The parent directory every local-discovery directory lives under.

    Deliberately NOT tempfile.gettempdir() directly, even though that's
    what this used originally. gettempdir() consults TMPDIR/TEMP/TMP
    environment variables before falling back to a platform default --
    and those aren't guaranteed to resolve to the same path across two
    genuinely separate process launches (different shells, different
    tool wrappers like `uv run`, different venv activation state, etc).
    A single Python process running multiple Discoverers can't ever hit
    this, since they all call gettempdir() identically within the same
    process and environment -- which is exactly why this bug hid from
    every in-process test while still being real: two actual separate
    `python3 script.py` launches on the same machine could each compute a
    DIFFERENT temp directory, silently write their announcements into two
    directories that never see each other, and neither side would ever
    know the other exists. No error, no timeout message, just permanent
    silence -- which matches "whoever launches first doesn't get found by
    receivers" as closely as a bug report can match its cause.

    The fix: use a fixed, well-known location that every process on this
    machine agrees on regardless of its own environment. "/tmp" on POSIX
    systems isn't affected by TMPDIR/TEMP/TMP at all -- it's a literal
    path, not an environment lookup -- so two processes with wildly
    different environments still end up writing to the exact same place.
    Falls back to tempfile.gettempdir() only if "/tmp" itself isn't usable
    (e.g. on Windows, which has no "/tmp" by convention).
    """
    if os.name == "posix" and os.path.isdir("/tmp") and os.access("/tmp", os.W_OK):
        return "/tmp"
    return tempfile.gettempdir()


def _local_discovery_dir(discovery_port: int) -> Optional[str]:
    """Directory every same-machine Discoverer on this discovery_port
    shares to announce itself with zero dependence on networking -- see
    Discoverer's docstring for why that's a separate tier from multicast,
    not just a fallback for it. Returns None (rather than raising) if the
    directory genuinely isn't writable; callers treat that the same as
    "this channel isn't available right now".

    Scoped by user ID where available (POSIX), not just discovery_port:
    "/tmp" is world-writable and shared across every user on the machine,
    so without this, two different users each running radiodish with the
    same discovery_port would collide in the same directory."""
    try:
        user_tag = f"_u{os.getuid()}" if hasattr(os, "getuid") else ""
        d = os.path.join(_local_discovery_root(), f"radiodish_local_{discovery_port}{user_tag}")
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        return None


def _safe_filename(node_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", node_id) + ".json"


