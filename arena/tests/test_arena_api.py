"""Arena HTTP and WebSocket API."""

import json
import time

import pytest
from conftest import SOC, make_arena, make_cast
from fastapi.testclient import TestClient

from arena.api import register_routes, slugify


def asyncio_run_setup(arena, client):
    """Run arena.setup() on the TestClient's event loop."""
    client.portal.call(arena.setup)


@pytest.fixture
def setup(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html>arena</html>")
    runs = tmp_path / "runs"
    runs.mkdir()
    arena = make_arena(make_cast(SOC, owner="northgate-soc", closer="northgate-soc"),
                       scripts={"_generator": lambda prompt: "You find mule accounts."})
    register_routes(arena, ui, runs)
    # The context manager keeps one event loop alive across requests, so the
    # replay task that POST /arena/replay starts keeps running after the response.
    with TestClient(arena.app) as client:
        yield arena, client, runs


INJECT = {"name": "Fraud Desk", "organization": "Coastal Bank",
          "domain": "coastal-bank.example", "capability": "fraud",
          "agenda": "Find mule accounts."}


def test_slugify():
    assert slugify("Fraud Desk #2") == "fraud-desk-2"
    assert slugify("!!!") == "agent"


def test_index_is_served(setup):
    _, client, _ = setup
    assert client.get("/").text == "<html>arena</html>"


def test_websocket_sends_history_then_live_events(setup):
    arena, client, _ = setup
    arena.bus.publish("arena.idle", {"reason": "test"})
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "arena.idle"
        assert ws.receive_json()["type"] == "ws.synced"
        client.post("/arena/pause")
        assert ws.receive_json()["type"] == "arena.paused"


def test_inject_agent(setup):
    arena, client, _ = setup
    response = client.post("/arena/agents", json=INJECT)
    assert response.status_code == 201
    assert response.json() == {"id": "fraud-desk.coastal-bank.example", "slug": "fraud-desk"}
    assert arena.agents["fraud-desk"].spec.system_prompt == "Find mule accounts."
    assert arena.agents["fraud-desk"].spec.cadence == (40.0, 60.0)


def test_inject_with_generated_prompt(setup):
    arena, client, _ = setup
    body = dict(INJECT, agenda="", generate=True)
    assert client.post("/arena/agents", json=body).status_code == 201
    assert arena.agents["fraud-desk"].spec.system_prompt == "You find mule accounts."


@pytest.mark.parametrize(
    "change, status",
    [
        ({"agenda": "", "generate": False}, 400),
        ({"name": "SOC Investigator", "domain": "northgate.example"}, 400),
        ({"capability": "Bad Cap"}, 422),
        ({"model": "opus"}, 422),
        ({"misconfigure": "maybe"}, 422),
    ],
)
def test_inject_rejects_bad_requests(setup, change, status):
    _, client, _ = setup
    first = client.post("/arena/agents", json=dict(INJECT, name="SOC Investigator",
                                                  domain="northgate.example"))
    assert first.status_code == 201
    assert client.post("/arena/agents", json=dict(INJECT, **change)).status_code == status


def test_logs_and_replay(setup):
    arena, client, runs = setup
    events = [{"seq": 0, "ts": 0.0, "run_id": "r1", "type": "agent.registered", "data": {}},
              {"seq": 1, "ts": 1.0, "run_id": "r1", "type": "message.sent", "data": {}}]
    (runs / "r1.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    assert client.get("/arena/logs").json() == {"logs": ["r1"]}
    assert client.post("/arena/replay", json={"log": "r1", "speed": 10}).status_code == 202
    for _ in range(100):
        if arena.bus.history[-1]["type"] == "message.sent":
            break
        time.sleep(0.02)
    assert [e["type"] for e in arena.bus.history] == [
        "bus.reset", "agent.registered", "message.sent"]
    assert client.post("/arena/replay", json={"log": "nope"}).status_code == 404
    assert client.post("/arena/replay", json={"log": "../x"}).status_code == 422


def test_new_replay_replaces_a_running_replay(setup):
    arena, client, runs = setup
    slow = [{"seq": i, "ts": float(i), "run_id": "slow", "type": "slow.event", "data": {}}
            for i in range(5)]
    fast = [{"seq": 0, "ts": 0.0, "run_id": "fast", "type": "fast.event", "data": {}}]
    (runs / "slow.jsonl").write_text("\n".join(json.dumps(e) for e in slow) + "\n")
    (runs / "fast.jsonl").write_text(json.dumps(fast[0]) + "\n")
    client.post("/arena/replay", json={"log": "slow", "speed": 1})
    client.post("/arena/replay", json={"log": "fast", "speed": 1})
    time.sleep(1.5)
    types = [e["type"] for e in arena.bus.history]
    assert types == ["bus.reset", "fast.event"]


def test_agent_list_and_detail(setup):
    arena, client, _ = setup
    asyncio_run_setup(arena, client)
    listed = client.get("/arena/agents").json()["agents"]
    assert [a["slug"] for a in listed] == ["northgate-soc"]
    assert set(listed[0]) >= {"id", "slug", "name", "organization", "domain", "capability",
                              "needs", "model", "role", "state", "counters", "verification"}
    detail = client.get("/arena/agents/northgate-soc").json()
    assert set(detail) >= {"system_prompt", "last_prompt", "last_decision", "decisions",
                           "threads", "inbox", "trust", "queries", "dns"}
    assert detail["dns"]["srv"] == "arena:8080"
    assert detail["threads"][0]["id"] == "t1"
    assert detail["inbox"] == [{"sender": "system", "intent": "seed", "trust": None,
                                "thread_id": "t1"}]
    assert client.get("/arena/agents/nobody").status_code == 404


def test_registry_proxies(setup):
    arena, client, _ = setup
    asyncio_run_setup(arena, client)
    entries = client.get("/arena/registry").json()["agents"]
    assert entries[0]["verification"]["status"] == "verified"
    card = client.get("/arena/registry/agents/northgate-soc.northgate.example/card")
    assert card.json()["name"] == "SOC Investigator"
    assert client.get("/arena/registry/agents/nobody.example/card").status_code == 404
    assert client.get("/arena/registry/orgs").json()["orgs"][0]["organization"] == \
        "Northgate Bank"


def test_registry_proxy_returns_502_when_unreachable(setup):
    arena, client, _ = setup

    async def down(path):
        from arena.acdp import AcdpError
        raise AcdpError("registry unreachable: connection refused")

    arena.ctx.acdp.registry_get = down
    response = client.get("/arena/registry")
    assert response.status_code == 502
    assert "registry unreachable" in response.json()["error"]


def test_injected_agent_defaults_to_provider_sector(setup):
    arena, client, _ = setup
    assert client.post("/arena/agents", json=INJECT).status_code == 201
    registered = [e["data"] for e in arena.bus.history if e["type"] == "agent.registered"]
    assert registered[-1]["sector"] == "provider"
    body = dict(INJECT, name="Member Desk", sector="member")
    assert client.post("/arena/agents", json=body).status_code == 201
    assert [e["data"] for e in arena.bus.history
            if e["type"] == "agent.registered"][-1]["sector"] == "member"
    bad = dict(INJECT, name="Bad", sector="x")
    assert client.post("/arena/agents", json=bad).status_code == 422
