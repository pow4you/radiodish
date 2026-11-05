# radiodish workspace

This repo is a `uv` workspace holding two separate, publishable Python
packages that are developed together but designed to stand alone:

- **[`packages/radiodish/`](packages/radiodish/)** — the core: a
  standalone, dependency-free, async implementation of ZeroMQ's
  RADIO-DISH pattern (RFC 48) over plain UDP, plus automatic port
  assignment, peer discovery, and autowiring.
- **[`packages/radiodish-actor/`](packages/radiodish-actor/)** — an
  Erlang-actor-model-flavored layer built on top of `radiodish`. Depends
  on it; `radiodish` doesn't know `radiodish-actor` exists.

Each package has its own `README.md`, its own `docs/` (including runnable
examples, documented as demonstrations rather than just code), and its
own `tests/` in the conventional top-level location test tooling expects.
Start with whichever package README matches what you're trying to do —
this file is just a map.

## Why two packages instead of one

`radiodish-actor` never imports anything from `radiodish` except its
public API (`from radish import RadioDishError`,
`from radish.autowire import autowired_radish`) — never internals, never
its private `_internal` subpackage. `radiodish`'s own code has zero
import dependency on `radiodish-actor` in the other direction — a few
docstrings in `radiodish` mention `radioactor` by name purely as
explanatory context (e.g. "nothing outside radish itself, not even
radioactor, needs to import this"), but nothing in `radiodish` actually
imports from it. That clean boundary is what makes the split make sense:
someone who wants a minimal, dependency-free UDP pub/sub layer for their
*own* project can take just `radiodish`, without also pulling in an
opinionated actor-model framework they may not want.

They're kept in one workspace (rather than fully separate repos) for now
because the two layers are still actively co-evolving — several real bugs
found during development required coordinated fixes across both (see
`packages/radiodish/docs/autowire.md` and
`packages/radiodish-actor/docs/actor-model.md` for the specifics). Once
this settles, splitting into fully separate repos is a small, mechanical
step: copy `packages/radiodish/` out, publish it, then point
`radiodish-actor`'s `[tool.uv.sources]` at the published version instead
of `{ workspace = true }`.

## Local development

```
uv sync --all-packages
```

`--all-packages` matters here — a plain `uv sync` only installs what the
(empty, non-published) workspace root itself depends on, which is
nothing; `--all-packages` installs every workspace member as an editable
install, which is what makes `from radish import ...` and
`from radioactor import ...` work together locally.

Run anything with `uv run --package <name> ...`, e.g.:

```
uv run --package radiodish python3 packages/radiodish/tests/test_autowire.py
uv run --package radiodish-actor python3 packages/radiodish-actor/tests/test_actor.py
```

## Package layout

```
radiodish-workspace/            (this file's directory -- not itself published)
├── pyproject.toml                declares the uv workspace, package = false
│
└── packages/
    ├── radiodish/                 the core package
    │   ├── pyproject.toml
    │   ├── README.md
    │   ├── radish/                  the actual importable code
    │   ├── tests/                     pytest-discoverable, but written as plain
    │   │                                scripts -- see each package's README
    │   └── docs/                      detailed docs + runnable, documented examples
    │       └── examples/
    │
    └── radiodish-actor/            the actor-model addon (depends on radiodish)
        ├── pyproject.toml            [tool.uv.sources] radiodish = { workspace = true }
        ├── README.md
        ├── radioactor/                 the actual importable code
        ├── tests/
        └── docs/
            └── examples/
```
