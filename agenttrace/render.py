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
_DIFF_SLOT = "__DIFF_PANEL__"


def _embed(trace: Trace) -> str:
    return trace.to_json().replace("<", "\\u003c")


def render(trace: Trace, *, compare_to: Trace | None = None) -> str:
    """Render the full trace timeline as one self-contained HTML page. When
    `compare_to` is given, a collapsible "프롬프트 변경점" (prompt diff) panel
    against that trace is embedded at the top of the SAME page."""
    template = _TEMPLATE.read_text(encoding="utf-8")
    panel = _diff_panel(compare_to, trace) if compare_to is not None else ""
    return template.replace(_DIFF_SLOT, panel).replace(_PLACEHOLDER, _embed(trace))


def render_to_file(trace: Trace, path: str, *, compare_to: Trace | None = None) -> None:
    Path(path).write_text(render(trace, compare_to=compare_to), encoding="utf-8")


def render_iframe(trace: Trace, *, height: str = "600px",
                  title: str = "agenttrace", compare_to: Trace | None = None) -> str:
    """Return a ready-to-embed `<iframe srcdoc=...>` snippet for dropping the
    trace into one panel of a host web dashboard. The full self-contained
    document is HTML-escaped into the `srcdoc` attribute, so it is style- and
    script-isolated from the host page and needs no separate file. `compare_to`
    adds the prompt-diff panel in the same embedded page."""
    doc = html.escape(render(trace, compare_to=compare_to), quote=True)
    return ('<iframe title="%s" style="width:100%%;height:%s;border:0" '
            'srcdoc="%s"></iframe>' % (html.escape(title, quote=True), height, doc))


def _diff_panel(trace_a: Trace, trace_b: Trace) -> str:
    """A collapsible prompt-diff fragment for embedding inside the trace page."""
    return ('<details class="diffpanel" open><summary>프롬프트 변경점</summary>'
            '<div class="cols">%s</div></details>' % _diff_body(trace_a, trace_b))


_DIFF_DOC = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agenttrace diff</title>
<style>
  body { margin: 0; background: #ffffff; color: #0b0e14;
         font: 500 14px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }
  @media (prefers-color-scheme: dark) { body { background: #0d0f13; color: #f4f6f8; } }
  h1 { font-size: 18px; padding: 16px 16px 0; }
  .cols { display: flex; gap: 2%; padding: 16px; }
  .diff-col { width: 49%; min-width: 0; }
  .diff-col h3 { margin: 0 0 8px; font-size: 13px; font-weight: 700; color: #4b5563; }
  @media (prefers-color-scheme: dark) { .diff-col h3 { color: #aeb6c2; } }
  .diff-col > div { white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;
                    padding: 2px 5px; border-radius: 3px;
                    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
                    font-size: 13px; font-weight: 500; }
  .diff-add { background: rgba(22,163,74,0.30); }
  .diff-del { background: rgba(220,38,38,0.30); }
  @media (prefers-color-scheme: dark) {
    .diff-add { background: rgba(34,197,94,0.32); }
    .diff-del { background: rgba(248,113,113,0.32); }
  }
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


def _diff_body(trace_a: Trace, trace_b: Trace) -> str:
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
    return _column("A", left) + _column("B", right)


def diff(trace_a: Trace, trace_b: Trace) -> str:
    """Standalone self-contained prompt-diff page (A vs B seed prompts)."""
    return _DIFF_DOC.replace("__DIFF_BODY__", _diff_body(trace_a, trace_b))
