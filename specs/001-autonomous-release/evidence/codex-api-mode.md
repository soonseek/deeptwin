# 선택적 Codex API 과금 모드 — T021 오프라인 경계 증거

확인일: 2026-09-08 · 범위: T021의 인증/모델 catalog 경계 · 실제 API/Keychain/유료 호출: **0회**

## 현재 판정

Codex 구독 기본 경로와 별개로, 상위 명령 경계가 **API 모드의 명시 action**을 전달한 경우에만 앱
소유 `codex_api` credential을 열어 공식 OpenAI Models API를 조회하는 경계를 구현했다. 이 bool을
인증된 사용자의 정확한 GUI 명령에 결속하는 일은 T023이며, 이 어댑터만으로 사용자 승인을
증명했다고 주장하지 않는다. 어댑터는 Codex 관리형 로그인 디렉터리·OAuth token·공유 구독
credential을 읽거나 변경하지 않으며, 실패 시 구독/API/다른 모델로 자동 전환하지 않는다.

두 차례 독립 검토에서 발견된 credential 반사, 회전/401 폐기 범위, 동시 응답 역전, catalog
현재성, 호출자 시각 우회, 응답 단계 오분류 결함은 실패 우선 회귀시험으로 재현한 뒤 수정했다.
최종 수정 후 별도 검토자가 모든 반례를 새 해시에서 다시 실행했고 P1/P2 blocker 없음으로
판정했다.

공식 근거는 [OpenAI API 인증](https://developers.openai.com/api/reference/overview),
[Models API](https://developers.openai.com/api/reference/resources/models/methods/list),
[Codex App Server](https://learn.chatgpt.com/docs/app-server),
[Codex 인증](https://learn.chatgpt.com/docs/auth)이다. API key 과금 경로와 Codex의 관리형 ChatGPT
인증은 별개의 제품 경계로 유지한다.

이 판정은 Codex API로 모델 생성이 이미 실행된다는 뜻이 아니다. Responses/App Server 중 실제
model-step transport 선택, capability qualification, per-agent 선택, GUI 과금 동의, budget+dispatch
원자성, 실제 account/model 호환성과 전체 업무 실행은 T014/T022/T023/T026 및 후속 runtime
qualification 범위다. 이 어댑터는 Models 행을 실행 가능성이나 modality/effort 지원의 증거로
추론하지 않는다.

## 구현 경계

- `CodexAPIBinding`은 provider가 정확히 `codex_api`인 opaque Keychain ref만 받는다. `codex`
  subscription, `claude`, 일반 `openai` ref를 재라벨링해 넣을 수 없다. 선택 project/organization
  식별자와 credential ref를 함께 binding ID에 고정한다.
- catalog 요청은 `explicit_action is True` 전에는 key를 열거나 HTTP client를 만들지 않는다. origin은
  `https://api.openai.com`, path는 `GET /v1/models`로 고정하고 환경 proxy를 신뢰하지 않으며
  redirect를 따라가지 않고 hidden retry를 수행하지 않는다.
- 키는 `CredentialVault.open()` 범위 안에서만 꺼내 Authorization header에 사용한다. 반환 catalog,
  selection, typed error와 repr에는 원본 key가 없다. provider-controlled request ID는 공개 failure에
  보존하거나 해시하지 않는다. 성공 catalog의 보존 대상 문자열에 의미 있는 길이의 원문 조각,
  표준 raw 인코딩 또는 MD5/SHA-1/SHA-224/SHA-256/SHA-384/SHA-512 fingerprint 인코딩이 반사되면
  전체 catalog를 거절하며 canary 자체는 기록하지 않는다. 이는 명시한 canary 범위의 방어이며
  임의의 모든 비밀 파생값을 탐지한다고 주장하지 않는다.
- 응답은 JSON content type, UTF-8/중복 key/비유한 상수, list/model shape, ID·owner·created,
  중복 모델, 최대 byte/model 수 및 응답 읽기 경과시간 한도를 검사한다. redirect·HTML·oversize·
  malformed catalog는 모델 목록으로 해석하지 않는다. 연결·읽기 timeout과 전체 runtime deadline의
  최종 결속은 T014/T022 범위다.
- snapshot은 provider/mode/binding/fetch time/max age/credential·binding generation/전체 model row로
  hash하고, 이 adapter 인스턴스가 실제 발급한 bounded registry와 함께 확인한다. 공개 dataclass를
  재구성하거나 다른 adapter에서 self-hash한 snapshot은 선택 권한을 얻지 못한다.
- 모델 선택 검증도 명시 action을 요구하고 Keychain ref가 아직 존재하는지 다시 확인한다. key
  rotation/delete, catalog 변조·만료, 모델 소실에는 선택을 거절한다. 401은 같은 credential ref의
  모든 binding catalog 권한을 폐기하고, 403은 해당 project/organization binding을 폐기한다. 각
  binding의 요청 시작 epoch도 단조 증가한다. 늦게 끝난 이전 요청은 새 성공 응답을 덮지 못하고,
  새 catalog를 publish할 때 같은 binding의 이전 catalog 선택 권한을 원자적으로 폐기한다. 따라서
  새 목록에서 제거된 모델은 이전 snapshot으로 계속 선택할 수 없다.
- Models API 기본 행에는 실행 capability 선언이 없으므로 `capabilities=()`와
  `execution_eligible=False`를 유지한다. 요청 modality/capability/effort를 모델명에서 추정하지 않고
  후속 qualification 전에는 거절한다.
- HTTP authentication/authorization/rate-limit/server, protocol, credential, transport-unknown 실패를
  서로 다른 typed 상태로 반환한다. 응답 header 이후 decode/stream 실패는 `response_observed`로
  남기며 `not_sent`로 축소하지 않는다. raw provider body와 예외 문자열을 전달하지 않으며 자동
  재시도와 fallback은 항상 없다.

## 오프라인 시험

```text
/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python \
  -m pytest -q app/tests/test_codex_api_mode.py
................................                                         [100%]
44 passed

/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python \
  -m pytest -q app/tests/test_codex_api_mode.py app/tests/test_claude_api.py
........................................................................ [ 76%]
......................                                                   [100%]
106 passed in 0.55s

/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python \
  -m compileall -q app/adapters/codex_api.py
PASS
```

첫 실패 우선 실행은 수정 전에 새 공격 회귀가 `10 failed, 19 passed in 0.10s`로 기존 결함을 실제
재현했다. 두 번째 독립 검토의 fragment/fingerprint 및 catalog-currentness 반례도 수정 전 재현되고
최종 해시에서 모두 차단됐다. 전체 suite는 병행 중인 권한 경계 수정이 안정화된 후 루트 통합에서
다시 실행한다.

시험은 `httpx.MockTransport`와 합성 `sk-test-*` 값만 사용했다. production URL로 구성한 request는
프로세스 내부 mock이 가로챘으며 DNS/socket·실제 계정·macOS Keychain에는 접근하지 않았다.

현재 코드/시험 SHA-256:

```text
cb4a390609abbabd35254e09f59db2113d70f678f5e02cadd93c97ada52de950  app/adapters/codex_api.py
1416ceeade7aaaa13dfc52499f6d9f2f7b1fabdf64ef69172ae6a05a2c3840b5  app/tests/test_codex_api_mode.py
```

## 검토 상태

최종 독립 감사에서 원문 prefix/suffix, 대문자 SHA-256, SHA-384/512, 지연된 이전 200, 최신 200,
모델 제거 refresh를 별도로 재현했다. Codex API 44개 및 Claude 결합 106개가 통과했고 P1/P2
blocker 없음(`CLEAR`)으로 판정됐다. 실제 네트워크·Keychain·유료 호출은 0회였다.
