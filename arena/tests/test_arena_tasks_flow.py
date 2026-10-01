"""Request → task → reply → observed by the requester, with real in-process A2A."""

import asyncio

from conftest import INTEL, SOC, make_arena, make_cast

SOC_ID = "northgate-soc.northgate.example"
INTEL_ID = "halcyon-intel.halcyon-intel.example"


def decision(to, intent, body, thread_id="t1"):
    return {"action": "send", "to": to, "thread_id": thread_id, "intent": intent, "body": body}


def updates(arena):
    return [e["data"] for e in arena.bus.history if e["type"] == "task.updated"]


def created(arena):
    return [e["data"] for e in arena.bus.history if e["type"] == "task.created"]


def build(scripts):
    arena = make_arena(make_cast(SOC, INTEL, owner="northgate-soc", closer="northgate-soc"), scripts)
    asyncio.run(arena.setup())
    arena.ctx.running.set()
    return arena


def test_reply_completes_the_request_and_the_requester_observes_it():
    steps = iter([decision(INTEL_ID, "request", "Seen these domains?"), {"action": "wait"}])
    arena = build({"northgate-soc": lambda p: next(steps),
                   "halcyon-intel": lambda p: decision(SOC_ID, "reply", "Yes: InvoiceDrop.")})
    soc, intel = arena.agents["northgate-soc"], arena.agents["halcyon-intel"]
    asyncio.run(soc.tick())
    task = created(arena)[0]
    assert (task["requester"], task["recipient"]) == (SOC_ID, INTEL_ID)
    assert task["task_id"] in soc.open_requests
    asyncio.run(intel.tick())
    asyncio.run(soc.tick())
    reply_id = [e["data"]["id"] for e in arena.bus.history
                if e["type"] == "message.sent" and e["data"]["from_id"] == INTEL_ID][0]
    assert updates(arena) == [{"task_id": task["task_id"], "state": "completed",
                               "artifact": "Yes: InvoiceDrop.", "reason": "", "reply_id": reply_id}]
    assert soc.open_requests == {}


def test_decline_rejects_and_the_oldest_request_is_answered_first():
    steps = iter([decision(INTEL_ID, "request", "first"), decision(INTEL_ID, "request", "second"),
                  {"action": "wait"}])
    arena = build({"northgate-soc": lambda p: next(steps),
                   "halcyon-intel": lambda p: decision(SOC_ID, "decline", "Not sharing.")})
    soc, intel = arena.agents["northgate-soc"], arena.agents["halcyon-intel"]
    asyncio.run(soc.tick())
    asyncio.run(soc.tick())
    first, second = [t["task_id"] for t in created(arena)]
    asyncio.run(intel.tick())
    asyncio.run(soc.tick())
    assert updates(arena) == [{"task_id": first, "state": "rejected", "artifact": "",
                               "reason": "Not sharing.", "reply_id": updates(arena)[0]["reply_id"]}]
    assert list(soc.open_requests) == [second]


def test_open_task_is_canceled_when_thread_closes():
    steps = iter([decision(INTEL_ID, "request", "q"), {"action": "wait"}])
    arena = build({"northgate-soc": lambda p: next(steps)})
    soc = arena.agents["northgate-soc"]
    asyncio.run(soc.tick())
    task_id = created(arena)[0]["task_id"]
    thread = arena.ctx.threads.get("t1")
    thread.closed, thread.close_reason = True, "verdict"
    asyncio.run(soc.tick())
    assert updates(arena)[0]["task_id"] == task_id
    assert updates(arena)[0]["state"] == "canceled"


def test_completed_task_is_not_canceled_on_thread_close():
    steps = iter([decision(INTEL_ID, "request", "q"), {"action": "wait"}])
    arena = build({"northgate-soc": lambda p: next(steps),
                   "halcyon-intel": lambda p: decision(SOC_ID, "reply", "answer")})
    soc, intel = arena.agents["northgate-soc"], arena.agents["halcyon-intel"]
    asyncio.run(soc.tick())
    asyncio.run(intel.tick())
    thread = arena.ctx.threads.get("t1")
    thread.closed, thread.close_reason = True, "verdict"
    asyncio.run(soc.tick())
    assert [u["state"] for u in updates(arena)] == ["completed"]
