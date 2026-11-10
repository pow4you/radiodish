# The actor model

## There's no "call actor X's method Y" — only "send to a group"

This is the single most important design decision to understand before
using this package, because it's the opposite of what "actor model
RPC framework" tends to imply. `radioactor` doesn't bolt RPC semantics
onto RADIO-DISH — it leans fully into RADIO-DISH's native broadcast
nature instead, because trying to force point-to-point addressing onto
a fundamentally broadcast/multicast transport fights the transport
rather than using it.

A handler's trigger-set, computed by `@expose(groups=...)`:

```
your explicit groups ∪ {the function's own name} ∪ {""}
```

Two consequences follow directly from this, and both are worth being
deliberate about rather than surprised by:

- **Every exposed function joins `""` by default**, so an unaddressed
  message reaches *every* exposed function on *every* actor you're
  connected to — a genuine broadcast-to-everyone channel, not an
  accident. If you send with no group specified, you are broadcasting to
  every capability of every actor you're wired to, on purpose.
- **Function names aren't actor-namespaced.** `@expose` runs at class
  definition time, before any actor instance exists, so it has no way to
  see `self.actor_id()` to build a namespaced group automatically. Two
  different actor classes both exposing a method called `login` will
  both receive anything sent to the bare group `"login"`. If you want to
  avoid that collision, bake your own namespace into an explicit group
  string yourself: `@expose(groups=["auth.users.v2.login"])`.

## `send()` vs `call()`

```python
class Greeter(Actor):
    id = "greeter"

    @expose()
    async def ping(self, payload):
        return {"pong": payload}

class Caller(Actor):
    pass

provider = await Greeter().register()
caller = await Caller().register()
```

`caller.send(group, payload)` fires a message and returns immediately,
without waiting for any reply. It fans out to every actor — and every
locally-registered handler on each of those actors — currently wired and
listening on that exact group.

`caller.call(group, payload, timeout=...)` does the same send, but
awaits a matching reply, tracked by an auto-generated `correlation_id`.
Since a group can legitimately have more than one handler across the
mesh (that's not a bug, see above), `call()` resolves to whichever reply
arrives first and silently drops any later ones for the same
`correlation_id` — there's no way to average or collect multiple
answers, first one wins.

There's also no "404, method not found" error distinct from "the message
just got lost" — a group nobody joined and a datagram that got dropped
in transit look identical from the sender's side, since that's simply
how UDP works. If you need to know "did anyone respond at all," `call()`
with a `timeout` and catching `asyncio.TimeoutError` is the only signal
available, deliberately, rather than a fake distinction this transport
can't actually guarantee.

## Dependencies are discovered dynamically

`depends_on` used to be *required* for a pure caller (an `Actor` with
nothing `@expose`'d) to be discoverable by anything at all. Without it,
its only announced interest was its own private reply group — a random
string nothing else on the network shares — so neither direction of
`AutoWirer`'s overlap check would ever fire, and the actor would sit
permanently isolated. That's a "predict your dependencies in advance"
pattern, not really self-discovery, and it didn't sit right once framed
that way.

Now `send()`/`call()` register interest in whatever group they're asked
to reach automatically, the first time they try — internally reusing
`add_dependency()`, which already existed and already did the right
thing (updates `AutoWirer`'s local interest and re-announces via
`Discoverer`). `caller.call("ping", ...)` cold, with zero `depends_on`
ever declared, just works:

```python
caller = await Caller().register()          # no depends_on
result = await caller.call("ping", {"x": 1}, timeout=3.0)  # just works
```

The first `call()` attempt declares interest in `"ping"` on the fly,
`AutoWirer` picks that up on its next poll cycle, and `call()`'s
built-in retry (it resends the same message, same `correlation_id`,
every `retry_interval` seconds — 0.5s default — until a reply arrives or
`timeout` elapses) carries the caller through that wiring latency
without needing to be told to wait first.

`depends_on` at construction time is now a pure optimization, not a
requirement — pre-warm the wiring before your first call, to skip that
latency, if you happen to know in advance what you'll need:

```python
caller = await Caller(depends_on=["ping"]).register()
# wiring can already be in progress by the time you get here
```

**One consequence worth knowing** if you're writing a script that calls
immediately after `register()`: don't gate the first `call()` behind
checking `wirer.wired_peers` first. With dynamic discovery, *nothing*
gets wired until a call actually happens — that's what triggers interest
registration — so a loop like `if not wired_peers: continue` before ever
calling would deadlock waiting for something that only starts once you
stop waiting. Just call; the retry handles the "not wired yet" window
gracefully. `docs/examples/example_actor.py`'s caller loop had exactly
this bug during development, and the fix was simply removing the check.

`call()`'s retry does mean it's *at-least-once*, not *exactly-once* —
there's no receiver-side deduplication of `correlation_id`s, so if a
resend arrives after the first attempt already reached the handler (its
*reply* was what got lost, not the request), the handler runs twice.
Fine for idempotent handlers — most reads, `"ping"`, cache invalidation.
If you're calling something that must never run twice (charging a
card), pass `retry_interval=None` and handle possible loss yourself, or
make your handler idempotent on `correlation_id` — that dedup layer
doesn't exist here. `send()` keeps its original single-shot contract on
purpose too (there's no reply to retry against for a fire-and-forget
message), so a caller who cares whether a bare broadcast landed has to
resend it themselves — see how `tests/test_actor.py`'s
`test_empty_group_broadcasts_to_every_handler` does this.

## Write a subclass, not `Actor()` directly

Instantiating `Actor` directly raises a `UserWarning`:

```python
>>> Actor()
UserWarning: Instantiating Actor directly is discouraged -- define a
subclass instead, even an empty `class MyCaller(Actor): pass`. ...
```

`actor_id()` defaults to the class name, so every bare `Actor()`
instance identifies itself as just `"Actor"` in logs, discovery
announcements, and `instance_id()` — indistinguishable from every other
bare `Actor()` in the same codebase. A named subclass, even an empty
`class Caller(Actor): pass`, makes that identity actually mean something
and gives you a natural place to grow into later (exposed methods,
`on_register()`, whatever comes up). The warning fires only for `Actor`
itself, never for any subclass, however minimal:

```python
class Caller(Actor):
    pass

Caller()  # no warning
Actor()   # warns
```

## Real bugs found while building this

**Wiring based on interest overlap was one-sided.** A consumer's
interest overlapping a provider's groups gets the consumer to
`connect()` to the provider — but nothing made the provider connect
*back*, so the provider's DISH never told the consumer's RADIO what it
had joined, and forward calls silently never transmitted even though
`wired_peers` looked satisfied on the consumer's side. Fixed at the
`radiodish.autowire` layer: `Discoverer` now announces each node's
`interest` alongside its `groups`, and `AutoWirer` connects if *either*
direction has a reason to. This class of bug looks completely fine
single-process and only breaks once there's actually a wire between two
independent processes, so it's checked that way:
`docs/examples/example_actor.py` is meant to be run as two separate
processes, and `tests/test_cross_process.py` automates exactly that (a
provider and a caller launched as real subprocesses, each with its own
temp directory on POSIX). `tests/test_actor.py` runs everything in one
event loop and covers the actor logic itself, not the wire between
processes.

## One open piece, flagged rather than built

The original design for this system (before it settled on the
group-addressing model above) mentioned validating payloads against a
compiled schema before a handler ever sees them. This implementation
uses plain JSON for the message envelope with no schema validation at
all. That slot is still exactly where it should go — between dequeue and
dispatch in `Actor._run()` — for whenever it's actually needed.

## Examples

See [docs/examples/](examples/) for a runnable provider + caller pair,
demonstrating zero-configuration discovery end to end.
