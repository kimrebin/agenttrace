"""Post-hoc replay of a saved Codex rollout file (`~/.codex/sessions/.../
rollout-*.jsonl`).

This schema differs from the live `--json` stream: each line is
`{timestamp, type, payload}` and the real event kind is `payload.type`.
Reasoning is stored encrypted with an empty summary, so the chain-of-
thought cannot be recovered here — only the agent's readable commentary
(`agent_message`) and the tool trace survive. Encrypted reasoning is
dropped with a one-time note.
"""

from __future__ import annotations

import json
from typing import Iterable

from agenttrace.model import Trace, Turn, Event


def parse_rollout(lines: Iterable[str]) -> Trace:
    trace = Trace(run_id=None, agent="codex",
                  seed={"system_prompt": None, "user_input": None},
                  turns=[], incomplete=False)
    turn = Turn(seq=0, events=[], meta={})
    trace.turns.append(turn)
    n = 0
    noted_encrypted = False
    seen_text: set[str] = set()

    def add(type: str, data: dict, raw: dict | None = None) -> None:
        nonlocal n
        turn.events.append(Event(id=f"e{n}", type=type, timestamp=None,
                                 raw=raw, data=data))
        n += 1

    def add_reasoning(text: str, role: str) -> None:
        # Codex records each assistant utterance twice (event_msg agent_message
        # AND response_item message/assistant); collapse the duplicate.
        key = (text or "").strip()
        if key and key in seen_text:
            return
        if key:
            seen_text.add(key)
        add("reasoning", {"text": text, "role": role})

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            add("unknown", {}, raw={"line": line})
            continue

        ttype = obj.get("type")
        payload = obj.get("payload", {}) or {}

        if ttype == "session_meta":
            trace.run_id = payload.get("session_id") or payload.get("id")
            bi = payload.get("base_instructions")
            trace.seed["system_prompt"] = bi.get("text") if isinstance(bi, dict) else bi
            continue
        if ttype == "turn_context":
            continue  # per-turn config, not a visible event

        ptype = payload.get("type")
        if ptype == "agent_message":
            add_reasoning(payload.get("message", ""), "agent_message")
        elif ptype == "user_message":
            if not trace.seed.get("user_input"):
                trace.seed["user_input"] = payload.get("message", "")
        elif ptype == "message":
            # response_item message: role-tagged, text split across content[]
            role = payload.get("role")
            text = _message_text(payload)
            if role == "assistant":
                add_reasoning(text, "assistant")
            elif role == "user":
                if not trace.seed.get("user_input"):
                    trace.seed["user_input"] = text
            # developer/system/tool roles are instruction boilerplate — skip
        elif ptype == "function_call":
            add("tool_call", {"name": payload.get("name", ""),
                              "arguments": payload.get("arguments", ""),
                              "call_id": payload.get("call_id")})
        elif ptype == "function_call_output":
            add("tool_result", {"output": payload.get("output", ""),
                                "call_id": payload.get("call_id")})
        elif ptype == "reasoning":
            # encrypted, empty summary — no readable CoT to recover
            if not noted_encrypted:
                add("meta", {"note": "reasoning encrypted — unavailable in rollout"},
                    raw=obj)
                noted_encrypted = True
        elif ptype in ("token_count", "task_started", "task_complete"):
            continue  # bookkeeping noise
        else:
            add("unknown", {"item_type": ptype}, raw=obj)

    return trace


def _message_text(payload: dict) -> str:
    parts = []
    for chunk in payload.get("content", []) or []:
        if isinstance(chunk, dict) and chunk.get("text"):
            parts.append(chunk["text"])
    return "\n".join(parts)
