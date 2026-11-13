"""Render a Trace into a self-contained HTML timeline.

The Trace JSON is embedded directly as a JS value; every `<` is escaped
to `\\u003c` so no string value (e.g. a tool output containing
`</script>`) can terminate the script context. The viewer inserts all
text via `textContent`, so embedded HTML stays inert.
"""

from __future__ import annotations

import difflib
import html
from pathlib import Path

from agenttrace.model import Trace

_TEMPLATE = Path(__file__).parent / "viewer" / "template.html"
_PLACEHOLDER = "__TRACE_JSON__"


def _embed(trace: Trace) -> str:
    return trace.to_json().replace("<", "\\u003c")


def render(trace: Trace) -> str:
    template = _TEMPLATE.read_text(encoding="utf-8")
    return template.replace(_PLACEHOLDER, _embed(trace))


def render_to_file(trace: Trace, path: str) -> None:
    Path(path).write_text(render(trace), encoding="utf-8")


_DIFF_DOC = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agenttrace diff</title>
<style>
  body { margin: 0; background: #fff; color: #1a1a1a;
         font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  @media (prefers-color-scheme: dark) { body { background: #0f1115; color: #e5e7eb; } }
  h1 { font-size: 18px; padding: 16px 16px 0; }
  .cols { display: flex; gap: 2%; padding: 16px; }
  .diff-col { width: 49%; }
  .diff-col h3 { margin: 0 0 8px; font-size: 13px; color: #6b7280; }
  .diff-col > div { white-space: pre-wrap; padding: 1px 4px; font-family: ui-monospace, monospace; }
  .diff-add { background: rgba(34,197,94,0.20); }
  .diff-del { background: rgba(239,68,68,0.20); }
</style></head>
<body><h1>seed 프롬프트 diff</h1><div class="cols">__DIFF_BODY__</div></body></html>"""


def _seed_lines(trace: Trace) -> list[str]:
    seed = trace.seed or {}
    text = ""
    if seed.get("system_prompt"):
        text += seed["system_prompt"] + "\n"
    text += seed.get("user_input") or ""
    return text.split("\n")


def _column(title: str, lines: list[tuple[str, str]]) -> str:
    rows = "".join(
        '<div class="%s">%s</div>' % (cls, html.escape(text) or "&nbsp;")
        for cls, text in lines)
    return '<div class="diff-col"><h3>%s</h3>%s</div>' % (html.escape(title), rows)


def diff(trace_a: Trace, trace_b: Trace) -> str:
    la, lb = _seed_lines(trace_a), _seed_lines(trace_b)
    left: list[tuple[str, str]] = []
    right: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=la, b=lb).get_opcodes():
        if tag == "equal":
            left += [("", la[k]) for k in range(i1, i2)]
            right += [("", lb[k]) for k in range(j1, j2)]
        elif tag == "delete":
            left += [("diff-del", la[k]) for k in range(i1, i2)]
        elif tag == "insert":
            right += [("diff-add", lb[k]) for k in range(j1, j2)]
        elif tag == "replace":
            left += [("diff-del", la[k]) for k in range(i1, i2)]
            right += [("diff-add", lb[k]) for k in range(j1, j2)]
    body = _column("A", left) + _column("B", right)
    return _DIFF_DOC.replace("__DIFF_BODY__", body)
