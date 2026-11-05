# The wire protocol

Every UDP datagram this library sends is exactly one frame — no framing
layer on top of that, no multipart concept, because RFC 48 explicitly
forbids multipart messages for the thread-safe socket family and a UDP
datagram is already an atomic "one send = one receive" unit at the OS
level. That's the whole reason this implementation builds directly on
UDP instead of on top of a stream transport: the delivery unit RFC 48
wants is the delivery unit UDP already gives you, for free.

## Frame layout

```
+--------+-----------+------------------+-------------------+
| type   | group_len | group (0-255 B)  | payload (rest)    |
| 1 byte | 1 byte    | group_len bytes  | remaining bytes   |
+--------+-----------+------------------+-------------------+
```

- **type** (1 byte): one of `MSG_DATA` (`0x01`), `MSG_JOIN` (`0x02`), or
  `MSG_LEAVE` (`0x03`).
- **group_len** (1 byte): the length of the group name that follows, 0 to
  255 — which is exactly why groups are capped at 255 bytes: that's the
  largest value a single byte can hold. RFC 48's own ABNF for groups
  (`group = 0*255group-char`) matches this length limit precisely; it
  isn't a coincidence, the wire format is built directly around what the
  spec already requires.
- **group**: the raw group name bytes, `group_len` bytes long.
- **payload**: whatever's left in the datagram. Empty for JOIN/LEAVE
  control frames, the actual application data for DATA frames.

`radish.protocol.encode_frame(msg_type, group, payload=b"")` and
`decode_frame(data)` are the only two functions that ever touch this
layout directly; everything else in the codebase works with parsed
`(msg_type, group, payload)` tuples.

## Which direction each frame type flows

- **DATA** frames flow RADIO → DISH. Every application message you send
  through `RadioSocket.send()` becomes one DATA frame.
- **JOIN** / **LEAVE** frames flow DISH → RADIO. They're how a DISH tells
  a RADIO "I want (or no longer want) this group" — see
  [Group filtering](#group-filtering) below for why this direction
  matters as much as it does.

A RADIO that receives anything *other* than JOIN/LEAVE from a peer
silently discards it — per RFC 48, "SHALL silently discard any messages
that dishes send it." A DISH never receives JOIN/LEAVE frames itself in
normal operation.

## Group filtering

This is the part of RFC 48 that does the actual work of a pub/sub
system, and it happens entirely on the RADIO side, driven by JOIN/LEAVE
frames it's received:

1. A DISH calls `.join("some_group")`. This immediately sends a JOIN
   frame to every RADIO it's currently connected to, and the frame gets
   re-sent periodically after that too (see
   [The rejoin problem](#the-rejoin-problem-a-udp-specific-wrinkle)
   below for why).
2. A RADIO receiving that JOIN frame records, for that specific peer
   address, that it's now interested in `"some_group"`.
3. When `RadioSocket.send(payload, group="some_group")` is called, the
   RADIO iterates its known peers and only actually transmits to the
   ones whose recorded group set contains `"some_group"` — exact match,
   no prefix or wildcard matching at all. Peers that never joined that
   exact group simply never receive the datagram; there's no error, no
   feedback, nothing — this is UDP, so "nobody was listening" and "the
   packet got lost" look identical from the sender's side, on purpose.

A RADIO also auto-registers any address it receives a JOIN/LEAVE frame
from, even one it never explicitly `connect()`ed to — which matters more
than it looks: it's what lets a DISH that only ever called `.connect()`
on a RADIO (never the other way around) still be reachable for replies,
without the RADIO needing to have proactively reached out first.

## The rejoin problem: a UDP-specific wrinkle

UDP gives no delivery guarantee. If a DISH's JOIN frame is sent before
the RADIO is actually listening yet — or the packet is simply lost, as
UDP packets sometimes are — the RADIO never learns that DISH wants a
group, and unlike TCP there's no retransmission happening underneath to
paper over it. Without anything else, that DISH would go silently deaf
forever: it thinks it joined, the RADIO never heard it, and no error
ever surfaces on either side.

`DishSocket` handles this by re-sending JOIN frames for every
currently-joined group, to every connected peer, on a periodic timer
(`rejoin_interval`, default 2 seconds, `None` to disable). This has no
equivalent anywhere in the original RFC — libzmq's actual transport for
this pattern is ZMTP over TCP, which has its own connection/handshake
reliability built in, so the underlying spec never had to think about
"what if the JOIN packet just vanishes." Building directly on
connectionless UDP means this implementation has to think about it, and
the rejoin timer is the fix.

## Queues: bounded, per-peer, drop-not-block

Both `RadioSocket` and `DishSocket` maintain one queue per connected
peer — outgoing on the RADIO side, incoming on the DISH side — backed by
`radish.transport._BoundedDropQueue`. Per RFC 48: "SHOULD constrain
queue sizes to a runtime-configurable limit" and "SHALL silently
discard/drop the message" when a queue is full. `_BoundedDropQueue`
implements exactly that: once a queue reaches its configured `maxsize`,
new items are refused (not blocked on, not evicting older items to make
room) and the caller never sees an exception — the message is just gone,
consistent with UDP's own no-guarantee nature.

On the DISH side specifically, `recv()` round-robins a cursor across
every connected peer's queue rather than draining one peer completely
before moving to the next — RFC 48's "fair-queuing" requirement, which
matters concretely: without it, one noisy RADIO sending a flood of
messages could starve out a quieter one indefinitely.

## What's deliberately *not* here

RFC 48 has no security aspects (its own words), and neither does this
implementation — no authentication, no encryption, no verification that
a peer claiming to be a particular address actually is. Anyone who can
reach your UDP ports can send JOIN frames or DATA frames. If you need
that layer, it has to be built on top (or run over an already-trusted
network, e.g. a VPN/tunnel — see `radish.autowire`'s docs for how that
composes with discovery).
