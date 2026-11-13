# agenttrace 구현 계획

> **에이전트 작업자용:** 필수 서브스킬: 이 계획을 태스크 단위로 구현하려면 superpowers:subagent-driven-development(권장) 또는 superpowers:executing-plans를 사용하세요. 스텝은 체크박스(`- [ ]`) 구문으로 추적합니다.

**목표:** Codex 에이전트 실행(추론 + 도구 trace)을 캡처해 프롬프트 디버깅용 자체완결 HTML 타임라인으로 렌더한다. 임베드 가능한 Python 라이브러리 + 얇은 CLI로 제공한다.

**아키텍처:** 단방향 4층 파이프라인 — Codex `codex exec --json` stdout(또는 저장된 롤아웃 파일) → 어댑터(스트림/롤아웃 파서) → 정규화 `Trace` 모델(에이전트 중립, JSON 직렬화 가능) → HTML 렌더러. 캡처와 렌더는 직렬화 가능한 `Trace`로 분리된다. 라이브러리의 1순위 임베드 경로는 호스트가 stdout 줄을 넣어주는 `Collector`다.

**기술 스택:** Python 3.10+, 표준 라이브러리만(`dataclasses`, `json`, `subprocess`, `difflib`, `html`, `argparse`, `pathlib`). 뷰어는 inline HTML/CSS/JS로 외부/CDN 자원 없음. 테스트: `pytest`.

**스펙:** `docs/superpowers/specs/2026-11-12-agenttrace-design.md`

## 전역 제약 (Global Constraints)

- Python 3.10+; **서드파티 런타임 의존성 금지**(표준 라이브러리만). `pytest`는 개발용 전용.
- 모든 파일/스트림 읽기·쓰기는 **UTF-8 명시**.
- 출력 HTML은 **완전 자체완결**(Trace JSON + JS + CSS inline; 네트워크/CDN 참조 없음).
- 뷰어가 보여주는 추론은 **"요약"**으로 라벨링(원본 CoT가 아니라 요약임).
- `run_codex`는 Codex를 띄울 때 `-c model_reasoning_summary="detailed"`(및 minimal 이상의 `model_reasoning_effort`)를 주입하고, 자식 프로세스의 **stdin을 닫아야** 한다. 안 그러면 Codex가 stdin 입력을 기다리며 멈춘다.
- 견고성 규칙(어댑터 전반 적용): 깨진 줄이나 모르는 이벤트는 원본(raw)으로 보존하고 처리를 계속한다 — 절대 크래시 금지.

## 리뷰 포커스 (Review Focus)

- **스트림 중간의 깨진 JSON 줄** → 파서는 계속 진행, 그 줄을 원본 텍스트를 담은 `unknown` 이벤트로 기록, 나머지 Trace는 온전. (태스크 2)
- **잘린 스트림(Codex 사망 / 호스트 조기 중단)** → `finish()`가 `incomplete=True`인 부분 Trace 반환. (태스크 2)
- **새 Codex 버전의 모르는 `item.type`** → 제네릭 이벤트로 보존(raw 유지), 크래시 없음, 제네릭 렌더. (태스크 2)
- **추론/도구 텍스트에 `</script>`·HTML·비ASCII(한국어) 포함** → 렌더된 페이지가 깨지면 안 됨; JSON은 깨지지 않게 임베드하고 텍스트는 이스케이프; UTF-8 왕복. (태스크 6)
- **읽을 수 있는 추론이 없는 턴(요약 설정 off, 또는 암호화된 롤아웃)** → 뷰어가 정직한 "추론 요약 없음" 안내 표시, 가짜 추론 금지. (태스크 6)

---

### 태스크 1: 코어 Trace 모델 + JSON 직렬화

**파일:**
- 생성: `agenttrace/__init__.py` (지금은 비움)
- 생성: `agenttrace/model.py`
- 테스트: `tests/test_model.py`

**인터페이스:**
- 제공(produces): 데이터클래스 `Event(id: str, type: str, timestamp: str | None, raw: dict | None, data: dict)`, `Turn(seq: int, events: list[Event], meta: dict)`, `Trace(run_id: str | None, agent: str, seed: dict, turns: list[Turn], incomplete: bool, started_at: str | None, ended_at: str | None, meta: dict)`. `type`은 `reasoning|tool_call|tool_result|error|meta|unknown` 중 하나. 페이로드 세부는 `Event.data`에 담음(추론 텍스트는 `data["text"]`; 에이전트 코멘터리는 `data["text"]` + `data["role"]="agent_message"`; 도구 호출은 `data["name"]`/`data["arguments"]`; 도구 결과는 `data["output"]` + 선택적 `data["sub_trace"]`). `seed`는 `{"system_prompt": str | None, "user_input": str | None}`.
- 제공: `Trace.to_dict() -> dict`, `Trace.from_dict(d: dict) -> Trace`, `Trace.to_json() -> str`, `Trace.from_json(s: str) -> Trace` (UTF-8, `ensure_ascii=False`).

- [ ] **스텝 1: 실패하는 테스트 작성**

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

- [ ] **스텝 2: 테스트 실행, 실패 확인** — `pytest tests/test_model.py -v` → FAIL (import/정의 오류)

- [ ] **스텝 3: `agenttrace/model.py`에 데이터클래스와 (역)직렬화 구현.** `@dataclass` 사용; `to_dict`는 재귀 순회(또는 `dataclasses.asdict`), `from_dict`는 `.get` 기본값으로 중첩 객체 구성해 누락 옵션에도 안 터지게. JSON은 `ensure_ascii=False`.

- [ ] **스텝 4: 테스트 실행, 통과 확인** — `pytest tests/test_model.py -v` → PASS

- [ ] **스텝 5: 커밋** — `git add agenttrace/ tests/test_model.py && git commit -m "feat: core Trace model with JSON serialization"`

---

### 태스크 2: Codex 스트림 파서 (thread/turn/reasoning/message + 견고성)

**파일:**
- 생성: `agenttrace/adapters/__init__.py`
- 생성: `agenttrace/adapters/codex.py`
- 생성: `tests/fixtures/codex_stream_basic.jsonl` (아래의 실측 프로브 출력)
- 테스트: `tests/test_codex_parser.py`

**인터페이스:**
- 사용(consumes): `agenttrace.model` (태스크 1).
- 제공(produces): 클래스 `CodexStreamParser` — `feed(line: str) -> None`, `finish() -> Trace`; 편의 함수 `parse_stream(lines: Iterable[str], *, user_input: str | None = None, system_prompt: str | None = None) -> Trace`. 매핑: `thread.started` → `run_id` + Trace 시작; `turn.started`/`turn.completed` → `Turn` 열고/닫기(usage는 `turn.meta["usage"]`로); `item.completed`·`item.type == "reasoning"` → `reasoning` 이벤트(`data["text"]`); `item.type == "agent_message"` → `reasoning` 이벤트 + `data["role"]="agent_message"`; 그 외/모르는 `item.type` → `raw` 세팅한 `unknown` 이벤트; 유효하지 않은 JSON 줄 → 현재(또는 암묵적 첫) 턴에 `raw={"line": <text>}`인 `unknown` 이벤트. `seed`는 인자로 채움(`--json` 스트림은 시스템 프롬프트를 싣지 않음). `finish()`는 `turn.started`가 짝 `turn.completed` 없이 끝났으면 `incomplete=True`.
- 제공: `load(path: str, *, user_input=None, system_prompt=None) -> Trace` — 이 태스크에서는 저장된 **`--json` 스트림** 파일을 `parse_stream`으로 파싱. (태스크 4가 `load`에 롤아웃 자동감지를 추가함.)

- [ ] **스텝 1: 픽스처 `tests/fixtures/codex_stream_basic.jsonl` 생성** — 아래 줄 그대로(실제 `codex exec --json` 실행에서 캡처한 것):

```
{"type":"thread.started","thread_id":"01a1cec6-5f08-7152-a821-a9b8ef1a2ca4"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"reasoning","text":"**Arranging house colors with milk constraint**"}}
{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"The ball costs $0.05."}}
{"type":"turn.completed","usage":{"input_tokens":15357,"reasoning_output_tokens":89}}
```

- [ ] **스텝 2: 실패하는 테스트 작성**

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

- [ ] **스텝 3: 테스트 실행, 실패 확인** — `pytest tests/test_codex_parser.py -v`

- [ ] **스텝 4: `agenttrace/adapters/codex.py`에 `CodexStreamParser`, `parse_stream`, `load` 구현.** `feed`는 한 줄을 try/except로 파싱(JSON 오류 → unknown 이벤트); 최상위 `type`으로 분기; 현재 열린 `Turn` 유지; `turn.started` 전의 이벤트는 암묵적 턴 0에 붙임. `finish`는 상태 마감 + `incomplete` 설정.

- [ ] **스텝 5: 테스트 실행, 통과 확인** — `pytest tests/test_codex_parser.py -v` → PASS

- [ ] **스텝 6: 커밋** — `git add agenttrace/adapters tests/test_codex_parser.py tests/fixtures/codex_stream_basic.jsonl && git commit -m "feat: codex stream parser with robustness handling"`

---

### 태스크 3: Codex 도구 호출/결과 매핑

**파일:**
- 수정: `agenttrace/adapters/codex.py`
- 생성: `tests/fixtures/codex_stream_tools.jsonl` (스텝 1에서 캡처)
- 테스트: `tests/test_codex_tools.py`

**인터페이스:**
- 사용: `CodexStreamParser` (태스크 2).
- 제공: `item.completed` 처리를 확장해 도구 호출 item → `tool_call` 이벤트(`data["name"]`, `data["arguments"]`), 도구 출력 item → `tool_result` 이벤트(`data["output"]`). 정확한 `item.type` 문자열/필드는 스텝 1에서 캡처한 픽스처로 확정; 그것들을 매핑하고, 여전히 모르는 건 태스크 2의 unknown-폴백 유지.

- [ ] **스텝 1: 도구 픽스처 캡처.** 실행(동작하는 `codex` 로그인 필요; read-only 샌드박스; 프로젝트 파일 안 씀):

```bash
codex exec --json --sandbox read-only -c model_reasoning_summary="detailed" \
  "List the files in the current directory, then tell me how many there are." \
  < /dev/null > tests/fixtures/codex_stream_tools.jsonl
```

파일을 살펴 쉘/명령 실행에 쓰인 `item.type` 값과 필드명(command, output, exit code)을 확인.

- [ ] **스텝 2: 실패하는 테스트 작성**

```python
def test_tool_call_and_result_mapped():
    tr = parse_stream(open("tests/fixtures/codex_stream_tools.jsonl", encoding="utf-8"))
    kinds = [e.type for e in tr.turns[0].events]
    assert "tool_call" in kinds and "tool_result" in kinds
    call = next(e for e in tr.turns[0].events if e.type == "tool_call")
    assert call.data["name"]
```

- [ ] **스텝 3: 테스트 실행, 실패 확인** — `pytest tests/test_codex_tools.py -v`

- [ ] **스텝 4: 도구 매핑 구현** — 스텝 1에서 관찰한 `item.type`/필드로 `codex.py`에 구현.

- [ ] **스텝 5: 테스트 실행, 통과 확인** — `pytest tests/test_codex_tools.py -v` → PASS

- [ ] **스텝 6: 커밋** — `git add agenttrace/adapters/codex.py tests/test_codex_tools.py tests/fixtures/codex_stream_tools.jsonl && git commit -m "feat: map codex tool calls and results"`

---

### 태스크 4: 롤아웃 파일 리플레이 (사후, 추론 degraded) + `load` 자동감지

**파일:**
- 생성: `agenttrace/adapters/codex_rollout.py`
- 수정: `agenttrace/adapters/codex.py` (`load`가 포맷 자동감지 후 위임하게)
- 생성: `tests/fixtures/codex_rollout.jsonl`
- 테스트: `tests/test_rollout.py`

**인터페이스:**
- 사용: `agenttrace.model` (태스크 1).
- 제공: `parse_rollout(lines: Iterable[str]) -> Trace` — `~/.codex/sessions/.../rollout-*.jsonl` 스키마(최상위 `{timestamp, type, payload}`) 파싱. 매핑: `session_meta` → `run_id = payload.session_id`, `seed.system_prompt = payload.base_instructions.text`; `payload.type == "agent_message"` → `reasoning` 이벤트 + `data["role"]="agent_message"`; `payload.type == "function_call"` → `tool_call`(`data["name"]`, `data["arguments"]`); `payload.type == "function_call_output"` → `tool_result`(`data["output"]`); `payload.type == "reasoning"`(암호화, 빈 summary) → **생략**(읽을 CoT 없음) + 1회성 `meta` 이벤트 `data["note"]="reasoning encrypted — unavailable in rollout"`; 모든 이벤트는 v1에선 단일 `Turn`(seq 0)으로 묶음. `load`(in `codex.py`)는 첫 비어있지 않은 줄을 엿봄: `payload` 키가 있으면 → `parse_rollout`, 아니면 → `parse_stream`.

- [ ] **스텝 1: 픽스처 `tests/fixtures/codex_rollout.jsonl` 생성** (최소, 실제 스키마):

```
{"timestamp":"2026-07-24T09:59:32Z","type":"session_meta","payload":{"session_id":"019f938e","cwd":"D:/x","cli_version":"0.142.5","base_instructions":{"text":"You are Codex, a coding agent."}}}
{"timestamp":"2026-07-24T09:59:40Z","type":"response_item","payload":{"type":"reasoning","summary":[],"encrypted_content":"gAAAAAB_encrypted_blob=="}}
{"timestamp":"2026-07-24T09:59:41Z","type":"event_msg","payload":{"type":"agent_message","message":"I'll list the files.","phase":"commentary"}}
{"timestamp":"2026-07-24T09:59:42Z","type":"response_item","payload":{"type":"function_call","id":"fc_1","name":"shell_command","arguments":"{\"command\":\"ls\"}","call_id":"call_1"}}
{"timestamp":"2026-07-24T09:59:44Z","type":"response_item","payload":{"type":"function_call_output","call_id":"call_1","output":"Exit code: 0\nfile.txt"}}
```

- [ ] **스텝 2: 실패하는 테스트 작성**

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

- [ ] **스텝 3: 테스트 실행, 실패 확인** — `pytest tests/test_rollout.py -v`

- [ ] **스텝 4: `parse_rollout`과 `load` 자동감지/위임 구현.**

- [ ] **스텝 5: 테스트 실행, 통과 확인** — `pytest tests/test_rollout.py -v` → PASS

- [ ] **스텝 6: 커밋** — `git add agenttrace/adapters tests/test_rollout.py tests/fixtures/codex_rollout.jsonl && git commit -m "feat: codex rollout replay with load auto-detect"`

---

### 태스크 5: 공개 캡처 API — `Collector`, `run_codex`

**파일:**
- 생성: `agenttrace/collector.py`
- 생성: `agenttrace/runner.py`
- 수정: `agenttrace/__init__.py` (공개 이름 export)
- 테스트: `tests/test_collector.py`, `tests/test_runner.py`

**인터페이스:**
- 사용: `CodexStreamParser`, `parse_stream`, `load` (태스크 2–4).
- 제공: `Collector(agent: str = "codex", *, user_input: str | None = None, system_prompt: str | None = None)` — `.feed(line: str)`, `.finish() -> Trace`(해당 에이전트의 스트림 파서에 위임; 모르는 `agent`는 `ValueError`). `run_codex(prompt: str, *, reasoning: str = "detailed", model: str | None = None, launcher: Callable[[list[str]], Iterable[str]] = _subprocess_launcher) -> Trace` — `codex exec --json` argv 구성(`-c model_reasoning_summary=<reasoning>` 주입), `Collector`로 줄을 흘리고, `seed.user_input=prompt` 설정; `launcher`는 테스트용으로 주입 가능. `Collector`, `run_codex`, `load`를 `agenttrace/__init__.py`에서 재export.

- [ ] **스텝 1: 실패하는 테스트 작성**

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

- [ ] **스텝 2: 테스트 실행, 실패 확인** — `pytest tests/test_collector.py tests/test_runner.py -v`

- [ ] **스텝 3: `Collector`(collector.py)와 `run_codex` + `_subprocess_launcher`(runner.py) 구현.** `_subprocess_launcher`는 `codex exec --json ...`을 `stdin=subprocess.DEVNULL`로 실행, UTF-8 디코딩한 stdout 줄을 yield. `__init__.py`에서 export.

- [ ] **스텝 4: 테스트 실행, 통과 확인** — `pytest tests/test_collector.py tests/test_runner.py -v` → PASS

- [ ] **스텝 5: 커밋** — `git add agenttrace tests/test_collector.py tests/test_runner.py && git commit -m "feat: public capture API (Collector, run_codex)"`

---

### 태스크 6: HTML 렌더러 (자체완결 타임라인 뷰어)

**파일:**
- 생성: `agenttrace/viewer/template.html` (inline CSS + JS; 플레이스홀더 토큰 `__TRACE_JSON__`)
- 생성: `agenttrace/render.py`
- 수정: `agenttrace/__init__.py` (`render`, `render_to_file` export)
- 테스트: `tests/test_render.py`

**인터페이스:**
- 사용: `agenttrace.model` (태스크 1).
- 제공: `render(trace: Trace) -> str`(완전 자체완결 HTML), `render_to_file(trace: Trace, path: str) -> None`(UTF-8). `render`는 `__TRACE_JSON__`을 Trace의 JSON으로 치환하되 스크립트 컨텍스트를 끊지 못하게 이스케이프(`<` → `\u003c`). inline JS가 DOM 타임라인 구성: 턴은 순서 있는 접이식 블록(`seq` 표시), 이벤트는 리스트 순서대로; `reasoning`은 "요약" 라벨, `tool_call`/`tool_result`는 구분(결과는 기본 접힘), `error`는 강조, `meta`/`unknown`은 옅게; `reasoning` 이벤트가 0개인 턴은 "추론 요약 없음" 안내 렌더. 모든 이벤트 텍스트는 `textContent`로 삽입(절대 `innerHTML` 금지)해 임베드된 HTML/`</script>`가 무력화되게.

- [ ] **스텝 1: 실패하는 테스트 작성**

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

- [ ] **스텝 2: 테스트 실행, 실패 확인** — `pytest tests/test_render.py -v`

- [ ] **스텝 3: `template.html` 작성**(타임라인 CSS + 인터페이스대로 턴/이벤트를 순회하는 JS `render(trace)`, `textContent` 사용) + **`render`/`render_to_file` 구현**(in `render.py`; 템플릿 UTF-8로 읽고 이스케이프한 JSON 치환). "추론 요약 없음" 문자열은 JS 안에 두고 추론 없는 턴마다 출력.

- [ ] **스텝 4: 테스트 실행, 통과 확인** — `pytest tests/test_render.py -v` → PASS

- [ ] **스텝 5: 렌더된 파일을 한 번 직접 열어** 타임라인이 보이는지 확인(`agenttrace.render_to_file(agenttrace.load("tests/fixtures/codex_rollout.jsonl"), "sample.html")`, 브라우저로 열기). 테스트 통과면 블로커 아님; 확인 후 `sample.html` 삭제.

- [ ] **스텝 6: 커밋** — `git add agenttrace/render.py agenttrace/viewer agenttrace/__init__.py tests/test_render.py && git commit -m "feat: self-contained HTML timeline renderer"`

---

### 태스크 7: 프롬프트 diff 뷰

**파일:**
- 수정: `agenttrace/render.py`
- 수정: `agenttrace/__init__.py` (`diff` export)
- 테스트: `tests/test_diff.py`

**인터페이스:**
- 사용: `Trace` (태스크 1), `render` 헬퍼 (태스크 6).
- 제공: `diff(trace_a: Trace, trace_b: Trace) -> str` — 두 `seed` 프롬프트(시스템 + 유저)를 나란히 보여주는 자체완결 HTML, `difflib`로 라인 단위 diff 하이라이트; 추가/삭제 라인에 `diff-add`/`diff-del` CSS 클래스. 템플릿의 스타일과 동일한 `<` 이스케이프 재사용.

- [ ] **스텝 1: 실패하는 테스트 작성**

```python
def test_diff_marks_changed_prompt_lines():
    a = _trace_with_user_input("find the bug\nbe careful")
    b = _trace_with_user_input("find the bug\nbe very careful")
    html = diff(a, b)
    assert "be careful" in html and "be very careful" in html
    assert 'class="diff-add"' in html and 'class="diff-del"' in html
```

- [ ] **스텝 2: 테스트 실행, 실패 확인** — `pytest tests/test_diff.py -v`

- [ ] **스텝 3: `diff` 구현** — seed 프롬프트 라인에 `difflib.SequenceMatcher`/`ndiff` 적용; 이스케이프한 나란히 보기 HTML + diff 클래스 출력.

- [ ] **스텝 4: 테스트 실행, 통과 확인** — `pytest tests/test_diff.py -v` → PASS

- [ ] **스텝 5: 커밋** — `git add agenttrace/render.py agenttrace/__init__.py tests/test_diff.py && git commit -m "feat: prompt diff view"`

---

### 태스크 8: CLI

**파일:**
- 생성: `agenttrace/cli.py`
- 수정: `agenttrace/__init__.py` (`main` 노출)
- 생성: `pyproject.toml`
- 테스트: `tests/test_cli.py`

**인터페이스:**
- 사용: `run_codex`, `load`, `render_to_file`, `diff` (태스크 5–7).
- 제공: `main(argv: list[str]) -> int` — 서브커맨드: `replay <path> -o <out.html>`(load → render_to_file; `load`가 스트림/롤아웃 자동감지), `diff <A> <B> -o <out.html>`(둘 load → diff → 쓰기), `run <prompt> -o <out.html>`(run_codex → render_to_file). 얇게: 각 서브커맨드는 라이브러리 호출 몇 개뿐, 자체 로직 없음. `pyproject.toml`은 패키지 선언(Python ≥3.10, 런타임 의존성 없음) + `[project.scripts] agenttrace = "agenttrace.cli:main"`.

- [ ] **스텝 1: 실패하는 테스트 작성** (라이브 Codex 회피 — `replay`·`diff`를 픽스처로 테스트):

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

- [ ] **스텝 2: 테스트 실행, 실패 확인** — `pytest tests/test_cli.py -v`

- [ ] **스텝 3: `argparse`로 `main` 구현**(in `cli.py`); 스크립트 엔트리 포함한 `pyproject.toml` 작성.

- [ ] **스텝 4: 테스트 실행, 통과 확인** — `pytest tests/test_cli.py -v` → PASS

- [ ] **스텝 5: 전체 스위트 실행** — `pytest -v` → 전부 PASS

- [ ] **스텝 6: 커밋** — `git add agenttrace/cli.py agenttrace/__init__.py pyproject.toml tests/test_cli.py && git commit -m "feat: agenttrace CLI"`
