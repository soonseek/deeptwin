# DeepTwin Critic Audit and Offline Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모델에게 보이지 않는 별도 journal에 호출을 먼저 고정하고, 오프라인 대역으로 예산·취소·중복·늦은 응답·결과 분류를 검증한다.

**Architecture:** SQLite의 사전 commit과 단일 종료 상태를 중심으로 구성한다. 입력은 B1의 불변 PreparedInput을 재사용하고 선택은 기존 ModelSelection을 통해 다시 확인한다. 실행기는 명시적으로 주입한 오프라인 transport만 사용하며 실제 제공자 활성화·의미 점수화·자동 재시도는 하지 않는다.

**Tech Stack:** 기존 Python/pytest, 표준 라이브러리 SQLite·threading·dataclasses·hashlib·json. 설치 없음.

---

## 경계와 파일

[B 전체 계획](2026-09-07-deeptwin-critic-evaluation.md)의 승인·사용자 UX·보안·C 진입 경계를 그대로 따른다. 후속 사용자 “진행해”는 이 문서의 Task 1–3 오프라인 구현을 승인한 것이며 실제 모델·비용·B4 설치/서비스를 승인한 것은 아니다. 초기 Python 예제 네 블록은 검토를 통과한 실제 구현·테스트 링크와 아래 실행 기록으로 대체했다. 작업 기준은 `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure`다. 명령은 구현 에이전트용이며 커밋·설치·실계정 호출은 없다.

진행 기록: Task 1과 Task 2의 구현은 각각 별도 명세·품질 검토를 통과했다. 집중 검사는 각각 140개·107개, 관련 회귀는 315개, 전체 Python 앱 회귀는 729개와 기존 경고 1건이다. Task 3의 결과 분류·문서 동기화와 전체 회귀 기록을 반영했다. 최종 문서 명세 검토와 전체 품질 검토도 통과했으며, 실행 증거는 마지막 기록에 구분했다.

| 파일 | 책임 |
| --- | --- |
| `app/critic_audit.py` | 불변 호출과 별도 내구성 journal |
| `app/critic_trial.py` | 선택 재검증, 명시적 오프라인 실행, 상태·결과 분류 |
| `app/tests/test_critic_audit.py` | 저장 실패·중복·한도·경쟁·복구 |
| `app/tests/test_critic_trial.py` | 입력 동결·격리 경로·취소·늦은 응답·모델 오류와 무효의 구별 |

기존 Store·Understanding·Codex 전송 코드와 API·UI는 수정하지 않는다. journal 경로와 runtime 경로는 서로 다른 **전용 합성 디렉터리**로 주입한다. 소유자가 같은 로컬 프로세스의 파일 변조나 파일시스템 경합을 방어하는 보안 저장소는 아니다. SQL transaction·해시 검사는 crash/동시 호출·우발적 손상 경계이며 암호학적 서명이나 적대적 OS 격리가 아니다.

## Task 1: 사전 commit과 단일 종료 상태

**Files:** Create `app/critic_audit.py`; Test `app/tests/test_critic_audit.py`.

- [x] **Step 1 — 테스트 소스 파일을 작성한다.**

실제 검사: [test_critic_audit.py](../../../app/tests/test_critic_audit.py). 불변 필드·canonical JSON·중복·예산 경쟁·첫 종료 commit·명시적 복구·전용 경로·실제 SQLite rollback과 읽기 snapshot을 검사한다.

- [x] **Step 2 — 실패를 확인한다.**

Run: `/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -m pytest app/tests/test_critic_audit.py -q`

Expected: 새 모듈 부재로 실패. 실제 초기 RED는 collection 오류 대신 모듈 부재 assertion으로 확인했다. 의존성 설치나 사용자 DB 변경으로 해결하지 않았다.

- [x] **Step 3 — 구현 소스 파일을 작성한다.**

실제 구현: [critic_audit.py](../../../app/critic_audit.py). 아래 불변 조건과 실행 기록이 초기 예제 네 블록을 대체하며, 검토를 통과한 소스와 테스트를 기준으로 삼는다.

`FrozenCall`은 `request_id`, `run_id`, `purpose`, `candidate_id`, `candidate_version`, `prompt`, `schema_json`, `manifest_json`, `selection_json`, `metadata_json`의 불변 문자열 10개다. 정확한 가시 입력·canonical schema/manifest/선택과 지시 내용·해시 및 caller가 제공한 코드 내용 해시 스냅샷을 보존한다. 별도 전용 SQLite journal은 디렉터리 0700·파일 0600으로 만들며 호출 레코드·예산 사용·reserved event를 하나의 transaction으로 commit한 뒤에만 dispatch를 시작한다. 중복 ID와 한도 경쟁을 막고 첫 종료 commit만 유지하며 상태와 events를 같은 읽기 snapshot으로 반환한다. 쓰기 실패는 해당 transaction을 rollback한다.

영속 예산의 벽시계는 재시작 시 만료를 판단하기 위한 것이다. 실행 중 제한은 Task 2의 monotonic 시계로 별도 집행한다. 시스템 시계 후퇴까지 견디는 보안 예산 저장소라고 주장하지 않는다. 생성자는 자동 복구하지 않는다. 호출자가 이전 worker가 없음을 확인한 뒤에만 `recover()`를 명시적으로 호출해 미완료를 `interrupted`로 기록하며 자동 재생하지 않는다. 실행 중인 다른 프로세스에 `recover()`를 호출하지 않는다.

- [x] **Step 4 — 같은 명령으로 PASS를 확인하고 diff를 검토한다.**

Run: `/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -m pytest app/tests/test_critic_audit.py -q`

Expected: 모든 새 journal 검사 PASS. 새 패키지·사용자 DB·계정 접근 없음. 별도 명세 검토 후 코드 품질 검토를 받으며 아직 커밋하지 않는다.

## Task 2: 선택 동결과 오프라인 실행기

**Files:** Create `app/critic_trial.py`; Test `app/tests/test_critic_trial.py`.

B1의 `PreparedInput`, `parse_response`, `ResponseContractError`가 선행한다. 실제 Codex transport를 이 실행기에 전달하지 못하도록 `OfflineTransport` 계약을 사용한다. 이는 실수 방지용 명시적 API 경계이지 악의적인 Python subclass를 막는 sandbox가 아니다. 실제 backend 연결에는 B 전체 계획 §5의 별도 수명주기 검토가 필요하다.

- [x] **Step 1 — 테스트 소스 파일을 작성한다.**

실제 검사: [test_critic_trial.py](../../../app/tests/test_critic_trial.py). 네 책임의 정확한 schema roundtrip, 준비 결과 재구성, SQL 선택 재검증, 기록/시작/조회 장애, 취소 경쟁, 모든 timeout 경로와 늦은 관측을 검사한다.

- [x] **Step 2 — 실패를 확인한다.**

Run: `/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -m pytest app/tests/test_critic_trial.py -q`

Expected: 새 `critic_trial` module/API 부재로 실패. 실제로는 모듈 부재 assertion, 동결 API 30개와 실행기 56개의 부재 RED를 확인했다. 이는 구현 부재 확인이며 의미 행동의 실패 86건을 뜻하지 않는다. B1 계약 부품을 선행 완료한 상태에서 진행했다.

- [x] **Step 3 — 구현 소스 파일을 작성한다.**

실제 구현: [critic_trial.py](../../../app/critic_trial.py). 준비·선택 동결과 caller가 명시한 오프라인 대역의 실행, 로컬 적용 차단, 결과 분류를 담당한다.

`OfflineTransport.generate`의 `NotImplementedError`는 caller가 통제한 대역을 명시하라는 계약이다. 실행 가능한 대역은 연결된 테스트 파일에 있으며 실제 provider 기본값은 없다. `OfflineRunner`는 인스턴스별로 직렬 실행하고, audit와 별도인 `runtime_root / run / purpose / request`에 재사용하지 않는 0700 요청 디렉터리를 만든다. 타입·경로 검사는 우발적 사용 방지이며 적대적 Python이나 OS 수준 격리가 아니다. 네 책임 모두 정확한 schema의 응답 roundtrip과 잘못된 출력 분류를 검사하지만 fixture의 의미 verdict를 정답으로 인증하지 않는다.

reserve·journal·thread 시작·조회 장애는 로컬 결과 적용을 막고 실행기를 quarantine하며 활성 등록을 정리한다. 기록 실패를 가짜 종료 상태로 바꾸지 않는다. 중복·예산 등 정상 reserve 전제조건 거부는 호출하지 않고 반환 오류로 남는다. 모든 timeout 분기는 worker 완료 후 첫 poll과 dispatch 전 만료까지 quarantine한다. 활성 요청 취소가 성공하면 먼저 cancellation을 commit한 뒤 중단 신호를 보내고, 이미 worker가 끝난 경우도 quarantine한다. 취소 쓰기 실패는 취소 호출자에게 전파되고 원래 실행에도 명시적 audit fault가 되어 `dispatching`을 정상 결과로 반환하지 않는다. 공유 journal의 취소 실패는 다른 ID를 지정했더라도 모든 활성 결과 적용을 막으며, 준비 검증 중 발생한 quarantine도 reserve 직전 최종 gate를 우회할 수 없다.

늦은 worker의 종료는 원래 요청에 크기가 제한된 별도 event로만 관측하며 원래 종료 상태를 바꾸지 않는다. 늦은 원시 본문은 보존하지 않는다. worker 강제 종료나 관측 쓰기 실패 시 event가 없을 수 있으므로 완전한 감사나 원격 프로세스·사용량 종료를 보장하지 않는다. 현재 결과의 UTF-8 원문 보존 한도는 64,000 bytes이며 상세 분류는 Task 3을 따른다. 실제 모델 기록 정책과 전 구간 중단 확인은 B4/C 준비에 남긴다.

`freeze_call`과 실행 직전 모두 현재 SQL 선택의 버전·account binding을 재검증하며 실제 provider refresh는 하지 않는다. prepared 입력을 재구성해 모든 필드가 맞는지도 확인한다. 요청한 model/effort는 선택 snapshot에, 대역이 보고한 실제 model과 확인 불가 `actual_effort: null`은 완료 결과에 구분한다. runtime profile의 증거 상태는 `declared_not_preflight_confirmed`(DECLARED_NOT_PREFLIGHT_CONFIRMED)이며 실제 preflight 완료가 아니다. 독립 DB와 provider 사이의 분산 transaction은 아니므로 실계정 preflight와 경합 처리는 B4/C adapter에 남긴다. FrozenCall 생성자와 caller 제공 `code_hashes`는 인증 경계가 아니다. 0 해시는 테스트 전용이며 실제 C 기록은 정확한 변경 파일 내용을 해시해야 한다. `call_seconds`는 worker 구간을 제한하며 앞선 SQL 검증·commit과 원격 프로세스 종료까지 제한하는 숫자가 아니다. 자동 모델 대체·API 전환·재시도·재생은 없다.

- [x] **Step 4 — 집중 시험과 회귀를 실행한다.**

Run: `/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -m pytest app/tests/test_critic_audit.py app/tests/test_critic_trial.py app/tests/test_model_catalog.py app/tests/test_model_selection.py app/tests/test_codex_critic.py -q`

Expected: 새 오프라인 경계와 기존 선택·전송 회귀 PASS. 실제 provider 실행 없음. 실패 시 기대값을 약하게 바꾸거나 안전 프로필을 완화하지 않는다.

## Task 3: 결과 분류·상위 문서와 연결 검토

**Files:** 이 감사·실행 계획, [B 전체 계획](2026-09-07-deeptwin-critic-evaluation.md), [DG-V01](../specs/2026-09-07-deeptwin-verification-selection-design.md), [Q01 Task](../../../evals/deeptwin/tasks/v01-q01/Task.md)의 상태·실행 기록을 동기화한다. Task 3의 코드 변경은 없다.

- [x] **Step 1 — 실제 결과 분류와 상위 문서를 동기화한다.**

| 관측 | 기록 | 아직 주장하지 않을 것 |
| --- | --- | --- |
| 명세와 일치한 입출력·참조 | `completed` + `output_contract: valid` | 의미상 올바른 판단 |
| 정상 대역 실행의 잘못된 JSON/참조/상태 | `completed` + `output_contract: model_output_invalid` | 인프라 무효로 제외하거나 자동 최종 점수 |
| transport/factory 오류 또는 다른 model 보고 | `invalid` + 일반화한 원인 + `score: null`; 예외 본문 미보존 | 에이전트의 철학적 판단 실패 |
| 취소/시간 초과/기록 실패 | 실제 commit된 `cancelled`/`timed_out` 또는 명시적 audit 오류; 점수 없음 | 가짜 종료 상태·정상 완료, 원격 종료 확인 |
| 완료 출력의 의미 평가 미연결 | 항상 `semantic: not_checked` + `score: null` | Q1–Q8 성적, 동일 모델 오류 독립성, 렌즈 효과, 실제 파일 수행 성능 |

UTF-8 인코딩 가능한 완료 원문은 SHA-256과 byte 수를 남긴다. 64,000 bytes 이하는 원문을 보존하고, 초과하면 원문을 생략하면서 `raw_omitted: exceeds_64000_bytes`·해시·byte 수를 남긴다. 잘못된 Unicode는 `raw_omitted: invalid_unicode`이며 해시/byte 수가 `null`이다. 두 경우 모두 출력 계약 오류다. `Ledger.begin`의 dispatch 전 만료는 기존 `timed_out` + `{"transfer":"not_started"}` 기록을 사용하므로 점수가 없지만 literal `score: null` 필드가 있는 것은 아니다.

- [x] **Step 2 — 전체 회귀와 diff 검사를 수행한다.**

Run: `/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -m pytest app/tests -q`

Expected: 기존 검사와 새 B 검사 PASS. 최종 개수·경고는 실제 출력에서 기록한다. 아직 실행하지 않은 수치를 예상 완료값으로 넣지 않는다.

Run: `git diff --check`

Expected: 공백 오류 없음. untracked 신규 파일은 별도로 읽고 검토한다.

- [x] **Step 3 — 최종 문서 명세 검토와 전체 품질 검토를 각각 받은 뒤 종료 경계를 보고한다.**

DG-V01과 Q01 상태에는 “B의 오프라인 입력·기록·실행 경계 구현 및 검사”만 추가한다. 실제 harness 패키지, 전 구간 제공자 수명주기, 의미 판정기·C 예산 확인은 B 전체 계획 §5의 미완료로 유지한다. Q01을 실행형 Harbor Task나 모델 자격 시험 완료로 표시하지 않는다. 사용자에게는 완료 범위와 다음 준비 게이트를 설명하고 실행되지 않은 모델 시험을 승인받은 것처럼 시작하지 않는다.

## 2026-09-07 B2/B3 실행 기록

완료 표시 후 root 최종 재검사: 전체 앱 `729 passed, 1 warning in 10.25s`. 기존 핵심 파일 100개와 검토된 신규 코드/테스트 4개의 해시가 모두 동일했다. B2 Task 1–3의 11개 체크박스는 완료, B4 준비 5개는 미완료다. 브랜치 `codex/ui-structure`와 기존 변경을 유지했으며 커밋·스테이징·푸시는 하지 않았다.

최종 문서 명세 검토는 `b2_ledger_preflight`, 전체 코드·통합·문서 품질 검토는 `b2_final_review`가 각각 PASS로 확인했다. 최종 검토자가 입력 계약·journal·실행기 통합 검사 `360 passed in 1.97s`를 별도 실행했다. root는 문서 파일 링크 39개와 제목 anchor 6개, 공백·개행, B4 미완료 체크박스 5개를 다시 확인했다. 완료 표시만 갱신했으며 검토한 코드 네 파일의 내용 해시는 그대로다. 이 검토는 B2/B3의 오프라인 범위만 완료하며 Q01 의미 시험·B4/C를 완료하지 않는다.

- B2 시작 전 전체 기준선은 `482 passed`, 기존 Starlette/AnyIO 경고 1건이다. Task 1은 `b2_ledger_preflight` 명세 검토와 `b2_task1_quality` 품질 검토 PASS, 집중 검사 `140 passed`(root 0.22초)다. 초기 RED 139건은 모듈 부재 assertion이었다. 이후 숫자 subclass·중복 ID·사용 불가 run의 실제 행동 RED 5건을 수정했다. journal symlink 거부와 trigger 기반 transaction rollback 검사를 보강했다.
- Task 2는 `critic_b_contract_plan` 명세 검토와 `b2_task2_quality` 품질 검토 PASS, 집중 검사 `107 passed`(별도 검토 1.54초)다. 초기 모듈 부재 assertion 뒤 동결 API 부재 30 RED → 30 GREEN, 실행기 부재 56 RED → 누적 86 GREEN을 확인했다. 이후 동시 취소/audit 경계의 실제 행동 실패 2건을 수정하고 다른 경계 검사를 보강해 107개가 통과했다. 초기 구현 부재 수치를 의미 행동 coverage로 집계하지 않는다.
- 메모리에서만 수행한 보호장치 제거 확인: 읽기 `BEGIN` 제거 시 실제 SQLite snapshot 교차 실행 검사 1건 실패; prepared 재구성 제거 시 같은 내용으로 위조한 입력 검사 5건 실패; timeout quarantine 제거 시 완료가 poll보다 빠른 경계 검사 1건 실패; 취소 쓰기 실패의 중단/audit 처리 제거 시 취소 rollback 검사 1건 실패. 이 변형들은 파일에 저장하지 않았다.
- root의 위 Task 2 Step 4 관련 회귀 명령은 `315 passed in 1.75s`, Task 3 전체 명령은 `729 passed, 1 warning in 9.37s`였다. 기존 Starlette/AnyIO DeprecationWarning은 동일하다. `git diff --check`와 새 untracked Python 네 파일의 공백·마지막 개행 검사도 통과했다. 문서 수정 뒤 네 문서의 상대 파일 링크 39개·공백·마지막 개행 검사와 `git diff --check`도 통과했다. 최종 문서 명세/전체 품질 검토도 통과했다.
- 구현 두 파일·테스트 두 파일만 새로 추가했다. 기존 핵심 파일 100개의 root 내용 해시 snapshot은 모두 동일했고, 기존 production/UI·합성 fixture·렌즈 자료·World Skill·B1 역사 기록을 변경하지 않았다. Task 3은 지정된 Markdown 네 파일의 현재 상태를 동기화한다. API/UI/capability 변경, 실제 모델 호출·설치·서비스·사용자 DB 변경은 없다.

내부 journal은 제품의 배포 후 프레임워크가 관측 가능한 첫 제어 사건부터의 로그 보존·추출 및 선택적 사용자 내보내기/제작자 피드백 전체 기능이 아니다. 그 요구와 멀티에이전트 관제 그래프·원형 산출물·철학 렌즈 기반 DeepTwin 정체성은 유지한다. 이번 개발 산출물을 사용자 피드백으로 생성하거나 학습 사건으로 기록하지 않았다. B4의 실제 harness 패키지·교차 호출 원본 해시/부모 기록 계보·실제 provider 전 구간 중단·독립 의미 판정기·C 예산 승인은 남아 있다.
