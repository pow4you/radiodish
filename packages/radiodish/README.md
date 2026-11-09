# radiodish

A standalone, dependency-free, **async** implementation of ZeroMQ's
[RADIO-DISH pattern](https://rfc.zeromq.org/spec/48/), built directly on
`asyncio`'s UDP transport rather than on libzmq/pyzmq — plus automatic
port assignment, peer discovery, and autowiring on top.

- **Standalone**: pure Python stdlib (`asyncio`, `struct`, `collections`,
  `socket`). No libzmq, no third-party dependencies at all.
- **UDP**: each RADIO and DISH is a plain UDP endpoint. A UDP datagram is
  already an atomic, non-multipart unit, which lines up naturally with
  RFC 48's "no multipart messages" requirement for the thread-safe
  socket family.
- **Async**: `RadioSocket.send()` never blocks; `DishSocket.recv()` is an
  `await`-able coroutine fed by `asyncio`'s event loop — no threads.

Looking for the actor-model layer built on top of this? That's a separate
package, [`radiodish-actor`](https://github.com/pow4you/radiodish/tree/main/packages/radiodish-actor), which depends on this
one.

## Install

```
pip install radiodish
```

For local/editable development against this repo specifically, see the
workspace root README — this package is a member of a `uv` workspace.

## Documentation

Full documentation, with the reasoning behind the design decisions (not
just the API surface), lives in [`docs/`](https://github.com/pow4you/radiodish/blob/main/packages/radiodish/docs/index.md):

- **[docs/index.md](https://github.com/pow4you/radiodish/blob/main/packages/radiodish/docs/index.md)** — quick start, API sketch, package layout
- **[docs/protocol.md](https://github.com/pow4you/radiodish/blob/main/packages/radiodish/docs/protocol.md)** — the RFC 48 wire format and how this implementation maps to it
- **[docs/autowire.md](https://github.com/pow4you/radiodish/blob/main/packages/radiodish/docs/autowire.md)** — automatic port assignment, peer discovery (two tiers: same-machine and LAN), and autowiring; the real bugs found while building it and how they were fixed
- **[docs/examples/](https://github.com/pow4you/radiodish/tree/main/packages/radiodish/docs/examples)** — runnable examples, each documented with what it demonstrates and why

## 30-second version

```python
from radiodish import RadioSocket, DishSocket

radio = await RadioSocket().bind("0.0.0.0", 9000)
radio.connect("127.0.0.1", 9001)
await radio.send(b"hello", group="news")

dish = await DishSocket().bind("0.0.0.0", 9001)
dish.connect("127.0.0.1", 9000)
dish.join("news")
group, payload = await dish.recv()
```

Or skip manual wiring entirely:

```python
from radiodish.autowire import autowired_radish

radish, discoverer, wirer = await autowired_radish(groups=["sensors"])
radish.broadcast("21.5C", group="sensors")
group, payload = await radish.recv()
```

See [docs/index.md](https://github.com/pow4you/radiodish/blob/main/packages/radiodish/docs/index.md) for the full walkthrough.
