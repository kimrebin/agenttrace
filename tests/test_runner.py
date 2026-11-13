from agenttrace import run_codex


def test_run_codex_uses_injected_launcher_and_sets_seed():
    captured = {}

    def fake_launcher(argv):
        captured["argv"] = argv
        return list(open("tests/fixtures/codex_stream_basic.jsonl", encoding="utf-8"))

    tr = run_codex("puzzle", launcher=fake_launcher)
    assert tr.seed["user_input"] == "puzzle"
    assert "--json" in captured["argv"]
    assert any("model_reasoning_summary" in a for a in captured["argv"])
