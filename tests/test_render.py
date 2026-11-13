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


def _trace_with_user_input(u):
    return Trace(run_id="r", agent="codex",
                 seed={"system_prompt": None, "user_input": u}, turns=[],
                 incomplete=False)


def test_render_with_compare_includes_diff_panel_in_same_page():
    a = _trace_with_user_input("find the bug\nbe careful")
    b = _trace_with_user_input("find the bug\nbe very careful")
    html = render(a, compare_to=b)
    assert "프롬프트 변경점" in html                       # diff panel heading
    assert 'class="diff-add"' in html and 'class="diff-del"' in html
    assert "renderFlow" in html                            # same page still has the timeline
    assert "__DIFF_PANEL__" not in html


def test_render_without_compare_has_no_diff_panel():
    html = render(_sample_trace())
    assert "프롬프트 변경점" not in html
    assert "__DIFF_PANEL__" not in html


def test_render_has_flow_spine_and_summary():
    # the viewer builds DOM client-side, so check the static markers:
    html = render(_sample_trace())
    assert 'id="summary"' in html      # top summary bar element
    assert '.flow' in html             # vertical flow-spine styles
    assert 'renderFlow' in html        # flow builder present
    assert 'mdInto' in html            # lightweight markdown highlighter
    assert 'border-left' in html       # carded cells with a colored accent


def test_render_iframe_embeds_escaped_doc():
    from agenttrace import render_iframe
    snip = render_iframe(_sample_trace(), height="400px")
    assert snip.startswith("<iframe")
    assert 'srcdoc="' in snip and "height:400px" in snip
    # the inner document is escaped so its markup/quotes cannot break the attribute
    assert "<!doctype html>" not in snip
    assert "&lt;!doctype html&gt;" in snip
    assert "hello" in snip                      # reasoning text survives (no special chars)


def test_render_to_file_is_utf8(tmp_path):
    p = tmp_path / "out.html"
    render_to_file(_trace_with_reasoning_text("한국어 요약"), str(p))
    assert "한국어 요약" in p.read_text(encoding="utf-8")
