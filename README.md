# radiodish

**Message passing between Python processes with no broker, no config files and
no wiring.** Start a node, tell it which *groups* it cares about, and it finds
the other nodes by itself, on the same machine or across your LAN.

This repo holds two packages that are developed together but stand alone:

| Package | What it is | Dependencies |
| --- | --- | --- |
| [`radiodish`](packages/radiodish/) | An async, pure-Python implementation of ZeroMQ's [RADIO-DISH pattern](https://rfc.zeromq.org/spec/48/) over plain UDP, plus automatic ports, peer discovery and autowiring. Import it as `radiodish`. | none (stdlib only) |
| [`radiodish-actor`](packages/radiodish-actor/) | An Erlang-flavored actor layer on top: expose methods, call them by name, and let discovery do the rest. Import it as `radioactor`. | `radiodish` |

## See it work

Two actors, no addresses, no ports, no peer lists:

```python
from radioactor import Actor, expose

class Greeter(Actor):
    @expose()
    async def ping(self, payload):
        return {"pong": payload}

class Caller(Actor):
    pass

greeter = await Greeter().register()
caller = await Caller().register()
print(await caller.call("ping", {"seq": 1}, timeout=2.0))
# {'pong': {'seq': 1}}
```

`caller` discovers `greeter` and works out how to reach `"ping"` on its own.
Put the two actors in separate processes, or on separate machines on the same
network, and the code stays exactly the same.

Want to run it? Clone the repo and try the full demo in [`main.py`](main.py):

```
uv sync --all-packages
uv run python main.py
```

## Why not just use ZeroMQ, Redis or RPC?

- **No broker to run.** Every node talks to its peers directly over UDP.
- **No native dependencies.** `radiodish` is pure Python on top of `asyncio`;
  there is no libzmq or pyzmq to install.
- **Group addressing instead of point-to-point.** RADIO-DISH is a
  broadcast primitive, so this project builds on that instead of fighting it:
  you send to a *group*, and a group can have zero, one or many listeners.
  The trade-offs (at-least-once delivery, no built-in "method not found") are
  spelled out honestly in the
  [actor model docs](packages/radiodish-actor/docs/actor-model.md).
- **Language-agnostic wire format.** Anything that speaks the protocol can be a
  peer, so you aren't tied to a shared runtime the way Erlang's processes are.

## Install

```
pip install radiodish          # just the messaging layer
pip install radiodish-actor    # the actor layer (pulls in radiodish)
```

Requires Python 3.13 or newer.

## Where to go next

- **Raw sockets and autowiring:** start with the
  [`radiodish` README](packages/radiodish/README.md) and its
  [docs](packages/radiodish/docs/index.md) (wire format, discovery, and the
  real bugs found along the way).
- **Actors:** the [`radiodish-actor` README](packages/radiodish-actor/README.md)
  and [docs](packages/radiodish-actor/docs/index.md).
- **Runnable examples:**
  [`radiodish`](packages/radiodish/docs/examples/) and
  [`radiodish-actor`](packages/radiodish-actor/docs/examples/). Most take a
  role or a name on the command line, so you can run several in separate
  terminals and watch them find each other.

## Working on this repo

This is a [`uv`](https://docs.astral.sh/uv/) workspace. The root itself isn't
published; it only ties the two packages together.

```
uv sync --all-packages              # editable install of both packages + pytest
uv run --all-packages pytest        # run every test
uv run python main.py               # run the demo
```

GitHub Actions runs the test suite and builds both distributions on pushes to
`main` and pull requests. Publishing to PyPI is triggered by publishing a
GitHub release. Configure PyPI Trusted Publishing for both projects using this
repository, the `.github/workflows/ci.yml` workflow, and the `pypi` environment.

`--all-packages` matters: a plain `uv sync` installs only what the workspace
root depends on, which is nothing.

### Layout

```
.
├── pyproject.toml            workspace root (not published), test config
├── main.py                   the demo above
└── packages/
    ├── radiodish/
    │   ├── pyproject.toml
    │   ├── src/                the importable `radiodish` package
    │   ├── tests/
    │   └── docs/               docs + runnable examples
    └── radiodish-actor/
        ├── pyproject.toml
        ├── src/                the importable `radioactor` package
        ├── tests/
        └── docs/
```

Each `src/` folder *is* the import package: `packages/radiodish/src/` is
`radiodish`, and `packages/radiodish-actor/src/` is `radioactor`. The mapping
lives in each package's `pyproject.toml` under `[tool.setuptools.package-dir]`.
If you add a subpackage to `radiodish`, add a line for it there too.

### Building

Each package builds into its own `dist/` folder next to its `src/`:

```
uv build packages/radiodish --out-dir packages/radiodish/dist
uv build packages/radiodish-actor --out-dir packages/radiodish-actor/dist
```

Publish `radiodish` first, since `radiodish-actor` depends on it.

The two packages share a workspace because they are still evolving together;
several bugs needed coordinated fixes in both. `radiodish-actor` only uses
`radiodish`'s public API, so splitting them into separate repos later is a
mechanical step.

## License

[MIT](LICENSE)
