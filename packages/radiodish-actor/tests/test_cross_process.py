"""
The actor tests in test_actor.py run both sides inside one asyncio event
loop. These run them as two real, separate Python processes, which is the
only way to catch the class of bug that "looks completely fine
single-process" (see "Real bugs found while building this" in
docs/actor-model.md) -- e.g. two processes launched with different TMPDIRs
silently never finding each other.
"""
import asyncio
import json
import os
import socket
import sys
from pathlib import Path

import pytest

HELPER = Path(__file__).with_name("_proc_helper.py")


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _env_with_own_tmpdir(path: Path) -> dict:
    """Give a subprocess its own temp directory. On POSIX that is exactly the
    situation the fixed local-discovery root exists to survive (TMPDIR is
    ignored for discovery). Elsewhere (Windows has no fixed root) both
    processes keep the inherited environment, so the test checks the wire,
    not the temp-dir lookup."""
    env = dict(os.environ)
    if os.name == "posix":
        path.mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = str(path)
    return env


async def _spawn(role: str, port: int, env: dict, *, stdin: bool = False, file_tier_only: bool = False):
    return await asyncio.create_subprocess_exec(
        sys.executable, str(HELPER), role, str(port), *(["file-tier-only"] if file_tier_only else []),
        stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )


@pytest.mark.parametrize("file_tier_only", [False, True], ids=["default", "file-tier-only"])
async def test_call_across_two_real_processes(tmp_path, file_tier_only):
    """file-tier-only turns multicast off in both processes, so discovery has
    to work through the same-machine file tier alone -- the tier whose
    directory used to depend on each process's own TMPDIR."""
    port = _free_udp_port()  # private discovery port: no crosstalk with other tests
    provider = await _spawn(
        "provider", port, _env_with_own_tmpdir(tmp_path / "provider"),
        stdin=True, file_tier_only=file_tier_only,
    )
    try:
        ready = await asyncio.wait_for(provider.stdout.readline(), timeout=20)
        assert ready.startswith(b"READY"), ready + await provider.stderr.read()
        provider_tmp = ready.decode().split(" ", 1)[1].strip()

        caller = await _spawn(
            "caller", port, _env_with_own_tmpdir(tmp_path / "caller"),
            file_tier_only=file_tier_only,
        )
        out, err = await asyncio.wait_for(caller.communicate(), timeout=40)
        assert caller.returncode == 0, err.decode()

        reply = json.loads(out.decode().strip().splitlines()[-1])
        assert reply["result"] == {"pong": {"seq": 1}}
        if os.name == "posix":
            # prove the two processes really did have different temp dirs
            assert reply["tmp"] != provider_tmp
    finally:
        if provider.stdin:
            provider.stdin.close()
        try:
            await asyncio.wait_for(provider.wait(), timeout=10)
        except asyncio.TimeoutError:
            provider.kill()
            await provider.wait()
