# 문의 답변 예제

가상의 강사 서도윤이 온라인 강의 "도윤의 저녁 데이터 교실"로 온 교육 문의, 수강 상담, 구독자 질문에 답장을 쓰는 예제입니다. 사람, 강의, 문의, 답장은 모두 지어낸 것입니다. 데이터 파일마다 첫 줄 주석에도 그렇게 적어 두었습니다.

이 폴더를 그대로 프로젝트 루트로 씁니다. 스킬(`skills/`), 네 층과 과제와 원장(`.deeptwin/`), 가짜 모델의 답(`answers/`)이 들어 있어 `deeptwin init` 없이 바로 돕니다.

## 돌리는 법

저장소 안의 이 폴더는 고치지 마세요. 테스트가 이 폴더의 데이터(원장 10줄, 조립 결과의 골든 파일)에 기댑니다. 새로 만든 빈 폴더에 내용을 복사해서 돌립니다. `examples/inquiry-reply/.`처럼 끝에 `/.`을 붙이면 숨은 폴더 `.deeptwin/`도 함께, 폴더 안에 한 겹 더 들어가지 않고 복사됩니다.

```sh
D=$(mktemp -d) && cp -R examples/inquiry-reply/. "$D" && cd "$D"
```

명령은 이 버전의 deeptwin으로 돌립니다. 저장소를 받아 쓴다면 `deeptwin` 자리에 `uv run --project <저장소 폴더> deeptwin`을 씁니다.

가짜 모델로 돌리기. 모델을 부르지 않고 `answers/`의 답 파일을 결과물로 씁니다.

```sh
deeptwin compose inquiry-reply task-0001     # 조립한 지침만 본다
deeptwin run inquiry-reply task-0001 --provider fake --fake-answer answers/keeps-principles.md
deeptwin run inquiry-reply task-0001 --provider fake --fake-answer answers/breaks-promise.md
deeptwin verify
deeptwin status
```

- 첫 `run`은 어긴 원칙이 없고, 두 번째 `run`은 `어긴 원칙: prin-01 취업이나 성과를 보장한다고 쓰지 않는다`를 보여 줍니다. 위반은 오류가 아니라 두 실행 모두 원장에 남습니다.
- 실행마다 `.deeptwin/runs/run-NNNN/`에 지침을 넣은 `SKILL.md` 사본, 결과물 `output.md`, 호출 기록 `calls.jsonl`이 남습니다. `skills/inquiry-reply/`와 `.deeptwin/layers/`의 파일은 바뀌지 않습니다.
- 봉인 과제(`task-0101`~`task-0103`)는 `run`도 `compose`도 `sealed_access` 오류로 멈춥니다. 평가에서만 씁니다.

실제 모델로 돌리기. Claude Code의 `claude`를 구독 로그인으로 부릅니다. Claude Code를 설치하고 한 번 로그인해 두면 되고 API 키는 필요 없습니다.

```sh
env -u ANTHROPIC_API_KEY deeptwin run inquiry-reply task-0001
deeptwin verify
```

`env -u ANTHROPIC_API_KEY`는 환경 변수에 키가 있을 때 claude가 구독보다 키를 먼저 쓰지 않게 합니다. 결과물은 명령이 알려 준 실행 ID의 폴더(`.deeptwin/runs/<실행 ID>/output.md`)에 남고, 원본 스킬 파일은 그대로이며, `deeptwin verify`가 통과합니다.

## 데이터 구성

| 곳 | 든 것 |
|----|------|
| `skills/inquiry-reply/SKILL.md` | 고정 지침(답장에 쓸 수 있는 강의의 사실, 절차, 형식)과 유동 영역 표시 한 번 |
| `skills/inquiry-reply/skill.yaml` | 판단 지점 5개(첫 문장, 답의 핵심, 다음 할 일, 말투, 맺음), 맥락 축 `purpose: [교육문의, 수강상담, 구독자질문]`과 `audience: [입문자, 실무자]`, 상한, `checks: checks.py` |
| `skills/inquiry-reply/checks.py` | 원칙의 검사 함수 `no_outcome_promise`, `no_contact_details`. 표준 라이브러리만 씁니다 |
| `.deeptwin/layers/examples/` | 예시 7건: 대표작 good 4건, 대표작 avoid 1건, 보통(`usual`) good 1건, 고친 글(`pair`) 1건 |
| `.deeptwin/layers/cards/` | 판단 카드 12장. 판단 지점마다 한 장 이상이고 `when`이 서로 다릅니다. `card-0009`와 `card-0010`은 `conflicts_with`로 묶였고, `card-0012`는 우선순위 `pri-03`과 부딪쳐 조립에서 빠집니다 |
| `.deeptwin/layers/priorities.yaml` | 우선순위 3개 |
| `.deeptwin/layers/principles.yaml` | 원칙 3개. `prin-01`, `prin-02`는 `checks.py`의 함수를 `check`로 가리키고 `prin-03`은 `check`가 없습니다 |
| `.deeptwin/tasks/` | 과제 10개(아래 표). 모두 `context`가 있습니다 |
| `.deeptwin/ledger.jsonl` | 과제 10개를 `deeptwin task add`로 등록해 생긴 `task` 줄 10개뿐입니다. 봉인 과제의 줄에는 기준의 해시가 있습니다 |
| `answers/keeps-principles.md` | 가짜 모델이 `task-0001`에 돌려주는 답. 모든 원칙을 지킵니다 |
| `answers/breaks-promise.md` | 가짜 모델이 `task-0001`에 돌려주는 답. 검사 함수가 있는 원칙 `prin-01`을 어깁니다 |

| 과제 | 분할 | `purpose` | `audience` | 기준(`reference`) |
|------|------|-----------|------------|------------------|
| `task-0001` | 학습 | 교육문의 | 입문자 | `my_version` |
| `task-0002` | 학습 | 수강상담 | 실무자 | `edit` |
| `task-0003` | 학습 | 구독자질문 | 입문자 | `pick` |
| `task-0004` | 학습 | 교육문의 | 실무자 | `my_version` |
| `task-0005` | 학습 | 수강상담 | 입문자 | `my_version` |
| `task-0101` | 봉인 | 교육문의 | 실무자 | `my_version` |
| `task-0102` | 봉인 | 수강상담 | 입문자 | `edit` |
| `task-0103` | 봉인 | 구독자질문 | 실무자 | `pick` |
| `task-0201` | 예비 | 교육문의 | 입문자 | 없음 |
| `task-0202` | 예비 | 구독자질문 | 실무자 | `my_version` |

어느 과제로 조립해도 원칙과 우선순위가 상한을 넘지 않습니다(`over_budget`이 나지 않습니다). 승인 대기 후보(`candidates/`)는 아직 없습니다. 평가와 피드백을 맡는 뒤의 기능이 이 데이터를 씁니다.

`deeptwin status`는 이렇게 나옵니다.

```text
층별 항목(active/전체): 예시 7/7(대표작 5), 판단 카드 12/12, 우선순위 3/3, 원칙 3/3
승인 대기 후보 0개. 과제: 학습 5, 봉인 3, 예비 2
```
