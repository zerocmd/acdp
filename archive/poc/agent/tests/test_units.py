"""Unit tests for endpoint resolution, delegation state and DNS TXT parsing."""

from types import SimpleNamespace

from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
)

from discovery.dns_resolver import DNSResolver
from runtime.a2a_card import card_acdp_params, card_endpoint, card_skill_ids
from runtime.delegation import ACDP_EXTENSION_URI, DelegationState
from runtime.peer_client import extract_text
from utils.endpoints import a2a_url, base_url, endpoint_url


def test_base_url_prefers_a2a_then_rest_then_host_then_id():
    assert base_url("x", {"a2a": {"url": "http://a:9/"}, "interfaces": {"rest": "http://r:1/v1"}}) == "http://a:9"
    assert base_url("x", {"interfaces": {"rest": "http://agent0:8000/v1"}}) == "http://agent0:8000"
    assert base_url("x", {"host": "h", "port": "8123"}) == "http://h:8123"
    assert base_url("agent4.agents.local", {}) == "http://agent4:8000"
    assert base_url("nodots", {}) is None


def test_endpoint_url_handles_paths_and_absolute_urls():
    info = {"interfaces": {"rest": "http://agent0:8000/v1"}, "endpoints": {"peers": "/peers"}}
    assert endpoint_url("agent0.agents.local", info, "peers", "/peers") == "http://agent0:8000/peers"
    assert endpoint_url("agent0.agents.local", info, "ping", "/health") == "http://agent0:8000/health"
    info["endpoints"]["assist"] = "https://elsewhere/assist"
    assert endpoint_url("agent0.agents.local", info, "assist", "/assist") == "https://elsewhere/assist"


def test_a2a_url_only_for_a2a_capable_peers():
    assert a2a_url({"interfaces": {"rest": "http://agent0:8000/v1"}, "protocols": ["rest-json"]}) is None
    assert a2a_url({"a2a": {"url": "http://b:8000/"}}) == "http://b:8000/"
    assert a2a_url({"id": "c.agents.local", "host": "c", "port": 8000, "protocols": ["a2a/0.3"]}) == "http://c:8000/"


def test_delegation_state_round_trip_and_checks():
    root = DelegationState()
    assert root.check("a", "b", 2) is None
    assert "itself" in root.check("a", "a", 2)

    hop1 = DelegationState.from_metadata(root.next_hop("a"))
    assert hop1 == DelegationState(hops=1, trace=["a"])
    assert "already part" in hop1.check("b", "a", 2)
    assert hop1.check("b", "c", 2) is None

    hop2 = DelegationState.from_metadata(hop1.next_hop("b"))
    assert "maximum delegation depth" in hop2.check("c", "d", 2)


def test_delegation_state_ignores_malformed_metadata():
    assert DelegationState.from_metadata(None) == DelegationState()
    bad = {ACDP_EXTENSION_URI: {"hops": "many", "trace": ["a", 7, None]}}
    assert DelegationState.from_metadata(bad) == DelegationState(hops=0, trace=["a"])


def test_delegation_state_from_a2a_request_context():
    context = SimpleNamespace(message=SimpleNamespace(metadata=DelegationState().next_hop("a")))
    state = DelegationState.from_invocation_state({"a2a_request_context": context})
    assert state.trace == ["a"]


def test_card_helpers_accept_a2a_0_3_and_1_0_shapes():
    v03 = {"url": "http://a/", "skills": [{"id": "log_analysis", "tags": ["logs"]}]}
    v10 = {"supportedInterfaces": [{"url": "http://b/", "protocolBinding": "JSONRPC"}]}
    assert card_endpoint(v03) == "http://a/"
    assert card_endpoint(v10) == "http://b/"
    assert card_skill_ids(v03) == ["log_analysis", "logs"]
    ext = {"capabilities": {"extensions": [{"uri": ACDP_EXTENSION_URI, "params": {"id": "a"}}]}}
    assert card_acdp_params(ext) == {"id": "a"}
    assert card_acdp_params({}) == {}


def test_dns_resolver_parses_acdp_1_1_txt(monkeypatch):
    resolver = DNSResolver.__new__(DNSResolver)
    monkeypatch.setattr(resolver, "_get_srv_record", lambda d: ("agent3.agents.local", 8000), raising=False)
    monkeypatch.setattr(
        resolver,
        "_get_txt_record",
        lambda d: ["ver=1.1", "caps=security,log_analysis", "desc=Delta", "proto=a2a/0.3,rest-json",
                   "a2a=/.well-known/agent-card.json"],
        raising=False,
    )
    info = resolver.resolve_agent("agent3.agents.local")
    assert info["capabilities"] == ["security", "log_analysis"]
    assert info["protocols"] == ["a2a/0.3", "rest-json"]
    assert info["a2a"] == {
        "url": "http://agent3.agents.local:8000/",
        "card_url": "http://agent3.agents.local:8000/.well-known/agent-card.json",
    }
    assert a2a_url(info) == "http://agent3.agents.local:8000/"


def test_dns_resolver_keeps_acdp_1_0_records_legacy(monkeypatch):
    resolver = DNSResolver.__new__(DNSResolver)
    monkeypatch.setattr(resolver, "_get_srv_record", lambda d: ("agent1", 8000), raising=False)
    monkeypatch.setattr(resolver, "_get_txt_record", lambda d: ["ver=1.0", "caps=chat"], raising=False)
    info = resolver.resolve_agent("agent1.agents.local")
    assert "a2a" not in info
    assert a2a_url(info) is None


def _text(t):
    return Part(root=TextPart(text=t))


def test_extract_text_reads_artifacts_then_status_message():
    with_artifacts = Task(
        id="t1",
        context_id="c1",
        status=TaskStatus(state=TaskState.completed),
        artifacts=[
            Artifact(artifact_id="a1", parts=[_text("Lateral movement: "), _text("check 4624")]),
            Artifact(artifact_id="a2", parts=[_text(" and 4648.")]),
        ],
    )
    assert extract_text((with_artifacts, None)) == ("Lateral movement: check 4624 and 4648.", "completed")

    status_only = Task(
        id="t2",
        context_id="c1",
        status=TaskStatus(
            state=TaskState.failed,
            message=Message(role=Role.agent, message_id="m1", parts=[_text("Agent execution failed")]),
        ),
    )
    assert extract_text((status_only, None)) == ("Agent execution failed", "failed")

    direct = Message(role=Role.agent, message_id="m2", parts=[_text("hi")])
    assert extract_text(direct) == ("hi", None)
    assert extract_text(None) == ("", None)
