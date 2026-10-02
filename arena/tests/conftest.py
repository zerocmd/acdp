"""Arena test fixtures: scripted model, fake ACDP services, fake sender.

Nothing here touches the network or an LLM.
"""

import asyncio
import json
import random
import re
from typing import Any, Callable, Dict, List, Optional

from strands.models import Model

from arena.agent import ArenaContext
from arena.bus import EventBus
from arena.identity import fingerprint_jwk
from arena.rate import RunGuard, TokenBucket
from arena.threads import ThreadRegistry
from arena.transport import SendError, SendResult
from arena.verify import VERIFIED
from runtime.a2a_card import card_acdp_params


def first_user_text(messages: List[Dict[str, Any]]) -> str:
    for message in messages:
        if message["role"] == "user":
            for block in message["content"]:
                if "text" in block:
                    return block["text"]
    return ""


class ScriptedModel(Model):
    """Strands model driven by script(prompt_text).

    The script returns a dict (TurnDecision input, sent as the structured-output
    tool call), a str (plain text reply), or raises.
    """

    def __init__(self, script: Callable[[str], Any]):
        self.script = script
        self.calls = 0

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> Dict[str, Any]:
        return {"model_id": "scripted"}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls += 1
        action = self.script(first_user_text(messages))
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(action, dict):
            yield {"contentBlockStart": {"start": {"toolUse": {
                "toolUseId": f"tooluse_{self.calls}", "name": "TurnDecision"}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(action)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": str(action)}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


class FakeAcdp:
    """In-memory registry, DNS API, and resolver with the real verification rules."""

    def __init__(self, bad_zone_suffix: str = ".invalid"):
        self.zones: set = set()
        self.dns: Dict[str, Dict[str, Any]] = {}
        self.entries: Dict[str, Dict[str, Any]] = {}
        self.orgs: Dict[str, Dict[str, str]] = {}
        self.bad_zone_suffix = bad_zone_suffix

    async def create_zone(self, zone: str) -> str:
        from arena.acdp import AcdpError

        if zone.endswith(self.bad_zone_suffix):
            raise AcdpError("zone must end with an allowed suffix")
        if zone in self.zones:
            return "exists"
        self.zones.add(zone)
        return "created"

    async def publish_dns(self, *, agent_id, host, port, capability, description,
                          card_path, key) -> None:
        self.dns[agent_id] = {"id": agent_id, "key": key, "capabilities": [capability]}

    async def register(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        params = card_acdp_params(payload["agent_card"])
        org = self.orgs.setdefault(normalize(params["organization"]), {
            "organization": params["organization"], "canonical_domain": params["domain"]})
        dns = self.dns.get(payload["id"])
        reasons = []
        if dns is None:
            reasons.append("txt record missing")
        elif dns["key"] != fingerprint_jwk(params["publicKeyJwk"]):
            reasons.append("key mismatch")
        if org["canonical_domain"] != params["domain"]:
            reasons.append(f"organization registered under {org['canonical_domain']}")
        entry = dict(payload, verification={
            "status": "failed" if reasons else "verified", "reasons": reasons})
        self.entries[payload["id"]] = entry
        return entry

    async def find(self, capability: str) -> List[Dict[str, Any]]:
        return [dict(e) for e in self.entries.values() if capability in e["capabilities"]]

    async def org(self, organization: str) -> Optional[Dict[str, str]]:
        return self.orgs.get(normalize(organization))

    async def dns_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self.dns.get(agent_id)

    async def registry_get(self, path: str):
        if path == "/agents":
            return 200, {"agents": [
                {k: v for k, v in e.items() if k != "agent_card"}
                for e in self.entries.values()]}
        if path == "/orgs":
            return 200, {"orgs": sorted(self.orgs.values(),
                                        key=lambda o: o["organization"].lower())}
        if path.startswith("/agents/") and path.endswith("/card"):
            entry = self.entries.get(path[len("/agents/"):-len("/card")])
            if entry is None:
                return 404, {"error": "Agent not found"}
            return 200, entry["agent_card"]
        return 404, {"error": "not found"}


class FakeSender:
    """Records sends. failures = number of SendError raises before success."""

    def __init__(self, failures: int = 0):
        self.failures = failures
        self.sent: List[Any] = []

    async def send(self, base_url, message):
        if self.failures:
            self.failures -= 1
            raise SendError("peer down")
        self.sent.append((base_url, message))
        return SendResult(f"ack {message.id} verified", None)

    async def get_task(self, base_url, task_id):
        return "working", "", ""

    async def cancel_task(self, base_url, task_id):
        return "canceled"


class FixedVerifier:
    def __init__(self, trust=VERIFIED):
        self.trust = trust

    async def check(self, message):
        return self.trust


async def no_sleep(seconds):
    await asyncio.sleep(0)


def make_ctx(acdp=None, sender=None, verifier=None, rate_per_min=100) -> ArenaContext:
    return ArenaContext(
        bus=EventBus("test"),
        threads=ThreadRegistry(),
        bucket=TokenBucket(rate_per_min),
        guard=RunGuard(max_minutes=60, max_calls=1000),
        acdp=acdp or FakeAcdp(),
        verifier=verifier or FixedVerifier(),
        sender=sender or FakeSender(),
        rng=random.Random(1),
        sleep=no_sleep,
    )


def spec_dict(**change) -> Dict[str, Any]:
    data = {
        "slug": "northgate-soc", "name": "SOC Investigator",
        "organization": "Northgate Bank", "domain": "northgate.example",
        "capability": "soc-investigation", "description": "Investigator",
        "needs": ["threat-intel"], "model": "sonnet", "role": "investigation",
        "cadence": [15, 20], "system_prompt": "You lead the investigation.",
    }
    data.update(change)
    return data


from arena.cast import AgentSpec, Cast, Seed  # noqa: E402


def make_cast(*specs: Dict[str, Any], owner: str, closer: str) -> Cast:
    return Cast(
        seeds=[Seed(owner=owner, closer=closer, title="Phishing case", brief="Brief.")],
        agents=[AgentSpec.from_dict(spec_dict(**s)) for s in specs],
    )


SOC = dict(slug="northgate-soc")
INTEL = dict(slug="halcyon-intel", name="Threat Intel Analyst", organization="Halcyon Intel",
             domain="halcyon-intel.example", capability="threat-intel",
             needs=["soc-investigation"])
ISAC = dict(slug="finshare-isac", name="ISAC Coordinator", organization="FinShare ISAC",
            domain="finshare-isac.example", capability="coordination",
            needs=["soc-investigation", "threat-intel"])
IMPOSTOR = dict(slug="lookalike-intel", name="Threat Intel Analyst",
                organization="Halcyon Intel", domain="halcyon-inte1.example",
                capability="threat-intel", needs=["soc-investigation"], model="haiku",
                role="impostor", cadence=[120, 180])


def make_arena(cast: Cast, scripts: Optional[Dict[str, Callable]] = None, settings=None):
    """Arena wired to FakeAcdp, scripted models, and in-process HTTP."""
    import httpx

    from arena.host import Arena, Settings

    scripts = scripts or {}
    holder: Dict[str, Any] = {}
    arena = Arena(
        cast,
        acdp=FakeAcdp(),
        http_factory=lambda: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=holder["app"]), timeout=10
        ),
        model_factory=lambda tier, slug: ScriptedModel(
            scripts.get(slug, lambda prompt: {"action": "wait"})
        ),
        settings=settings or Settings(guard_interval=0.01),
        bus=EventBus("test"),
    )
    holder["app"] = arena.app
    arena.ctx.sleep = no_sleep
    arena.ctx.retry_delay = 0
    return arena
