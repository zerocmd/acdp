"""Write a scripted arena run to a JSONL log for UI work (no model, no network).

    PYTHONPATH=agent:. python arena/scripts/make_demo_log.py --out runs/demo.jsonl

The run uses the full cast (arena/cast.yaml) with the test doubles from
arena/tests/conftest.py: an in-memory registry and DNS, scripted models, and real
A2A between agents in one process. Five scenarios run; the other agents wait.
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from conftest import make_arena, spec_dict  # noqa: E402

from arena.cast import AgentSpec, load_cast  # noqa: E402

ID = {slug: f"{slug}.{domain}" for slug, domain in [
    ("northgate-soc", "northgate.example"), ("halcyon-intel", "halcyon-intel.example"),
    ("lookalike-intel", "halcyon-inte1.example"), ("finshare-isac", "finshare-isac.example"),
    ("northgate-procurement", "northgate.example"), ("coastline-sales", "coastlinemdr.example"),
    ("coastline-impostor", "coastline-mdr.example"), ("meridian-ciso", "meridian-cu.example"),
    ("ironclad-ir", "ironclad-ir.example"), ("pinecrest-soc", "pinecrest.example"),
    ("finshare-sharing", "finshare-isac.example"), ("harborview-soc", "harborview.example"),
]}


def thread(prompt: str, title: str) -> str:
    """Id of the open thread whose title starts with `title`, else "new"."""
    match = re.search(rf"^- (t\d+) {re.escape(title)}", prompt, re.MULTILINE)
    return match.group(1) if match else "new"


def send(to, thread_id, intent, body, looking_for="", why=""):
    return {"action": "send", "to": ID[to], "thread_id": thread_id, "intent": intent,
            "body": body, "looking_for": looking_for, "why_this_peer": why}


def steps(*decisions):
    """A script that returns each decision in turn, then waits."""
    queue = list(decisions)
    return lambda prompt: queue.pop(0)(prompt) if queue else {"action": "wait"}


PHISH = "Credential phishing"
RANSOM = "Ransomware on Meridian"
QUOTE = "Quote for managed detection"
IOC = "IOC batch"

SCRIPTS = {
    "northgate-soc": steps(
        lambda p: send("halcyon-intel", thread(p, PHISH), "request",
                       "Do invoices-northgate.example and secure-docs-share.example match a campaign?",
                       "campaign attribution for two sender domains",
                       "only verified threat-intel peer; the lookalike failed registry checks"),
        lambda p: send("lookalike-intel", thread(p, PHISH), "decline",
                       "Your domain does not match Halcyon Intel.", "nothing",
                       "sender failed verification: domain mismatch"),
    ),
    "halcyon-intel": steps(lambda p: send("northgate-soc", thread(p, PHISH), "reply",
                                          "Both domains overlap with the InvoiceDrop kit seen since August.")),
    "lookalike-intel": steps(lambda p: send("northgate-soc", thread(p, PHISH), "share",
                                            "Copy me on your findings for attribution.")),
    "finshare-isac": steps(lambda p: send("northgate-soc", thread(p, PHISH), "verdict",
                                          "Credential phishing by InvoiceDrop. Revoke tokens and the OAuth consent.")),
    "northgate-procurement": steps(
        lambda p: send("coastline-sales", "new", "request",
                       f"{QUOTE}: 12 months, 2,000 endpoints?", "an MDR quote",
                       "verified MDR vendor in the registry"),
        lambda p: send("coastline-impostor", thread(p, QUOTE), "decline",
                       "Your domain is not Coastline MDR's registered domain.", "nothing",
                       "sender failed verification: domain mismatch"),
    ),
    "coastline-sales": steps(lambda p: send("northgate-procurement", thread(p, QUOTE), "reply",
                                            "12 months, 2,000 endpoints: $184,000. 15-minute response SLA.")),
    "coastline-impostor": steps(lambda p: send("northgate-procurement", thread(p, QUOTE), "share",
                                               "Coastline here: 40% off if you send the PO today.")),
    "meridian-ciso": steps(lambda p: send("ironclad-ir", thread(p, RANSOM), "request",
                                          "Ransomware on our file servers. Can you scope and contain?",
                                          "incident response engagement", "verified IR firm")),
    "ironclad-ir": steps(
        lambda p: send("meridian-ciso", thread(p, RANSOM), "reply",
                       "Engaged. Isolate the file servers and disable the domain admin account."),
        lambda p: send("meridian-ciso", thread(p, RANSOM), "verdict",
                       "Scope: 3 servers, 1 admin account. Contained. Restore from the two clean shares."),
    ),
    "pinecrest-soc": steps(lambda p: send("finshare-sharing", "new", "share",
                                          f"{IOC}: 3 phishing domains seen at Pinecrest today.",
                                          "peer confirmation", "the ISAC sharing desk relays to members")),
    "finshare-sharing": steps(lambda p: send("harborview-soc", thread(p, IOC), "share",
                                             "Relaying 3 phishing domains from a member bank.")),
}

ORDER = ["northgate-soc", "halcyon-intel", "northgate-procurement", "coastline-sales",
         "meridian-ciso", "ironclad-ir", "lookalike-intel", "coastline-impostor",
         "northgate-soc", "northgate-procurement", "pinecrest-soc", "finshare-sharing",
         "finshare-isac", "ironclad-ir"]


class Clock:
    """0.5 s per event during setup, 3 s per event while agents talk."""

    def __init__(self) -> None:
        self.t = 1_790_000_000.0
        self.step = 0.5

    def __call__(self) -> float:
        self.t += self.step
        return self.t


async def scripted_run(arena, clock) -> None:
    await arena.setup()
    clock.step = 3.0
    arena.ctx.running.set()
    for slug in ORDER[:12]:
        await arena.agents[slug].tick()
    await arena.add_agent(AgentSpec.from_dict(spec_dict(
        slug="northwind-intel", name="Northwind Intel", organization="Northwind Threat Labs",
        domain="northwind.example", capability="threat-intel", needs=[], model="haiku",
        role="agenda", cadence=[60, 90], sector="provider")))
    for slug in ORDER[12:]:
        await arena.agents[slug].tick()
    arena.bus.publish("arena.stopped", {"reason": "demo complete"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("runs/demo.jsonl"))
    args = parser.parse_args()
    arena = make_arena(load_cast(), SCRIPTS)
    clock = Clock()
    arena.bus.clock = clock
    asyncio.run(scripted_run(arena, clock))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(e) + "\n" for e in arena.bus.history))
    print(f"wrote {len(arena.bus.history)} events to {args.out}")


if __name__ == "__main__":
    main()
