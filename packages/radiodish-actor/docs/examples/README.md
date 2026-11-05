# Examples

## `example_actor.py`

Two roles in one script — a provider and a caller — so you can run them
as separate real processes and watch actual cross-process discovery and
wiring happen, not just an in-memory simulation of it.

```
python3 example_actor.py provider
python3 example_actor.py caller
```

**What this demonstrates:**

- **The provider** exposes `ping` (callable by its function name) and an
  explicit `shout_topic` group alias for `shout` — showing both addressing
  styles from [`docs/actor-model.md`](../actor-model.md) in one place.
- **The caller** declares zero `depends_on`. It calls `"ping"` cold, the
  moment it registers — discovery, wiring, and the call itself all happen
  live, on the fly, with no pre-configuration at all. This is the
  clearest possible demonstration of dynamic dependency discovery: watch
  the first call or two in the caller's output, they may time out or take
  a moment while wiring catches up (expected — see the retry behavior in
  `docs/actor-model.md`), and then every subsequent call succeeds cleanly.
- Run both **in separate terminals** rather than as background processes
  in one shell if you want to watch the timing live — the interesting
  part is genuinely the first few seconds, watching independent
  processes find each other with no coordination beyond both listening
  on the same discovery channel.

You'll see occasional duplicate reply lines in the provider's log
(`got ping(...), replying` printed twice for the same sequence number).
That's expected, not a bug — it's `call()`'s retry doing its job: a
message legitimately can go out before wiring fully completes, so it
resends, and sometimes both the original and the resend get through.
See [`docs/actor-model.md`](../actor-model.md#dependencies-are-discovered-dynamically)
for why that's a deliberate trade-off (at-least-once delivery) rather
than something to fix.
