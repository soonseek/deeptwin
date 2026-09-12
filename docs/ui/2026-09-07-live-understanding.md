# Codex 구독 업무 이해 — 실제 합성 확인 기록

> **개발 호스트의 역사적 실험:** 아래 로컬 CLI/기존 인증 관찰은 현재 웹 제품의 배포 또는
> 최종사용자 여정이 아니다. 현행 요구는 브라우저 UI를 공식 제품 표면으로 하고, 서버가
> 소유·격리한 Codex 관리형 실행기를 사용한다. Claude 구독 항목은 Claude API-only 결정으로
> 대체됐다.

날짜: 2026-09-07  
상태: 실제 합성 추론 2건(직접 연결 1건, 실제 UI+파일 1건) 통과. 개발 UI 연결 완료.

## 실제로 확인한 것

- 설치된 공식 Codex CLI 0.144.4와 기존 ChatGPT 구독 인증을 사용했다. API 키를 읽거나
  API 과금 경로로 전환하지 않았고 로그인·전역 설정을 변경하지 않았다.
- 새로 만든 한국어 주간 회의 설명과 합성 작성 기준만 보냈다. 실제 사용자 업무나 기존 보관 자료는 사용하지 않았다.
- 명시 선택한 `gpt-5.6-terra`, 추론 수준 `low`로 약 6.95초 만에 구조화 응답을 받았다.
- 응답은 PDF 2쪽과 CSV 산출물 요구, 외부 전송 금지 제약, 원문과 정확히 일치하는 source quote를
  식별했다. 질문과 추정은 없다고 구분했다.
- 관찰 이벤트는 `userMessage`, `reasoning`, 최종 `agentMessage`였고 turn은 completed였다.
  완료 응답의 `itemsView`는 `notLoaded`였다. 메타데이터 로그에 reasoning 본문을 기록하지 않았다.

이는 작은 합성 예시 2개가 계약대로 왕복했다는 증거다. 다양한 문서, 긴 입력, 오류가 있는
현실 업무, 의미 정확도, 재현성, 속도 목표 또는 제품 품질을 통과했다는 뜻이 아니다.

## 입력 전 격리 경계

- 인증 RPC와 generation RPC를 분리하고 generation은 정확히 0.144.4만 허용한다.
- 공식 experimental API를 켠 뒤 thread와 turn에 `environments: []`를 명시한다. 공식 도구 계획은
  환경이 없을 때 shell/exec, apply_patch, request-permissions, view_image를 모델 도구에 등록하지 않는다.
- thread는 `ephemeral: true`, `dynamicTools: []`, `selectedCapabilityRoots: []`다.
  `instructionSources: []`를 사용자 글자 전송 전에 확인한다.
- 프로세스별 설정으로 MCP·skills·plugins·apps·검색·협업·hooks·memory와 관련 도구를 끄고,
  실제 설정/스킬 재조회가 안전하지 않으면 자료를 보내지 않는다. `CODEX_EXEC_SERVER_URL=none`으로
  기본 실행 환경을 없애며 사용자 `environments.toml`이 있거나 검사할 수 없으면 시작하지 않는다.
- 원격 관제는 process별 공식 비활성 환경변수로 끄고 실제 상태 알림이 disabled임을 확인했다.
- `update_plan` 같은 내부 도구까지 0개라고 주장하지 않는다. 예상 밖 tool item, MCP·approval 요청,
  서버 주도 요청, 설정·skill 변경 알림이 나오면 성공 결과로 받지 않는다.
- 응답의 `runtimeWorkspaceRoots` 한 항목은 cwd 메타데이터이며 환경 도구가 활성화됐다는 뜻이 아니다.
  실행 가능성의 기준은 빈 thread/turn environments와 빈 capability roots다.

처음 두 `turn/start` 시도는 당시 설치 스키마에 없는 `readOnly.access`를 보낸 탓에 로컬에서
JSON-RPC `-32600`으로 거절됐고 모델 추론은 시작되지 않았다. 실제 스키마에 맞춰
`sandboxPolicy: {type: "readOnly", networkAccess: false}`와 `environments: []`로 수정한 뒤에만
위 2건을 실행했다. 실패 시도를 성공 횟수에 포함하지 않는다.

## 실제 UI 왕복과 기록 검증

- 두 번째 실제 추론은 별도 임시 보관함의 개발 서버에서 설명 입력 → TXT 업로드 → 실제 모델
  목록 조회 → Terra/low 저장 → 명시 클릭 → 실제 응답 → 새로고침 후 GET 재열람으로 확인했다.
- 입력 revision 2와 모델 설정 버전이 요청에 고정됐고, 원문 응답·결과·실제 모델이 저장됐다.
  실제 모델 요청은 1회였으며 업로드·저장·재열람은 모델을 호출하지 않았다.
- 결과의 PDF/CSV 요구를 보존했다. 실제 모델의 `PDF`, `CSV` 형식을 MIME 문자열만 처리하던
  UI가 '기타 형식'으로 숨긴 문제를 RED 시험으로 재현하고 수정했다. 알 수 없는 형식도 원래
  이름을 안전한 텍스트로 표시하며 일반 텍스트로 바꾸지 않는다.
- 업로드 파일 ID를 포함한 실제 응답 근거 10쌍을 화면의 source_id·인용문과 정확히 대조했다.
- 실행 프로필 `codex-0.144.4-environmentless-v1`은 generate 전에 로컬 감사 입력과 요청에
  원자 저장한다. 이는 적용할 구현 프로필 기록이지 사전 점검 성공이나 전송 완료 표시가 아니다.
  DB 실패/잘못된 프로필 시 모델 미호출을 통제된 실제 SQLite 시험으로 확인했다.
- 운영 개발 화면 4193을 기존 보관함으로 재시작했다. 준비 상태 true, 업무 전후 0개,
  읽기 전용 화면 확인 POST 0회·스크립트 오류 0건. 사용자 마이크나 자료를 사용하지 않았다.
- [실제 합성 결과 화면](../../app/review-output/live-understanding-result.png)
  및 [전체 화면](../../app/review-output/live-understanding-synthetic-1200.png).

## 아직 확인하거나 구현하지 않은 것

- 실제 사용자 마이크·다양한 업무의 품질 검증, 실제 구독 실행 중 취소의 실측(취소/늦은 응답은
  통제된 provider 회귀로 검증했으며 원격 사용량의 즉시 종료를 보장하지 않는다).
- Claude 구독 연결과 Claude 모델 목록·선택. 공개 모델 이름을 연결 가능 목록으로 꾸미지 않는다.
- 철학 렌즈 선택·효과, 독립 크리틱, 구조적으로 다른 후보 그래프, 차이의 인과 검증.
- 그래프 노드와 에이전트별 provider/model/effort 배정, 변경 이력, 실제 에이전트 실행.
- 환경 승인·도구 실행·산출물 생성·재평가·버전 승격. 이번 추론에서 PDF나 CSV 파일 자체를
  생성하거나 외부로 보낸 것은 아니다.
- API fallback, API 키 입력, 추가 크레딧 구매 또는 자동 모델 대체. 모두 구현하지 않았고
  조용히 추가하지 않는다.

## 공식 근거

- [Codex App Server](https://learn.chatgpt.com/docs/app-server)
- [thread/start의 환경 계약](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/app-server-protocol/src/protocol/v2/thread.rs)
- [turn/start의 환경 계약](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/app-server-protocol/src/protocol/v2/turn.rs)
- [0.144.4 도구 등록 계획](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/core/src/tools/spec_plan.rs)
- [app-server 초기화와 MCP startup](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/core/src/session/session.rs)

## 최종 회귀

- Python 316개와 브라우저/오디오 worklet 62개, 합계 378개 통과. 실패·건너뜀 0.
  외부 Starlette/AnyIO deprecation 경고 1건은 남아 있다.
- 실행 환경/API opt-in, 추가 도구 feature gates, config projection, 원격 환경 설정,
  완료 알림 순서·유실·타 스레드/턴·내부 계획 호출, 전송 후 실패 문구, 빈 완료 알림 조립,
  실행 프로필 감사 저장, 실제 형식 표시를 RED→GREEN 회귀에 추가했다.
- OpenAI Docs와 공식 소스 검증이 실험적 실행 계약 선택에 영향을 주었다. Superpowers 원인 분석·
  TDD·완료 검증을 적용했고, Frontend Design은 기존 입력 중심 화면을 유지하면서 모델이 반환한
  산출물 형식을 사용자가 알아볼 수 있게 표시하는 수정에 사용했다.

이 기록은 같은 날의 이전 차단 기록을 지우지 않고 후속 해결 상태를 덧붙인다. 이전 회귀 수치와
통제된 모델 대역 결과는 당시 사실로 유지한다. 기능 연결 검증과 DeepTwin 효과 검증은 다르다.
