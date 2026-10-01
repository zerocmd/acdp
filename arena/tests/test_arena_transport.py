"""Inbox executor and A2A sender over in-process HTTP."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from arena.card import agent_base_url, build_card
from arena.cast import AgentSpec
from arena.envelope import ArenaMessage, Intent
from arena.identity import Identity
from arena.inbox_executor import InboxExecutor, build_a2a_app
from arena.transport import A2ASender, SendError
from arena.verify import Trust

BASE = "http://arena:8080"
SPEC = AgentSpec.from_dict({
    "slug": "northgate-soc", "name": "SOC Investigator", "organization": "Northgate Bank",
    "domain": "northgate.example", "capability": "soc-investigation", "description": "d",
    "needs": [], "model": "sonnet", "role": "investigation", "cadence": [15, 20],
    "system_prompt": "p",
})


def host_with_inbox():
    delivered = []

    async def deliver(message, task_id=None):
        delivered.append(message)
        return Trust("verified")

    ident = Identity(SPEC.slug, SPEC.domain)
    app = FastAPI()
    card = build_card(SPEC, ident, BASE)
    app.mount(f"/agents/{SPEC.slug}", build_a2a_app(card, InboxExecutor(deliver)))
    factory = lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app))  # noqa: E731
    return delivered, A2ASender(factory)


def message():
    return ArenaMessage(
        id="m1", thread_id="t1", from_id="a.x.example", to_id="northgate-soc.northgate.example",
        from_did="did:web:x.example:agents:a", to_did="did:web:northgate.example:agents:northgate-soc",
        ts=1.0, intent=Intent.REQUEST, body="Can you share IOCs?", card_url="http://arena:8080/c",
        sig="s",
    )


def test_sender_delivers_envelope_and_returns_ack():
    delivered, sender = host_with_inbox()
    reply = asyncio.run(sender.send(agent_base_url(BASE, SPEC.slug), message()))
    assert reply.text == "ack m1 verified"
    assert delivered == [message()]


def test_executor_rejects_missing_and_malformed_envelope():
    delivered, sender = host_with_inbox()
    base = agent_base_url(BASE, SPEC.slug)
    assert asyncio.run(sender.send_raw(base, None, "hi")).text == "rejected: missing arena envelope"
    bad = {"arena": {"id": 1}}
    assert asyncio.run(sender.send_raw(base, bad, "hi")).text == "rejected: invalid envelope"
    assert delivered == []
    assert asyncio.run(sender.send(base, message())).text == "ack m1 verified"


def test_unreachable_peer_raises_send_error():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    sender = A2ASender(lambda: httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
    with pytest.raises(SendError):
        asyncio.run(sender.send("http://nowhere:8080/agents/x/", message()))
