"""Event bus: sequence numbers, JSONL log, subscribers, reset, and replay."""

import asyncio
import json

from arena.bus import MAX_REPLAY_GAP, EventBus, load_log, replay


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_publish_assigns_seq_and_appends_jsonl(tmp_path):
    log = tmp_path / "run.jsonl"
    bus = EventBus("r1", log, clock=Clock())
    first = bus.publish("agent.registered", {"id": "a"})
    second = bus.publish("message.sent", {"id": "m"})
    assert (first["seq"], second["seq"]) == (0, 1)
    assert first == {"seq": 0, "ts": 1000.0, "run_id": "r1",
                     "type": "agent.registered", "data": {"id": "a"}}
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert [e["type"] for e in lines] == ["agent.registered", "message.sent"]
    assert bus.history == [first, second]


def test_non_persistent_events_skip_the_log(tmp_path):
    log = tmp_path / "run.jsonl"
    bus = EventBus("r1", log)
    bus.publish("x", {}, persist=False)
    assert not log.exists()
    assert len(bus.history) == 1


def test_subscribers_receive_events():
    async def run():
        bus = EventBus("r1")
        queue = bus.subscribe()
        bus.publish("x", {"n": 1})
        return await asyncio.wait_for(queue.get(), 1)

    assert asyncio.run(run())["data"] == {"n": 1}


def test_full_subscriber_is_dropped_others_continue():
    bus = EventBus("r1", max_queue=2)
    slow = bus.subscribe()
    fast = bus.subscribe()
    received = []
    for n in range(3):
        bus.publish("x", {"n": n})
        received.append(fast.get_nowait()["data"]["n"])
    assert received == [0, 1, 2]
    assert not bus.is_subscribed(slow)
    assert bus.is_subscribed(fast)


def test_reset_clears_history_and_announces():
    bus = EventBus("r1")
    bus.publish("x", {})
    queue = bus.subscribe()
    bus.reset("replay-1", note={"log": "r1"})
    assert bus.run_id == "replay-1"
    assert [e["type"] for e in bus.history] == ["bus.reset"]
    assert bus.history[0]["seq"] == 0
    assert queue.get_nowait()["data"] == {"run_id": "replay-1", "log": "r1"}


def test_load_log_and_replay_keep_order_and_scale_gaps(tmp_path):
    clock = Clock()
    source = EventBus("r1", tmp_path / "r1.jsonl", clock=clock)
    for step, kind in ((0, "a"), (4, "b"), (60, "c")):
        clock.t += step
        source.publish(kind, {"k": kind})

    events = load_log(tmp_path / "r1.jsonl")
    target = EventBus("replay")
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    asyncio.run(replay(events, target, speed=2, sleep=fake_sleep))
    assert [e["type"] for e in target.history] == ["a", "b", "c"]
    assert sleeps == [2.0, MAX_REPLAY_GAP]
