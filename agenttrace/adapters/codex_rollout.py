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

    def add(type: str, data: dict, raw: dict | None = None) -> None:
        nonlocal n
        turn.events.append(Event(id=f"e{n}", type=type, timestamp=None,
                                 raw=raw, data=data))
        n += 1

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
            trace.run_id = payload.get("session_id")
            bi = payload.get("base_instructions")
            trace.seed["system_prompt"] = bi.get("text") if isinstance(bi, dict) else bi
            continue

        ptype = payload.get("type")
        if ptype == "agent_message":
            add("reasoning", {"text": payload.get("message", ""),
                              "role": "agent_message"})
        elif ptype == "function_call":
            add("tool_call", {"name": payload.get("name", ""),
                              "arguments": payload.get("arguments", "")})
        elif ptype == "function_call_output":
            add("tool_result", {"output": payload.get("output", "")})
        elif ptype == "reasoning":
            # encrypted, empty summary — no readable CoT to recover
            if not noted_encrypted:
                add("meta", {"note": "reasoning encrypted — unavailable in rollout"},
                    raw=obj)
                noted_encrypted = True
        else:
            add("unknown", {}, raw=obj)

    return trace
