"""Public streaming capture entry point.

The host feeds Codex `--json` stdout lines in one at a time, then calls
`finish()` for the Trace. This is the primary embed path: the host keeps
its own run loop and only tees each line here.
"""

from __future__ import annotations

from agenttrace.adapters.codex import CodexStreamParser
from agenttrace.model import Trace


class Collector:
    def __init__(self, agent: str = "codex", *, user_input: str | None = None,
                 system_prompt: str | None = None):
        if agent != "codex":
            raise ValueError(f"unknown agent: {agent!r}")
        self.agent = agent
        self._parser = CodexStreamParser(user_input=user_input,
                                         system_prompt=system_prompt)

    def feed(self, line: str) -> None:
        self._parser.feed(line)

    def finish(self) -> Trace:
        return self._parser.finish()
