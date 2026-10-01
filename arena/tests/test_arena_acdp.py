"""Arena card, registration payload, and ACDP client."""

import asyncio
import json

import httpx
import pytest
import requests

from arena.acdp import AcdpClient, AcdpError
from arena.card import agent_base_url, build_card, card_path, registration_payload
from arena.cast import AgentSpec
from arena.identity import Identity
from runtime.a2a_card import card_acdp_params

BASE = "http://arena:8080"
SPEC = AgentSpec.from_dict({
    "slug": "halcyon-intel", "name": "Threat Intel Analyst",
    "organization": "Halcyon Intel", "domain": "halcyon-intel.example",
    "capability": "threat-intel", "description": "Threat intelligence",
    "needs": ["soc-investigation"], "model": "sonnet", "role": "investigation",
    "cadence": [15, 20], "system_prompt": "p",
})


def test_card_points_at_mounted_path_and_carries_identity():
    ident = Identity(SPEC.slug, SPEC.domain)
    card = build_card(SPEC, ident, BASE)
    assert card.url == "http://arena:8080/agents/halcyon-intel/"
    params = card_acdp_params(card.model_dump(mode="json", exclude_none=True))
    assert params["id"] == "halcyon-intel.halcyon-intel.example"
    assert params["did"] == ident.did
    assert params["organization"] == "Halcyon Intel"
    assert params["domain"] == "halcyon-intel.example"
    assert params["publicKeyJwk"] == ident.public_jwk()
    assert params["model"] == "claude-sonnet-5-5"


def test_registration_payload():
    ident = Identity(SPEC.slug, SPEC.domain)
    card = build_card(SPEC, ident, BASE)
    payload = registration_payload(SPEC, ident, BASE, card)
    assert payload["id"] == ident.agent_id
    assert payload["capabilities"] == ["threat-intel"]
    assert payload["a2a"]["card_url"] == (
        "http://arena:8080/agents/halcyon-intel/.well-known/agent-card.json"
    )
    assert payload["agent_card"]["name"] == "Threat Intel Analyst"
    assert payload["organization"] == "Halcyon Intel"
    assert agent_base_url(BASE, "x") == "http://arena:8080/agents/x/"
    assert card_path("x") == "/agents/x/.well-known/agent-card.json"


class FakeRegistry:
    def __init__(self, failures=0):
        self.failures = failures
        self.payloads = []

    def register_agent(self, payload):
        if self.failures:
            self.failures -= 1
            raise requests.ConnectionError("down")
        self.payloads.append(payload)
        return {"status": "success", "agent": dict(payload, verification={"status": "verified"})}

    def get_agents(self, capability=None):
        return {"agents": [{"id": "a", "capabilities": [capability]}]}

    def get_org(self, organization):
        return {"organization": organization, "canonical_domain": "x.example"}


class FakeResolver:
    def resolve_agent(self, agent_id):
        return {"id": agent_id, "key": "k"}


def dns_api(requests_seen, status=200, body=None):
    def handler(request):
        requests_seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(status, json=body or {"status": "success", "result": "created"})

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def no_sleep(seconds):
    return None


def client(seen, registry=None, **kw):
    return AcdpClient("http://bind:8053", registry or FakeRegistry(), FakeResolver(),
                      dns_api(seen, **kw), sleep=no_sleep)


def test_create_zone_and_publish_dns():
    seen = []
    acdp = client(seen)
    assert asyncio.run(acdp.create_zone("halcyon-intel.example")) == "created"
    asyncio.run(acdp.publish_dns(
        agent_id="halcyon-intel.halcyon-intel.example", host="arena", port=8080,
        capability="threat-intel", description="Threat intelligence",
        card_path="/agents/halcyon-intel/.well-known/agent-card.json", key="k" * 43,
    ))
    assert seen[0] == ("/zones", {"zone": "halcyon-intel.example"})
    path, body = seen[1]
    assert path == "/update_dns"
    assert body["domain"] == "halcyon-intel.halcyon-intel.example"
    assert body["key"] == "k" * 43
    assert body["a2a"] == "/agents/halcyon-intel/.well-known/agent-card.json"


def test_dns_api_error_message_is_raised():
    seen = []
    acdp = client(seen, status=400, body={"status": "error", "message": "zone must end with"})
    with pytest.raises(AcdpError, match="zone must end with"):
        asyncio.run(acdp.create_zone("evil.com"))


def test_register_retries_then_returns_entry():
    registry = FakeRegistry(failures=2)
    entry = asyncio.run(client([], registry).register({"id": "a"}))
    assert entry["verification"]["status"] == "verified"
    assert len(registry.payloads) == 1


def test_register_gives_up_with_acdp_error():
    with pytest.raises(AcdpError, match="registry unreachable"):
        asyncio.run(client([], FakeRegistry(failures=9)).register({"id": "a"}))


def test_lookups():
    acdp = client([])
    assert asyncio.run(acdp.find("threat-intel"))[0]["id"] == "a"
    assert asyncio.run(acdp.org("Halcyon Intel"))["canonical_domain"] == "x.example"
    assert asyncio.run(acdp.dns_agent("a.x.example"))["key"] == "k"


def test_dns_api_connection_errors_are_retried_but_400_is_not():
    attempts = []

    def flaky(request):
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectError("not up yet", request=request)
        return httpx.Response(200, json={"status": "success", "result": "created"})

    acdp = AcdpClient("http://bind:8053", FakeRegistry(), FakeResolver(),
                      lambda: httpx.AsyncClient(transport=httpx.MockTransport(flaky)),
                      sleep=no_sleep)
    assert asyncio.run(acdp.create_zone("x.example")) == "created"
    assert len(attempts) == 3

    seen = []
    refused = client(seen, status=400, body={"status": "error", "message": "bad zone"})
    with pytest.raises(AcdpError, match="bad zone"):
        asyncio.run(refused.create_zone("evil.com"))
    assert len(seen) == 1


def test_registry_get_returns_status_and_body_or_raises():
    def handler(request):
        if request.url.path == "/agents":
            return httpx.Response(200, json={"agents": []})
        return httpx.Response(404, json={"error": "Agent not found"})

    acdp = AcdpClient("http://bind:8053", FakeRegistry(), FakeResolver(),
                      lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                      sleep=no_sleep, registry_url="http://registry:5000")
    assert asyncio.run(acdp.registry_get("/agents")) == (200, {"agents": []})
    assert asyncio.run(acdp.registry_get("/agents/x/card"))[0] == 404

    def down(request):
        raise httpx.ConnectError("down", request=request)

    broken = AcdpClient("http://bind:8053", FakeRegistry(), FakeResolver(),
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(down)),
                        sleep=no_sleep, registry_url="http://registry:5000")
    with pytest.raises(AcdpError, match="registry unreachable"):
        asyncio.run(broken.registry_get("/agents"))
