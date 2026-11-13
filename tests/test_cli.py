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


def test_cli_diff_writes_html(tmp_path):
    out = tmp_path / "d.html"
    rc = main(["diff", "tests/fixtures/codex_stream_basic.jsonl",
               "tests/fixtures/codex_stream_basic.jsonl", "-o", str(out)])
    assert rc == 0 and out.exists()
