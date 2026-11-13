# agenttrace

Codex(및 추후 다른 에이전트) 실행의 **추론 과정과 도구 호출/결과 trace**를 캡처해, 사람이 보기 좋은 **자체완결 HTML 타임라인**으로 그려주는 Python 라이브러리 + CLI. 프롬프트 디버깅과, 에이전트를 호출하는 프로그램에 끼워넣는 용도.

> 이 저장소의 `ReasonGraph/`는 설계 영감을 받은 별개의 참고 프로젝트입니다. agenttrace 본체는 `agenttrace/` 패키지입니다.

## 요구 사항

- **Python 3.10+** — 런타임 의존성 **없음**(표준 라이브러리만).
- 라이브 캡처(`run_codex`)나 세션 로그 사용 시 **Codex CLI**가 설치돼 있어야 함.
- 개발/테스트용으로 `pytest`.

## 설치 (git에서)

```bash
git clone <this-repo-url>
cd Resongraph
pip install -e .
```

`pip install -e .`를 하면:
- 어디서나 `import agenttrace` 가능
- `agenttrace` CLI 명령 등록

설치 없이 저장소 루트에서 바로 쓰려면 `python -m pytest`처럼 루트 기준으로 실행하면 됩니다.

---

## 빠른 시작

### A. CLI로 저장된 세션 보기 (가장 쉬움)

Codex는 세션을 `~/.codex/sessions/<연>/<월>/<일>/rollout-*.jsonl`에 남깁니다.

```bash
# 저장된 세션 → HTML 타임라인
agenttrace replay ~/.codex/sessions/2026/07/24/rollout-....jsonl -o trace.html

# 두 실행의 입력 프롬프트 비교(diff)
agenttrace diff runA.jsonl runB.jsonl -o diff.html

# Codex를 직접 실행하며 캡처 (추론 요약 자동 on)
agenttrace run "이 레포 구조 설명해줘" -o run.html
```

`replay`는 저장된 `--json` 스트림이든 `~/.codex` 롤아웃이든 **포맷을 자동 판별**합니다.

### B. 라이브러리로 내 프로그램에 끼워넣기 (핵심 용도)

내 프로그램이 이미 `codex exec --json`을 띄워 출력을 읽고 있다면, 그 줄을 흘려보내기만 하면 됩니다:

```python
import agenttrace

collector = agenttrace.Collector(agent="codex", user_input=my_prompt)
for line in codex_process.stdout:    # 내가 이미 읽던 루프
    collector.feed(line)
    # ... 내 로직은 그대로 ...
trace = collector.finish()
agenttrace.render_to_file(trace, "trace.html")
```

> ⚠️ Codex를 띄울 때 `-c model_reasoning_summary="detailed"`를 줘야 **읽을 수 있는 추론**이 스트림에 담깁니다. (안 주면 추론이 비어 나옴.)

### C. 라이브러리 — 우리가 대신 실행 / 저장 파일 로드

```python
import agenttrace

# (a) 우리가 Codex를 직접 실행 (추론 요약 자동 on, stdin 처리 등 알아서)
trace = agenttrace.run_codex("버그 찾아줘")

# (b) 저장 파일 로드 (스트림/롤아웃 자동 판별)
trace = agenttrace.load("~/.codex/sessions/.../rollout-....jsonl")

agenttrace.render_to_file(trace, "out.html")
```

---

## 대시보드에 임베드하기

호스트가 웹 대시보드(HTML/JS)라면, trace를 **iframe 패널**로 한쪽에 꽂을 수 있습니다:

```python
import agenttrace
trace = agenttrace.load("~/.codex/sessions/.../rollout-....jsonl", link_subagents=True)
panel = agenttrace.render_iframe(trace, height="600px")
# 이 문자열(<iframe srcdoc=...>)을 대시보드 HTML의 원하는 <div> 안에 그대로 삽입
```

- iframe이라 agenttrace의 CSS/JS가 대시보드와 **섞이지 않음**(격리), 추가 파일도 없음.
- 서버로 서빙하는 대시보드면 `render_to_file(trace, "trace.html")` 후 `<iframe src="trace.html">`도 가능(이스케이프 불필요).

---

## 프롬프트 diff

같은 작업을 프롬프트만 바꿔 두 번 돌린 뒤, 입력 프롬프트 차이를 나란히:

```python
html = agenttrace.diff(trace_a, trace_b)   # 자체완결 HTML
open("diff.html", "w", encoding="utf-8").write(html)
```

(행동 trace diff가 아니라 **입력 프롬프트** diff입니다.)

---

## 서브에이전트 중첩

Codex는 `multi_agent`가 켜져 있으면 서브에이전트를 **별도 스레드(별도 롤아웃 파일)**로 돌립니다. 사후 로드 시 자식까지 자동으로 끌어와 중첩해 보여줄 수 있습니다:

```python
trace = agenttrace.load(main_rollout_path, link_subagents=True)
# main의 'sub_agent:<path>' 호출 밑에 자식 에이전트의 추론·도구 trace가 중첩 렌더됨
```

내가 직접 서브에이전트를 오케스트레이션하는 경우, 자식 Trace를 수동으로 끼울 수도 있습니다:

```python
agenttrace.nest_sub_trace(parent_trace, call_id, child_trace)
```

---

## Trace 데이터 구조 (참고)

캡처 결과는 JSON 직렬화 가능한 `Trace`입니다. 3단 중첩:

```
Trace          실행 1회 (run_id, agent, seed={system_prompt,user_input}, incomplete)
 └─ Turn[]     ReAct 왕복 (seq=0,1,2…)
     └─ Event[]  reasoning / tool_call / tool_result / error / meta  (각 data 딕셔너리)
```

```python
trace.to_json(); agenttrace.Trace.from_json(s)   # 저장/전송
```

---

## 한계 (현재 v1)

- **라이브 캡처(`run_codex` / `Collector`)에선 서브에이전트가 납작하게** 나옵니다 — 자식은 별도 스레드/파일이라 스트림만으론 중첩 불가. 완전 중첩은 사후 `load(..., link_subagents=True)`에서만.
- 저장 롤아웃의 **추론은 암호화**되어 원본 사고사슬은 복원 불가 — 코멘터리/요약과 도구 trace만 보입니다(라이브 스트림은 추론 요약 가능).
- 뷰어는 선형 ReAct 흐름을 타임라인으로 보여줍니다(분기 트리가 아님).
- 대상 에이전트: 현재 **Codex**. (어댑터만 추가하면 다른 에이전트 확장 가능.)

---

## 개발

```bash
python -m pytest -q      # 전체 테스트 (36개)
```

구조:
- `agenttrace/model.py` — Trace/Turn/Event + 직렬화
- `agenttrace/adapters/codex.py` — 라이브 `--json` 스트림 파서 + `load` 자동 판별
- `agenttrace/adapters/codex_rollout.py` — 저장 롤아웃 파서(포맷 이원화) + 서브에이전트 링크
- `agenttrace/collector.py`, `runner.py` — 캡처 진입점(`Collector`, `run_codex`)
- `agenttrace/render.py` + `viewer/template.html` — HTML 타임라인, diff, iframe 임베드
- `agenttrace/cli.py` — `replay` / `diff` / `run`
