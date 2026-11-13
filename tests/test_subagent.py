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


def test_rollout_subagent_activity_becomes_sub_agent_call():
    from agenttrace.adapters.codex_rollout import parse_rollout
    lines = [
        '{"type":"session_meta","payload":{"id":"parent"}}',
        '{"type":"event_msg","payload":{"type":"item_completed","item":{"type":"SubAgentActivity",'
        '"id":"a1","kind":"started","agent_thread_id":"child1","agent_path":"/repo_analysis"}}}',
    ]
    tr = parse_rollout(lines)
    tc = next(e for e in tr.turns[0].events if e.type == "tool_call")
    assert tc.data["call_id"] == "child1" and "sub_agent" in tc.data["name"]


def test_link_sub_agents_nests_child_from_sessions_dir(tmp_path):
    parent = tmp_path / "parent.jsonl"
    child = tmp_path / "child.jsonl"
    parent.write_text("\n".join([
        '{"type":"session_meta","payload":{"id":"parent"}}',
        '{"type":"event_msg","payload":{"type":"item_completed","item":{"type":"SubAgentActivity",'
        '"id":"a1","kind":"started","agent_thread_id":"child1","agent_path":"/x"}}}',
    ]), encoding="utf-8")
    child.write_text("\n".join([
        '{"type":"session_meta","payload":{"id":"child1"}}',
        '{"type":"event_msg","payload":{"type":"item_completed","item":{"type":"AgentMessage",'
        '"content":[{"type":"Text","text":"child did work"}],"phase":"commentary"}}}',
    ]), encoding="utf-8")
    tr = agenttrace.load(str(parent), link_subagents=True, sessions_dir=str(tmp_path))
    tc = next(e for e in tr.turns[0].events if e.type == "tool_call")
    assert "sub_trace" in tc.data
    assert "child did work" in agenttrace.render(tr)
