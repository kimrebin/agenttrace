from agenttrace.adapters.codex import parse_stream


def test_tool_call_and_result_mapped():
    tr = parse_stream(open("tests/fixtures/codex_stream_tools.jsonl", encoding="utf-8"))
    kinds = [e.type for e in tr.turns[0].events]
    assert "tool_call" in kinds and "tool_result" in kinds
    call = next(e for e in tr.turns[0].events if e.type == "tool_call")
    assert call.data["name"]
    result = next(e for e in tr.turns[0].events if e.type == "tool_result")
    assert "output" in result.data
