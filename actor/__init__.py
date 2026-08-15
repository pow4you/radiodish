"""
actor — an Erlang-actor-model-flavored layer on top of radish. Not RPC
bolted onto pub/sub; it leans fully into RADIO-DISH's native broadcast
nature. There's no "call actor X's method Y" — there's only "send to a
group." A handler's trigger-set, computed by @expose(groups=...):

    your explicit groups ∪ {the function's own name} ∪ {""}

Every exposed function joins "" by default, so an unaddressed message
reaches every exposed function on every actor you're connected to — a
genuine broadcast-to-everyone channel, not accidental. Function names
aren't actor-namespaced (@expose runs before any actor instance exists,
so it can't see self.actor_id()) — two actor classes both exposing
`login` both receive anything sent to bare group "login"; bake your own
namespace into an explicit group string if you want to avoid that.

    from actor import Actor, expose

    class Greeter(Actor):
        id = "greeter"

        @expose()
        async def ping(self, payload):
            return {"pong": payload}

    class Caller(Actor):
        pass

    provider = await Greeter().register()
    caller = await Caller().register()
    result = await caller.call("ping", {"seq": 1}, timeout=2.0)
"""

from actor.decorators import expose
from actor.base import Actor

__all__ = ["Actor", "expose"]
