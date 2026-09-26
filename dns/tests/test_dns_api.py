"""DNS update API validation and zone-script rendering tests."""

import importlib.util
import os
import shutil
import stat
import subprocess

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
spec = importlib.util.spec_from_file_location("dns_api", os.path.join(SCRIPTS, "dns_api.py"))
dns_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dns_api)

GOOD = {
    "domain": "agent3.agents.local",
    "host": "agent3.agents.local",
    "port": 8000,
    "capabilities": "security,threat_detection",
    "description": 'Delta "the" \\ analyst',
    "ip_address": "172.18.0.5",
    "a2a": "/.well-known/agent-card.json",
    "protocols": "a2a/0.3,rest-json",
    "version": "1.1",
}


def test_valid_update_is_normalised():
    clean = dns_api.validate_update(dict(GOOD))
    assert clean["port"] == "8000"
    assert clean["description"] == "Delta the  analyst"
    assert clean["a2a"] == "/.well-known/agent-card.json"


@pytest.mark.parametrize(
    "field, value",
    [
        ("domain", "agent3.agents.local\nupdate delete agents.local ANY"),
        ("domain", "agent3.example.com"),
        ("host", "agent3; rm -rf /"),
        ("port", 70000),
        ("capabilities", 'chat" "evil=1'),
        ("a2a", '/card" "x=1'),
        ("protocols", "a2a\nsend"),
        ("version", "1.1\n"),
        ("ip_address", "not-an-ip"),
    ],
)
def test_injection_attempts_are_rejected(field, value):
    with pytest.raises(dns_api.ValidationError):
        dns_api.validate_update(dict(GOOD, **{field: value}))


def test_control_characters_are_stripped_from_description():
    clean = dns_api.validate_update(dict(GOOD, description="line1\nupdate add x 1 A 1.2.3.4"))
    assert "\n" not in clean["description"]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_zone_script_renders_acdp_1_1_txt(tmp_path):
    for tool, body in (("nsupdate", 'cat "$1"'), ("dig", "true")):
        path = tmp_path / tool
        path.write_text(f"#!/bin/bash\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    clean = dns_api.validate_update(dict(GOOD))
    args = [clean[k] for k in ("domain", "host", "port", "capabilities", "description",
                               "ip_address", "a2a", "protocols", "version")]
    out = subprocess.run(
        ["bash", os.path.join(SCRIPTS, "update_zone.sh"), *args],
        capture_output=True, text=True, check=True,
        env=dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}"),
    ).stdout
    assert (
        'update add _llm-agent._tcp.agent3.agents.local 300 TXT "ver=1.1" '
        '"caps=security,threat_detection" "desc=Delta the  analyst" '
        '"proto=a2a/0.3,rest-json" "a2a=/.well-known/agent-card.json"'
    ) in out
    assert "SRV 0 0 8000 agent3.agents.local." in out
