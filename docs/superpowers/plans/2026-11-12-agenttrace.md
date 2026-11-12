# agenttrace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture a Codex agent run (reasoning + tool trace) and render it as a self-contained HTML timeline for prompt debugging, usable as an embeddable Python library and a thin CLI.

**Architecture:** Single-direction 4-layer pipeline — Codex `codex exec --json` stdout (or a saved rollout file) → adapter (stream/rollout parser) → normalized `Trace` model (agent-neutral, JSON-serializable) → HTML renderer. Capture and render are decoupled via the serializable `Trace`. The library's primary embed path is a `Collector` the host feeds stdout lines into.

**Tech Stack:** Python 3.10+, standard library only (`dataclasses`, `json`, `subprocess`, `difflib`, `html`, `argparse`, `pathlib`). Viewer is inline HTML/CSS/JS with no external/CDN assets. Tests: `pytest`.

**Spec:** `docs/superpowers/specs/2026-11-12-agenttrace-design.md`

## Global Constraints

- Python 3.10+; **no third-party runtime dependencies** (stdlib only). `pytest` is dev-only.
- All file/stream reads and writes use **UTF-8 explicitly**.
- The output HTML is **fully self-contained** (Trace JSON + JS + CSS inline; no network/CDN references).
- Reasoning shown in the viewer is labeled **"요약"** (it is a summary, not raw chain-of-thought).
- `run_codex` must launch Codex with `-c model_reasoning_summary="detailed"` (and a non-minimal `model_reasoning_effort`) and must **close the child's stdin**, or Codex hangs waiting for stdin input.
- Robustness rule (applies to the adapter everywhere): a bad line or unknown event is preserved as raw data and processing continues — never crash.

## Review Focus

- **Malformed JSON line mid-stream** → parser keeps going, records it as an `unknown` event carrying the raw text, rest of the Trace is intact. (Task 2)
- **Truncated stream (Codex died / host stopped early)** → `finish()` returns the partial Trace with `incomplete=True`. (Task 2)
- **Unknown `item.type` from a newer Codex version** → preserved as a generic event (raw kept), no crash, renders generically. (Task 2)
- **Reasoning/tool text containing `</script>`, HTML, or non-ASCII (Korean)** → must not break the rendered page; JSON is embedded unbreakably and text is escaped; UTF-8 round-trips. (Task 6)
- **A turn with no readable reasoning (summary config off, or an encrypted rollout)** → viewer shows an honest "추론 요약 없음" notice, never fabricated reasoning. (Task 6)

---

### Task 1: Core Trace model + JSON serialization

**Files:**
- Create: `agenttrace/__init__.py` (empty for now)
- Create: `agenttrace/model.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Produces: dataclasses `Event(id: str, type: str, timestamp: str | None, raw: dict | None, data: dict)`, `Turn(seq: int, events: list[Event], meta: dict)`, `Trace(run_id: str | None, agent: str, seed: dict, turns: list[Turn], incomplete: bool, started_at: str | None, ended_at: str | None, meta: dict)`. `type` is one of `reasoning|tool_call|tool_result|error|meta|unknown`. Payload specifics live in `Event.data` (reasoning text at `data["text"]`; agent commentary at `data["text"]` with `data["role"]="agent_message"`; tool call at `data["name"]`/`data["arguments"]`; tool result at `data["output"]` and optional `data["sub_trace"]`). `seed` is `{"system_prompt": str | None, "user_input": str | None}`.
- Produces: `Trace.to_dict() -> dict`, `Trace.from_dict(d: dict) -> Trace`, `Trace.to_json() -> str`, `Trace.from_json(s: str) -> Trace` (UTF-8, `ensure_ascii=False`).

- [ ] **Step 1: Write the failing test**

```python
def test_trace_json_round_trip():
    tr = Trace(run_id="r1", agent="codex",
               seed={"system_prompt": None, "user_input": "안녕"},
               turns=[Turn(seq=0, events=[Event(id="e0", type="reasoning",
                           timestamp=None, raw=None, data={"text": "요약"})], meta={})],
               incomplete=False, started_at=None, ended_at=None, meta={})
    back = Trace.from_json(tr.to_json())
    assert back == tr
    assert "안녕" in tr.to_json()  # ensure_ascii=False keeps UTF-8 readable

def test_from_dict_tolerates_missing_optionals():
    tr = Trace.from_dict({"agent": "codex", "turns": []})
    assert tr.agent == "codex" and tr.turns == [] and tr.incomplete is False
```

- [ ] **Step 2: Run tests, verify they fail** — `pytest tests/test_model.py -v` → FAIL (import/definition error)

- [ ] **Step 3: Implement the dataclasses and (de)serialization in `agenttrace/model.py`.** Use `@dataclass`; `to_dict` via a recursive walk (or `dataclasses.asdict`), `from_dict` constructing nested objects with `.get` defaults so missing optionals don't raise. JSON uses `ensure_ascii=False`.

- [ ] **Step 4: Run tests, verify they pass** — `pytest tests/test_model.py -v` → PASS

- [ ] **Step 5: Commit** — `git add agenttrace/ tests/test_model.py && git commit -m "feat: core Trace model with JSON serialization"`

---

### Task 2: Codex stream parser (thread/turn/reasoning/message + robustness)

**Files:**
- Create: `agenttrace/adapters/__init__.py`
- Create: `agenttrace/adapters/codex.py`
- Create: `tests/fixtures/codex_stream_basic.jsonl` (real probe output, below)
- Test: `tests/test_codex_parser.py`

**Interfaces:**
- Consumes: `agenttrace.model` (Task 1).
- Produces: class `CodexStreamParser` with `feed(line: str) -> None` and `finish() -> Trace`; convenience `parse_stream(lines: Iterable[str], *, user_input: str | None = None, system_prompt: str | None = None) -> Trace`. Mapping: `thread.started` → `run_id` + start Trace; `turn.started`/`turn.completed` → open/close a `Turn` (usage into `turn.meta["usage"]`); `item.completed` with `item.type == "reasoning"` → `reasoning` event (`data["text"]`); `item.type == "agent_message"` → `reasoning` event with `data["role"]="agent_message"`; any other/unknown `item.type` → `unknown` event with `raw` set; a line that is not valid JSON → `unknown` event with `raw={"line": <text>}` on the current (or an implicit first) turn. `seed` is filled from the arguments (the `--json` stream does not carry the system prompt). `finish()` sets `incomplete=True` if a `turn.started` had no matching `turn.completed`.
- Produces: `load(path: str, *, user_input=None, system_prompt=None) -> Trace` — for this task, parses a saved **`--json` stream** file via `parse_stream`. (Task 4 extends `load` to also auto-detect rollout files.)

- [ ] **Step 1: Create the fixture `tests/fixtures/codex_stream_basic.jsonl`** with these exact lines (captured from a real `codex exec --json` run):

```
{"type":"thread.started","thread_id":"01a1cec6-5f08-7152-a821-a9b8ef1a2ca4"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"reasoning","text":"**Arranging house colors with milk constraint**"}}
{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"The ball costs $0.05."}}
{"type":"turn.completed","usage":{"input_tokens":15357,"reasoning_output_tokens":89}}
```

- [ ] **Step 2: Write the failing tests**

```python
def test_parses_basic_stream():
    tr = parse_stream(open("tests/fixtures/codex_stream_basic.jsonl", encoding="utf-8"),
                      user_input="puzzle")
    assert tr.run_id == "01a1cec6-5f08-7152-a821-a9b8ef1a2ca4"
    assert tr.agent == "codex"
    assert tr.seed["user_input"] == "puzzle"
    assert len(tr.turns) == 1 and tr.turns[0].seq == 0
    assert [e.type for e in tr.turns[0].events] == ["reasoning", "reasoning"]
    assert tr.turns[0].events[0].data["text"].startswith("**Arranging")
    assert tr.turns[0].events[1].data["role"] == "agent_message"
    assert tr.turns[0].meta["usage"]["reasoning_output_tokens"] == 89
    assert tr.incomplete is False

def test_malformed_line_becomes_unknown_event_and_continues():
    lines = ['{"type":"thread.started","thread_id":"x"}', '{"type":"turn.started"}',
             'NOT JSON {{{', '{"type":"turn.completed"}']
    tr = parse_stream(lines)
    assert any(e.type == "unknown" for e in tr.turns[0].events)
    assert tr.incomplete is False

def test_unknown_item_type_preserved():
    lines = ['{"type":"turn.started"}',
             '{"type":"item.completed","item":{"type":"future_thing","blob":1}}']
    tr = parse_stream(lines)
    ev = tr.turns[0].events[-1]
    assert ev.type == "unknown" and ev.raw["item"]["type"] == "future_thing"

def test_truncated_stream_marks_incomplete():
    lines = ['{"type":"thread.started","thread_id":"x"}', '{"type":"turn.started"}']
    tr = parse_stream(lines)
    assert tr.incomplete is True
```

- [ ] **Step 3: Run tests, verify they fail** — `pytest tests/test_codex_parser.py -v`

- [ ] **Step 4: Implement `CodexStreamParser`, `parse_stream`, `load` in `agenttrace/adapters/codex.py`.** `feed` parses one line in try/except (JSON error → unknown event); dispatch on top-level `type`; keep a current open `Turn`; events before any `turn.started` attach to an implicit turn 0. `finish` closes state and sets `incomplete`.

- [ ] **Step 5: Run tests, verify they pass** — `pytest tests/test_codex_parser.py -v` → PASS

- [ ] **Step 6: Commit** — `git add agenttrace/adapters tests/test_codex_parser.py tests/fixtures/codex_stream_basic.jsonl && git commit -m "feat: codex stream parser with robustness handling"`

---

### Task 3: Codex tool-call / tool-result mapping

**Files:**
- Modify: `agenttrace/adapters/codex.py`
- Create: `tests/fixtures/codex_stream_tools.jsonl` (captured in Step 1)
- Test: `tests/test_codex_tools.py`

**Interfaces:**
- Consumes: `CodexStreamParser` (Task 2).
- Produces: extends `item.completed` handling so tool-call items become `tool_call` events (`data["name"]`, `data["arguments"]`) and tool-output items become `tool_result` events (`data["output"]`). The exact `item.type` strings/fields are confirmed from the fixture captured in Step 1; map those, keep the Task 2 unknown-fallback for anything still unrecognized.

- [ ] **Step 1: Capture the tool fixture.** Run (requires a working `codex` login; read-only sandbox; writes no project files):

```bash
codex exec --json --sandbox read-only -c model_reasoning_summary="detailed" \
  "List the files in the current directory, then tell me how many there are." \
  < /dev/null > tests/fixtures/codex_stream_tools.jsonl
```

Inspect the file; note the `item.type` value(s) used for shell/command execution and their field names (command, output, exit code).

- [ ] **Step 2: Write the failing tests**

```python
def test_tool_call_and_result_mapped():
    tr = parse_stream(open("tests/fixtures/codex_stream_tools.jsonl", encoding="utf-8"))
    kinds = [e.type for e in tr.turns[0].events]
    assert "tool_call" in kinds and "tool_result" in kinds
    call = next(e for e in tr.turns[0].events if e.type == "tool_call")
    assert call.data["name"]
```

- [ ] **Step 3: Run tests, verify they fail** — `pytest tests/test_codex_tools.py -v`

- [ ] **Step 4: Implement the tool mapping** in `codex.py` using the `item.type`/fields observed in Step 1.

- [ ] **Step 5: Run tests, verify they pass** — `pytest tests/test_codex_tools.py -v` → PASS

- [ ] **Step 6: Commit** — `git add agenttrace/adapters/codex.py tests/test_codex_tools.py tests/fixtures/codex_stream_tools.jsonl && git commit -m "feat: map codex tool calls and results"`

---

### Task 4: Rollout-file replay (post-hoc, degraded reasoning) + `load` auto-detect

**Files:**
- Create: `agenttrace/adapters/codex_rollout.py`
- Modify: `agenttrace/adapters/codex.py` (make `load` auto-detect format and delegate)
- Create: `tests/fixtures/codex_rollout.jsonl`
- Test: `tests/test_rollout.py`

**Interfaces:**
- Consumes: `agenttrace.model` (Task 1).
- Produces: `parse_rollout(lines: Iterable[str]) -> Trace` — parses the `~/.codex/sessions/.../rollout-*.jsonl` schema (top-level `{timestamp, type, payload}`). Mapping: `session_meta` → `run_id = payload.session_id`, `seed.system_prompt = payload.base_instructions.text`; `payload.type == "agent_message"` → `reasoning` event with `data["role"]="agent_message"`; `payload.type == "function_call"` → `tool_call` (`data["name"]`, `data["arguments"]`); `payload.type == "function_call_output"` → `tool_result` (`data["output"]`); `payload.type == "reasoning"` (encrypted, empty summary) → **omitted** (no readable CoT) and a one-time `meta` event `data["note"]="reasoning encrypted — unavailable in rollout"`; all events grouped into a single `Turn` (seq 0) for v1. `load` (in `codex.py`) peeks the first non-empty line: if it has a `payload` key → `parse_rollout`, else → `parse_stream`.

- [ ] **Step 1: Create the fixture `tests/fixtures/codex_rollout.jsonl`** (minimal, real schema):

```
{"timestamp":"2026-07-24T09:59:32Z","type":"session_meta","payload":{"session_id":"019f938e","cwd":"D:/x","cli_version":"0.142.5","base_instructions":{"text":"You are Codex, a coding agent."}}}
{"timestamp":"2026-07-24T09:59:40Z","type":"response_item","payload":{"type":"reasoning","summary":[],"encrypted_content":"gAAAAAB_encrypted_blob=="}}
{"timestamp":"2026-07-24T09:59:41Z","type":"event_msg","payload":{"type":"agent_message","message":"I'll list the files.","phase":"commentary"}}
{"timestamp":"2026-07-24T09:59:42Z","type":"response_item","payload":{"type":"function_call","id":"fc_1","name":"shell_command","arguments":"{\"command\":\"ls\"}","call_id":"call_1"}}
{"timestamp":"2026-07-24T09:59:44Z","type":"response_item","payload":{"type":"function_call_output","call_id":"call_1","output":"Exit code: 0\nfile.txt"}}
```

- [ ] **Step 2: Write the failing tests**

```python
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
```

- [ ] **Step 3: Run tests, verify they fail** — `pytest tests/test_rollout.py -v`

- [ ] **Step 4: Implement `parse_rollout` and the `load` auto-detect/delegate.**

- [ ] **Step 5: Run tests, verify they pass** — `pytest tests/test_rollout.py -v` → PASS

- [ ] **Step 6: Commit** — `git add agenttrace/adapters tests/test_rollout.py tests/fixtures/codex_rollout.jsonl && git commit -m "feat: codex rollout replay with load auto-detect"`

---

### Task 5: Public capture API — `Collector`, `run_codex`

**Files:**
- Create: `agenttrace/collector.py`
- Create: `agenttrace/runner.py`
- Modify: `agenttrace/__init__.py` (export public names)
- Test: `tests/test_collector.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: `CodexStreamParser`, `parse_stream`, `load` (Tasks 2–4).
- Produces: `Collector(agent: str = "codex", *, user_input: str | None = None, system_prompt: str | None = None)` with `.feed(line: str)` and `.finish() -> Trace` (delegates to the agent's stream parser; unknown `agent` raises `ValueError`). `run_codex(prompt: str, *, reasoning: str = "detailed", model: str | None = None, launcher: Callable[[list[str]], Iterable[str]] = _subprocess_launcher) -> Trace` — builds the `codex exec --json` argv (injecting `-c model_reasoning_summary=<reasoning>`), streams lines through a `Collector`, sets `seed.user_input=prompt`; `launcher` is injectable for tests. Re-export `Collector`, `run_codex`, `load` from `agenttrace/__init__.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_collector_feed_finish():
    c = Collector(agent="codex", user_input="puzzle")
    for line in open("tests/fixtures/codex_stream_basic.jsonl", encoding="utf-8"):
        c.feed(line)
    tr = c.finish()
    assert tr.run_id and tr.seed["user_input"] == "puzzle"

def test_collector_rejects_unknown_agent():
    with pytest.raises(ValueError):
        Collector(agent="nope")

def test_run_codex_uses_injected_launcher_and_sets_seed():
    captured = {}
    def fake_launcher(argv):
        captured["argv"] = argv
        return list(open("tests/fixtures/codex_stream_basic.jsonl", encoding="utf-8"))
    tr = run_codex("puzzle", launcher=fake_launcher)
    assert tr.seed["user_input"] == "puzzle"
    assert "--json" in captured["argv"]
    assert any("model_reasoning_summary" in a for a in captured["argv"])
```

- [ ] **Step 2: Run tests, verify they fail** — `pytest tests/test_collector.py tests/test_runner.py -v`

- [ ] **Step 3: Implement `Collector` (collector.py) and `run_codex` + `_subprocess_launcher` (runner.py).** `_subprocess_launcher` runs `codex exec --json ...` with `stdin=subprocess.DEVNULL`, yielding decoded UTF-8 stdout lines. Export from `__init__.py`.

- [ ] **Step 4: Run tests, verify they pass** — `pytest tests/test_collector.py tests/test_runner.py -v` → PASS

- [ ] **Step 5: Commit** — `git add agenttrace tests/test_collector.py tests/test_runner.py && git commit -m "feat: public capture API (Collector, run_codex)"`

---

### Task 6: HTML renderer (self-contained timeline viewer)

**Files:**
- Create: `agenttrace/viewer/template.html` (inline CSS + JS; placeholder token `__TRACE_JSON__`)
- Create: `agenttrace/render.py`
- Modify: `agenttrace/__init__.py` (export `render`, `render_to_file`)
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `agenttrace.model` (Task 1).
- Produces: `render(trace: Trace) -> str` (full self-contained HTML) and `render_to_file(trace: Trace, path: str) -> None` (UTF-8). `render` embeds the Trace by replacing `__TRACE_JSON__` with its JSON, escaped so it cannot terminate the script context (replace `<` with `\u003c`). The inline JS builds the DOM timeline: turns as ordered collapsible blocks (`seq` shown), events in list order; `reasoning` styled with a "요약" label, `tool_call`/`tool_result` distinct (result collapsed by default), `error` emphasized, `meta`/`unknown` muted; a turn with zero `reasoning` events renders an "추론 요약 없음" notice. All event text is inserted via `textContent` (never `innerHTML`) so embedded HTML/`</script>` is inert.

- [ ] **Step 1: Write the failing tests**

```python
def test_render_embeds_trace_and_is_self_contained():
    html = render(_sample_trace())
    assert "__TRACE_JSON__" not in html
    assert "http://" not in html and "https://" not in html   # no external assets
    assert "요약" in html

def test_render_escapes_script_breakout():
    tr = _trace_with_reasoning_text("</script><img src=x onerror=alert(1)>")
    html = render(tr)
    assert "</script><img" not in html
    assert "u003c/script" in html                              # escaped in embedded JSON

def test_render_shows_no_reasoning_notice():
    tr = _trace_with_only_tool_events()                        # a turn with no reasoning
    assert "추론 요약 없음" in render(tr)

def test_render_to_file_is_utf8(tmp_path):
    p = tmp_path / "out.html"
    render_to_file(_trace_with_reasoning_text("한국어 요약"), str(p))
    assert "한국어 요약" in p.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests, verify they fail** — `pytest tests/test_render.py -v`

- [ ] **Step 3: Build `template.html`** (timeline CSS + a JS `render(trace)` walking turns/events per the Interfaces block, using `textContent`) and **implement `render`/`render_to_file`** in `render.py` (read template UTF-8, substitute escaped JSON). The "추론 요약 없음" string lives in the JS, emitted per reasoning-less turn.

- [ ] **Step 4: Run tests, verify they pass** — `pytest tests/test_render.py -v` → PASS

- [ ] **Step 5: Manually open a rendered file once** to confirm the timeline displays (`agenttrace.render_to_file(agenttrace.load("tests/fixtures/codex_rollout.jsonl"), "sample.html")`, open in a browser). Not a blocker if tests pass; delete `sample.html` after.

- [ ] **Step 6: Commit** — `git add agenttrace/render.py agenttrace/viewer agenttrace/__init__.py tests/test_render.py && git commit -m "feat: self-contained HTML timeline renderer"`

---

### Task 7: Prompt diff view

**Files:**
- Modify: `agenttrace/render.py`
- Modify: `agenttrace/__init__.py` (export `diff`)
- Test: `tests/test_diff.py`

**Interfaces:**
- Consumes: `Trace` (Task 1), `render` helpers (Task 6).
- Produces: `diff(trace_a: Trace, trace_b: Trace) -> str` — self-contained HTML showing the two `seed` prompts (system + user) side by side with line-level diff highlighting via `difflib`; added/removed lines carry `diff-add`/`diff-del` CSS classes. Reuses the template's styling and the same `<`-escaping.

- [ ] **Step 1: Write the failing test**

```python
def test_diff_marks_changed_prompt_lines():
    a = _trace_with_user_input("find the bug\nbe careful")
    b = _trace_with_user_input("find the bug\nbe very careful")
    html = diff(a, b)
    assert "be careful" in html and "be very careful" in html
    assert 'class="diff-add"' in html and 'class="diff-del"' in html
```

- [ ] **Step 2: Run test, verify it fails** — `pytest tests/test_diff.py -v`

- [ ] **Step 3: Implement `diff`** using `difflib.SequenceMatcher`/`ndiff` over the seed prompt lines; emit escaped side-by-side HTML with the diff classes.

- [ ] **Step 4: Run test, verify it passes** — `pytest tests/test_diff.py -v` → PASS

- [ ] **Step 5: Commit** — `git add agenttrace/render.py agenttrace/__init__.py tests/test_diff.py && git commit -m "feat: prompt diff view"`

---

### Task 8: CLI

**Files:**
- Create: `agenttrace/cli.py`
- Modify: `agenttrace/__init__.py` (expose `main`)
- Create: `pyproject.toml`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_codex`, `load`, `render_to_file`, `diff` (Tasks 5–7).
- Produces: `main(argv: list[str]) -> int` with subcommands: `replay <path> -o <out.html>` (load → render_to_file; `load` auto-detects stream vs rollout), `diff <A> <B> -o <out.html>` (load both → diff → write), `run <prompt> -o <out.html>` (run_codex → render_to_file). Thin: each subcommand is a few library calls, no logic of its own. `pyproject.toml` declares the package (Python ≥3.10, no runtime deps) and `[project.scripts] agenttrace = "agenttrace.cli:main"`.

- [ ] **Step 1: Write the failing tests** (avoid live Codex — test `replay` and `diff` on fixtures):

```python
def test_cli_replay_writes_html(tmp_path):
    out = tmp_path / "o.html"
    rc = main(["replay", "tests/fixtures/codex_rollout.jsonl", "-o", str(out)])
    assert rc == 0 and "<html" in out.read_text(encoding="utf-8").lower()

def test_cli_diff_writes_html(tmp_path):
    out = tmp_path / "d.html"
    rc = main(["diff", "tests/fixtures/codex_stream_basic.jsonl",
               "tests/fixtures/codex_stream_basic.jsonl", "-o", str(out)])
    assert rc == 0 and out.exists()
```

- [ ] **Step 2: Run tests, verify they fail** — `pytest tests/test_cli.py -v`

- [ ] **Step 3: Implement `main` with `argparse`** in `cli.py`; write `pyproject.toml` with the script entry.

- [ ] **Step 4: Run tests, verify they pass** — `pytest tests/test_cli.py -v` → PASS

- [ ] **Step 5: Run the full suite** — `pytest -v` → all PASS

- [ ] **Step 6: Commit** — `git add agenttrace/cli.py agenttrace/__init__.py pyproject.toml tests/test_cli.py && git commit -m "feat: agenttrace CLI"`
