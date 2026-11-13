# agenttrace

Codex(및 추후 다른 에이전트) 실행의 **추론 과정과 도구 호출/결과 trace**를 캡처해, 사람이 보기 좋은 **자체완결 HTML 타임라인**으로 그려주는 Python 라이브러리 + CLI. 프롬프트 디버깅과, 에이전트를 호출하는 프로그램(대시보드 등)에 끼워넣는 용도.

> 이 저장소의 `ReasonGraph/`는 설계 영감을 받은 별개의 참고 프로젝트입니다. agenttrace 본체는 `agenttrace/` 패키지입니다.

## 목차
- [요구 사항](#요구-사항)
- [설치](#설치-git에서)
- [핵심 개념](#핵심-개념)
- [CLI 사용법](#cli-사용법)
- [라이브러리 사용법](#라이브러리-사용법)
- [대시보드에 임베드](#대시보드에-임베드)
- [한 페이지에 모든 기능 (트레이스 + 프롬프트 diff)](#한-페이지에-모든-기능)
- [서브에이전트 중첩](#서브에이전트-중첩)
- [공개 API 레퍼런스](#공개-api-레퍼런스)
- [한계](#한계-현재-v1)
- [개발](#개발)

## 요구 사항
- **Python 3.10+** — 런타임 의존성 **없음**(표준 라이브러리만).
- 라이브 캡처(`run_codex`)나 세션 로그 사용 시 **Codex CLI** 필요.
- 개발/테스트용으로 `pytest`.

## 설치 (git에서)
```bash
git clone https://github.com/kimrebin/agenttrace.git
cd agenttrace
pip install -e .
```
설치하면 어디서나 `import agenttrace` 가능하고, `agenttrace` CLI 명령이 등록됩니다.

## 핵심 개념
캡처 결과는 JSON 직렬화 가능한 `Trace`입니다. 3단 중첩:
```
Trace          실행 1회 (run_id, agent, seed={system_prompt,user_input}, incomplete)
 └─ Turn[]     ReAct 왕복 (seq=0,1,2…)
     └─ Event[]  reasoning / tool_call / tool_result / error / meta / unknown
```
- **캡처**와 **렌더**가 분리돼 있어, `Trace`를 저장했다가 나중에 그리거나 비교할 수 있습니다.
- 뷰어는 선형 ReAct 흐름을 **세로 플로우 타임라인**(단계별 색/배지, 도구 호출+결과 한 카드)으로 보여줍니다.

---

## CLI 사용법

```bash
# 저장된 세션 → HTML 타임라인 (스트림/롤아웃 자동 판별)
agenttrace replay <session.jsonl> -o out.html

# 트레이스 + 프롬프트 diff 패널을 한 페이지에
agenttrace replay <session.jsonl> --compare <other.jsonl> -o out.html

# 이전 세션(같은 프로젝트)과 자동 비교
agenttrace replay <session.jsonl> --compare-prev -o out.html

# Codex 서브에이전트 자식 세션까지 찾아 중첩
agenttrace replay <session.jsonl> --link-subagents -o out.html

# 두 실행의 입력 프롬프트만 비교하는 독립 페이지
agenttrace diff <runA.jsonl> <runB.jsonl> -o diff.html

# Codex를 직접 실행하며 캡처 (추론 요약 자동 on)
agenttrace run "이 레포 구조 설명해줘" -o run.html
```
Codex 세션은 보통 `~/.codex/sessions/<연>/<월>/<일>/rollout-*.jsonl`에 쌓입니다.

---

## 라이브러리 사용법

### A. 내 프로그램에 끼워넣기 (핵심 용도)
내 프로그램이 이미 `codex exec --json`을 띄워 출력을 읽고 있다면, 그 줄을 흘려보내기만:
```python
import agenttrace

collector = agenttrace.Collector(agent="codex", user_input=my_prompt)
for line in codex_process.stdout:    # 내가 이미 읽던 루프
    collector.feed(line)
trace = collector.finish()
agenttrace.render_to_file(trace, "trace.html")
```
> ⚠️ Codex를 띄울 때 `-c model_reasoning_summary="detailed"`를 줘야 **읽을 수 있는 추론**이 스트림에 담깁니다.

### B. 우리가 대신 실행 / 저장 파일 로드
```python
import agenttrace

trace = agenttrace.run_codex("버그 찾아줘")                          # 우리가 Codex 실행
trace = agenttrace.load("~/.codex/sessions/.../rollout-....jsonl")   # 저장 파일 (자동 판별)
agenttrace.render_to_file(trace, "out.html")
```

### C. 저장/전송
```python
s = trace.to_json()
trace2 = agenttrace.Trace.from_json(s)   # 독립 복사본(깊은 복사)
```

---

## 대시보드에 임베드
호스트가 웹 대시보드(HTML/JS)라면 trace를 **iframe 패널**로 한쪽에 꽂습니다. iframe이라 스타일/스크립트가 호스트와 섞이지 않습니다.
```python
panel = agenttrace.render_iframe(trace, height="600px")
# 이 문자열(<iframe srcdoc=...>)을 대시보드 HTML의 원하는 <div>에 그대로 삽입
```
서버로 서빙하면 `render_to_file(trace, "trace.html")` 후 `<iframe src="trace.html">`도 가능.

---

## 한 페이지에 모든 기능
트레이스 타임라인과 **프롬프트 diff**를 한 페이지에서 함께 보려면 `compare_to`를 넘깁니다. 페이지 상단에 "프롬프트 변경점" 패널(접이식)이 붙고, 아래에 트레이스 타임라인이 그대로 나옵니다.
```python
a = agenttrace.load("runA.jsonl")
b = agenttrace.load("runB.jsonl")

agenttrace.render_to_file(a, "out.html", compare_to=b)   # a의 trace + (a vs b) 프롬프트 diff
panel = agenttrace.render_iframe(a, compare_to=b)        # 대시보드 패널로도 동일
```
CLI로는 `agenttrace replay runA.jsonl --compare runB.jsonl -o out.html`.

> 이건 **입력(seed) 프롬프트** diff입니다(시스템+유저, 라인 단위 add/del). 행동 trace diff는 아닙니다(v1 non-goal).

### 이전 세션과 자동 비교
비교 대상을 직접 고르는 대신, **같은 프로젝트(cwd)의 시간상 바로 이전 세션**을 자동으로 기준(A)으로 잡을 수 있습니다:
```python
prev = agenttrace.find_previous_session(cur_path)   # 없으면 None (sessions_dir 자동 추론)
trace = agenttrace.load(cur_path)
agenttrace.render_to_file(trace, "out.html",
                          compare_to=agenttrace.load(prev) if prev else None)
```
CLI: `agenttrace replay <path> --compare-prev -o out.html`
(다른 프로젝트까지 포함해 비교하려면 `find_previous_session(path, same_cwd=False)`.)

---

## 서브에이전트 중첩
Codex는 `multi_agent`가 켜져 있으면 서브에이전트를 **별도 스레드(별도 롤아웃 파일)**로 돌립니다. 사후 로드 시 자식까지 찾아와 중첩:
```python
trace = agenttrace.load(main_rollout, link_subagents=True)   # (sessions_dir 자동 추론)
# main의 'sub_agent:<path>' 호출 밑에 자식 에이전트의 추론·도구 trace가 중첩 렌더됨
```
직접 오케스트레이션하는 경우 수동으로 끼울 수도 있습니다:
```python
agenttrace.nest_sub_trace(parent_trace, call_id, child_trace)
```

---

## 공개 API 레퍼런스

**캡처**
- `Collector(agent="codex", *, user_input=None, system_prompt=None)` → `.feed(line)`, `.finish() -> Trace`
- `run_codex(prompt, *, reasoning="detailed", model=None, launcher=...) -> Trace`
- `load(path, *, user_input=None, system_prompt=None, link_subagents=False, sessions_dir=None) -> Trace`
- `find_previous_session(path, *, sessions_dir=None, same_cwd=True) -> str | None` — 자동 비교용 직전 세션

**렌더**
- `render(trace, *, compare_to=None) -> str` — 자체완결 HTML(옵션: 프롬프트 diff 패널)
- `render_to_file(trace, path, *, compare_to=None) -> None`
- `render_iframe(trace, *, height="600px", title="agenttrace", compare_to=None) -> str` — 임베드용 iframe 스니펫
- `diff(trace_a, trace_b) -> str` — 프롬프트 diff만 담은 독립 페이지

**모델/구성**
- `Trace`, `Turn`, `Event` (+ `Trace.to_json()/from_json()/to_dict()/from_dict()`)
- `nest_sub_trace(parent, call_id, child) -> bool`

**CLI** (`agenttrace <cmd>`)
- `replay <path> -o <out> [--compare <path>] [--compare-prev] [--link-subagents] [--sessions-dir <dir>]`
- `diff <A> <B> -o <out>`
- `run <prompt> -o <out>`

---

## 한계 (현재 v1)
- **라이브 캡처(`run_codex`/`Collector`)에선 서브에이전트가 납작하게** 나옵니다 — 자식은 별도 스레드/파일이라 스트림만으론 중첩 불가. 완전 중첩은 사후 `load(..., link_subagents=True)`에서만.
- 저장 롤아웃의 **추론은 암호화**되어 원본 사고사슬은 복원 불가 — 코멘터리/요약과 도구 trace만 보입니다(라이브 스트림은 추론 요약 가능).
- 뷰어는 선형 ReAct 흐름을 보여줍니다(분기 트리가 아님).
- 대상 에이전트: 현재 **Codex**. (어댑터만 추가하면 확장 가능.)

---

## 개발
```bash
python -m pytest -q      # 전체 테스트 (42개)
```
구조:
- `agenttrace/model.py` — Trace/Turn/Event + 직렬화 + `nest_sub_trace`
- `agenttrace/adapters/codex.py` — 라이브 `--json` 스트림 파서 + `load`(포맷 자동 판별)
- `agenttrace/adapters/codex_rollout.py` — 저장 롤아웃 파서(포맷 이원화) + 서브에이전트 링크
- `agenttrace/collector.py`, `runner.py` — 캡처 진입점(`Collector`, `run_codex`)
- `agenttrace/render.py` + `viewer/template.html` — HTML 타임라인, 프롬프트 diff(통합/독립), iframe 임베드
- `agenttrace/cli.py` — `replay` / `diff` / `run`
