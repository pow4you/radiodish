# radish 🌱

An asyncio-native actor library for Python, built from scratch on a stdlib-UDP
implementation of the RADIO-DISH pattern (RFC 48). No broker, no external
dependencies, no manual peer configuration — actors find each other and wire
themselves up.

## Why

Most actor/message-passing libraries either lean on a broker (RabbitMQ, Redis)
or require you to hand-configure who talks to whom. radish takes a different
approach: actors discover peers on their own — first checking the local
filesystem, then loopback multicast, then LAN multicast — and wire themselves
together automatically via `AutoWirer`. You write actors with an `@expose`
decorator; radish handles the rest.

## Core ideas

- **Groups as the only addressing primitive.** `send_to(target, data)` and
  `broadcast(topic, data)` are the same operation under the hood — just
  different group strings. One mental model, no separate pub/sub topology.
- **Broker-less, self-discovering mesh.** No central registry to stand up or
  keep alive. Peers announce themselves and are found via a three-tier
  discovery chain.
- **Per-actor inbox, not per-method.** Preserves the actor model's core
  guarantee — one actor, one thread of state mutation — with an opt-in flag
  for methods that are safe to run concurrently.
- **Lazy peer registration.** `depends_on` is optional pre-warming only;
  `send()`/`call()` register interest on first use, so nothing needs to be
  known upfront.

## Quick example

\`\`\`python
from radish import Actor, expose

class Greeter(Actor):
    @expose
    async def hello(self, name):
        return f"Hello, {name}!"
\`\`\`

## Status

Actively developed as the actor-model foundation for a larger distributed
runtime project. Tested on macOS with and without WiFi active.
