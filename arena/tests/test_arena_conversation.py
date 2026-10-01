"""Message envelope, turn decision, threads, and rate limits."""

import pytest
from pydantic import ValidationError

from arena.decision import TurnDecision
from arena.envelope import MAX_BODY, ArenaMessage, Intent
from arena.identity import Identity, verify_signature
from arena.rate import RunGuard, TokenBucket
from arena.threads import ThreadRegistry


def message(thread_id="t1", sender="a", to="b", intent=Intent.SHARE, body="x"):
    return ArenaMessage(
        id=f"m-{sender}-{to}-{body}", thread_id=thread_id, from_id=sender, to_id=to,
        from_did=f"did:web:{sender}", to_did=f"did:web:{to}", ts=1.0,
        intent=intent, body=body, card_url=f"http://arena:8080/agents/{sender}/card",
    )


def test_message_payload_is_json_and_signature_verifies():
    ident = Identity("a", "a.example")
    signed = message().signed(ident)
    payload = signed.payload()
    assert payload["intent"] == "share"
    assert verify_signature(payload, ident.public_jwk())


def test_message_rejects_long_body_and_unknown_fields():
    with pytest.raises(ValidationError):
        message(body="x" * (MAX_BODY + 1))
    with pytest.raises(ValidationError):
        ArenaMessage.model_validate(dict(message().payload(), extra="no"))


def test_turn_decision_defaults_and_validation():
    assert TurnDecision(action="wait").to == ""
    with pytest.raises(ValidationError):
        TurnDecision(action="maybe")
    with pytest.raises(ValidationError):
        TurnDecision(action="send", body="x" * (MAX_BODY + 1))


def test_thread_ids_and_colors_increment():
    reg = ThreadRegistry()
    first, second = reg.open("a", "one"), reg.open("b", "two")
    assert (first.id, first.color, second.id, second.color) == ("t1", 0, "t2", 1)
    assert first.participants == {"a"}


def test_unknown_thread_is_rejected():
    assert ThreadRegistry().check_send("t9") == "unknown thread"


def test_cap_closes_thread():
    reg = ThreadRegistry(default_cap=3)
    thread = reg.open("a", "t")
    assert reg.append(message(body="1")) is None
    assert reg.append(message(body="2")) is None
    assert reg.append(message(body="3")) == "cap reached"
    assert thread.closed
    assert thread.participants == {"a", "b"}


def test_closed_thread_rejects_send():
    reg = ThreadRegistry()
    reg.open("a", "t")
    assert reg.append(message(intent=Intent.CLOSE, sender="a")) == "closed by owner"
    assert reg.check_send("t1") == "thread closed"
    assert reg.open_count() == 0
    assert reg.open_threads() == []


def test_close_by_non_owner_does_not_close():
    reg = ThreadRegistry()
    reg.open("a", "t")
    assert reg.append(message(intent=Intent.CLOSE, sender="b", to="a")) is None
    assert reg.check_send("t1") is None


def test_verdict_closes_only_when_sent_by_closer():
    reg = ThreadRegistry()
    reg.open("soc", "case", closer="isac")
    assert reg.append(message(intent=Intent.VERDICT, sender="soc", to="isac")) is None
    assert reg.append(message(intent=Intent.VERDICT, sender="isac", to="soc")) == "verdict"


def test_for_agent_lists_threads_with_that_participant():
    reg = ThreadRegistry()
    reg.open("a", "one")
    reg.open("c", "two")
    reg.append(message(thread_id="t2", sender="c", to="b"))
    assert [t.id for t in reg.for_agent("b")] == ["t2"]
    assert [t.id for t in reg.open_threads()] == ["t1", "t2"]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_token_bucket_limits_rate():
    clock = Clock()
    bucket = TokenBucket(rate_per_min=2, clock=clock)
    assert bucket.available() is True
    assert [bucket.try_take() for _ in range(3)] == [True, True, False]
    assert bucket.available() is False
    clock.t = 30.0
    assert bucket.available() is True
    assert bucket.try_take() is True
    assert bucket.try_take() is False


def test_run_guard_limits_calls_and_time():
    clock = Clock()
    guard = RunGuard(max_minutes=1, max_calls=2, clock=clock)
    guard.note_call()
    assert guard.exceeded() is None
    guard.note_call()
    assert guard.exceeded() == "model call limit reached"
    other = RunGuard(max_minutes=1, max_calls=99, clock=clock)
    clock.t = 61.0
    assert other.exceeded() == "time limit reached"
