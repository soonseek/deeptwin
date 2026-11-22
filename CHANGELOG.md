# 변경 기록

## 0.1.0a1

TestPyPI에만 올린 첫 알파입니다. 함수 서명과 명령은 0.x 동안 바뀔 수 있습니다.

- 저장 형식: 네 층(예시, 판단 카드, 우선순위, 원칙), 과제, 후보 파일을 읽고 쓰고, 틀린 파일은 파일과 줄을 알려 주고 거부합니다. 모든 파일은 `schema: 1`입니다.
- 원장: 추가만 하는 `ledger.jsonl`을 줄마다 해시로 잇습니다. `deeptwin verify`가 손상된 줄과 바뀐 봉인 기준을 찾습니다.
- 과제: `deeptwin task add`로 학습, 봉인, 예비 가운데 하나로 등록하고 분할은 바뀌지 않습니다. 봉인 과제는 저장 계층에서 토큰 없이 읽지 않습니다.
- 조립: `deeptwin compose`가 모델 없이 원칙, 우선순위, 판단 카드, 예시를 규칙대로 조립합니다. 같은 입력이면 `guide_hash`가 같고, `--ablate`로 층을 뺄 수 있습니다.
- 실행: `deeptwin run`이 조립, 실행 폴더의 SKILL.md 사본, 생성, 원장 기록, 원칙 검사(`checks.py`)를 한 번에 합니다. 공급자는 claude CLI(구독 로그인)와 테스트용 `fake`입니다.
- 가져오기와 상태: `deeptwin skill new`, `deeptwin import --signature`, `deeptwin status`.
- 모든 명령이 `--json`으로 JSON 객체 하나를 냅니다. Ctrl-C로 멈추면 `interrupted`이고 종료 코드는 130입니다.
- 예제: `examples/inquiry-reply`(가상 강사의 문의 답변 스킬과 데이터).
- 프롬프트 자산은 아직 없습니다(실행 기록의 `prompt_version`은 `null`).
- 0.0.1에서 올릴 때: 0.0.1이 쓴 원장 줄에는 `prev_hash`와 `hash`가 없어서 `deeptwin verify`는 손상으로 알리고 `deeptwin run`은 `ledger_broken`으로 멈춥니다. `.deeptwin/ledger.jsonl`을 다른 이름으로 옮겨 두면 새 체인이 시작됩니다.

## 0.0.1

뼈대입니다: `init`, 원칙 하나로 조립, 가짜 모델로 `run`, 원장 한 줄.
