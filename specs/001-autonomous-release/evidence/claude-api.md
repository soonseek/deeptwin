# Claude 공식 API 전용 경계 — 오프라인 구현 증거

확인일: 2026-09-08 · 범위: T019/T020의 독립 어댑터 조각 · 실제 API/Keychain/유료 호출: **0회**

## 판정

Claude 구독이나 Claude Code 로그인을 탐색하지 않는 **공식 직접 API 전용** 경계를 구현했다. catalog
조회와 유료 generation은 각각 keyword-only `explicit_action is True`를 요구한다. 고정 origin, 환경
프록시 미신뢰, redirect 미추적, SDK 재시도 0회, opaque credential ref, 엄격한 모델 pagination과
stale selection, 완결된 메시지까지 보류하는 client-tool 요청, 누적 usage 및 실패/취소 사실을 오프라인
`httpx2.MockTransport`로 검증했다. `anthropic`/`httpx2`가 설치되지 않은 기본 앱 환경에서도 모듈
import는 성공하며, 자격증명을 열거나 패키지를 자동 설치하지 않고 `dependency_unavailable`로 fail
closed 한다.

이 판정은 Claude가 제품에서 이미 연결·실행된다는 뜻이 아니다. GUI/API route, 가격·예산 예약,
durable runtime ledger와 인증된 command/consent token, 실제 tool dispatcher, tool-result replay 방지, 라이브 API
호환성 및 서명된 패키지의 실제 macOS Keychain 수용은 후속 통합·검증이다. 따라서 이 조각만으로
T019의 P01–P12 전체나 T020의 제품 통합 완료를 주장하지 않는다.

## 구현 경계

- `app/adapters/keychain.py`
  - 앱 소유 generic-password service와 provider가 포함된 account key를 사용한다.
  - data-protection Keychain과 서명된 host 전용 access group을 요구한다. 동기화를 끄고 가능한 경우
    `WhenUnlockedThisDeviceOnly` 접근성을 요청한다.
  - 잠김은 `needs_unlock`, entitlement/auth 거절은 `blocked`, 부재는 `missing`으로 분리한다.
  - DB·로그에 원본 키 대신 `CredentialRef`만 보관할 수 있는 인터페이스다.
  - 키 변경은 같은 ref를 덮어쓰지 않고 새 ref로 회전시켜 기존 catalog binding을 무효화한다.
  - production backend는 Security.framework를 프로세스 안에서 호출한다. shell argv나 환경 변수로
    키를 전달하지 않는다. `InMemoryCredentialVault`는 명시적 시험용이며 production fallback이 아니다.
  - 반환 material은 redacted repr과 best-effort mutable-buffer zeroing을 제공한다. 공식 SDK 호출 중에는
    Python 문자열 형태의 키가 프로세스 메모리에 잠시 존재하므로 메모리 덤프 방어를 입증한 것은 아니다.
  - Security.framework 예외와 비정상 반환은 원문 예외를 공개 chain에 연결하지 않고, 민감 query/result를
    지운 다음 정규화한다. 잘못된 UTF-8 material도 공개 오류를 만들기 전에 mutable buffer를 파기한다.
- `app/adapters/claude_api.py`
  - origin은 `https://api.anthropic.com`, mode는 `api`로 고정하며 임의 base URL 입력을 받지 않는다.
  - `httpx2.Client(trust_env=False, follow_redirects=False)`와
    `anthropic.Anthropic(max_retries=0)`을 명시한다.
  - provider packages는 선택 의존성이다. import 시 설치/자격증명 접근을 하지 않고, 실행 시 빠진
    의존성을 typed failure로 돌려준다.
  - catalog 조회와 generation은 서로 독립된 명시 action guard를 먼저 통과해야 한다. 이는 adapter의
    fail-closed 경계이며 실제 사용자·origin·consent 권위는 후속 command service가 결합해야 한다.
  - Models 응답의 `data/has_more/first_id/last_id/after_id`를 페이지·모델·byte·절대시간 상한 아래
    검사하고 중복/빈 continuation/불일치 cursor/null capability를 구분한다.
  - catalog는 credential ref + workspace binding, 조회 시각, 모델 원자료로 hash되며 이 adapter가
    실제 발급한 bounded registry와 함께 확인한다. credential/binding generation과 binding별 request
    epoch로 늦게 도착한 과거 성공이나 동시 refresh가 최신 실패·성공을 덮지 못한다. 키 회전, workspace
    변경, catalog 변조/만료, 사라진 모델, unknown capability 및 출력 한도 초과는 전송 전에 거절한다.
    401/credential missing은 같은 credential의 모든 catalog를, 403은 관찰된 workspace binding만
    폐기한다. 이미 만든 lazy stream도 실제 SDK request 경계에서 현재 권위를 다시 확인한다.
  - Messages 입력은 agent/call/model/history/tool manifest의 호출별 복사본이다. image/PDF는 허용된
    base64 media type만 받고 URL/provider-managed source를 거절하며, 중첩 tool-result modality도 catalog
    capability를 통과해야 한다. historical `tool_use`/`tool_result` 연결·순서와 전체 history의 tool ID
    중복을 검사한다.
    effort는 catalog가 명시적으로 허용한 값만 요청하고, provider가 보고하지 않은 observed effort를
    요청값으로 꾸며내지 않는다. thinking 연속성은 구현 전이므로 현재 명시적으로 거절한다.
  - SSE는 UTF-8/JSON 중복 키·비유한 상수/event 순서/index/ID/stop/전체 byte/event/text/tool JSON 및
    절대시간 상한을 검사한다. 모든 configurable bound에는 더 큰 값을 받을 수 없는 release ceiling이
    있고 model-call ceiling은 runtime 계약의 180초다. credential preflight 뒤와 실제 request 직전
    socket timeout도 남은 adapter deadline 이하로 다시 줄인다. `tool_use`는 모든 block과
    `message_delta/message_stop`이 끝나고 stop reason이 일치한 뒤에만 typed `ToolRequested`로 노출한다.
    입력은 canonical JSON으로 동결하고 접근할 때마다 새 tree를 반환한다. 어댑터 자체는 도구를 실행하지
    않는다.
  - credential을 여는 짧은 수명 안에서 raw key fragment와 hex/base64 및 일반 digest fingerprint canary를
    catalog 공개 필드, provider message/model/text/tool ID·이름·인자, outbound workspace/prompt/history/tool
    projection에 대조한다. 반사 가능성이 있으면 내용은 공개 event/error에 넣지 않고 fail closed 한다.
  - start usage와 최종 cumulative delta의 단조 증가를 확인한 뒤 한 `UsageObserved`로 내보내 중복
    합산을 피한다. 감소한 usage는 known/completed로 승인하지 않는다.
  - `end_turn`, `tool_use`, `max_tokens/context`, `refusal`, `pause_turn`, stream/HTTP/EOF, 전송 전 취소,
    전송 후 취소 요청을 서로 다른 terminal/failure로 보존한다. 취소 도중 context close가 실패해도
    terminal은 정확히 한 개이며 cleanup 불확실성을 함께 남긴다.
  - provider request ID는 키를 반사할 수 있고 hash도 금지된 안정 fingerprint가 되므로 현재 공개 event에는
    넣지 않고 `None`으로 둔다. 별도 비밀 없는 correlation mapping이 구현되기 전까지 이를 추적 가능하다고
    주장하지 않는다.
  - 401/403/413, 일반 429, spend-cap 429, 5xx, transport unknown, stream error를 분류하되 재시도는
    수행하지 않는다. 프로토콜/미래 unknown 오류는 자동 재시도 대상으로 분류하지 않는다.

## P01–P12 커버리지와 남은 통합

| ID | 이 조각에서 확인한 것 | 아직 이 조각으로 확인할 수 없는 것 |
| --- | --- | --- |
| P01 | Claude `subscription` mode 생성 거절, API binding 고정 | Codex subscription/API와 실제 route·DB 혼합 없음 |
| P02 | 생성·credential 저장만으로 HTTP 0회, catalog와 message 각각 `explicit_action=True`만 전송 | guard boolean을 인증된 GUI command·consent에 결합, bootstrap/upload/UI 전체의 외부 호출 0회 |
| P03 | 원본 key의 ref/repr/error/traceback 비노출, 반사 canary, outbound projection scan, 고정 origin, proxy/redirect 차단, Keychain host group | frontend/export/log 전체 secret scan, OS memory 공격 |
| P04 | credential 회전/workspace/catalog 만료·변조, generation/request epoch, 401 credential-wide·403 binding-only 무효화, lazy dispatch 재확인 | 폐기 사실의 durable 저장과 UI 복구 |
| P05 | pagination 중복·불완전·cursor, null capability, missing model, modality/effort/output 검사 | 실제 provider의 모든 모델별 compatibility profile |
| P06 | 병렬 호출별 모델/history/tool 복사, observed model mismatch | 실제 provider 동시 호출과 effort 실제 관찰 |
| P07 | 완전한 tool ID/name/JSON, provider tool 인자 반사 차단, declared client tool만 immutable typed 출력 | schema/grant/path/symlink/artifact/외부 전송 dispatcher 인가 |
| P08 | 여러 block 완전성, 현재·history 전체 중복 ID, tool-use/result 연결, message stop 전 미노출 | side-effect idempotency와 durable restart/replay ledger |
| P09 | partial/duplicate/nonfinite JSON, UTF-8/byte/event/절대시간/EOF/error/stop 및 고정 release ceiling | 장시간 실제 socket 및 미래 이벤트 compatibility 정책 |
| P10 | cumulative usage 단조성·1회 출력, SDK hidden retry 0회, byte/call ceiling | budget 예약과 provider dispatch의 동일 durable transaction |
| P11 | stream/HTTP rate-limit·spend cap·5xx·timeout과 caller-owned retry 사실 | 실제 계정별 오류 변종, 가격/청구 일치 |
| P12 | 준비 시작부터 180초 이하 deadline, 전송 전 cancel, 전송 후 cancel-request, cleanup failure의 정확히 한 terminal | 상위 session remaining deadline 전달, 프로세스·dispatcher 정지, late result/restart ledger 연결 |

## 실행 증거

고정 환경은 T003의 Python 3.12 wheel 검증 환경과 `anthropic==1.4.0`, `httpx2==2.12.0`이다.

```text
/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python -m pytest -q \
  app/tests/test_claude_api.py
........................................................................ [ 67%]
..................................                                       [100%]
106 passed in 1.01s

/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python -m pytest -q \
  app/tests/test_claude_api.py app/tests/test_codex_api_mode.py app/tests/test_codex_api.py
........................................................................ [ 47%]
........................................................................ [ 94%]
........                                                                 [100%]
152 passed, 1 warning in 1.06s

/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python -m pytest -q app/tests
[progress output omitted]
2030 passed, 1 warning in 59.39s

/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python \
  -m compileall -q app/adapters/claude_api.py app/adapters/keychain.py \
  app/tests/test_claude_api.py
PASS

# AST 검사: 모든 focused `fetch_catalog`/`stream` callsite가 explicit_action을 명시
explicit-action callsites: PASS
```

시험은 production URL로 구성된 request를 `MockTransport`가 프로세스 안에서 가로채는 방식이다.
DNS/socket은 사용하지 않았고 합성 키만 사용했다. 선택 의존성 시험은 격리된 Python subprocess에서
두 package import만 의도적으로 차단했다. 테스트 spy가 header 구성을 확인하려고 합성 키를 메모리에
보관하는 것은 production logging 동작이 아니다.

현재 코드/시험 SHA-256:

```text
f5a5779a1645e38d4ae034d70d739b8d5828e302ff6a3a85ba6dfd454105c96d  app/adapters/keychain.py
8782cd5e7a6175d9b83c26df986ba332b35d02442b767336ca389242a84d1410  app/adapters/claude_api.py
7e5fef878479dd349dcf2d1a68bd6b8b4f79889c0c3a7e03e700794768940af6  app/tests/test_claude_api.py
```

## 독립 공격 검토

초기 독립 검토는 data-protection/access-group, 취소+close terminal, 절대 deadline/비유한 timeout/usage,
provider request ID, immutable tool input, self-hash catalog 및 401 재사용 문제를 발견해 먼저 실패 시험을
추가한 뒤 닫았다.

최종 독립 재검토에서는 다시 P01–P12를 공격적으로 대조했다. 첫 failure-first 묶음은 provider 공개
필드의 키/일반 fingerprint 반사, request ID hash, credential-wide 401, 실패 refresh 뒤 stale catalog,
lazy dispatch, concurrent catalog resurrection, caller clock, cancel/deadline preflight, 중첩 modality,
history ID, gzip finality를 포함해 **19 failed**였다. 다음 묶음의 예외 chain/outbound secret projection/
Security.framework 오류는 **3 failed**, provider tool 인자 및 비우회 자원·시간 ceiling은 15개 중
**14 failed / 1 passed**, explicit catalog/generation action guard는 **1 failed**, invalid multimodal 및
request tree의 예외 chain은 각각 **1 failed**였다. 마지막 response-ordering 검토에서는 늦은 catalog
401/503이 더 최신 성공을 폐기하는 경우 **2 failed**, HTTP 200 뒤 늦은 stream 401/403 event가 더 최신
catalog를 폐기하는 경우 **2 failed**를 재현했다. request epoch를 catalog ID에 포함하고 현재 catalog를
조건으로만 failure invalidation하도록 닫았다. 각 실패를 재현한 뒤 소유 경계만 수정했고 마지막 focused
106개, Claude/Codex 교차 152개, 전체 app 2030개가 위 hash에서 통과했다.

독립 adapter 범위의 잔여 P1/P2 blocker는 **없다(CLEAR)**. 이는 위에 적은 command-service consent,
durable budget/permit/tool/replay, 라이브 Claude 호환성, 서명된 macOS Keychain 및 제품 E2E를 통과했다는
뜻이 아니다. 그 미구현/미검증 항목은 이 조각의 완료 판정으로 승계하지 않는다.
