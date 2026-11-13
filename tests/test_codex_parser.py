from agenttrace.adapters.codex import parse_stream


def test_parses_basic_stream():
    tr = parse_stream(open("tests/fixtures/codex_stream_basic.jsonl", encoding="utf-8"),
                      user_input="puzzle")
    assert tr.run_id == "01a1cec6-5f08-7152-a821-a9b8ef1a2ca4"
    assert tr.agent == "codex"
    assert tr.seed["user_input"] == "puzzle"
    assert len(tr.turns) == 1 and tr.turns[0].seq == 0
    assert [e.type for e in tr.turns[0].events] == ["reasoning", "reasoning"]
    assert tr.turns[0].events[0].data["text"].startswith("**Arranging")
    assert tr.turns[0].events[1].data["role"] == "agent_message"
    assert tr.turns[0].meta["usage"]["reasoning_output_tokens"] == 89
    assert tr.incomplete is False


def test_malformed_line_becomes_unknown_event_and_continues():
    lines = ['{"type":"thread.started","thread_id":"x"}', '{"type":"turn.started"}',
             'NOT JSON {{{', '{"type":"turn.completed"}']
    tr = parse_stream(lines)
    assert any(e.type == "unknown" for e in tr.turns[0].events)
    assert tr.incomplete is False


def test_unknown_item_type_preserved():
    lines = ['{"type":"turn.started"}',
             '{"type":"item.completed","item":{"type":"future_thing","blob":1}}']
    tr = parse_stream(lines)
    ev = tr.turns[0].events[-1]
    assert ev.type == "unknown" and ev.raw["item"]["type"] == "future_thing"


def test_truncated_stream_marks_incomplete():
    lines = ['{"type":"thread.started","thread_id":"x"}', '{"type":"turn.started"}']
    tr = parse_stream(lines)
    assert tr.incomplete is True
