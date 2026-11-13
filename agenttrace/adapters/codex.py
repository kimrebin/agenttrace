"""Codex adapter: turn a `codex exec --json` event stream into a Trace.

This is the only layer that knows Codex's wire format. Anything it does
not recognize is preserved as an `unknown` event and never crashes the
parse (robustness rule).
"""

from __future__ import annotations

import json
from typing import Iterable

from agenttrace.model import Trace, Turn, Event


class CodexStreamParser:
    """Incremental parser: feed() one JSONL line at a time, then finish()."""

    def __init__(self, *, user_input: str | None = None,
                 system_prompt: str | None = None):
        self._trace = Trace(
            run_id=None, agent="codex",
            seed={"system_prompt": system_prompt, "user_input": user_input},
            turns=[], incomplete=False)
        self._cur: Turn | None = None
        self._turn_open = False
        self._event_n = 0

    # -- internal helpers -------------------------------------------------
    def _ensure_turn(self) -> Turn:
        if self._cur is None:
            self._cur = Turn(seq=len(self._trace.turns), events=[], meta={})
            self._trace.turns.append(self._cur)
        return self._cur

    def _add_event(self, type: str, data: dict, raw: dict | None = None) -> None:
        turn = self._ensure_turn()
        turn.events.append(Event(id=f"e{self._event_n}", type=type,
                                 timestamp=None, raw=raw, data=data))
        self._event_n += 1

    # -- public API -------------------------------------------------------
    def feed(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            self._add_event("unknown", {}, raw={"line": line})
            return

        etype = obj.get("type")
        if etype == "thread.started":
            self._trace.run_id = obj.get("thread_id")
        elif etype == "turn.started":
            self._cur = Turn(seq=len(self._trace.turns), events=[], meta={})
            self._trace.turns.append(self._cur)
            self._turn_open = True
        elif etype == "turn.completed":
            turn = self._ensure_turn()
            if "usage" in obj:
                turn.meta["usage"] = obj["usage"]
            self._turn_open = False
        elif etype == "item.completed":
            self._handle_item(obj.get("item", {}) or {})
        elif etype == "item.started":
            # streaming start half of an item.completed; ignore the duplicate
            return
        # anything else: preserve without crashing
        else:
            self._add_event("meta", {"note": str(etype)}, raw=obj)

    def _handle_item(self, item: dict) -> None:
        itype = item.get("type")
        if itype == "reasoning":
            self._add_event("reasoning", {"text": item.get("text", "")})
        elif itype == "agent_message":
            self._add_event("reasoning",
                            {"text": item.get("text", ""), "role": "agent_message"})
        elif itype == "command_execution":
            # Codex combines call + result in one item; split into two events.
            self._add_event("tool_call",
                            {"name": "command_execution",
                             "arguments": item.get("command", "")})
            self._add_event("tool_result",
                            {"output": item.get("aggregated_output", ""),
                             "exit_code": item.get("exit_code")})
        else:
            self._add_event("unknown", {}, raw={"item": item})

    def finish(self) -> Trace:
        self._trace.incomplete = self._turn_open
        return self._trace


def parse_stream(lines: Iterable[str], *, user_input: str | None = None,
                 system_prompt: str | None = None) -> Trace:
    parser = CodexStreamParser(user_input=user_input, system_prompt=system_prompt)
    for line in lines:
        parser.feed(line)
    return parser.finish()


def load(path: str, *, user_input: str | None = None,
         system_prompt: str | None = None) -> Trace:
    """Parse a saved `--json` stream file. (Task 4 extends this to also
    auto-detect rollout files.)"""
    with open(path, encoding="utf-8") as f:
        return parse_stream(f, user_input=user_input, system_prompt=system_prompt)
