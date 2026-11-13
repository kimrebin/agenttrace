from agenttrace.model import Trace, Turn, Event


def test_trace_json_round_trip():
    tr = Trace(run_id="r1", agent="codex",
               seed={"system_prompt": None, "user_input": "안녕"},
               turns=[Turn(seq=0, events=[Event(id="e0", type="reasoning",
                           timestamp=None, raw=None, data={"text": "요약"})], meta={})],
               incomplete=False, started_at=None, ended_at=None, meta={})
    back = Trace.from_json(tr.to_json())
    assert back == tr
    assert "안녕" in tr.to_json()  # ensure_ascii=False keeps UTF-8 readable


def test_from_dict_tolerates_missing_optionals():
    tr = Trace.from_dict({"agent": "codex", "turns": []})
    assert tr.agent == "codex" and tr.turns == [] and tr.incomplete is False
