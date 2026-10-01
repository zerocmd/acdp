"""A2A tasks: created for requests, finished by the arena, read and canceled over A2A."""

import asyncio

import httpx
from a2a.server.tasks import InMemoryTaskStore
from fastapi import FastAPI

from arena.card import agent_base_url, build_card
from arena.cast import AgentSpec
from arena.envelope import ArenaMessage, Intent
from arena.identity import Identity
from arena.inbox_executor import InboxExecutor, build_a2a_app
from arena.tasks import finish_task
from arena.transport import A2ASender
from arena.verify import Trust

BASE = "http://arena:8080"
SPEC = AgentSpec.from_dict({
    "slug": "halcyon-intel", "name": "Threat Intel Analyst", "organization": "Halcyon Intel",
    "domain": "halcyon-intel.example", "capability": "threat-intel", "description": "d",
    "needs": [], "model": "sonnet", "role": "investigation", "cadence": [15, 20],
    "system_prompt": "p",
})


def host():
    delivered = []

    async def deliver(message, task_id):
        delivered.append((message.id, task_id))
        return Trust("verified")

    store = InMemoryTaskStore()
    app = FastAPI()
    card = build_card(SPEC, Identity(SPEC.slug, SPEC.domain), BASE)
    app.mount(f"/agents/{SPEC.slug}", build_a2a_app(card, InboxExecutor(deliver), store))
    sender = A2ASender(lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app)))
    return delivered, store, sender, agent_base_url(BASE, SPEC.slug)


def message(intent, msg_id="m1"):
    return ArenaMessage(
        id=msg_id, thread_id="t1", from_id="northgate-soc.northgate.example",
        to_id="halcyon-intel.halcyon-intel.example", from_did="d1", to_did="d2", ts=1.0,
        intent=intent, body="Do these domains match?", card_url=f"{BASE}/c", sig="s")


def test_request_creates_a_working_task_and_other_intents_do_not():
    delivered, _, sender, base = host()
    result = asyncio.run(sender.send(base, message(Intent.REQUEST)))
    assert result.task_id
    assert result.text == "ack m1 verified"
    assert delivered == [("m1", result.task_id)]
    state, _, _ = asyncio.run(sender.get_task(base, result.task_id))
    assert state == "working"
    share = asyncio.run(sender.send(base, message(Intent.SHARE, "m2")))
    assert share.task_id is None and share.text == "ack m2 verified"
    assert delivered[-1] == ("m2", None)


def test_finished_task_is_read_back_over_a2a():
    _, store, sender, base = host()
    task_id = asyncio.run(sender.send(base, message(Intent.REQUEST))).task_id
    assert asyncio.run(finish_task(store, task_id, "completed", "Overlap with InvoiceDrop.", "r9"))
    assert asyncio.run(sender.get_task(base, task_id)) == ("completed", "Overlap with InvoiceDrop.", "r9")
    assert not asyncio.run(finish_task(store, task_id, "rejected", "late"))


def test_rejected_and_canceled_tasks():
    _, store, sender, base = host()
    first = asyncio.run(sender.send(base, message(Intent.REQUEST))).task_id
    asyncio.run(finish_task(store, first, "rejected", "Sender failed verification."))
    assert asyncio.run(sender.get_task(base, first))[:2] == ("rejected", "Sender failed verification.")
    second = asyncio.run(sender.send(base, message(Intent.REQUEST, "m3"))).task_id
    assert asyncio.run(sender.cancel_task(base, second)) == "canceled"
