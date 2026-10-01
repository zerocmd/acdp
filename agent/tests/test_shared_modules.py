"""Tests for agent modules that the arena reuses after the PoC archive."""

import os
import subprocess
import sys

import pytest

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_reused_modules_do_not_import_poc_code():
    code = (
        "import sys, runtime.models, runtime.a2a_card;"
        "bad = [m for m in ('runtime.tools', 'runtime.delegation', 'node')"
        " if m in sys.modules];"
        "assert not bad, bad"
    )
    subprocess.run([sys.executable, "-c", code], cwd=AGENT_DIR, check=True)


def test_build_model_rejects_unknown_provider():
    from runtime.models import build_model

    with pytest.raises(ValueError, match="Unsupported MODEL_PROVIDER"):
        build_model({"provider": "other"})


def test_build_model_bedrock_requires_model_id():
    from runtime.models import build_model

    with pytest.raises(ValueError, match="MODEL_ID is required"):
        build_model({"provider": "bedrock"})



def test_dns_resolver_reads_key_field(monkeypatch):
    from discovery.dns_resolver import DNSResolver

    resolver = DNSResolver(dns_server="127.0.0.1")
    monkeypatch.setattr(resolver, "_get_srv_record", lambda d: ("arena", 8080))
    monkeypatch.setattr(
        resolver,
        "_get_txt_record",
        lambda d: ["ver=1.1", "caps=threat-intel", "a2a=/agents/x/card", "key=abc"],
    )
    info = resolver.resolve_agent("x.halcyon-intel.example")
    assert info["key"] == "abc"
    assert info["capabilities"] == ["threat-intel"]


def test_registry_client_get_org(monkeypatch):
    from discovery import registry_client as rc

    calls = []

    class Response:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

        def raise_for_status(self):
            if self.status_code >= 400:
                raise rc.requests.HTTPError(str(self.status_code))

    def fake_get(url, timeout):
        calls.append(url)
        if url.endswith("/orgs/halcyonintel"):
            return Response(200, {"organization": "Halcyon Intel",
                                  "canonical_domain": "halcyon-intel.example"})
        return Response(404, {"error": "not found"})

    monkeypatch.setattr(rc.requests, "get", fake_get)
    client = rc.RegistryClient("http://registry:5000")
    assert client.get_org("Halcyon Intel")["canonical_domain"] == "halcyon-intel.example"
    assert client.get_org("Nobody Inc") is None
    assert calls[0] == "http://registry:5000/orgs/halcyonintel"


def _card_config(**extra):
    config = {
        "id": "halcyon-intel.halcyon-intel.example",
        "name": "Threat Intel Analyst",
        "description": "Threat intelligence",
        "capabilities": ["threat-intel"],
        "interfaces": {"a2a": "http://arena:8080/agents/halcyon-intel/"},
    }
    config.update(extra)
    return config


def test_card_carries_identity_params_when_configured():
    from runtime.a2a_card import build_agent_card, card_acdp_params

    jwk = {"kty": "OKP", "crv": "Ed25519", "x": "abc"}
    card = build_agent_card(_card_config(
        did="did:web:halcyon-intel.example:agents:halcyon-intel",
        organization="Halcyon Intel",
        domain="halcyon-intel.example",
        publicKeyJwk=jwk,
        model_name="claude-sonnet-5-5",
    ))
    params = card_acdp_params(card.model_dump(mode="json", exclude_none=True))
    assert params["did"] == "did:web:halcyon-intel.example:agents:halcyon-intel"
    assert params["organization"] == "Halcyon Intel"
    assert params["domain"] == "halcyon-intel.example"
    assert params["publicKeyJwk"] == jwk
    assert params["model"] == "claude-sonnet-5-5"


def test_card_omits_identity_params_when_not_configured():
    from runtime.a2a_card import build_agent_card, card_acdp_params

    card = build_agent_card(_card_config())
    params = card_acdp_params(card.model_dump(mode="json", exclude_none=True))
    assert not {"did", "organization", "domain", "publicKeyJwk", "model"} & params.keys()
