# radiodish-actor

An Erlang-actor-model-flavored layer on top of
[`radiodish`](../radiodish/), running actors over an autowired RADIO-DISH
mesh instead of a custom VM. The point of doing it this way: any process,
in any language, that speaks radiodish's wire protocol can participate as
a peer actor — interoperability doesn't depend on sharing a runtime the
way BEAM's process/PID model does.

```python
from radioactor import Actor, expose

class Greeter(Actor):
    id = "greeter"

    @expose()
    async def ping(self, payload):
        return {"pong": payload}

class Caller(Actor):
    pass

provider = await Greeter().register()
caller = await Caller().register()
result = await caller.call("ping", {"seq": 1}, timeout=2.0)
```

No manual wiring, no pre-declared dependencies required — `caller`
discovers `provider` and figures out how to reach `"ping"` entirely on
its own.

## Install

```
pip install radiodish-actor
```

This pulls in `radiodish` automatically. For local/editable development
against this repo, see the workspace root README — this package is a
member of a `uv` workspace, developed alongside `radiodish` itself.

## Documentation

- **[docs/index.md](docs/index.md)** — quick start, install
- **[docs/actor-model.md](docs/actor-model.md)** — the group-addressing
  model in depth (there's no "call actor X's method Y" — only "send to a
  group"), dynamic dependency discovery, why direct `Actor()`
  instantiation is discouraged, and the real bugs found while building it
- **[docs/examples/](docs/examples/)** — a runnable provider + caller demo

## Why not just RPC?

Because the transport underneath (RADIO-DISH) is fundamentally a
broadcast/multicast primitive, not a point-to-point one — trying to force
point-to-point RPC semantics on top of it fights the transport instead of
using it. This package leans fully into that instead: addressing is
"send to a group," and a group can legitimately have more than one
listener. See [docs/actor-model.md](docs/actor-model.md) for what that
means in practice, including the real trade-offs (at-least-once
delivery, no built-in "method not found" error) that come with embracing
it honestly rather than papering over it.
