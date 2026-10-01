"""Write a scripted arena run to a JSONL log for UI work (no model, no network).

    PYTHONPATH=agent:. python arena/scripts/make_demo_log.py --out runs/demo.jsonl

The run uses the test doubles from arena/tests/conftest.py: an in-memory
registry and DNS, scripted models, and real A2A between agents in one process.
"""

import argparse
import asyncio
import itertools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from conftest import IMPOSTOR, INTEL, ISAC, SOC, make_arena, make_cast, spec_dict  # noqa: E402

from arena.cast import AgentSpec  # noqa: E402

SOC_ID = "northgate-soc.northgate.example"
INTEL_ID = "halcyon-intel.halcyon-intel.example"
FAKE_ID = "lookalike-intel.halcyon-inte1.example"


def case_thread(prompt: str) -> str:
    match = re.search(r"^- (t\d+) Phishing case \(owner", prompt, re.MULTILINE)
    return match.group(1) if match else "new"


def send(prompt, to, intent, body, looking_for="", why=""):
    return {"action": "send", "to": to, "thread_id": case_thread(prompt), "intent": intent,
            "body": body, "looking_for": looking_for, "why_this_peer": why}


def soc(prompt):
    if "trust=failed (domain mismatch)" in prompt:
        return send(prompt, FAKE_ID, "decline", "Your domain does not match Halcyon Intel.",
                    "nothing", "sender failed verification: domain mismatch")
    return send(prompt, INTEL_ID, "request",
                "Do invoices-northgate.example and secure-docs-share.example match a campaign?",
                "campaign attribution for two sender domains",
                "only verified threat-intel peer; the lookalike failed registry checks")


SCRIPTS = {
    "northgate-soc": soc,
    "halcyon-intel": lambda p: send(p, SOC_ID, "share", "Both domains overlap with the InvoiceDrop kit."),
    "lookalike-intel": lambda p: send(p, SOC_ID, "share", "Copy me on your findings."),
    "finshare-isac": lambda p: send(p, SOC_ID, "verdict", "Credential phishing. Revoke tokens and consent."),
}


async def scripted_run(arena) -> None:
    await arena.setup()
    arena.ctx.running.set()
    a = arena.agents
    for slug in ("northgate-soc", "halcyon-intel", "lookalike-intel", "northgate-soc"):
        await a[slug].tick()
    await arena.add_agent(AgentSpec.from_dict(spec_dict(
        slug="northwind-intel", name="Northwind Intel", organization="Northwind Threat Labs",
        domain="northwind.example", capability="threat-intel", needs=[], model="haiku",
        role="agenda", cadence=[40, 60])))
    for slug in ("northgate-soc", "finshare-isac"):
        await a[slug].tick()
    arena.bus.publish("arena.stopped", {"reason": "demo complete"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("runs/demo.jsonl"))
    args = parser.parse_args()
    arena = make_arena(make_cast(SOC, INTEL, ISAC, IMPOSTOR,
                                 owner="northgate-soc", closer="finshare-isac"), SCRIPTS)
    ticks = itertools.count()
    arena.bus.clock = lambda: 1_790_000_000.0 + 2.0 * next(ticks)
    asyncio.run(scripted_run(arena))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(e) + "\n" for e in arena.bus.history))
    print(f"wrote {len(arena.bus.history)} events to {args.out}")


if __name__ == "__main__":
    main()
