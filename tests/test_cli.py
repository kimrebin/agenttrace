from agenttrace import main


def test_cli_replay_writes_html(tmp_path):
    out = tmp_path / "o.html"
    rc = main(["replay", "tests/fixtures/codex_rollout.jsonl", "-o", str(out)])
    assert rc == 0 and "<html" in out.read_text(encoding="utf-8").lower()


def test_cli_diff_writes_html(tmp_path):
    out = tmp_path / "d.html"
    rc = main(["diff", "tests/fixtures/codex_stream_basic.jsonl",
               "tests/fixtures/codex_stream_basic.jsonl", "-o", str(out)])
    assert rc == 0 and out.exists()
