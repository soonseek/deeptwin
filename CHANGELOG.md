# 변경 기록

## 다음 버전(아직 배포하지 않음)

0.1.0a1 뒤에 더했고 아직 배포하지 않은 변경입니다.

- 평가: `deeptwin eval pairs`, `deeptwin eval judge`, `deeptwin eval report` 세 명령으로 같은 바탕 스킬의 세 조건(`base` 바탕만, `examples` 바탕+예시, `full` 바탕+딥트윈)을 견줍니다. 쌍 목록과 판정 화면에는 조건 이름이 나오지 않고, 대응표는 보고서를 낼 때 처음 합칩니다. 쌍의 순서와 좌우는 씨앗(`--seed`, 기본은 평가 ID)으로 정하므로 같은 씨앗이면 같습니다.
- 바탕+예시는 가져온 대표작 good 3개만 넣고, 모자라면 모델을 부르기 전에 `not_enough_examples`로 멈춥니다. 견줄 상대(`base`, `examples`)는 `--against`로 고릅니다.
- 판정: 터미널에서 1이나 2로 고르거나, `--web`이면 127.0.0.1에만 여는 웹 화면에서 고릅니다. 한 번에 `--limit`(기본 15)쌍, 한 평가에서 하루에 `--daily-limit`(기본 30)쌍까지 보여 주고, 멈춘 뒤 다시 부르면 남은 쌍부터 이어 고릅니다.
- 봉인 평가: `--split sealed`는 생성 바로 앞에서 묶음을 열고 원장에 `seal_open` 줄을 남깁니다. 다른 평가에서 이미 연 과제는 재사용으로 적고, 기준이 등록 때와 다르면 판정과 보고서에서 알립니다. `--task`로 과제를 좁히고, 생성이 멈추면 `deeptwin eval pairs --resume <평가 ID>`로 남은 것만 만듭니다.
- 바탕 스킬 해시: 평가를 시작할 때 바탕 스킬의 세 파일(SKILL.md, skill.yaml, checks.py)의 해시를 `eval.json`에 남기고, 평가 중에 바뀌면 막지 않고 알린 뒤 보고서에 표시합니다.
- 보고서: 상대마다 바탕+딥트윈이 이긴 횟수, 선택률, 한쪽 꼬리 이항 검정의 p값(30쌍 중 20번이면 0.0494), 고르는 데 걸린 초의 평균과 중앙값을 `report.json`과 `report.md`에 씁니다. 조건마다 호출 수, 호출에 걸린 초, 입출력 글자 수를 적고, 보고서 전체에는 패키지 버전, 커밋, 프롬프트 버전을 적습니다. 평가를 시작할 때와 패키지가 다르면 `package_changed`로 표시합니다.
- 빌드: 빌드 훅(`hatch_build.py`)이 sdist와 wheel 안의 `deeptwin/_commit.py`에 커밋 해시를 넣고, 배포(`release.yml`)는 올리기 전에 그 커밋이 들어 있는지 확인합니다.
- 라이브러리: `deeptwin.runs`의 `prepare_run`과 `execute_run`, 평가 모듈 `deeptwin.eval`, 패키지 버전과 커밋을 돌려주는 `deeptwin.provenance`.
- 새 오류 코드: `no_tasks`, `not_enough_examples`, `eval_not_found`, `eval_incomplete`, `judging_unfinished`, `invalid_choice`, `port_unavailable`.
- 예제: `examples/inquiry-reply`의 README에 봉인 과제 3개로 평가하는 법(쌍 만들기, 고르기, 이어 가기, 보고서)을 더했습니다.

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
