"""
actor/base.py — Actor: an Erlang-actor-model-flavored base class running
over autowired RadishSockets. See actor/__init__.py's docstring for the
addressing model (groups, not "call actor X's method Y").
"""

from __future__ import annotations

import asyncio
import inspect
import json
import uuid
import warnings
from typing import Callable, Iterable, Optional

from radish import RadioDishError
from radish.autowire import autowired_radish, DEFAULT_DISCOVERY_PORT


class Actor:
    """
    Base class for radish-backed actors. Subclass it and tag methods with
    @expose, then `await register()`.

    `depends_on` is optional now, not required: send()/call() register
    interest in whatever group they're asked to reach the first time they
    try, so an actor discovers what it needs on the fly instead of you
    having to predict it up front. Pass `depends_on` only if you want to
    pre-warm that wiring before your first call, to skip the latency of
    waiting for AutoWirer's next poll -- not because anything requires it.
    """

    def __init__(self, depends_on: Iterable[str] = ()):
        if type(self) is Actor:
            warnings.warn(
                "Instantiating Actor directly is discouraged -- define a "
                "subclass instead, even an empty `class MyCaller(Actor): "
                "pass`. actor_id() defaults to the class name, so every "
                "bare Actor() instance identifies itself as just 'Actor' "
                "in logs, discovery announcements, and instance_id() -- a "
                "named subclass makes that identity actually mean "
                "something, and gives you a natural place to grow into "
                "(exposed methods, on_register(), etc.) later.",
                stacklevel=2,
            )
        self._instance_id = f"{self.actor_id()}#{uuid.uuid4().hex[:8]}"
        self._depends_on: set = set(depends_on)
        self._groups_to_handlers: dict[str, list[Callable]] = self._discover_exposed_methods()
        self._pending: dict[str, asyncio.Future] = {}
        self.radish = None
        self.discoverer = None
        self.wirer = None
        self._run_task: Optional[asyncio.Task] = None

    # ---- identity ---------------------------------------------------------

    def actor_id(self) -> str:
        """Logical, human-readable identity -- shared on purpose if you run
        several replicas under the same class/id. Not used for routing at
        all in this design (see module docstring); it's here for logging,
        discovery bookkeeping, and as a building block if you want to
        construct your own namespaced group strings."""
        return getattr(self, "id", self.__class__.__name__)

    def instance_id(self) -> str:
        """Always unique to this running process. Used only to build the
        private reply group -- never appears in capability routing."""
        return self._instance_id

    def _reply_group(self) -> str:
        return f"{self._instance_id}.replies"

    # ---- setup --------------------------------------------------------------

    def _discover_exposed_methods(self) -> dict[str, list[Callable]]:
        groups_to_handlers: dict[str, list[Callable]] = {}
        for _, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if getattr(method, "_exposed", False):
                for group in method._exposed_groups:
                    groups_to_handlers.setdefault(group, []).append(method)
        return groups_to_handlers

    def _own_groups(self) -> list[str]:
        return list(self._groups_to_handlers.keys()) + [self._reply_group()]

    async def register(
        self,
        *,
        host: Optional[str] = None,
        discovery_port: int = DEFAULT_DISCOVERY_PORT,
        seeds: Iterable[tuple[str, int]] = (),
        port_range: tuple[int, int] = (20000, 40000),
    ) -> "Actor":
        """
        Finds ports, binds a RadishSocket, joins every exposed group plus
        this instance's private reply group, starts discovery/autowiring
        (using `depends_on`, from __init__, as extra connect-worthy
        interest beyond what this actor itself exposes), then starts the
        dispatch loop. Returns self so `x = await Foo().register()` works.
        """
        own_groups = self._own_groups()
        interest = set(own_groups) | self._depends_on
        self.radish, self.discoverer, self.wirer = await autowired_radish(
            host=host,
            groups=own_groups,
            interest_groups=interest,
            discovery_port=discovery_port,
            seeds=seeds,
            port_range=port_range,
            node_id=self._instance_id,
        )
        if hasattr(self, "on_register"):
            await self.on_register()
        self._run_task = asyncio.ensure_future(self._run())
        return self

    def add_endpoint(self, method: Callable) -> None:
        """
        Expose a new @expose'd method after registration. No disconnect
        needed for existing peers to pick it up: DishSocket.join() was
        already safe to call any time, and radiodish's periodic rejoin
        announces it to every already-connected peer automatically. What
        DOES need an explicit push is the Discoverer's advertised group
        list, so *new* peers (ones not connected yet) can find this
        capability during discovery -- that's the one line that's genuinely
        new here, not a disconnect/reconnect.
        """
        groups = getattr(method, "_exposed_groups", None)
        if groups is None:
            raise RadioDishError("add_endpoint() expects an @expose'd method")
        new_groups = [g for g in groups if g not in self._groups_to_handlers]
        for g in groups:
            self._groups_to_handlers.setdefault(g, []).append(method)
        if self.radish is not None:
            for g in new_groups:
                self.radish.join(g)
            self.discoverer.update_groups(self._own_groups())

    def add_dependency(self, group: str) -> None:
        """Declare interest in reaching `group` even though this actor
        doesn't expose it -- lets AutoWirer connect out to a provider once
        one is discovered, AND (since connecting is decided from both
        sides -- see autowire.Discoverer's docstring) lets a provider who's
        already running connect back to us once it hears our updated
        interest in our next announcement."""
        self._depends_on.add(group)
        if self.wirer is not None:
            self.wirer.add_interest(group)
        if self.discoverer is not None:
            self.discoverer.update_interest(set(self._own_groups()) | self._depends_on)

    def _ensure_interest(self, group: str) -> None:
        """The dynamic half of dependency discovery: called by send()/call()
        so an actor registers interest in a group automatically, the first
        time it actually tries to reach it, instead of requiring that to be
        predicted upfront via depends_on. Skips the (cheap but not free --
        it triggers a re-announce) work entirely for groups already covered,
        either because add_dependency() already ran for this one, or
        because it's something this actor exposes itself already."""
        if group in self._depends_on or group in self._groups_to_handlers:
            return
        self.add_dependency(group)

    # ---- dispatch loop ---------------------------------------------------

    async def _run(self):
        try:
            while True:
                group, raw = await self.radish.recv()
                try:
                    group_str = group.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if group_str == self._reply_group():
                    self._handle_reply(raw)
                    continue
                try:
                    msg = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                for handler in self._groups_to_handlers.get(group_str, ()):
                    await self._dispatch_one(handler, msg)
        except asyncio.CancelledError:
            pass

    async def _dispatch_one(self, handler: Callable, msg: dict) -> None:
        await self._send_status(msg, status=202)  # "accepted" ack -- UDP
        # gives no delivery confirmation of its own, so this is the only
        # signal a caller gets that the message actually arrived at all.
        try:
            result = await handler(msg.get("payload"))
            await self._send_result(msg, result=result)
        except Exception as e:
            await self._send_result(msg, error=str(e))

    def _handle_reply(self, raw: bytes) -> None:
        try:
            msg = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        fut = self._pending.get(msg.get("correlation_id"))
        if fut is None or fut.done():
            return  # nobody waiting -- timed out already, a dupe, or a
            # second handler's reply to the same correlation_id (see
            # call()'s docstring: first reply wins, rest are dropped)
        if msg.get("status") == 202:
            return  # just the accept-ack; keep waiting for the real result
        if msg.get("error") is not None:
            fut.set_exception(RadioDishError(msg["error"]))
        else:
            fut.set_result(msg.get("result"))

    async def _send_status(self, msg: dict, status: int) -> None:
        target = msg.get("callback_target")
        if not target:
            return
        self.radish.broadcast(
            json.dumps({"correlation_id": msg.get("correlation_id"), "status": status}).encode(),
            group=target,
        )

    async def _send_result(self, msg: dict, result=None, error=None) -> None:
        target = msg.get("callback_target")
        if not target:
            return
        self.radish.broadcast(
            json.dumps(
                {"correlation_id": msg.get("correlation_id"), "result": result, "error": error}
            ).encode(),
            group=target,
        )

    # ---- sending to other actors ------------------------------------------

    def send(self, group: str, payload=None, correlation_id: Optional[str] = None) -> str:
        """Fire a message at `group`. Fans out to every actor (and every
        locally-registered handler on each) currently wired and listening
        on that exact group. Returns the correlation_id immediately without
        waiting for any reply -- use call() to await one.

        Registers interest in `group` automatically if this is the first
        time it's been reached (see _ensure_interest) -- no depends_on
        needed up front. This send itself may still miss its target if the
        resulting wiring hasn't finished yet; call() handles that with
        retries, but send() is fire-and-forget by design, so a caller that
        cares whether THIS particular send lands has to resend it
        themselves, the same as always."""
        self._ensure_interest(group)
        correlation_id = correlation_id or uuid.uuid4().hex
        self.radish.broadcast(
            json.dumps(
                {
                    "payload": payload,
                    "callback_target": self._reply_group(),
                    "correlation_id": correlation_id,
                }
            ).encode(),
            group=group,
        )
        return correlation_id

    async def call(
        self,
        group: str,
        payload=None,
        timeout: Optional[float] = None,
        retry_interval: Optional[float] = 0.5,
    ):
        """
        send() and await the matching reply, matched by correlation_id. If
        more than one handler matched `group`, resolves to whichever
        replies first; later ones are silently dropped. Raises
        asyncio.TimeoutError if nothing comes back in time.

        Retries by default: a single UDP datagram can genuinely go missing
        even in normal operation -- not just from packet loss, but because
        it can legitimately be sent before a peer's reciprocal wiring has
        finished (two AutoWirers converging on each other isn't
        instantaneous or synchronized), and nothing resends a dropped
        datagram on its own. call() resends the same message, same
        correlation_id, every `retry_interval` seconds until a reply
        arrives or `timeout` elapses. Pass retry_interval=None to send
        exactly once instead.

        This makes call() "at least once," not "exactly once": there's no
        receiver-side deduplication of correlation_ids, so if a resend
        arrives after the first attempt already reached the handler (its
        reply was just what got lost, not the request), the handler runs
        twice. Fine for idempotent handlers (most reads, "ping", cache
        invalidation); if you're calling something that must not run twice
        (charging a card), pass retry_interval=None and handle the
        possible loss yourself, or ensure your handler is idempotent on
        correlation_id — that dedup layer doesn't exist here yet.

        Also registers interest in `group` automatically if this is the
        first time it's been reached (see _ensure_interest) -- combined
        with the retry above, this is what makes depends_on genuinely
        optional: the first call() to a brand new group declares interest
        on the fly, then just keeps resending while AutoWirer catches up
        on its own poll cycle, arriving once wiring completes.
        """
        self._ensure_interest(group)
        loop = asyncio.get_running_loop()
        correlation_id = uuid.uuid4().hex
        fut = loop.create_future()
        self._pending[correlation_id] = fut
        self.send(group, payload, correlation_id=correlation_id)

        async def _resend_loop():
            try:
                while True:
                    await asyncio.sleep(retry_interval)
                    if fut.done():
                        return
                    self.send(group, payload, correlation_id=correlation_id)
            except asyncio.CancelledError:
                pass

        resend_task = asyncio.ensure_future(_resend_loop()) if retry_interval is not None else None
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            if resend_task:
                resend_task.cancel()
            self._pending.pop(correlation_id, None)

    async def close(self) -> None:
        if self._run_task:
            self._run_task.cancel()
        if self.wirer:
            await self.wirer.stop()
        if self.discoverer:
            await self.discoverer.stop()
        if self.radish:
            await self.radish.close()
