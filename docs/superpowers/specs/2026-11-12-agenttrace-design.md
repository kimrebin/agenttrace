# agenttrace — 에이전트 추론·도구 trace 디버깅 뷰어 설계

- 상태: 설계 승인 완료, 구현 계획(writing-plans) 대기
- 작성일: 2026-11-12
- 독자: 이 도구를 구현할 엔지니어

## 1. 개요와 목적

`agenttrace`는 **에이전트(1차 대상: Codex)의 추론 과정과 도구 호출/결과 trace를 사람이 보기 좋게 보여주고, 프롬프트 디버깅에 쓰는 도구**다. ReasonGraph(LLM 추론을 Mermaid로 시각화한 데모)의 "추론을 시각화한다"는 발상을 빌리되, 대상과 방법이 다르다:

- 대상: 단발 API 응답이 아니라 **에이전트의 실행 trace**(ReAct 루프 — 추론 → 도구 호출 → 결과 → 다시 추론).
- 방법: 추론을 템플릿으로 강제해 뽑아내지 않고, **에이전트가 네이티브로 내는 것을 캡처**한 뒤 **우리 뷰어가 사후 구조화**한다.
- 용도: "프롬프트를 이렇게 바꿨더니 에이전트가 왜 이렇게 행동했나"를 추적하는 **프롬프트 디버깅**.
- 배포: **다른 프로그램(사용자가 개발한, Codex를 호출하는 프로그램)에 끼워넣기 쉬울 것**이 최우선 요구.

## 2. 범위

### v1 목표
- Codex 실행을 **라이브 캡처**(`codex exec --json` stdout 스트림)해 정규화 Trace로 만든다.
- Trace를 **자체완결 HTML**(JSON 임베드 + inline JS/CSS 뷰어)로 렌더한다. 뷰어는 **추론**과 **도구 호출/결과 trace**를 둘 다 보여준다.
- **입력 프롬프트 diff**: 두 run의 seed 프롬프트(시스템+유저)를 나란히 텍스트 diff.
- **Python 라이브러리 + 얇은 CLI** 둘 다 제공.

### v1 비목표 (non-goal)
- **행동(trace) diff** — 두 실행의 도구 호출/추론 경로를 정렬·비교하는 것. 정렬(alignment) 문제가 본질적으로 어려워 별도 과제. (모델은 나중에 확장 가능하게만 둠.)
- 스트리밍/실시간 라이브 뷰(캡처는 라이브지만 렌더는 실행 종료 후 1회).
- 추론 템플릿 강제(아래 3.1 근거).
- OpenTelemetry 등 표준 연동(네이밍은 나중에 업그레이드 가능하게).
- 제3자(사용자가 코드를 못 고치는) 프로그램에 바깥에서 attach — v1 대상 아님(사용자 시나리오가 "본인이 개발한 프로그램"으로 확정됨).

## 3. 핵심 설계 결정과 근거

### 3.1 추론은 템플릿으로 강제하지 않는다 (자유 추론 + 사후 구조화)
외부 리서치 결과, 형식을 강하게 조일수록 추론 과제 성능이 떨어진다(Tam et al. "Let Me Speak Freely?", EMNLP 2024; 보강: Self-Discover 2025 등). 최선은 "자유 추론 → 사후 구조 변환". 또한 디버깅 대상 에이전트의 행동을 바꾸는 관측자 효과를 피해야 한다. → 에이전트에 아무 템플릿도 강제하지 않고, 네이티브 출력을 캡처해 우리 뷰어(③④층)에서만 구조화한다.

### 3.2 Codex 추론은 저장 로그에 암호화되어 안 남는다 → 라이브 캡처 (실측 근거)
사용자의 실제 Codex 세션 로그 32개(`~/.codex/sessions/.../rollout-*.jsonl`)를 전수 조사한 결과:
- 도구 호출(`function_call`)·결과(`function_call_output`)·코멘터리(`agent_message`)·시스템 프롬프트(`session_meta.base_instructions.text`)는 **평문**으로 남는다.
- **추론(`reasoning`) 이벤트 275건 전부 `encrypted_content`(암호화)이고 읽을 수 있는 `summary`는 0건.** 화면에 스쳐가는 추론은 실시간 스트리밍되는 요약일 뿐, 저장 파일엔 안 남는다.

따라서 읽을 수 있는 추론을 얻으려면 **저장 파일이 아니라 실행 중 라이브 스트림**을 잡아야 한다. `codex exec --json` 프로브로 확정:
- `--json`은 stdout에 정돈된 이벤트를 JSONL로 낸다: `thread.started` → `turn.started` → `item.completed`(item.type=`reasoning`/`agent_message`/도구…) → `turn.completed`(usage).
- 기본 설정에선 추론 토큰이 0으로 비어 나왔고, **`-c model_reasoning_effort="high" -c model_reasoning_summary="detailed"`를 주니 `item.type="reasoning"`에 읽을 수 있는 `text`가 실제로 담겼다**(`reasoning_output_tokens: 89`).
- 단 이 추론은 **원본 CoT가 아니라 요약(summary)**이다(OpenAI가 raw CoT를 안 내보냄). 뷰어는 정직하게 "요약"으로 표기한다.

### 3.3 함정 (실측에서 겪음)
- `codex exec`는 프롬프트 인자를 줘도 **stdin이 파이프/열려 있으면 추가 입력을 기다리며 멈춘다**("Reading additional input from stdin…"). 우리가 직접 띄울 땐 stdin을 닫아야 한다.
- 콘솔 출력에서 한국어가 깨져 보였으나 파일은 UTF-8. 파싱은 어디서나 **UTF-8 명시**.

## 4. 아키텍처 개요

단방향 4층 파이프라인. 각 층은 단일 책임이고, 사이는 잘 정의된 인터페이스로만 통신한다.

```
[agent native output]
   → ① Adapter (에이전트별: codex, claude_code …)      # 유일하게 에이전트를 아는 층
   → ② Trace (정규화 이벤트 모델; 에이전트 중립, 직렬화 가능)
   → ③ Renderer (Trace → 자체완결 HTML)
   → ④ Entry points (library: Collector/run/load/render/diff; CLI: 얇은 래퍼)
```

경계 원칙:
- 새 에이전트 지원 = **어댑터 1개 추가**, 그 외 전부 불변.
- UI 교체 = **렌더러만 교체**, 모델·어댑터 불변.
- 캡처와 렌더는 분리. 사이는 직렬화 가능한 Trace(JSON) → 저장/전송/diff/HTML 임베딩이 전부 이 한 포맷으로.

## 5. 정규화 이벤트 모델 (②)

3층 중첩: `Trace` → `Turn` → `Event`.

### Trace (한 번의 에이전트 실행)
| 필드 | 의미 |
|---|---|
| `run_id` | 실행의 안정적 식별자 (diff 기준점; Codex `thread_id` 매핑) |
| `agent` | `"codex"` / `"claude_code"` … (렌더링 힌트) |
| `seed` | `{ system_prompt, user_input }` — **프롬프트 diff 대상** |
| `started_at` / `ended_at` | 타임스탬프 |
| `turns[]` | **순서 있는** 턴 목록 |
| `incomplete` | 부분 캡처 여부(스트림이 끊겼는지) |
| `meta` | 자유 딕셔너리(모델명, 토큰 usage 등) |

### Turn (ReAct 한 왕복)
- `seq`(0,1,2…)로 순서 명시 — "몇 번째 왕복에서 틀어졌나"가 또렷.
- `events[]` — **순서 있는** 이벤트 목록.
- `meta`(해당 턴 usage 등).

### Event (5종)
공통: `id`, `type`, `timestamp`, `raw`(원본 조각 보존).

| `type` | 담는 것 |
|---|---|
| `reasoning` | 에이전트 네이티브 추론 서술(Codex의 경우 **요약**) |
| `tool_call` | 도구 이름 + 인자 |
| `tool_result` | 도구 반환값/출력 (+ 선택적 `sub_trace`로 서브에이전트 중첩) |
| `error` | 실패·예외·거부 |
| `meta` | 모델 전환, 컨텍스트 압축 등 시스템 이벤트 |

- 신뢰 등급(trust tier) 개념은 모델에 넣지 않는다(의도적으로 단순화). `reasoning`과 `tool_call`은 `type`으로 구분되며, 시각 구분은 뷰어(③)가 담당.
- 서브에이전트: `tool_result.sub_trace`에 자식 `Trace`를 중첩할 수 있음. v1에서 모델은 중첩을 **표현**하되, 어댑터는 로그에 정보가 있을 때만 채운다.

## 6. 어댑터 (①)

### 공통 계약
```
parse_stream(lines_iterable) -> Trace     # 라이브/스트림
load(path) -> Trace                        # 사후(저장 로그)
```
어댑터는 "지저분한 에이전트별 현실"을 "깨끗한 Trace"로 격리하는 벽. 바깥은 어떤 에이전트인지 모른다.

### Codex 어댑터 (v1 1순위, 실측 기반)
- 소스: `codex exec --json`의 stdout JSONL 스트림.
- **래퍼 책임**: Codex를 띄울 때 `-c model_reasoning_summary="detailed"`(및 적절한 `model_reasoning_effort`)를 주입해야 읽을 수 있는 추론이 스트림에 나온다. 안 주면 추론이 비어 나온다.
- 이벤트 매핑:

| Codex `--json` 이벤트 | → Trace |
|---|---|
| `thread.started`(thread_id) | Trace 시작, `run_id` |
| `turn.started` / `turn.completed`(usage) | Turn 경계 + 토큰 meta |
| `item.completed` · item.type=`reasoning`(text) | `reasoning` 이벤트(**요약 표기**) |
| `item.completed` · item.type=`agent_message` | `reasoning`/코멘터리 서술 |
| `item.completed` · 도구 호출/결과 류 | `tool_call` / `tool_result` |
| exec 프롬프트 + `base_instructions` | `seed`(유저+시스템) |

- **미확정(구현 시작 때 1회 프로브로 해결)**: `--json`에서 도구 호출 item의 정확한 타입명/필드. 이번 프로브는 도구를 안 쓴 실행이라 못 봄. 설계 레벨에선 "도구는 `item.completed`로 나온다"로 충분.

### Claude Code 어댑터 (2순위)
- 동일 인터페이스로 Claude Code 트랜스크립트 JSONL을 변환. 샘플은 세션 트랜스크립트로 확보 가능. 인터페이스가 고정이라 하류 불변.

## 7. 렌더러 / 뷰어 (③)

- 입력: Trace 1개. 출력: **자체완결 HTML 파일 1개**(Trace를 JSON으로 박고 JS/CSS 뷰어 inline). 서버 없이 열리고 공유·첨부 가능.
- 데이터와 뷰어 분리(JSON 블록 ↔ 제네릭 뷰어 스크립트) → UI 교체 용이.
- **1차 뷰 = DOM 타임라인**(Mermaid 플로우차트 아님). trace는 순차+중첩이라 타임라인이 맞다. 그래프 뷰는 나중에 선택적으로.
  - 턴이 시간순 세로 블록, 각 턴 접힘(`seq` 표시).
  - 턴 안 이벤트는 **시간순 interleave**(reason → tool_call → tool_result → reason …) — ReAct 루프가 보이게, "왜 이 도구를 불렀나"가 바로 위 추론에 붙게.
- 이벤트 타입별 시각 구분:
  - `reasoning` — 부드러운 스타일 + **"요약" 라벨**.
  - `tool_call` — 도구 이름 + 인자(펼침).
  - `tool_result` — 기본 접힘 + 펼치기(출력이 길다).
  - `error` — 강조. `meta` — 옅게. 서브에이전트 — 중첩 블록 접기/펴기.
- **프롬프트 diff 모드**: run 두 개를 받으면 상단에 두 seed 프롬프트를 나란히 텍스트 diff 하이라이트.

## 8. 엔트리 포인트 (④)

### 라이브러리 — 캡처/렌더 2레이어

캡처(1순위 임베드 = (b), 사용자 시나리오 확정):
```
# (b) 호스트(사용자 프로그램)가 codex exec --json을 띄우고 줄을 넘김 — 1순위
collector = agenttrace.Collector(agent="codex")
for line in codex_proc.stdout:   # 사용자 프로그램의 기존 읽기 루프에 한 줄 추가
    collector.feed(line)
trace = collector.finish()

# (a) 우리가 대신 실행 — 보조/단독
trace = agenttrace.run_codex("프롬프트", reasoning="detailed")   # stdin 닫음

# (c) 사후 — 저장 롤아웃 리플레이 (추론은 코멘터리까지만)
trace = agenttrace.load("~/.codex/sessions/.../rollout-*.jsonl")
```

렌더:
```
html = agenttrace.render(trace)
agenttrace.render_to_file(trace, "out.html")
html = agenttrace.diff(trace_a, trace_b)
```

### CLI — 얇은 래퍼(로직 없음, 전부 라이브러리 호출)
```
agenttrace run "프롬프트"     # 실행→캡처→HTML 열기 (단독 체험)
agenttrace replay <rollout>   # 저장 로그 사후 렌더
agenttrace diff <A> <B>       # 두 run 프롬프트 diff
```

### 임베드 친화 원칙
- 의존성 최소(표준 라이브러리 위주) — 호스트 프로젝트에 부담 없게.
- 비침습적 — (b)에서 호스트 실행 코드를 바꾸라고 강요하지 않음(스트림만 tee).
- Trace는 JSON 왕복 가능.

## 9. 에러 처리

원칙: **무슨 일이 있어도 Trace는 나온다.**
- 깨진 JSON 줄 → 크래시 금지, `raw`에 담은 "unknown" 이벤트로 남기고 계속.
- 부분 스트림(프로세스 종료/조기 중단) → `finish()`가 부분 Trace 반환 + `incomplete=true`, 뷰어가 "끊김" 표시.
- 모르는 `item.type` → 버리지 않고 `meta`/`raw` 보존, 제네릭 렌더.
- 추론 요약이 비어 있으면 → 가짜로 채우지 말고 "요약 없음 — 이 설정을 켜라" 경고.
- `run_codex`는 stdin을 닫아 멈춤 함정 방지.
- 인코딩은 어디서나 UTF-8 명시.
- 렌더 에러 시에도 최소 골격은 그려지게.

## 10. 테스트 전략

강점: 실측 샘플이 이미 있다(실제 롤아웃 32개 + `--json` 프로브 출력).
- **골든/스냅샷**: 실제 `--json` 스트림 픽스처 → 어댑터 → Trace 구조 대조.
- **단위**: 이벤트 타입별 파싱, `Collector.feed/finish`, `diff`, `render`(유효 HTML + JSON 임베드 + 핵심 노드).
- **견고성**: 깨진 줄/잘린 스트림/모르는 타입 → 크래시 없이 부분 Trace(섹션 9 보장 검증).
- 뷰어 JS는 v1에선 가볍게(임베드·주요 섹션 렌더 확인). 무거운 E2E는 뒤로.
- 구현은 TDD(실패 테스트 → 구현). 픽스처가 실물이라 테스트가 곧 명세.

## 11. 미해결 사항 / 위험

- **Codex `--json` 도구 item 스키마**: 도구를 쓴 실행을 아직 안 봄. 구현 시작 때 도구 쓰는 프롬프트로 1회 프로브 필요.
- **추론은 요약이지 원본 CoT 아님**: 뷰어·문서에서 정직하게 "요약"으로 다룰 것.
- **Codex 버전 드리프트**: 이벤트 스키마가 버전마다 바뀔 수 있음(조사 샘플은 cli 0.142.x~0.151.0). 어댑터의 "모르는 타입 보존" 원칙으로 완충.
- **최신 모델에서의 형식-강제 해악**: 3.1 근거 중 가장 강한 수치는 구형 모델 기준. 방향성은 일관하나 최신 벤치는 직접 못 찾음. (어차피 v1은 템플릿 강제 안 하므로 영향 적음.)
- **Claude Code 트랜스크립트 포맷**: 2순위라 아직 미조사.
