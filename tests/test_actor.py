import asyncio
import warnings

from actor import Actor, expose


class Echo(Actor):
    id = "echo"

    @expose()
    async def ping(self, payload):
        return {"pong": payload}

    @expose(groups=["shout_topic"])
    async def shout(self, payload):
        return str(payload).upper()


class Caller(Actor):
    """A pure caller, no @expose'd methods -- the recommended way to write
    one now: a named subclass, even an empty one, rather than instantiating
    Actor directly (see test_direct_instantiation_warns)."""
    pass


async def _wait_until(predicate, timeout=5.0, interval=0.1):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def test_call_by_function_name():
    """No depends_on anywhere here -- call() discovers 'ping' on its own,
    the first time it's asked to reach it, and its built-in retry carries
    the caller through the wiring latency. This is the default path now,
    not a special case."""
    echo = await Echo().register(port_range=(25000, 25100), discovery_port=27001)
    caller = await Caller().register(port_range=(25000, 25100), discovery_port=27001)

    assert caller._depends_on == set(), "should start with zero pre-declared dependencies"
    result = await caller.call("ping", {"x": 1}, timeout=3.0)
    assert result == {"pong": {"x": 1}}, result
    assert "ping" in caller._depends_on, "call() should have auto-registered interest"

    await caller.close()
    await echo.close()
    print("test_call_by_function_name: PASS")


async def test_explicit_group_alias():
    echo = await Echo().register(port_range=(25100, 25200), discovery_port=27002)
    caller = await Caller().register(port_range=(25100, 25200), discovery_port=27002)

    # addressed via the *explicit* group, not the function name "shout" --
    # again with zero depends_on, relying purely on dynamic discovery
    result = await caller.call("shout_topic", "hi", timeout=3.0)
    assert result == "HI", result

    await caller.close()
    await echo.close()
    print("test_explicit_group_alias: PASS")


async def test_explicit_depends_on_still_works():
    """depends_on at construction is optional now, not required -- but
    still works, as a way to pre-warm the wiring before the first call
    rather than paying that latency on it. Confirms it the direct way:
    wiring should already be in progress before any call() is made."""
    echo = await Echo().register(port_range=(25150, 25180), discovery_port=27009)
    caller = await Caller(depends_on=["ping"]).register(port_range=(25150, 25180), discovery_port=27009)

    ok = await _wait_until(lambda: len(caller.wirer.wired_peers) >= 1)
    assert ok, "pre-declared depends_on should wire before any call() happens"

    result = await caller.call("ping", {"y": 2}, timeout=3.0)
    assert result == {"pong": {"y": 2}}, result

    await caller.close()
    await echo.close()
    print("test_explicit_depends_on_still_works: PASS")


async def test_empty_group_broadcasts_to_every_handler():
    echo = await Echo().register(port_range=(25200, 25300), discovery_port=27003)
    caller = await Caller().register(port_range=(25200, 25300), discovery_port=27003)

    # send() (not call()) since BOTH ping and shout will independently
    # reply to the same correlation_id -- we just want to see that both
    # handlers actually ran, not race for "whichever reply wins".
    seen = []
    orig_ping, orig_shout = echo.ping, echo.shout

    async def tracking_ping(payload):
        seen.append("ping")
        return await orig_ping(payload)

    async def tracking_shout(payload):
        seen.append("shout")
        return await orig_shout(payload)

    echo._groups_to_handlers[""] = [tracking_ping, tracking_shout]

    # send() has no reply to retry against (unlike call(), which resends
    # internally), so a caller who cares whether a fire-and-forget
    # broadcast actually landed resends it themselves. The FIRST send()
    # call also auto-registers interest in "" (see _ensure_interest) --
    # zero depends_on needed here either, same as everywhere else in this
    # file now.
    deadline = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < deadline:
        if set(seen) == {"ping", "shout"}:
            break
        caller.send("", payload="hello")
        await asyncio.sleep(0.2)
    ok = set(seen) == {"ping", "shout"}
    assert ok, f"expected both handlers to fire on the empty group, got {seen}"

    await caller.close()
    await echo.close()
    print("test_empty_group_broadcasts_to_every_handler: PASS")


async def test_call_times_out_when_nobody_listens():
    caller = await Caller().register(port_range=(25300, 25400), discovery_port=27004)
    try:
        await caller.call("nobody_home", None, timeout=0.5)
        raised = False
    except asyncio.TimeoutError:
        raised = True
    assert raised, "expected a timeout calling a group with no subscribers"
    await caller.close()
    print("test_call_times_out_when_nobody_listens: PASS")


async def test_dynamic_expose_and_dependency():
    echo = await Echo().register(port_range=(25400, 25500), discovery_port=27005)

    class Bare(Actor):
        pass

    caller = await Bare().register(port_range=(25400, 25500), discovery_port=27005)

    await asyncio.sleep(1.0)
    assert len(caller.wirer.wired_peers) == 0, "shouldn't be wired without any shared interest"

    @expose(groups=["whisper_topic"])
    async def whisper(self, payload):
        return f"...{payload}..."

    echo.add_endpoint(whisper.__get__(echo))
    caller.add_dependency("whisper_topic")

    ok = await _wait_until(lambda: len(caller.wirer.wired_peers) >= 1)
    assert ok, "caller never wired after dynamic dependency + dynamic expose"

    result = await caller.call("whisper_topic", "secret", timeout=3.0)
    assert result == "...secret...", result

    await caller.close()
    await echo.close()
    print("test_dynamic_expose_and_dependency: PASS")


async def test_direct_instantiation_warns():
    """Instantiating Actor directly should warn, nudging toward a named
    subclass instead; a subclass -- even an empty one -- should not."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Actor()
        assert len(caught) == 1, f"expected exactly one warning, got {len(caught)}"
        assert issubclass(caught[0].category, UserWarning)
        assert "subclass" in str(caught[0].message)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Caller()
        assert len(caught) == 0, f"a named subclass should not warn, got {caught}"

    print("test_direct_instantiation_warns: PASS")


async def main():
    await test_call_by_function_name()
    await test_explicit_group_alias()
    await test_explicit_depends_on_still_works()
    await test_empty_group_broadcasts_to_every_handler()
    await test_call_times_out_when_nobody_listens()
    await test_dynamic_expose_and_dependency()
    await test_direct_instantiation_warns()


if __name__ == "__main__":
    asyncio.run(main())
