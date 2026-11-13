from agenttrace.adapters.codex import parse_stream


def test_tool_call_and_result_mapped():
    tr = parse_stream(open("tests/fixtures/codex_stream_tools.jsonl", encoding="utf-8"))
    kinds = [e.type for e in tr.turns[0].events]
    assert "tool_call" in kinds and "tool_result" in kinds
    call = next(e for e in tr.turns[0].events if e.type == "tool_call")
    assert call.data["name"]
    result = next(e for e in tr.turns[0].events if e.type == "tool_result")
    assert "output" in result.data


def test_nonzero_exit_code_becomes_error_event():
    lines = ['{"type":"turn.started"}',
             '{"type":"item.completed","item":{"type":"command_execution",'
             '"command":"bad","aggregated_output":"boom","exit_code":1}}']
    tr = parse_stream(lines)
    kinds = [e.type for e in tr.turns[0].events]
    assert "tool_call" in kinds and "error" in kinds
    assert "tool_result" not in kinds
    err = next(e for e in tr.turns[0].events if e.type == "error")
    assert err.data["output"] == "boom" and err.data["exit_code"] == 1


def test_top_level_error_event_mapped():
    lines = ['{"type":"turn.started"}', '{"type":"error","message":"rate limited"}']
    tr = parse_stream(lines)
    err = [e for e in tr.turns[0].events if e.type == "error"]
    assert err and err[0].data.get("message") == "rate limited"
