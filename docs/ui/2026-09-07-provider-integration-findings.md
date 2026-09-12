# 공급자 통합 확인 기록

> **역사적 조사:** 이후 사용자는 Claude를 API-only로 확정했다. Claude 구독 통합·사전 승인과
> 양쪽 구독 필수 문구는 현재 릴리스 조건이 아니다. Codex 구독은 DeepTwin 웹 인스턴스의
> 서버 소유 관리형 실행기, Codex API는 별도 명시 선택이다. 최신 정본은
> `specs/001-autonomous-release/spec.md`와 `provider-research.md`다.

확인일: 2026-09-07

이 문서의 구현 상태 표현은 **연결 작업 전 초기 조사 시점**을 보존한 것이다.
후속 Codex 계정 연결은 [연결 기록](2026-09-07-codex-connection.md), 모델 조회·선택과
남은 실행 경계는 [모델·음성 기록](2026-09-07-model-control-and-voice.md)을 따른다.

이 기록은 DeepTwin 최종 사용자 앱에서 Codex와 Claude를 연결할 수 있는지 공식 문서로 확인한 결과다. 현재 구현은 로컬 실행 파일의 존재만 찾는다. 로그인, 모델 호출, 토큰 확인, 사용량 조회는 하지 않는다.

## 서로 다른 세 가지 상태

- **설치됨**: 운영체제에서 공식 CLI 실행 파일을 찾았다는 뜻일 뿐이다.
- **인증됨**: 해당 CLI 또는 공식 프로토콜이 현재 계정을 확인했다는 별도 상태다. 설치 여부로 추정할 수 없다.
- **통합 허용됨**: 공급자 정책상 DeepTwin 같은 제3자 제품이 그 인증과 구독 한도를 사용해도 된다는 뜻이다. 인증 성공만으로 허용을 추정할 수 없다.

현재 `list_providers()`는 첫 번째 상태만 보고한다. 실행 파일을 찾더라도 인증과 결제 방식은 `unknown`, 실제 실행 capability는 `false`다.

## Codex / ChatGPT

OpenAI의 [Codex app-server 문서](https://learn.chatgpt.com/docs/app-server)는 제품 내부 통합을 위한 인증, 대화 기록, 승인, 스트리밍 이벤트 프로토콜을 제공한다. [인증 문서](https://learn.chatgpt.com/docs/auth)는 ChatGPT 로그인이 구독 접근이고 API 키 로그인이 사용량 기반 API 과금임을 구분한다.

따라서 향후 Codex 어댑터는 app-server가 반환하는 인증 모드와 플랜을 직접 확인하고, 브라우저 또는 기기 코드 로그인을 공식 흐름으로 시작해야 한다. 현재는 어댑터가 연결되지 않았고 로그인도 확인하지 않았다.

## Claude

Anthropic의 [Agent SDK 개요](https://code.claude.com/docs/en/agent-sdk/overview)는 사전 승인이 없는 제3자 개발자가 자기 제품에서 claude.ai 로그인이나 구독 rate limits를 제공하는 것을 허용하지 않는다고 명시한다. [Claude 로그인 정책](https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account)도 제3자 소프트웨어에는 API 키를 우선 권장하며, 제3자 트래픽을 구독 한도로 가장해 보내는 행위를 금지한다.

[Claude 플랜의 Agent SDK 사용 안내](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)는 2026-06-15 변경을 일시 중단했으며, 현재 Agent SDK, `claude -p`, 제3자 앱 사용량이 구독 사용량 한도에서 차감된다고 설명한다. 그러나 이 사용량 회계 상태가 모든 제3자 앱에 로그인·통합 권한을 부여한다는 뜻은 아니다. 공식 SDK 문서의 사전 승인 제한과 함께 적용해야 하며, 정책이 다시 바뀔 수 있다.

또한 [Claude Code의 Pro/Max 안내](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan)와 [API 키 환경변수 안내](https://support.claude.com/en/articles/12304248-manage-api-key-environment-variables-in-claude-code)는 `ANTHROPIC_API_KEY`가 있으면 구독보다 API 과금이 우선된다고 밝힌다. 향후 두 결제 경로를 구현한다면 프로세스와 사용자 동의를 분리해야 한다.

## 충족되지 않은 필수 요구

사용자가 요구한 **Codex와 Claude 모두를 각 구독으로 사용하는 통합**은 아직 충족되지 않았다. Claude 구독 통합에는 Anthropic의 명시적인 사전 승인이 필요하다. API 키 기반 Claude 연결은 기술적 대안이지만 별도 사용량 과금이며, 필수 구독 요구를 대신 충족했다고 표시해서는 안 된다.

따라서 현재 화면이나 API는 설치 여부만 정직하게 표시하고, 로그인됨·구독 사용 가능·실행 가능 상태를 만들거나 암시하지 않아야 한다.
