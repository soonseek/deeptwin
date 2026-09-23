# DeepTwin 공급자 연동 조사: Claude API · Codex 구독

확인일: 2026-09-07. 상태: **조사·설계 제안이며 구현 또는 실계정 검증 완료가 아니다.**

## 0. 현재 요구와 변경 이력

2026-09-07 조사 도중 사용자가 **“클로드는 사전 승인 안받고 그냥 api 방식으로만 하는걸로 할게.”**라고 명시적으로 변경했다. 따라서 최초의 양쪽 구독 필수 요구와 이 문서 초안의 Claude 사전 승인 release blocker는 현재 요구에서 폐기됐다.

현재 범위는 **Claude API 전용 + Codex 구독 기본, Codex API는 명시적으로 선택한 경우에만**이다. 최종 사용자는 독립 DeepTwin UI를 사용하고, DeepTwin이 실행 수명주기·실제 도구·에이전트별 모델 선택을 관리한다. 구독 실패를 API로 자동 전환하지 않는다. API 방식 채택은 무제한 유료 실험 승인이 아니다.

공식 문서·공개 소스·약관과 저장소 소스만 읽었다. 인증 파일/토큰·사용자 DB를 읽거나 복사하지 않았고, 로그인·설치·실모델 호출·서비스 실행은 하지 않았다. research 스킬의 1차 출처 조사 방식과 OpenAI Docs 스킬의 공식 문서 우선 순서를 적용했다. 법률 의견이 아니라 명시된 서비스 사용 경로와 기술적 인수 조건의 기록이다.

## 1. 권고 결론

| 경로 | 권고 | 인수 전 남은 일 |
| --- | --- | --- |
| Claude API | **직접 Messages API + Models API + DeepTwin 소유 client-tool loop**. 공식 API SDK는 HTTP/타입/streaming 수단으로 사용 | API 키 보관·명시적 비용 동의·모델 capability 카탈로그·도구 인가·예산·취소·실제 업무 E2E |
| Codex 구독 | 전용 `CODEX_HOME`에서 공식 비대화형 CLI(`codex login --device-auth`, `codex exec --json`)를 격리된 관리형 실행기로 사용 | 정확한 CLI 버전, 모델·sandbox·approval·명시적 MCP/도구 bridge, JSONL·취소·배포 적격성 |
| Codex API | 별도 mode/credential/catalog/과금 선택으로 격리 | 명시적 선택 UX와 별도 어댑터 검증. 구독 fallback으로 재사용하지 않음 |
| Claude 구독/Claude Code 로그인 | **현재 범위 제외** | 승인 획득을 현 프로젝트 출시 조건으로 두지 않음 |

Claude 직접 API는 다음 모델 응답을 받는 stateless Messages와 애플리케이션이 실행하는 client tools를 제공하므로, 프레임워크 소유 루프라는 요구에 잘 맞는다. 이는 문서에서 도출한 설계 판단이다. [Messages API](https://platform.claude.com/docs/en/api/messages/create), [How tool use works](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works)

Anthropic Commercial Terms는 해당 서비스를 고객 제품에 사용하는 경로를 설명한다. 모든 배포/사용 사례의 무조건 허용을 뜻하지는 않지만, 이제 Claude 구독 제3자 승인 문제를 해결할 필요는 없다. 일반 서비스 약관·Usage Policy·지원 지역·데이터 처리 조건은 적용된다. [Commercial Terms — 적용 범위 및 §A.1/§D](https://www.anthropic.com/legal/commercial-terms)

## 2. Claude API: 공식 계약과 구현 방향

### 인증·비용·모델 목록

공식 직접 API 주소는 `https://api.anthropic.com`이며 Console API 키로 접근한다. 현재 문서는 `Authorization: Bearer` 및 기존 `x-api-key`를 지원하고 `anthropic-version`을 요구한다. 여러 workspace를 다루는 키는 workspace 지정이 필요할 수 있다. 공식 SDK가 인증/버전 헤더를 구성하므로, 검증한 SDK 버전과 공식 응답 계약에 맞춰 구현한다. [API overview — Authentication](https://platform.claude.com/docs/en/api/overview)

키 처리에 대한 설계 제안:

- 최종 사용자가 명시적인 API 연결 화면에 제공한 키만 사용한다. Claude Code 인증 파일, 브라우저 쿠키, 구독 OAuth 토큰에서 가져오지 않는다.
- 원본 키는 로컬 backend의 OS credential store 등 별도 비밀 저장소에 보관하는 방향으로 설계한다. UI 상태·업무 DB·prompt·tool args·export에는 opaque `credential_ref`만 사용한다. 키 저장 구현은 아직 없다.
- browser bundle/localStorage에 원본 키를 저장하지 않는다. 로컬 UI의 연결 변경 요청에도 origin/CSRF·loopback 접근 경계를 검증한다. 재시작 후 “키 있음”과 “현재 API 접근 확인됨”은 다른 상태다.
- 개인 키 직접 사용을 기본 설계 가정으로 둔다. 운영자 공용 키로 사용자의 비용을 대신 부담하는 서버형 사업 모델은 이번 조사에서 승인/설계하지 않았다.
- Models API로 연결을 확인하는 것도 네트워크/인증 전송이므로 명시적 사용자 액션으로만 수행한다. 목록 성공을 충분한 잔액·최종 실행 성공으로 표현하지 않는다.

API는 사용량 기반 비용과 조직/workspace 한도의 적용을 받는다. 정적 금액 대신 비용 추정의 단가 출처·확인일·캐시/도구 가정을 기록한다. 공급자 한도와 DeepTwin 업무별 예산은 다른 장치다. [Pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Rate limits](https://platform.claude.com/docs/en/api/rate-limits)

`GET /v1/models`는 사용 가능한 API 모델을 제공한다. `data`, `has_more`, `first_id`, `last_id` 및 `after_id` 페이지 계약을 사용한다. 현재 응답은 모델 ID/표시명 외에 nullable capabilities, 최대 입력/출력 토큰 등을 포함한다. 예제 모델 이름이나 숫자를 실제 계정 값으로 복사하지 않는다. [List Models](https://platform.claude.com/docs/en/api/models/list)

DeepTwin은 provider/mode, credential/workspace binding, catalog ID, 조회 시각에 묶인 snapshot을 만들고 각 에이전트의 정확한 모델·effort/thinking·입력 modality·structured output 요구를 검증한다. capabilities가 없으면 지원된다고 추측하지 않는다. 상세 조회나 버전별 compatibility profile이 필요하면 출처를 기록한다. 키/workspace 변경, 모델 retirement, 갱신 실패 시 재확인을 요구하고 다른 모델/공급자로 몰래 전환하지 않는다.

Messages의 `model`과 `output_config`는 요청별 설정이며 시스템 지침은 문서화된 top-level `system`에 넣는다. DeepTwin이 agent별 history를 소유하고, provider client를 공유하더라도 선택·메시지·도구 grant를 공유 mutable 설정으로 두지 않는다. 응답 모델과 요청 모델을 비교하고 실제 effort가 보고되지 않으면 null로 둔다. [Create a Message](https://platform.claude.com/docs/en/api/messages/create)

### DeepTwin이 소유하는 client-tool loop

공식 client-tool 흐름은 모델이 `tool_use`를 반환하고 애플리케이션이 실행 후 `tool_result`를 보내는 방식이다. server tools는 Anthropic 측에서 실행되는 별도 루프다. 기본 DeepTwin 프로필은 명시한 client tools만 선언하고 server tools/원격 MCP/관리형 환경을 묵시적으로 활성화하지 않는 것이 적합하다. [How tool use works](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works)

제안하는 실행 순서:

1. 입력·선택·tool manifest·권한·예산을 고정하고 감사 예약을 durable하게 기록한다.
2. agent별 시스템 지침·허용 자료·정확한 모델과 `name/description/input_schema` 도구 목록으로 Messages 요청을 보낸다. [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
3. 완성된 응답의 모든 tool ID·이름·입력을 파싱한다. 실행 전에 DeepTwin이 schema, grant, 경로, artifact 버전, 외부 전송/발행 권한, 남은 예산을 검증한다. 모델의 요청은 사용자 승인이 아니다.
4. 실제 도구는 DeepTwin dispatcher가 실행한다. 병렬 요청도 각각 인가하고 공유 파일 쓰기는 충돌 정책을 따른다. `call_id + tool_use_id` 기록으로 replay/restart의 중복 부작용을 차단한다.
5. assistant content를 보존하고 바로 뒤의 user message에 대응하는 `tool_result`를 전달한다. 누락·다른 call ID·순서 오류를 거절한다. 비신뢰 도구 결과를 system 지침으로 승격하지 않는다. [Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)
6. 후속 요청도 같은 선택/권한과 전체 deadline·호출/도구/토큰 예산을 검사한다. `end_turn`은 모델 응답 종료이지 업무 성공 증거가 아니다. 실제 artifact/verifier가 완료를 판단한다.

Claude Agent SDK/Claude Code subprocess 없이 구현 가능한 구조이므로, 구독 CLI의 사용자 hooks/skills/MCP 자동 발견 문제를 새 API 어댑터로 가져올 이유가 없다. 서버 실행 도구가 나중에 필요하면 별도 runtime profile·전송 동의·실행 위치/비용 표시·적격성 검증을 거친다.

### 스트리밍·중단·오류·재시도

공식 SSE는 message/content block 시작·delta·종료와 최종 `message_stop`을 제공한다. `input_json_delta`는 부분 JSON이고 usage delta는 누적 값이다. HTTP 200 이후에도 stream error가 올 수 있으며 새 이벤트 유형이 추가될 수 있다. [Streaming messages](https://platform.claude.com/docs/en/build-with-claude/streaming)

DeepTwin 설계 제안:

- 완전한 tool block과 해당 메시지의 종료/stop reason을 검증하기 전 실제 도구를 실행하지 않는다. UI text delta와 실행 권위를 분리한다.
- event/JSON/UTF-8/전체 출력 크기·block 수·시간 상한을 명시한다. 비핵심 미래 이벤트는 기록/무시할 수 있지만 실행 권한·모델 선택에 영향을 주는 알 수 없는 구조는 fail-closed한다.
- `tool_use`는 도구 처리 대기, `max_tokens`/context 초과는 미완료, `refusal`은 정상 HTTP에서도 가능한 거절이다. client-only 프로필의 예상 밖 server tool/`pause_turn`은 프로필 불일치다. 무한 continuation이나 안전 거절 우회를 하지 않는다. [Stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons)
- 취소 시 신규 tool/model dispatch를 먼저 막고 스트림을 닫는다. 연결 종료가 이미 처리된 추론/비용까지 취소했다는 증거는 아니다. 취소 요청, local transport 종료, 관찰된 terminal, usage/과금 불명을 구별한다.
- 공급자 request ID와 정규화된 오류를 내부 감사에 연결하되 원시 오류에 섞일 수 있는 키/입력은 노출하지 않는다. 401/403, 크기 오류, 429, 5xx, stream error를 구분한다. [API errors](https://platform.claude.com/docs/en/api/errors)
- 공식 Python SDK의 일부 오류 재시도는 기본 2회, timeout은 기본 10분이다. 최초 어댑터는 `max_retries=0`과 명시 timeout으로 숨은 요청을 제거하고, 필요한 재시도는 프레임워크가 예산·감사·전송 불확실성을 반영해 결정하는 방향을 권고한다. SDK `extra_*` overrides를 사용자 데이터에서 직접 전달하지 않는다. [Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)

429에는 rate limit뿐 아니라 spend cap도 있다. 현재 문서는 일반 rate limit의 `retry-after`와 spend-cap 오류 코드 및 재시도해도 회복되지 않는 경우를 구별한다. “429이면 반복”하지 않고, 한도 인상·인증 모드 전환도 자동 수행하지 않는다. [Rate limits — Spend caps / Response headers](https://platform.claude.com/docs/en/api/rate-limits)

공식 API SDK 소스도 확인했다. 이는 Claude Agent SDK와 다른 라이브러리다. 구현 전에 프로젝트 의존성과 SDK 버전을 확인·고정해야 하며 이번 조사에서는 설치하지 않았다. [anthropics/anthropic-sdk-python](https://github.com/anthropics/anthropic-sdk-python), [공식 README](https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/main/README.md)

## 3. Codex: 공식 경로와 저장소 재사용 경계

첫 정식 후보는 공식 비대화형 실행 경로다. 전용 `CODEX_HOME`에서 `codex login --device-auth`로 관리형 ChatGPT 인증을 만들고, 정확한 CLI 버전의 `codex exec --json`을 `--ignore-user-config`, `--ignore-rules`, `--ephemeral`, 명시적 `--model`, `--sandbox`, 작업 디렉터리와 검증된 설정으로 실행한다. 저장된 CLI 인증은 재사용하되 `auth.json`을 공개 저장소·이미지·일반 로그나 DeepTwin 업무 저장소에 복사하지 않는다. JSONL은 무제한 passthrough가 아니라 크기·순서·종료가 검증된 내부 이벤트로 정규화한다. [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode), [Authentication](https://learn.chatgpt.com/docs/auth)

이 경로는 Codex의 자체 agent loop를 실행하므로 Claude API의 raw model-step과 동일하다고 표현하지 않는다. DeepTwin은 바깥의 업무 그래프, 에이전트별 모델 선택, 투영된 입력, sandbox/approval, 허용된 framework-tool bridge, 예산·취소·artifact·감사 권위를 유지한다. 일반 사용자 프로젝트나 hooks/skills/MCP를 ambient하게 읽지 않으며, 실제 프레임워크 도구가 필요하면 DeepTwin dispatcher로만 이어지는 명시적이고 버전 고정된 MCP/IPC 구성을 별도 적격성 검증한다.

App Server는 인증·대화·승인·스트리밍 및 `model/list`를 통합할 수 있는 공식 인터페이스지만, **명령 전체가 experimental이고 production workload에 지원되지 않는다**. 기본 stdio가 원격 WebSocket 고유 위험을 피한다는 사실은 이 maturity 제한을 없애지 않는다. 첫 릴리스 실행은 App Server에 의존하지 않으며, 추후 `model/list` 같은 기능을 쓸 경우 UI에 preview로 명시하고 실패 시 허위 카탈로그를 만들지 않는다. fallback은 CLI가 확인한 기본 모델과 사용자가 입력한 정확한 모델 ID를 실제 실행 preflight로 검증하는 방식이다. [App Server](https://learn.chatgpt.com/docs/app-server)

Codex API는 명시적으로 선택한 별도 과금 경로다. 현재 구독 어댑터의 API 거절 조건을 삭제하여 같은 실행으로 통과시키지 않는다. mode별 credential binding·카탈로그·비용 동의·어댑터를 분리한다. 이번 조사에서는 Codex API 전용 구현 방식을 확정하거나 실호출하지 않았다.

| 로컬 근거 | 확인한 범위 | 확대하면 안 되는 결론 |
| --- | --- | --- |
| [providers.py](<repo>/app/providers.py:63) | 실행 파일 발견과 unknown 상태 | 설치됨 = 로그인/실행 가능 |
| [CodexConnection](<repo>/app/codex_connection.py:151) | account/read에서 chatgpt/API 분리, 비밀을 반환하지 않는 UI 상태 | 인증 확인 = 자율 실행 완성 |
| [모델 조회](<repo>/app/codex_connection.py:209), [선택 검증](<repo>/app/model_catalog.py:198) | 명시 조회 목록, 계정 binding과 현재 SQL 목록 검증 | 공개 모델 이름·오래된 선택 = 가용 모델 |
| [격리 프로필](<repo>/app/codex_understanding.py:339), [thread/turn](<repo>/app/codex_understanding.py:453) | `0.144.4` 고정, environmentless, 빈 dynamicTools, exact model 확인 | 일반 DeepTwin tool host 구현 완료 |
| [OfflineRunner](<repo>/app/critic_trial.py:108) | 통제된 fixture 실행과 감사 수명주기 | 실구독·전체 환경·의미적 성능 qualification 완료 |

기존 텍스트 critic의 도구 금지 조건을 전역으로 완화하지 않는다. 새 tool host는 별도 profile과 평가가 필요하다. 최신 문서 옵션을 검증 없이 `0.144.4`에 추가하지 않는다. 현 Claude unavailable 문구/카탈로그가 구독 승인 대기를 표현하는 것은 **기존 구현 상태**다. 이제 API-only 모델로 변경할 구현 항목이지 새 요구의 차단 사유가 아니다.

## 4. 제안하는 공급자 중립 인터페이스

아래는 설계 제안이며 아직 코드가 아니다. B1의 `PreparedInput` 6필드, `prepare_input`, `parse_response` 및 두 예외는 바꾸지 않는다. 연결·과금·선택·감사 metadata는 모델 prompt 밖 execution envelope에 둔다.

| 경계 | 제안 계약 | 불변식 |
| --- | --- | --- |
| 연결 | `ProviderConnection(provider, mode, auth_state, credential_ref, account_binding, checked_at)` | Claude api만, Codex subscription/api 분리. 원본 키/토큰/이메일은 모델·공용 감사에 전달하지 않음 |
| 카탈로그 | `ModelCatalogSnapshot(provider, mode, binding, catalog_id, fetched_at, models)` | 실제 조회 모델/기능만 제공. 인증·목록 가용성·실행 적격성 별도 표시 |
| 선택 | `AgentModelChoice(agent_id, provider, mode, catalog_id, model_id, effort, thinking)` | agent별 immutable 선택, 미지원/unknown 옵션 거절, 요청/관찰 값 구분 |
| 런타임 | `RuntimeProfile(id, adapter_version, tool_manifest_sha, isolation_rules_sha)` | 선언과 이번 preflight 증거 구분; 도구 실행 위치 명시 |
| 입력 | `AgentTurn(call_id, agent_id, frozen_input_ref, selection, runtime, deadline, budget, consent_ref)` | 프레임워크가 그래프·허용 자료·예산·권한·수명주기의 권위자 |
| 이벤트 | `Started / TextDelta / ToolRequested / ToolResult / Usage / ModelObserved / Terminal` | call/agent/tool ID·순서·중복·크기 검증; 원시 JSON arbitrary passthrough 금지 |
| 도구 | `dispatch_tool(call_id, agent_id, tool_name, args, grant_ref)` | 스키마·경로·artifact 버전·읽기/쓰기/외부 전송 인가를 실행 직전 수행 |
| 취소 | `cancel(call_id)` + terminal observation | 요청·전송 불확실성·실제 종료 구분; late result가 terminal을 덮어쓰지 않음 |

API budget은 호출·최대 입력/출력·도구 수·시간·통화 예산을 함께 제한한다. 추정 비용은 청구서가 아니며 usage 불명 호출을 0원으로 확정하지 않는다. Codex 구독 로그인도 추가 credits 사용 여부나 무료 실행을 자동 보증하지 않는다. 실제 과금 분류가 확인되지 않으면 unknown으로 남긴다.

Claude 직접 API에서는 DeepTwin이 모델-도구 루프도 소유할 수 있다. Codex 구독의 `exec --json`은 공급자 agent loop이므로 DeepTwin의 외부 작업 그래프·선택·dispatcher 통제와 공급자 내부 루프 대체를 구분한다. 후자까지 필요한 기능은 별도 Codex API model-step 어댑터로 검증하며, CLI/MCP 연결만으로 동등성을 선언하지 않는다.

## 5. 추가해야 할 실제 검증

아래는 **아직 실행하지 않았다**. fake HTTP/RPC 단위 검증, 임시 도구·파일 통합, 승인된 유료/구독 실호출 및 제품 E2E를 구분한다. 실호출에는 별도 사용자 승인, 합성 자료, 횟수/시간/금액 한도, 비공개 감사 저장소를 사용한다.

| ID | 검증과 관찰할 결과 | 단계 |
| --- | --- | --- |
| P01 | Claude subscription 선택 거절; Claude API와 Codex subscription/API 연결·카탈로그·credential 혼합 없음. 자동 mode fallback 0회 | 오프라인 계약 |
| P02 | bootstrap·업로드·저장·snapshot의 provider/login/생성 요청 0회. 연결/목록 조회와 유료 생성 동의 분리 | UI/backend 통합 |
| P03 | 합성 키가 frontend state·export·오류·로그·prompt·tool args에 없음. origin/CSRF, 악성 base URL/redirect/proxy override로 credential 유출 불가 | 오프라인 보안 |
| P04 | 키/workspace/계정 변경·401/403·만료·unknown에서 stale 선택 거절 및 자료 전송 0회. API 연결이 Codex 공유 구독 인증을 몰래 변경하지 않음 | 오프라인 + 명시 연결 |
| P05 | pagination 중복/불완전, capability null, 모델 삭제/hidden, effort/modality 부적합 검출. 예제 이름을 계정 가용성으로 꾸미지 않음 | fake Models API/RPC |
| P06 | 서로 다른 provider/model/effort의 동시 agent에서 입력·history·grant·선택 교차 없음. actual model mismatch/fallback·effort 미보고 기록 | 오프라인 + 승인 실호출 |
| P07 | tool ID/이름/인자 위조, cross-agent grant, 경로 탈출/symlink, stale artifact, 승인 전 발행/overwrite를 실행 전 거절. artifact hash/writer 확인 | 임시 파일/통제 도구 |
| P08 | 병렬 tool_use 전체 결과 연결·tool_result 순서·중복 ID 처리. replay/restart 후 동일한 외부 부작용 자동 재실행 없음 | fault injection |
| P09 | 부분 JSON·초과 UTF-8/stream bytes·error event·EOF·missing message_stop·max_tokens·refusal·예상 밖 server tool 처리. 불완전 입력으로 dispatcher 호출 없음 | fake SSE |
| P10 | 누적 usage delta 중복 합산 없음. per-agent/전체 예산 동시 예약 강제. SDK hidden retries 0회, 통제한 재시도만 감사/예산 반영 | HTTP spy |
| P11 | 429 retry-after/spend cap, 5xx, timeout/전송 불명 구분. 무한 재시도·한도 인상·모델/모드 자동 전환 없음 | 오류 fixtures |
| P12 | 시작/preflight 실패, cancel commit 실패, deadline, 종료 실패, late result, 재시작 복구에서 신규 dispatch 차단과 사실대로 terminal/unknown 보존 | 수명주기 injection |
| P13 | Codex 고정 버전에서 미승인 hooks/skills/MCP/context canary 유입 없음과 허용 DeepTwin 도구 실제 호출을 함께 입증 | 런타임 적격성 |
| P14 | 지원 OS의 새 사용자 환경에서 독립 UI로 Claude API 연결/Codex 공식 로그인·선택·작업·취소·재시작 완료. 개발자 개인 설정 의존 없음 | 제품 E2E |
| P15 | **Claude API와 Codex 구독 각각** 선택 모델과 DeepTwin 도구로 합성 업무의 산출물 생성·검증·인계. optional Codex API는 별도 mode로 검증 | 승인·한도 있는 최종 인수 |

P15의 업무 성공은 schema-valid 응답이나 연결 성공으로 대체할 수 없다. 실제 artifact와 외부 의미 verifier/사람의 기준이 필요하다. B1/B2 오프라인 PASS는 이 증거가 아니다. 합성 canary 통과도 시험한 버전/경계의 증거이지 모든 호스트의 보편적 샌드박스 증명은 아니다.

## 6. 제외된 대안과 인계

### 변경 전 조사 기록 — 현재 요구가 아님

Claude Code print/Agent SDK는 기술적으로 프로그램 실행·MCP 도구를 제공하지만 SDK overview는 사전 승인 없는 제3자 구독 로그인/한도 제공을 제한한다. 2026-06-15 SDK 과금 변경 유예를 제품별 승인으로 볼 수는 없다. **사용자의 API-only 변경으로 승인 확보와 구독 transport 구현은 현재 범위에서 제외됐다.** [SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [Login — Developers](https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account), [SDK plan update, 표시일 2026-06-16](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)

CLI `--bare`/SDK settings·MCP 격리 조합은 새 Claude API 어댑터의 선행 조건이 아니다. 이를 위해 인증 파일을 복사하거나 승인을 요청하지 않는다. [초기 공급자 조사](<repo>/docs/ui/2026-09-07-provider-integration-findings.md)는 역사적 상태로 읽는다.

### 현재 인계 항목

- 런타임 구현자: Claude 직접 API/client-tool dispatcher, 키 보관·비용 동의, mode별 카탈로그를 구현한다. Codex 기존 인증 자산과 텍스트 critic 격리를 유지하면서 별도 tool host를 검증한다.
- UI 설계자: Claude API 키/사용량 과금, Codex 구독 기본/명시 API 선택을 표시한다. 키 있음·인증·모델 가용성·실행 준비·업무 성공을 분리하고 Claude 승인 대기는 현재 흐름에서 제거한다.
- 평가 책임자: 오프라인, 실제 프로토콜/도구/취소, 실제 업무 성공, 비용/보안 인수를 각각 기록한다. 비용이 드는 검증을 무제한 실행하지 않는다.

미해결은 OS credential store, 지원 OS/패키징, SDK 버전·catalog capability 호환성, Codex tool-host/optional API 구현, 수명주기와 업무 E2E다. **현재 blocker는 Claude 구독 승인이 아니라 이 구현·검증 항목들이다.** 이번 변경은 이 연구 문서뿐이며 앱 코드는 수정하지 않았다.
