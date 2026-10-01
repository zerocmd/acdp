"""Registry API tests (Flask test client, no network)."""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as registry_app  # noqa: E402

CARD = {
    "name": "Agent Delta",
    "url": "http://agent3:8000/",
    "protocolVersion": "0.3.0",
    "skills": [{"id": "threat_detection", "name": "Threat Detection", "tags": ["threat_detection"]}],
}


def agent(agent_id="agent3.agents.local", **overrides):
    data = {
        "id": agent_id,
        "name": "Agent Delta",
        "description": "Security analysis",
        "capabilities": ["security", "log_analysis"],
        "interfaces": {"rest": "http://agent3:8000", "a2a": "http://agent3:8000/"},
        "protocols": ["a2a/0.3", "rest-json"],
        "model_info": {"provider": "Anthropic"},
        "a2a": {"url": "http://agent3:8000/", "skills": ["security", "log_analysis"]},
        "agent_card": CARD,
    }
    data.update(overrides)
    return data


@pytest.fixture
def client(monkeypatch):
    registry_app.agents.clear()
    registry_app.orgs.clear()
    monkeypatch.setattr(registry_app, "fetch_card", lambda url: None)
    monkeypatch.setattr(registry_app, "lookup_txt", lambda name: None)
    registry_app.app.config["TESTING"] = True
    return registry_app.app.test_client()


def test_register_stores_card_and_list_omits_it(client):
    assert client.post("/registerAgent", json=agent()).status_code == 200
    listed = client.get("/agents").get_json()["agents"]
    assert len(listed) == 1
    assert "agent_card" not in listed[0]
    assert listed[0]["status"] == "online"
    assert client.get("/agents/agent3.agents.local/card").get_json() == CARD


def test_acdp_1_0_registration_without_card_still_works(client):
    legacy = agent("agent0.agents.local", protocols=["rest-json"])
    del legacy["agent_card"], legacy["a2a"]
    assert client.post("/registerAgent", json=legacy).status_code == 200
    assert client.get("/agents/agent0.agents.local/card").status_code == 404


@pytest.mark.parametrize(
    "bad, message",
    [
        (agent("Bad Id!"), "DNS-style"),
        (agent(capabilities="security"), "capabilities must be a list"),
        (agent(agent_card={"name": "x"}), "supportedInterfaces"),
    ],
)
def test_register_rejects_malformed_entries(client, bad, message):
    response = client.post("/registerAgent", json=bad)
    assert response.status_code == 400
    assert message in response.get_json()["error"]


def test_filters_by_capability_skill_protocol_and_status(client):
    client.post("/registerAgent", json=agent())
    legacy = agent("agent0.agents.local", capabilities=["chat"], protocols=["rest-json"])
    del legacy["agent_card"], legacy["a2a"]
    client.post("/registerAgent", json=legacy)

    ids = lambda qs: [a["id"] for a in client.get(f"/agents?{qs}").get_json()["agents"]]  # noqa: E731
    assert ids("capability=log_analysis") == ["agent3.agents.local"]
    # A2A skill ids are searchable as capabilities too
    assert ids("capability=threat_detection") == ["agent3.agents.local"]
    assert ids("skill=threat_detection") == ["agent3.agents.local"]
    assert ids("protocol=a2a") == ["agent3.agents.local"]
    assert sorted(ids("protocol=rest-json")) == ["agent0.agents.local", "agent3.agents.local"]

    registry_app.agents["agent0.agents.local"]["last_update"] = time.time() - 3600
    assert ids("status=online") == ["agent3.agents.local"]
    assert ids("status=stale") == ["agent0.agents.local"]


def test_registration_keeps_registered_at_across_updates(client):
    client.post("/registerAgent", json=agent())
    first = registry_app.agents["agent3.agents.local"]["registered_at"]
    client.post("/registerAgent", json=agent())
    assert registry_app.agents["agent3.agents.local"]["registered_at"] == first


def test_well_known_registry_descriptor(client):
    body = client.get("/.well-known/agent-registry").get_json()
    [reg] = body["registries"]
    assert reg["endpoints"]["agent_card"] == "/agents/{id}/card"


def test_agent_base_url_resolution():
    assert registry_app._agent_base_url("a.agents.local", {"interfaces": {"rest": "http://agent0:8000/v1"}}) == "http://agent0:8000"
    assert registry_app._agent_base_url("agent4.agents.local", {}) == "http://agent4:8000"


def test_dashboard_renders_protocols_and_card_link(client):
    client.post("/registerAgent", json=agent())
    html = client.get("/").get_data(as_text=True)
    assert "a2a/0.3, rest-json" in html
    assert 'href="/agents/agent3.agents.local/card"' in html
