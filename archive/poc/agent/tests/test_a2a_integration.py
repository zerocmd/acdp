"""End-to-end behaviour of ACDP nodes talking A2A, with a scripted model."""

import asyncio
import uuid

import pytest
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, TextPart
from fastapi.testclient import TestClient

from conftest import ScriptedModel, first_user_text, make_config, tool_results
from runtime.delegation import ACDP_EXTENSION_URI, DelegationState
from runtime.peer_client import PeerCallError, extract_text


def echo_script(prefix):
    def script(messages):
        return ("text", f"{prefix}: {first_user_text(messages)}")

    return script


def delegate_once(target_id, question="What does the specialist think?"):
    """Ask ``target_id`` on the first turn, then answer with its tool result."""

    def script(messages):
        results = tool_results(messages)
        if results:
            return ("text", "Final answer. " + " | ".join(results))
        return ("tools", [("ask_agent", {"agent_id": target_id, "question": question})])

    return script


def test_agent_card_maps_acdp_metadata(network):
    node = network.add(make_config("agent-b", "Agent Beta", ["log_analysis", "threat_detection"]), echo_script("B"))
    client = TestClient(network.apps["agent-b"])

    card = client.get("/.well-known/agent-card.json").json()
    assert card["name"] == "Agent Beta"
    assert card["url"] == "http://agent-b:8000/"
    assert card["protocolVersion"] == "0.3.0"
    assert card["preferredTransport"] == "JSONRPC"
    assert [s["id"] for s in card["skills"]] == ["log_analysis", "threat_detection"]
    [ext] = card["capabilities"]["extensions"]
    assert ext["uri"] == ACDP_EXTENSION_URI
    assert ext["params"]["id"] == node.id
    assert ext["params"]["dns_srv"] == "_llm-agent._tcp.agent-b.agents.local"
    assert "securitySchemes" not in card

    metadata = client.get("/metadata").json()
    assert metadata["a2a"]["card_url"] == "http://agent-b:8000/.well-known/agent-card.json"
    assert metadata["a2a"]["skills"] == ["log_analysis", "threat_detection"]
    assert "a2a/0.3" in metadata["protocols"]


def test_plain_a2a_client_can_call_an_acdp_agent(network):
    network.add(make_config("agent-b", "Agent Beta", ["log_analysis"]), echo_script("B"))

    async def call():
        async with network.client_factory()() as http:
            card = await A2ACardResolver(http, "http://agent-b:8000/").get_agent_card()
            client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card)
            message = Message(
                role=Role.user,
                message_id=str(uuid.uuid4()),
                parts=[Part(root=TextPart(text="hello over A2A"))],
            )
            final = None
            async for event in client.send_message(message):
                final = event
            return extract_text(final)

    text, state = asyncio.run(call())
    assert text == "B: hello over A2A"
    assert state == "completed"


def test_chat_delegates_over_a2a_and_blocks_cycles(network):
    a = network.add(make_config("agent-a", "Agent Alpha", ["chat"]), None)
    b = network.add(make_config("agent-b", "Agent Beta", ["log_analysis"]), None)
    # A asks B; B tries to ask A back. The delegation trace carried in the A2A message
    # metadata must make B's tool refuse the cycle.
    a.runtime._model_factory = lambda: ScriptedModel(delegate_once(b.id))
    b.runtime._model_factory = lambda: ScriptedModel(delegate_once(a.id, "Back to you?"))
    a.peer_manager.add_peer(b.id, b.to_dict())

    response = TestClient(network.apps["agent-a"]).post(
        "/chat", json={"text": "Is this login pattern suspicious?", "session_id": "s1"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "Agent Beta (agent-b.agents.local, via a2a) answered" in body["response"]
    assert "already part of this delegation chain" in body["response"]
    assert body["meta"] == {
        "collaborative": True,
        "peer_count": 1,
        "peers": ["Agent Beta"],
        "transports": ["a2a"],
    }
    assert body["memory_recorded"] is True
    assert a.peer_manager.health_of(b.id) == "healthy"


def test_depth_limit_stops_long_chains(network):
    cfg = lambda svc, name: make_config(svc, name, ["chat"], max_depth=1)  # noqa: E731
    a = network.add(cfg("agent-a", "Agent Alpha"), None)
    b = network.add(cfg("agent-b", "Agent Beta"), None)
    c = network.add(cfg("agent-c", "Agent Gamma"), echo_script("C"))

    a.runtime._model_factory = lambda: ScriptedModel(delegate_once(b.id))
    b.runtime._model_factory = lambda: ScriptedModel(delegate_once(c.id))

    body = TestClient(network.apps["agent-a"]).post("/chat", json={"text": "go"}).json()
    assert "maximum delegation depth (1) reached" in body["response"]
    assert "C:" not in body["response"]


def test_peer_call_budget_applies_per_request(network):
    a = network.add(make_config("agent-a", "Agent Alpha", ["chat"], max_peer_calls=2), None)
    b = network.add(make_config("agent-b", "Agent Beta", ["chat"]), echo_script("B"))
    calls = [("ask_agent", {"agent_id": b.id, "question": f"q{i}"}) for i in range(3)]

    def script(messages):
        results = tool_results(messages)
        return ("text", " | ".join(results)) if results else ("tools", calls)

    a.runtime._model_factory = lambda: ScriptedModel(script)
    a.peer_manager.add_peer(b.id, b.to_dict())
    client = TestClient(network.apps["agent-a"])

    body = client.post("/chat", json={"text": "fan out", "session_id": "x"}).json()
    assert body["response"].count("answered:") == 2
    assert "Peer-call budget for this request (2) is used up" in body["response"]

    # A new request gets a fresh budget.
    body = client.post("/chat", json={"text": "again", "session_id": "y"}).json()
    assert body["response"].count("answered:") == 2


def test_peer_call_budget_applies_over_a2a(network):
    # Same budget, but the request arrives over A2A, so invocation_state is built by the
    # Strands A2A executor rather than by /chat.
    a = network.add(make_config("agent-a", "Agent Alpha", ["chat"], max_peer_calls=2), None)
    b = network.add(make_config("agent-b", "Agent Beta", ["chat"]), echo_script("B"))
    calls = [("ask_agent", {"agent_id": b.id, "question": f"q{i}"}) for i in range(3)]

    def script(messages):
        results = tool_results(messages)
        return ("text", " | ".join(results)) if results else ("tools", calls)

    a.runtime._model_factory = lambda: ScriptedModel(script)
    a.peer_manager.add_peer(b.id, b.to_dict())

    async def call():
        async with network.client_factory()() as http:
            card = await A2ACardResolver(http, "http://agent-a:8000/").get_agent_card()
            client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card)
            message = Message(
                role=Role.user,
                message_id=str(uuid.uuid4()),
                parts=[Part(root=TextPart(text="fan out"))],
            )
            final = None
            async for event in client.send_message(message):
                final = event
            return extract_text(final)

    text, state = asyncio.run(call())
    assert state == "completed"
    assert text.count("answered:") == 2
    assert "Peer-call budget for this request (2) is used up" in text


def test_assist_requests_get_an_agent_without_peer_tools(network):
    node = network.add(make_config("agent-a", "Agent Alpha", ["chat"]), echo_script("A"))
    assert set(node.runtime.new_agent(peer_tools=False).tool_names) == {
        "read_shared_memory",
        "write_shared_memory",
    }
    assert "find_agents" in node.runtime.new_agent().tool_names
    body = TestClient(network.apps["agent-a"]).post("/assist", json={"question": "hi"}).json()
    assert body["status"] == "success"
    assert body["response"].endswith("hi")


def test_session_eviction_skips_sessions_in_flight(network):
    cfg = make_config("agent-a", "Agent Alpha", ["chat"])
    cfg["sessions"]["max_sessions"] = 2
    node = network.add(cfg, echo_script("A"))
    runtime = node.runtime
    runtime.session("s1")
    runtime.session("s2")
    _, lock = runtime.session("s1")  # s1 is now most recent; s2 is the LRU candidate
    asyncio.run(lock.acquire())  # a /chat on s1 is in flight
    runtime.session("s2")  # s2 becomes most recent; s1 is the LRU candidate but busy
    runtime.session("s3")
    assert set(runtime._sessions) == {"s1", "s3"}


def test_legacy_acdp_1_0_peer_is_reached_through_assist(network):
    a = network.add(make_config("agent-a", "Agent Alpha", ["chat"]), None)
    b = network.add(make_config("agent-b", "Agent Beta", ["statistics"]), echo_script("B"))

    a.runtime._model_factory = lambda: ScriptedModel(delegate_once(b.id))
    # What an ACDP 1.0 agent registered: REST interface only, no A2A advertisement.
    legacy_info = {
        "id": b.id,
        "name": "Agent Beta",
        "capabilities": ["statistics"],
        "interfaces": {"rest": "http://agent-b:8000/v1"},
        "endpoints": {"assist": "/assist"},
        "protocols": ["rest-json"],
    }
    a.peer_manager.add_peer(b.id, legacy_info)

    body = TestClient(network.apps["agent-a"]).post("/chat", json={"text": "variance?"}).json()
    assert "via rest-assist" in body["response"]
    assert body["meta"]["transports"] == ["rest-assist"]


def test_bearer_token_guards_a2a_but_not_discovery(network):
    b = network.add(make_config("agent-b", "Agent Beta", ["chat"], token="s3cret"), echo_script("B"))
    client = TestClient(network.apps["agent-b"])

    card = client.get("/.well-known/agent-card.json").json()
    assert card["securitySchemes"]["acdpBearer"]["scheme"] == "bearer"
    assert client.get("/metadata").status_code == 200
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {}}
    assert client.post("/", json=rpc).status_code == 401
    assert client.post("/assist", json={"question": "hi"}).status_code == 401
    assert client.post("/memory", json={"key": "k", "value": 1}).status_code == 401
    assert client.post("/gossip/start").status_code == 401
    assert client.post("/gossip/stop").status_code == 401
    # The user-facing chat surface is deliberately left to network-level control.
    assert client.post("/chat", json={"text": "hello"}).json()["response"] == "B: hello"

    a_without = network.add(make_config("agent-a", "Agent Alpha", ["chat"]), echo_script("A"))
    with pytest.raises(PeerCallError):
        asyncio.run(a_without.peer_client.ask(b.id, b.to_dict(), "hi", DelegationState()))

    a_with = network.add(
        make_config("agent-c", "Agent Gamma", ["chat"]), echo_script("C"), peer_token="s3cret"
    )
    reply = asyncio.run(a_with.peer_client.ask(b.id, b.to_dict(), "hi", DelegationState()))
    assert reply.text == "B: hi"
    assert reply.transport == "a2a"


def test_card_identity_mismatch_is_rejected(network):
    a = network.add(make_config("agent-a", "Agent Alpha", ["chat"]), echo_script("A"))
    b = network.add(make_config("agent-b", "Agent Beta", ["chat"]), echo_script("B"))
    spoofed = dict(b.to_dict(), id="agent-z.agents.local")

    with pytest.raises(PeerCallError, match="claims ACDP id"):
        asyncio.run(a.peer_client.ask("agent-z.agents.local", spoofed, "hi", DelegationState()))


def test_collaboration_off_removes_peer_tools(network):
    cfg = make_config("agent-a", "Agent Alpha", ["chat"])
    cfg["collaboration"]["mode"] = "off"
    node = network.add(cfg, echo_script("A"))
    names = set(node.runtime.new_agent().tool_names)
    assert names == {"read_shared_memory", "write_shared_memory"}
