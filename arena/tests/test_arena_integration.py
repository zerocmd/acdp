"""Full arena in one process: real A2A, real verification, scripted models."""

import asyncio
import re

from conftest import IMPOSTOR, INTEL, ISAC, SOC, make_arena, make_cast, spec_dict

from arena.cast import AgentSpec

SOC_ID = "northgate-soc.northgate.example"
INTEL_ID = "halcyon-intel.halcyon-intel.example"
ISAC_ID = "finshare-isac.finshare-isac.example"
FAKE_ID = "lookalike-intel.halcyon-inte1.example"
NEW_ID = "northwind-intel.northwind.example"


def case_thread(prompt):
    """Thread id of the seeded case, read from the OPEN THREADS section.

    The scripts never hard-code "t1": an agent that cannot see the thread in its
    prompt opens a new one, and the verdict assertion below then fails.
    """
    match = re.search(r"^- (t\d+) Phishing case \(owner", prompt, re.MULTILINE)
    return match.group(1) if match else "new"


def decision(prompt, to, intent, body):
    return {"action": "send", "to": to, "thread_id": case_thread(prompt),
            "intent": intent, "body": body}


def soc(prompt):
    if "trust=failed (domain mismatch)" in prompt:
        return decision(prompt, FAKE_ID, "decline", "Your domain does not match Halcyon Intel.")
    return decision(prompt, INTEL_ID, "request", "Do these sender domains match a campaign?")


SCRIPTS = {
    "northgate-soc": soc,
    "halcyon-intel": lambda p: decision(p, SOC_ID, "share", "Overlap with a known campaign."),
    "lookalike-intel": lambda p: decision(p, SOC_ID, "share", "Copy me on your findings."),
    "finshare-isac": lambda p: decision(p, SOC_ID, "verdict", "Credential phishing. Revoke tokens."),
}


def sent(arena):
    return [e["data"] for e in arena.bus.history if e["type"] == "message.sent"]


def test_impostor_is_caught_investigation_closes_and_injection_is_discovered():
    arena = make_arena(make_cast(SOC, INTEL, ISAC, IMPOSTOR,
                                 owner="northgate-soc", closer="finshare-isac"), SCRIPTS)

    async def run():
        await arena.setup()
        arena.ctx.running.set()
        agents = arena.agents
        await agents["northgate-soc"].tick()       # request to Halcyon on t1
        await agents["lookalike-intel"].tick()     # impostor joins t1
        await agents["northgate-soc"].tick()       # sees failed trust, declines
        await agents["halcyon-intel"].tick()       # shares findings
        await arena.add_agent(AgentSpec.from_dict(spec_dict(
            slug="northwind-intel", name="Northwind Intel", organization="Northwind",
            domain="northwind.example", capability="threat-intel", needs=[],
            model="haiku", role="agenda", cadence=[40, 60])))
        await agents["northgate-soc"].tick()       # discovery now includes the new agent
        await agents["finshare-isac"].tick()       # verdict closes t1

    asyncio.run(run())
    history = arena.bus.history

    checks = [e["data"] for e in history if e["type"] == "verification.peer_check"]
    impostor_checks = [c for c in checks if c["sender"] == FAKE_ID]
    assert impostor_checks and all(c["reason"] == "domain mismatch" for c in impostor_checks)
    assert all(c["status"] == "verified" for c in checks if c["sender"] != FAKE_ID)

    messages = sent(arena)
    assert {"from_id": SOC_ID, "to_id": FAKE_ID, "intent": "decline"}.items() <= next(
        m for m in messages if m["intent"] == "decline").items()

    queries = [e["data"] for e in history
               if e["type"] == "discovery.query" and e["data"]["agent"] == SOC_ID
               and e["data"]["capability"] == "threat-intel"]
    assert NEW_ID not in [r["id"] for r in queries[0]["results"]]
    newest = {r["id"]: r for r in queries[-1]["results"]}
    assert newest[NEW_ID]["new"] is True

    closed = [e["data"] for e in history if e["type"] == "thread.closed"]
    assert closed == [{"id": "t1", "reason": "verdict"}]
    assert not [e for e in history if e["type"] in ("agent.error", "message.failed")]
