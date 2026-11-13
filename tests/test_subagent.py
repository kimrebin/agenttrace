import agenttrace
from agenttrace.model import Trace, Turn, Event


def _parent():
    return Trace(run_id="p", agent="codex",
                 seed={"system_prompt": None, "user_input": "u"},
                 turns=[Turn(0, [Event("e0", "tool_call", None, None,
                        {"name": "spawn", "arguments": "", "call_id": "c1"})], {})],
                 incomplete=False)


def _child():
    return Trace(run_id="ch", agent="codex",
                 seed={"system_prompt": None, "user_input": "sub"},
                 turns=[Turn(0, [Event("e0", "reasoning", None, None,
                        {"text": "child thinking"})], {})],
                 incomplete=False)


def test_nest_sub_trace_attaches_child_by_call_id():
    p = _parent()
    assert agenttrace.nest_sub_trace(p, "c1", _child()) is True
    tc = p.turns[0].events[0]
    assert tc.data["sub_trace"]["run_id"] == "ch"


def test_nest_sub_trace_missing_call_id_returns_false():
    assert agenttrace.nest_sub_trace(_parent(), "nope", _child()) is False


def test_render_includes_nested_sub_trace():
    p = _parent()
    agenttrace.nest_sub_trace(p, "c1", _child())
    html = agenttrace.render(p)
    assert "child thinking" in html     # child trace embedded
    assert "sub_trace" in html          # viewer knows how to nest
