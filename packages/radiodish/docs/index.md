# radiodish

A standalone, dependency-free, async implementation of ZeroMQ's
[RADIO-DISH pattern](https://rfc.zeromq.org/spec/48/) (RFC 48), built
directly on `asyncio`'s UDP transport rather than on libzmq/pyzmq.

RADIO-DISH is the thread-safe alternative to PUB-SUB: a RADIO broadcasts,
any number of DISH sockets can listen, and each DISH decides which
*groups* it wants by joining them — the RADIO doesn't need to know who's
listening, and a DISH doesn't need to know who's sending. This package
reimplements that pattern from scratch over plain UDP sockets, then adds
a layer on top for finding peers and wiring them together automatically.

## Why build this instead of using pyzmq?

Three reasons, in order of how much they actually mattered:

1. **Dependency-free.** No libzmq to compile or vendor, no C extension,
   just Python's standard library. That matters for anywhere installing
   a compiled dependency is friction (containers, embedded targets,
   sandboxed environments).
2. **UDP datagrams are naturally atomic.** RFC 48 requires the
   thread-safe socket family to never allow multipart messages — a
   single send must be a single receive. A UDP datagram already has
   exactly that property built in at the OS level, so building directly
   on it (rather than on top of ZMTP/TCP framing) is a more direct fit
   for what the spec actually asks for, not just a workaround.
3. **It's genuinely readable.** The whole implementation is small enough
   to read end to end in an afternoon, which matters if you want to
   understand exactly what your messaging layer does, not just trust
   that it does something.

## Quick start

Terminal 1:
```
python3 docs/examples/example_radio.py --bind-port 9000 --dish 127.0.0.1:9001
```

Terminal 2:
```
python3 docs/examples/example_dish.py --bind-port 9001 --radio 127.0.0.1:9000 --group temp
```

The dish will only print `temp` readings — `humidity` messages are
filtered out because it never joined that group. Start a second dish
with `--group humidity` to see the "many subscribers, different
interests" side of the pattern. See [docs/examples/](examples/) for what
every example demonstrates.

## API sketch

The manual, RFC-48-literal way to use it:

```python
from radiodish import RadioSocket, DishSocket

radio = await RadioSocket(queue_size=1000).bind("0.0.0.0", 9000)
radio.connect("127.0.0.1", 9001)          # register a dish
await radio.send(b"hello", group="news")  # never blocks; drops if that
                                           # dish's queue is full

dish = await DishSocket(queue_size=1000).bind("0.0.0.0", 9001)
dish.connect("127.0.0.1", 9000)           # register a radio
dish.join("news")                         # exact-match group filter
group, payload = await dish.recv()
```

`RadishSocket` bundles a `RadioSocket` and a `DishSocket` behind one
object with one address pair, for when you want to both broadcast and
receive without juggling two sockets:

```python
from radiodish import RadishSocket

node = await RadishSocket().bind("127.0.0.1", 20000)
node.connect("127.0.0.1", 20010)   # wires both directions at once
node.join("chat")
node.broadcast("hello", group="chat")   # non-blocking, just enqueues
group, payload = await node.recv()      # fed by a background receive loop
```

And the fully automatic way — no manual `connect()` calls, no manual
port picking — is [`radiodish.autowire`](autowire.md):

```python
from radiodish.autowire import autowired_radish

radish, discoverer, wirer = await autowired_radish(groups=["sensors"])
radish.broadcast("21.5C", group="sensors")
group, payload = await radish.recv()
```

## How this maps to RFC 48

| RFC 48 requirement | Implementation |
|---|---|
| No multipart messages | One UDP datagram == one frame, always |
| Per-peer outgoing/incoming queues | `dict[addr, _Peer]` with a bounded `_BoundedDropQueue` each |
| Silently drop when a peer's queue is full | `try_put` returns `False` and is ignored, no exception, no block |
| Exact-match group filtering | RADIO tracks each dish's joined groups from JOIN/LEAVE control frames; `group_b in peer.groups` |
| RADIO discards anything a dish sends it besides JOIN/LEAVE | non-JOIN/LEAVE frames from a peer are dropped in `_on_datagram` |
| Fair-queuing on the DISH side | `recv()` round-robins a cursor across connected peers so one noisy radio can't starve the others |
| Thread-safe send/recv | Not literally multi-threaded (asyncio is single-threaded), but concurrent `await send()` / `await recv()` calls from multiple coroutines are safe by construction |

See [protocol.md](protocol.md) for the wire format itself, in detail.

## A UDP-specific wrinkle worth knowing about

UDP gives no delivery guarantee, so if a dish's JOIN command is sent
before the radio is listening (or just gets lost), the radio would never
learn that dish wants a group, and the dish would go silently deaf
forever. `DishSocket` handles this by re-announcing all currently-joined
groups to all connected radios every `rejoin_interval` seconds (default
2s, configurable, or `None` to disable). This has no equivalent in the
original RFC — it exists because this implementation is intentionally
connectionless, unlike libzmq's ZMTP-over-TCP transport, which has its
own connection/handshake reliability.

## Package layout

Structured the way you'd expect a small Java project to be — one class
(or a handful of tightly-coupled ones) per file, grouped into packages
by responsibility, shared internals pulled into a private subpackage
rather than duplicated:

```
src/                      (src/ is the `radiodish` package)
    errors.py                 RadioDishError, InvalidGroupError (public re-exports)
    protocol.py                 wire format: encode_frame/decode_frame, MSG_DATA/JOIN/LEAVE
    transport.py                 shared plumbing: _UDPProtocol, _BoundedDropQueue, _Peer
    radio.py                      RadioSocket
    dish.py                        DishSocket
    unified.py                      RadishSocket (radio+dish combined, one object)
    _internal/                   private implementation details, not public API
        errors.py                  the actual exception definitions
        groups.py                   group-name validation/conversion (wire format + JSON)
    autowire/                    automatic port assignment, peer discovery, autowiring
        network.py                  find_free_port_pair, detect_local_addresses
        local_discovery.py           the "my machine" file-based discovery tier
        discovery.py                  the "my LAN" multicast tier, Discoverer
        wiring.py                      AutoWirer -- the actual autowiring
        compose.py                      autowired_radish() -- one-call entrypoint

tests/       test_radiodish.py, test_radish_socket.py, test_autowire.py,
              test_network_resilience.py
docs/
    examples/   example_radio.py, example_dish.py, example_radish.py,
                 example_autowire.py
```

`__init__.py` and `autowire/__init__.py` each re-export
their package's public API, so day-to-day usage only ever needs the
top-level imports:

```python
from radiodish import RadioSocket, DishSocket, RadishSocket, RadioDishError
from radiodish.autowire import autowired_radish
```

`radiodish._internal` is deliberately private (leading underscore) — the
group-handling and error-definition code that both `radiodish.protocol` and
`radiodish.autowire.discovery` need, pulled into one place instead of
duplicated between them. Nothing outside `radiodish` itself imports from it
directly, including the `radioactor` package, which only ever reaches
`RadioDishError` via the public `from radiodish import RadioDishError`.
