# `radiodish.autowire` — automatic ports, discovery, and connection

A separate, optional layer on top of `radiodish`'s core sockets — nothing
here is part of RFC 48, it's pure convenience for the common case of
"I don't want to manually pick ports or call `.connect()` on every peer
myself." Four pieces, three independent and one composing them:

- **`find_free_port_pair(host, start, end)`** — the port assigner.
- **`Discoverer`** — finds peers, without needing to know their addresses in advance.
- **`AutoWirer`** — watches what `Discoverer` finds and calls `.connect()` automatically.
- **`autowired_radish(...)`** — one call that does all three plus binds a `RadishSocket`.

```python
radish, discoverer, wirer = await autowired_radish(groups=["sensors"])
radish.broadcast("21.5C", group="sensors")
group, payload = await radish.recv()
```

## The port assigner

`find_free_port_pair(host, start, end)` returns `(port, radio_sock,
dish_sock)` — two *already-bound* OS sockets, not just a number. That
matters: if it only returned an integer, there'd be a gap between
"confirmed this port is free" and "actually bound it," where another
process could grab the same port in between (a classic
check-then-act race). Handing back live sockets closes that gap
entirely — the port is yours from the moment the function returns.

Only even base ports are ever handed out, so two nodes on the same host
can never be assigned overlapping `RadishSocket` pairs (a `RadishSocket`
uses `base_port` for its RADIO and `base_port + 1` for its DISH — if node
A got `(9000, 9001)` and node B got `(9001, 9002)`, they'd both think
they owned port 9001).

## Discovery: two tiers, deliberately not three

The actual design question here isn't "is there internet access" — it's
"local machine, or local network," with reaching further than that being
something you ask for explicitly (`seeds=`) rather than something that
happens automatically. Two tiers are active by default:

### Tier 1: "my machine" (`radiodish.autowire.local_discovery`)

Every `Discoverer` sharing a `discovery_port` writes its own
announcement into a shared directory, and periodically reads whatever
every other `Discoverer` there has written. Pure filesystem — no
sockets, no network stack involvement at all — so it works identically
whether or not any network interface is up.

This tier exists because of something confirmed empirically, not
assumed: UDP multicast group-join can fail outright with no active
route. On a laptop with WiFi off, joining a multicast group with "let
the OS pick an interface" (`INADDR_ANY`) can error out on some OSes
(confirmed on macOS) even though loopback itself would happily carry the
traffic if asked *directly* instead of left to auto-selection. When that
join fails, it fails the *same way* for every process on the machine —
so without this tier, two processes sitting on the exact same laptop
couldn't discover each other at all, despite being inches apart.

The shared directory lives at a fixed location — `/tmp` on POSIX systems
specifically, *not* `tempfile.gettempdir()`'s default resolution. That
distinction turned out to matter more than it looks: `gettempdir()`
consults `TMPDIR`/`TEMP`/`TMP` environment variables before falling back
to a platform default, and those variables aren't guaranteed identical
across two genuinely separate process launches (different shells,
different tool wrappers, different venv activation state). A single test
script running several `Discoverer` instances in one process can never
hit this — they all resolve the same environment identically, since it's
the same process — which is exactly why this hid from every in-process
test while still being a real, reproducible bug for two actual `python3
script.py` processes started separately. `/tmp` sidesteps the whole
class of bug: it's a literal path, not an environment-variable lookup,
so two processes with wildly different environments still agree on where
to look. The directory is additionally scoped by user ID where available
(POSIX), since `/tmp` is shared across every user on the machine and two
unrelated users both running radiodish with the same `discovery_port`
shouldn't see each other.

### Tier 2: "my LAN" (`radiodish.autowire.discovery`, UDP multicast)

A small homemade mDNS: each node periodically announces
`(node_id, addresses, port, groups, interest)` to a multicast group
(`239.255.42.99:9999` by default — an organization-local-scope address
per RFC 2365, chosen specifically to avoid colliding with real allocated
multicast groups), and every node listening on that same group hears
every announcement, including its own (filtered out by `node_id`).

Setting up the actual multicast socket is tried in three progressively
weaker ways every time, not just once at startup:

1. **Any interface** (`INADDR_ANY`) — the normal case, reaches other
   machines on the LAN. This is what can fail with no active network
   route, as described above.
2. **Loopback-scoped specifically** — join the multicast group by
   explicitly naming `127.0.0.1` as the interface, rather than letting
   the OS auto-select one. This bypasses the OS's auto-selection logic
   entirely, and empirically does let multicast work over loopback even
   with no other interface active. Confirmed to actually deliver real
   traffic, not just avoid raising an exception —
   `tests/test_network_resilience.py`'s
   `test_loopback_scoped_multicast_actually_delivers` proves two nodes
   forced onto this tier still find each other.
3. **A plain non-multicast bind** — the last resort before giving up on
   sockets entirely and relying on the file tier alone. Explicit
   `seeds=` unicast still works even here, since that doesn't need
   multicast group membership at all.

This three-step attempt isn't only made once at startup - it's re-run
every 8 seconds for the *entire lifetime* of the `Discoverer`
(`_revalidate_loop`). Each cycle opens a fresh socket and, if that worked,
switches to it and closes the one it replaces - so it picks up a better
tier the moment one becomes available, without sockets piling up - and if
nothing could be opened the working socket is simply kept. It falls back
gracefully if a tier that was working stops working (network dropped
mid-session). Both directions matter: a node
that starts degraded should upgrade automatically once a real network
shows up, and a node that was on a working LAN shouldn't crash or go
silent if that network later disappears - it should just fall back to
whatever's still available (loopback, or the file tier) without anyone
needing to restart it.

## Detecting your own addresses, without touching the internet

`detect_local_addresses()` returns every address this machine could
plausibly be reached at, ordered "most local first" — and does it
without making outbound contact with anything, including the harmless
"connect a UDP socket to 8.8.8.8 just to see what route the OS picks"
trick this used to rely on. That trick was dropped deliberately: it
still asks the OS to resolve a route toward the *public internet*
specifically, and what that resolves to when there's no real internet
route turned out to be genuinely inconsistent across OSes and network
states — confirmed in practice by it occasionally producing addresses
that couldn't actually reach a same-machine peer, not just suspected in
theory.

Two techniques are combined instead, since each catches cases the other
misses:

1. **Local hostname resolution** (`socket.gethostbyname_ex`) — pure
   local resolver/hosts-file/NSS lookup, no network round-trip at all.
   Can be stale or simply not reflect the current LAN address on some
   systems (notably laptops that roam between networks).
2. **A route-table lookup aimed at a *private* address**
   (`10.255.255.255`) rather than a public one. Still zero packets sent
   — UDP `connect()` is purely a local routing-table lookup, nothing is
   ever transmitted — but asking "what's my LAN route" instead of
   "what's my internet route" matters: a LAN-only setup with no default
   gateway configured at all can still have a specific route to a
   private subnet, so this can succeed where the old public-address
   version would just fail outright.

Every candidate from either technique is verified with an actual bind
attempt before being trusted — a route lookup succeeding doesn't
guarantee the resulting address is bindable on this host. `"127.0.0.1"`
is always first and always present regardless of whether either
technique finds anything else, so same-machine discovery never depends
on either one succeeding.

`RadishSocket`s bind on `0.0.0.0` by default (every interface at once —
no guessing needed for *binding*, only for what to *announce*), and
`AutoWirer` connects to every address a peer announces, unconditionally.
See [Real bugs found while building this](#real-bugs-found-while-building-this)
below for why "just connect to everything, don't be clever about
picking one" is the deliberate, hard-won default rather than an
oversight.

## `AutoWirer`: the actual autowiring

Watches a `Discoverer`'s peer table and calls `RadishSocket.connect()`
for peers where either side has a reason to: my interest overlaps what
they provide, **or** their interest (which they also announce) overlaps
what I provide. Checking only one direction is a real bug, not a style
choice — see
[the symmetric wiring bug](#real-bugs-found-while-building-this) below.

Reaching beyond machine + LAN is explicit only: pass
`seeds=[(host, port), ...]` to also unicast the same announcements
directly at specific addresses. A seed that doesn't look like a
loopback/private/link-local address triggers a `UserWarning` at
construction time, nudging toward a real tunnel/VPN in front of it
rather than trusting bare UDP discovery against the open internet.

## On the "Spring autowire" comparison

It's a useful shape, not a literal port. Spring resolves a **fixed**
graph of known local objects **once**, at construction. `AutoWirer`
resolves a **live** graph of remote, unreliable processes that can
appear or vanish at any moment, and it never stops looking — it's a
background loop for the socket's whole lifetime, not a one-shot
injection step. There's no equivalent of a startup failure if a
"dependency" isn't found yet; a peer that shows up 10 seconds late just
gets wired in 10 seconds late, silently.

## Real bugs found while building this

Worth reading if you're extending this code, since each of these is the
kind of thing that looks fine in a quick test and breaks in real usage —
which is exactly how each one was originally missed.

**Wiring was one-sided.** A consumer's interest overlapping a provider's
groups gets the consumer to `connect()` to the provider — but nothing
made the provider connect back, so the provider's DISH never told the
consumer's RADIO what it had joined, and forward calls silently never
transmitted even though `wired_peers` looked satisfied on the consumer's
side. Fixed by having `Discoverer` announce each node's `interest`
alongside its `groups`, so `AutoWirer` can check both directions.

**`Discoverer` computed its own address list exactly once, at
construction.** A node started before WiFi came on stayed stuck
announcing only loopback forever, even long after a real address became
available, because nothing ever asked again. Now re-detected every
revalidate cycle (8s) and re-announced immediately if anything changed.

**`AutoWirer` marked a peer "wired" permanently on first contact.** Even
after the address-refresh fix above, a peer that was already wired via
loopback never got a newly-available address tried, since the peer's
`node_id` was already in the "done" set. Now tracks which *addresses*
it's connected per peer and connects to new ones as they appear, without
needing to "unwire" anything first.

**Connecting to every address a peer announces looked wasteful, so it
was made "smarter" — and that was a mistake.** The fix tried: skip
loopback if a peer shares a non-loopback address with you, on the theory
that meant "same machine, so loopback alone is enough, avoid
double-delivery." Caught by testing an offline start followed by WiFi
turning on partway through: a process that started offline only ever
knew its own loopback address, so the heuristic concluded "different
machine" even when it wasn't, and skipped the one address that actually
worked. Missing a connection entirely is a far worse failure than an
occasional duplicate delivery, and RFC 48 already treats connections as
cheap and unconditional on purpose — filtering happens at the JOIN/group
layer, not by being clever about which address to dial. The fix was
reverted back to "connect to everything"; every `send()`/`call()` in the
`radioactor` package already documents itself as at-least-once, not
exactly-once, so a peer occasionally getting a message twice because two
of its addresses both happen to work is consistent with everything else
in this system, not a new problem.

## If same-machine discovery still seems unreliable

Every mechanism identified so far is fixed and covered by a test in
`tests/test_network_resilience.py`, built directly from a reported
symptom rather than guessed at — including a laptop with WiFi
genuinely off, not a simulated approximation of one. If something's
still off in your environment, the fastest way to narrow it down:

- Print `discoverer._local_dir` from both processes and confirm they
  match exactly. If they do, and files are genuinely appearing there for
  both, the write/scan mechanism is working and the bug is downstream —
  check `discoverer.addresses` on each side, and `wirer.wired_peers` /
  `radiodish.radio._peers` to see what actually got connected.
- `Discoverer._revalidate_loop`'s own docstring has a walkthrough for the
  "reconnected but an already-running node hasn't picked it up yet"
  timing case specifically — a node that started degraded doesn't notice
  a network coming back until its own next revalidate tick, up to 8
  seconds later, which can look like a stuck node from outside if you're
  not aware of the delay.

## Examples

See [docs/examples/](examples/) — `example_radish.py` wires peers up by
hand as a baseline, `example_autowire.py` does the same thing fully
automatically so you can compare the two directly.
