from agenttrace.adapters.codex import load


def test_rollout_maps_tools_and_commentary_but_omits_encrypted_reasoning():
    tr = load("tests/fixtures/codex_rollout.jsonl")   # auto-detect → rollout
    assert tr.run_id == "019f938e"
    assert tr.seed["system_prompt"].startswith("You are Codex")
    kinds = [e.type for e in tr.turns[0].events]
    assert "tool_call" in kinds and "tool_result" in kinds
    # commentary survives as reasoning(role=agent_message); encrypted CoT does not
    assert any(e.type == "reasoning" and e.data.get("role") == "agent_message"
               for e in tr.turns[0].events)
    assert all(not (e.type == "reasoning" and e.data.get("role") != "agent_message")
               for e in tr.turns[0].events)


def test_load_autodetects_stream_vs_rollout():
    stream = load("tests/fixtures/codex_stream_basic.jsonl")
    assert stream.run_id == "01a1cec6-5f08-7152-a821-a9b8ef1a2ca4"


def test_rollout_real_schema_message_and_id():
    tr = load("tests/fixtures/codex_rollout_real.jsonl")
    assert tr.run_id == "019dfc8a-real"                      # session_meta.payload.id
    assert tr.seed["user_input"] == "list files"            # from user_message
    assert tr.seed["system_prompt"].startswith("You are Codex")
    kinds = [e.type for e in tr.turns[0].events]
    assert "tool_call" in kinds and "tool_result" in kinds
    # assistant message text surfaces as a readable event
    reason_texts = [e.data.get("text", "") for e in tr.turns[0].events
                    if e.type == "reasoning"]
    assert any("There is 1 file." in t for t in reason_texts)
    # the large developer/system instruction block is not dumped as an event
    assert all("permissions instructions" not in e.data.get("text", "")
               for e in tr.turns[0].events)
