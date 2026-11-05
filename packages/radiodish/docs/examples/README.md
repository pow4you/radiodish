# Examples

Each of these is meant to be read as much as run — they're structured to
demonstrate one specific thing about the library, in order of "closest to
the raw RFC 48 spec" to "fully automatic." Run them from this directory:
`cd docs/examples && python3 example_radio.py ...`.

## `example_radio.py` + `example_dish.py`

The most literal, RFC-48-level demo: a `RadioSocket` broadcasting on two
groups (`temp`, `humidity`), and a `DishSocket` that joins only one of
them. **What this demonstrates**: exact-match group filtering is doing
real work — the dish only ever sees the group it explicitly joined, even
though both groups arrive on the same socket. Run a second dish with
`--group humidity` alongside the first to see two independent subscribers
with different interests, sharing one radio.

```
python3 example_radio.py --bind-port 9000 --dish 127.0.0.1:9001
python3 example_dish.py --bind-port 9001 --radio 127.0.0.1:9000 --group temp
```

## `example_radish.py`

The same idea, but using `RadishSocket` (radio+dish combined) so each
node both broadcasts and listens, and peers are wired together **by
hand** via `--peer`. **What this demonstrates**: what manual mesh-building
actually looks like — you have to know every peer's address in advance
and pass it explicitly. This is the baseline to compare against
`example_autowire.py` below, which removes that requirement entirely.

```
python3 example_radish.py --port 20000 --name alice --group chat --peer 127.0.0.1:20010 --peer 127.0.0.1:20020
python3 example_radish.py --port 20010 --name bob   --group chat --peer 127.0.0.1:20000 --peer 127.0.0.1:20020
python3 example_radish.py --port 20020 --name carol --group chat --peer 127.0.0.1:20000 --peer 127.0.0.1:20010
```

Each `RadishSocket` reserves *two* ports (`--port` for RADIO, `--port+1`
for DISH), so give each node's `--port` a gap of at least 2.

## `example_autowire.py`

The same three-node chat idea, but with **no `--peer` flag at all** —
peers are found and connected automatically via `radish.autowire`.
**What this demonstrates**: nodes only connect where their groups
overlap. Give alice and carol non-overlapping groups with bob bridging
both, and watch the `[wired]` log lines — alice and carol never connect
to each other directly, only through bob.

```
python3 example_autowire.py --name alice --group sensors
python3 example_autowire.py --name bob   --group sensors --group logs
python3 example_autowire.py --name carol --group logs
```

Two things you'll notice running this, both expected rather than bugs:
messages sent in the first second or so after startup can miss their
peer (discovery + wiring hasn't completed yet — a direct, honest
demonstration of UDP giving no delivery guarantee), and a node that
joins a group but never broadcasts on it as its *first* `--group` won't
see outgoing traffic on that group either — that's this example script's
"only broadcast on `groups[0]`" simplification, not a library limitation.

For pointing discovery at specific addresses instead of relying on
multicast/local-file discovery (useful across Docker/cloud boundaries),
see `--seed host:port`:

```
python3 example_autowire.py --name remote --group sensors --seed 10.0.0.5:9999
```
