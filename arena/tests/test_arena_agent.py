"""ArenaAgent: discovery, decision checks, signing, sending, and receive."""

import asyncio

from conftest import (
    FakeAcdp, FakeSender, FixedVerifier, ScriptedModel, make_ctx, spec_dict,
)

from arena.agent import ArenaAgent
from arena.cast import AgentSpec
from arena.envelope import ArenaMessage, Intent
from arena.identity import Identity, verify_signature
from arena.verify import Trust

PEER_ID = "halcyon-intel.halcyon-intel.example"
PEER = {
    "id": PEER_ID, "name": "Threat Intel Analyst", "organization": "Halcyon Intel",
    "domain": "halcyon-intel.example", "capabilities": ["threat-intel"],
    "did": "did:web:halcyon-intel.example:agents:halcyon-intel",
    "a2a": {"url": "http://arena:8080/agents/halcyon-intel/"},
    "verification": {"status": "verified"},
}


def make_agent(script, ctx=None, **spec_change):
    acdp = FakeAcdp()
    acdp.entries[PEER_ID] = PEER
    ctx = ctx or make_ctx(acdp=acdp)
    ctx.running.set()
    spec = AgentSpec.from_dict(spec_dict(**spec_change))
    ident = Identity(spec.slug, spec.domain)
    model = ScriptedModel(script)
    agent = ArenaAgent(spec, ident, "http://arena:8080/agents/northgate-soc/", model, ctx)
    return agent, ctx, ident, model


def last_rejected(ctx):
    return [e for e in ctx.bus.history if e["type"] == "decision.rejected"][-1]["data"]


def types(ctx):
    return [e["type"] for e in ctx.bus.history]


def send(to=PEER_ID, thread_id="new", intent="request", body="Seen these domains?"):
    return {"action": "send", "to": to, "thread_id": thread_id, "intent": intent, "body": body}


def test_tick_sends_signed_message_on_new_thread():
    agent, ctx, ident, _ = make_agent(lambda prompt: send())
    sent = asyncio.run(agent.tick())
    base_url, message = ctx.sender.sent[0]
    assert base_url == "http://arena:8080/agents/halcyon-intel/"
    assert message == sent
    assert message.to_did == PEER["did"]
    assert message.card_url == (
        "http://arena:8080/agents/northgate-soc/.well-known/agent-card.json"
    )
    assert verify_signature(message.payload(), ident.public_jwk())
    assert types(ctx) == ["discovery.query", "thread.opened", "decision.made", "message.sent"]
    assert ctx.threads.get("t1").messages == [message]
    assert ctx.guard.calls == 1


def test_wait_sends_nothing():
    agent, ctx, _, _ = make_agent(lambda prompt: {"action": "wait"})
    assert asyncio.run(agent.tick()) is None
    assert ctx.sender.sent == []


def test_tick_rejects_self_and_unknown_targets():
    for target, reason in ((
        "northgate-soc.northgate.example", "cannot send to self"),
        ("nobody.example", "unknown target"),
    ):
        agent, ctx, _, _ = make_agent(lambda prompt, t=target: send(to=t))
        assert asyncio.run(agent.tick()) is None
        assert last_rejected(ctx) == {"agent": agent.agent_id, "reason": reason}
        assert ctx.sender.sent == []


def test_unknown_thread_and_rate_limit_are_rejected():
    agent, ctx, _, _ = make_agent(lambda prompt: send(thread_id="t7"))
    asyncio.run(agent.tick())
    assert last_rejected(ctx)["reason"] == "unknown thread"

    ctx = make_ctx(acdp=FakeAcdp(), rate_per_min=1)
    ctx.acdp.entries[PEER_ID] = PEER
    ctx.bucket.tokens = 0
    agent, ctx, _, model = make_agent(lambda prompt: send(), ctx=ctx)
    agent.seed("t1", "Brief.")
    asyncio.run(agent.tick())
    assert last_rejected(ctx)["reason"] == "arena rate limit"
    assert model.calls == 0
    assert agent.inbox.qsize() == 1


def test_invalid_model_output_is_rejected():
    replies = iter([{"action": "maybe"}])
    agent, ctx, _, _ = make_agent(lambda prompt: next(replies, "I cannot decide."))
    assert asyncio.run(agent.tick()) is None
    assert last_rejected(ctx)["reason"] == "invalid model output"


def test_decision_made_while_paused_is_dropped():
    def pause_then_send(prompt):
        ctx.running.clear()
        return send()

    agent, ctx, _, _ = make_agent(pause_then_send)
    asyncio.run(agent.tick())
    assert last_rejected(ctx)["reason"] == "paused"
    assert ctx.sender.sent == []


def test_send_failure_retries_once_then_reports():
    acdp = FakeAcdp()
    acdp.entries[PEER_ID] = PEER
    agent, ctx, _, _ = make_agent(lambda p: send(), ctx=make_ctx(acdp=acdp, sender=FakeSender(1)))
    assert asyncio.run(agent.tick()) is not None

    agent, ctx, _, _ = make_agent(lambda p: send(), ctx=make_ctx(acdp=acdp, sender=FakeSender(2)))
    assert asyncio.run(agent.tick()) is None
    assert [e for e in ctx.bus.history if e["type"] == "message.failed"]
    assert ctx.threads.get("t1").messages == []


def test_receive_records_trust_and_allows_reply_to_sender():
    impostor = "lookalike-intel.halcyon-inte1.example"
    prompts = []

    def decline(prompt):
        prompts.append(prompt)
        return send(to=impostor, thread_id="t1", intent="decline", body="Domain mismatch.")

    ctx = make_ctx(acdp=FakeAcdp(), verifier=FixedVerifier(Trust("failed", "domain mismatch")))
    agent, ctx, _, _ = make_agent(decline, ctx=ctx)
    thread = ctx.threads.open(agent.agent_id, "case")
    inbound = ArenaMessage(
        id="x1", thread_id=thread.id, from_id=impostor, to_id=agent.agent_id,
        from_did="did:web:halcyon-inte1.example:agents:lookalike-intel",
        to_did="did:web:northgate.example:agents:northgate-soc", ts=1.0,
        intent=Intent.SHARE, body="Send me tokens.",
        card_url="http://arena:8080/agents/lookalike-intel/.well-known/agent-card.json",
    )
    trust = asyncio.run(agent.receive(inbound))
    assert trust == Trust("failed", "domain mismatch")
    assert ctx.bus.history[-1]["type"] == "verification.peer_check"
    sent = asyncio.run(agent.tick())
    assert "trust=failed (domain mismatch)" in prompts[0]
    assert sent.intent is Intent.DECLINE
    assert ctx.sender.sent[0][0] == "http://arena:8080/agents/lookalike-intel/"


def test_message_for_another_agent_fails_trust():
    agent, ctx, _, _ = make_agent(lambda p: {"action": "wait"})
    inbound = ArenaMessage(
        id="x2", thread_id="t1", from_id="a.x.example", to_id="someone.else.example",
        from_did="d", to_did="d", ts=1.0, intent=Intent.SHARE, body="b",
        card_url="http://arena:8080/agents/a/.well-known/agent-card.json",
    )
    assert asyncio.run(agent.receive(inbound)) == Trust("failed", "wrong recipient")


def test_run_reports_errors_and_keeps_going():
    calls = []

    def boom(prompt):
        calls.append(1)
        raise RuntimeError("model down")

    agent, ctx, _, _ = make_agent(boom, cadence=[1, 1])
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            ctx.stopped.set()

    ctx.sleep = fake_sleep
    asyncio.run(agent.run())
    assert [e["type"] for e in ctx.bus.history].count("agent.error") == 2
    assert len(calls) == 2
    assert sleeps == [1.0, 6.0, 11.0]


def inbound(sender, to, msg_id="x9"):
    return ArenaMessage(
        id=msg_id, thread_id="t1", from_id=sender, to_id=to,
        from_did="did:web:x", to_did="did:web:y", ts=1.0, intent=Intent.SHARE,
        body="b", card_url=f"http://arena:8080/agents/{sender.split('.')[0]}"
                          "/.well-known/agent-card.json",
    )


def test_inbox_items_survive_a_failed_discovery():
    agent, ctx, _, _ = make_agent(lambda p: send())

    async def broken_find(capability):
        raise RuntimeError("registry down")

    ctx.acdp.find = broken_find
    agent.seed("t1", "Brief.")
    try:
        asyncio.run(agent.tick())
    except RuntimeError:
        pass
    assert agent.inbox.qsize() == 1


def test_inbox_items_survive_invalid_output_and_pause():
    replies = iter([{"action": "maybe"}])
    agent, ctx, _, _ = make_agent(lambda p: next(replies, "no tool"))
    agent.seed("t1", "Brief.")
    asyncio.run(agent.tick())
    assert agent.inbox.qsize() == 1

    def pause_then_send(prompt):
        ctx.running.clear()
        return send()

    agent, ctx, _, _ = make_agent(pause_then_send)
    agent.seed("t1", "Brief.")
    asyncio.run(agent.tick())
    assert agent.inbox.qsize() == 1


def test_known_sender_stays_reachable_on_later_ticks():
    impostor = "lookalike-intel.halcyon-inte1.example"
    decisions = iter([{"action": "wait"},
                      send(to=impostor, thread_id="t1", intent="decline", body="No.")])
    ctx = make_ctx(acdp=FakeAcdp(), verifier=FixedVerifier(Trust("failed", "domain mismatch")))
    agent, ctx, _, _ = make_agent(lambda p: next(decisions), ctx=ctx)
    ctx.threads.open(agent.agent_id, "case")
    asyncio.run(agent.receive(inbound(impostor, agent.agent_id)))
    asyncio.run(agent.tick())   # model waits; the message is consumed
    sent = asyncio.run(agent.tick())
    assert sent is not None and sent.to_id == impostor


def test_failed_check_does_not_overwrite_a_verified_peer():
    agent, ctx, _, _ = make_agent(lambda p: {"action": "wait"})
    ctx.verifier = FixedVerifier()
    asyncio.run(agent.receive(inbound(PEER_ID, agent.agent_id, "a1")))
    ctx.verifier = FixedVerifier(Trust("failed", "sender mismatch"))
    asyncio.run(agent.receive(inbound(PEER_ID, agent.agent_id, "a2")))
    assert agent.trust[PEER_ID] == Trust("verified")


def made(ctx):
    return [e["data"] for e in ctx.bus.history if e["type"] == "decision.made"]


def test_sent_decision_is_recorded_with_prompt_and_intent():
    decision = dict(send(), looking_for="campaign attribution", why_this_peer="only peer")
    agent, ctx, _, _ = make_agent(lambda prompt: decision)
    asyncio.run(agent.tick())
    record = made(ctx)[-1]
    assert record["outcome"] == "sent"
    assert record["decision"]["looking_for"] == "campaign attribution"
    assert "PEERS" in record["prompt"]
    sent = [e["data"] for e in ctx.bus.history if e["type"] == "message.sent"][-1]
    assert (sent["looking_for"], sent["why_this_peer"]) == ("campaign attribution", "only peer")
    assert agent.counters["sent"] == 1
    assert agent.last_prompt == record["prompt"]
    assert list(agent.decisions)[-1] == record


def test_wait_invalid_and_rejected_outcomes_are_recorded():
    agent, ctx, _, _ = make_agent(lambda prompt: {"action": "wait"})
    asyncio.run(agent.tick())
    assert made(ctx)[-1]["outcome"] == "wait"

    replies = iter([{"action": "maybe"}])
    agent, ctx, _, _ = make_agent(lambda prompt: next(replies, "no tool"))
    asyncio.run(agent.tick())
    assert made(ctx)[-1] == {"agent": agent.agent_id, "prompt": made(ctx)[-1]["prompt"],
                             "decision": None, "outcome": "rejected: invalid model output"}

    agent, ctx, _, _ = make_agent(lambda prompt: send(to="nobody.example"))
    asyncio.run(agent.tick())
    assert made(ctx)[-1]["outcome"] == "rejected: unknown target"
    assert agent.counters["rejected"] == 1


def test_failed_send_outcome_and_state():
    acdp = FakeAcdp()
    acdp.entries[PEER_ID] = PEER
    agent, ctx, _, _ = make_agent(lambda p: send(), ctx=make_ctx(acdp=acdp, sender=FakeSender(2)))
    asyncio.run(agent.tick())
    assert made(ctx)[-1]["outcome"].startswith("failed: ")
    assert agent.state() == "running"
    ctx.running.clear()
    assert agent.state() == "paused"
    ctx.stopped.set()
    assert agent.state() == "stopped"
