# radioactor

An Erlang-actor-model-flavored `Actor` base class, running over
`radish.autowire.autowired_radish()` instead of a custom VM.

## Install

```
pip install radiodish-actor
```

Depends on [`radiodish`](../../radiodish/) automatically — you don't need
to install that separately.

## Quick start

Terminal 1:
```
python3 docs/examples/example_actor.py provider
```

Terminal 2:
```
python3 docs/examples/example_actor.py caller
```

No manual peer configuration on either side — discovery finds both
processes, `AutoWirer` wires them together, and calls start flowing.
See [docs/examples/](examples/) for what this demonstrates in more
detail, and [actor-model.md](actor-model.md) for the design underneath
it.

## The shape of it

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

`send(group, payload)` fires and forgets. `call(group, payload,
timeout=)` awaits a reply, matched by an auto-generated
`correlation_id`, and retries automatically until one arrives or the
timeout elapses. Neither call needs a pre-declared list of dependencies
— see [actor-model.md](actor-model.md#dependencies-are-discovered-dynamically)
for why that's true and what changed to make it true.

Write a named subclass, even an empty one, rather than instantiating
`Actor` directly — see
[actor-model.md](actor-model.md#write-a-subclass-not-actor-directly) for
why the base class now warns if you do.
