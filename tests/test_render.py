from agenttrace import render, render_to_file
from agenttrace.model import Trace, Turn, Event


def _trace(events):
    return Trace(run_id="r", agent="codex",
                 seed={"system_prompt": None, "user_input": "u"},
                 turns=[Turn(seq=0, events=events, meta={})], incomplete=False)


def _sample_trace():
    return _trace([Event("e0", "reasoning", None, None, {"text": "hello"})])


def _trace_with_reasoning_text(t):
    return _trace([Event("e0", "reasoning", None, None, {"text": t})])


def _trace_with_only_tool_events():
    return _trace([Event("e0", "tool_call", None, None, {"name": "cmd", "arguments": "ls"}),
                   Event("e1", "tool_result", None, None, {"output": "x"})])


def test_render_embeds_trace_and_is_self_contained():
    html = render(_sample_trace())
    assert "__TRACE_JSON__" not in html
    assert "http://" not in html and "https://" not in html   # no external assets
    assert "요약" in html


def test_render_escapes_script_breakout():
    tr = _trace_with_reasoning_text("</script><img src=x onerror=alert(1)>")
    html = render(tr)
    assert "</script><img" not in html
    assert "u003c/script" in html                              # escaped in embedded JSON


def test_render_shows_no_reasoning_notice():
    tr = _trace_with_only_tool_events()                        # a turn with no reasoning
    assert "추론 요약 없음" in render(tr)


def test_render_to_file_is_utf8(tmp_path):
    p = tmp_path / "out.html"
    render_to_file(_trace_with_reasoning_text("한국어 요약"), str(p))
    assert "한국어 요약" in p.read_text(encoding="utf-8")
