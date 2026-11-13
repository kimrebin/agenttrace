from agenttrace.adapters.codex_rollout import find_previous_session


def _w(p, name, ts, cwd):
    (p / name).write_text(
        '{"type":"session_meta","payload":{"id":"%s","timestamp":"%s","cwd":"%s"}}'
        % (name, ts, cwd), encoding="utf-8")


def test_find_previous_session_picks_most_recent_before_same_cwd(tmp_path):
    _w(tmp_path, "a.jsonl", "2026-05-01T10:00:00Z", "C:/proj")
    _w(tmp_path, "b.jsonl", "2026-05-02T10:00:00Z", "C:/proj")
    _w(tmp_path, "c.jsonl", "2026-05-03T10:00:00Z", "C:/other")   # different project
    _w(tmp_path, "d.jsonl", "2026-05-04T10:00:00Z", "C:/proj")    # current
    prev = find_previous_session(str(tmp_path / "d.jsonl"), sessions_dir=str(tmp_path))
    assert prev is not None and prev.endswith("b.jsonl")          # c excluded (other cwd)


def test_find_previous_session_none_when_earliest(tmp_path):
    _w(tmp_path, "only.jsonl", "2026-05-01T10:00:00Z", "C:/p")
    assert find_previous_session(str(tmp_path / "only.jsonl"),
                                 sessions_dir=str(tmp_path)) is None
