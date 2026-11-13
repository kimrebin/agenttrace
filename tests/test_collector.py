import pytest

from agenttrace import Collector


def test_collector_feed_finish():
    c = Collector(agent="codex", user_input="puzzle")
    for line in open("tests/fixtures/codex_stream_basic.jsonl", encoding="utf-8"):
        c.feed(line)
    tr = c.finish()
    assert tr.run_id and tr.seed["user_input"] == "puzzle"


def test_collector_rejects_unknown_agent():
    with pytest.raises(ValueError):
        Collector(agent="nope")
