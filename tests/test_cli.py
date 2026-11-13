from agenttrace import main


def test_cli_replay_writes_html(tmp_path):
    out = tmp_path / "o.html"
    rc = main(["replay", "tests/fixtures/codex_rollout.jsonl", "-o", str(out)])
    assert rc == 0 and "<html" in out.read_text(encoding="utf-8").lower()


def test_cli_replay_with_compare_puts_diff_panel_in_page(tmp_path):
    out = tmp_path / "o.html"
    rc = main(["replay", "tests/fixtures/codex_rollout.jsonl",
               "--compare", "tests/fixtures/codex_rollout_real.jsonl", "-o", str(out)])
    assert rc == 0
    page = out.read_text(encoding="utf-8")
    assert "프롬프트 변경점" in page and "renderFlow" in page   # diff + timeline, one page


def test_cli_replay_compare_prev_auto_selects_previous(tmp_path):
    def w(name, ts):
        (tmp_path / name).write_text(
            '{"type":"session_meta","payload":{"id":"%s","timestamp":"%s","cwd":"C:/p"}}\n'
            '{"type":"event_msg","payload":{"type":"user_message","message":"prompt %s"}}'
            % (name, ts, name), encoding="utf-8")
    w("prev.jsonl", "2026-05-01T10:00:00Z")
    w("cur.jsonl", "2026-05-02T10:00:00Z")
    out = tmp_path / "o.html"
    rc = main(["replay", str(tmp_path / "cur.jsonl"), "--compare-prev", "-o", str(out)])
    assert rc == 0
    page = out.read_text(encoding="utf-8")
    assert "프롬프트 변경점" in page            # auto-picked previous session as baseline


def test_cli_diff_writes_html(tmp_path):
    out = tmp_path / "d.html"
    rc = main(["diff", "tests/fixtures/codex_stream_basic.jsonl",
               "tests/fixtures/codex_stream_basic.jsonl", "-o", str(out)])
    assert rc == 0 and out.exists()
