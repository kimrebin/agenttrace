"""Render a Trace into a self-contained HTML timeline.

The Trace JSON is embedded directly as a JS value; every `<` is escaped
to `\\u003c` so no string value (e.g. a tool output containing
`</script>`) can terminate the script context. The viewer inserts all
text via `textContent`, so embedded HTML stays inert.
"""

from __future__ import annotations

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
