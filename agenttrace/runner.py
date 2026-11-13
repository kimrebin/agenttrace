"""Convenience entry point that launches Codex itself and captures it.

For embedding where the host does not already run Codex, this spawns
`codex exec --json`, injects the reasoning-summary config (without which
the readable reasoning never appears), and closes stdin (otherwise Codex
blocks waiting for input). `launcher` is injectable for testing.
"""

from __future__ import annotations

import subprocess
from typing import Callable, Iterable

from agenttrace.collector import Collector
from agenttrace.model import Trace


def _subprocess_launcher(argv: list[str]) -> Iterable[str]:
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            yield line
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        proc.wait()


def run_codex(prompt: str, *, reasoning: str = "detailed",
              model: str | None = None,
              launcher: Callable[[list[str]], Iterable[str]] = _subprocess_launcher
              ) -> Trace:
    argv = ["codex", "exec", "--json", "-c",
            f"model_reasoning_summary={reasoning}"]
    if model:
        argv += ["-m", model]
    argv.append(prompt)

    collector = Collector(agent="codex", user_input=prompt)
    for line in launcher(argv):
        collector.feed(line)
    return collector.finish()
