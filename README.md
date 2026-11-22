# deeptwin

개인의 판단 기준을 층별 파일로 쌓고, 작업마다 맞는 기준만 모델 없이 조립해 스킬의 유동 영역에 넣는 Python 라이브러리입니다.

> 아직 초기 단계입니다(0.1.0a1, 시험용 저장소 TestPyPI에만 있습니다). 지금은 스킬 뼈대를 만들고, 과거 작업물을 예시로 가져오고, 과제를 등록하고, 원칙, 우선순위, 판단 카드, 예시를 조립해 스킬을 한 번 돌리고, 결과물이 어긴 원칙을 알려 주고, 쌓인 상태를 보고, 바탕만과 바탕+딥트윈의 결과물을 가린 채 골라 보고서를 내는 길까지 있습니다. 함수 서명과 명령은 0.x 동안 바뀔 수 있습니다.

## 설치

```sh
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple deeptwin==0.1.0a1
```

Python 3.11 이상이 필요합니다. 알파 버전은 TestPyPI에만 올립니다. `--extra-index-url`은 TestPyPI에 없는 의존성(pydantic, pyyaml, filelock, typer 등)을 PyPI에서도 찾게 합니다. pip은 두 저장소를 같은 무게로 보므로, TestPyPI에 같은 이름의 패키지가 있으면 그쪽을 받을 수도 있습니다. PyPI의 `pip install deeptwin`은 아직 뼈대만 든 0.0.1입니다. 바뀐 것은 [CHANGELOG.md](https://github.com/soonseek/deeptwin/blob/main/CHANGELOG.md)에 적습니다.

## 쓰는 법

프로젝트 폴더에서 개인 데이터 폴더를 만듭니다. `.deeptwin/`이 생기고 `.gitignore`에 `.deeptwin/` 줄이 더해집니다.

```sh
deeptwin init
```

`.deeptwin/`이나 그 안에 만들 폴더의 자리에 파일이 있거나, `.gitignore`가 파일이 아니면(폴더 등) 아무것도 만들거나 바꾸지 않고 `init_blocked` 오류로 멈춥니다.

스킬 뼈대를 만듭니다. `skills/<스킬 ID>/`에 `skill.yaml`, 유동 영역 표시가 든 `SKILL.md`, 주석만 든 `checks.py`가 생기고, 만든 직후 그대로 `compose`가 돕니다. `run`은 이 스킬에 걸리는 원칙이 `check`에 적은 검사 함수가 `checks.py`에 있어야 돕니다(없으면 `check_not_found`). `SKILL.md`에 고정 지침을, `skill.yaml`에 판단 지점(`decision_points`)과 맥락 축(`context_axes`)을 채워 씁니다.

```sh
deeptwin skill new <스킬 ID>
```

- `skill.yaml`은 `schema: 1`, `id`, `version: 1`, 빈 `decision_points`와 `context_axes`, 기본 `budget`, `example_policy: random_signature`, `checks: checks.py`로 시작합니다. `checks.py`에는 함수 없이 검사 함수의 규약을 적은 주석만 있습니다(아래 원칙 검사 참고).
- 그 폴더가 이미 있으면(비어 있어도) `skill_exists` 오류로 멈추고 아무 파일도 바꾸지 않습니다. ID가 ID 규칙(영문자, 숫자, `.`, `_`, `-`만 쓰고 영문자나 숫자로 시작)에 맞지 않으면 `invalid_id`입니다.
- `--json` 결과는 `skill`, `files`(프로젝트 루트 기준, `skill.yaml`, `SKILL.md`, `checks.py` 순)입니다.

과거 작업물을 예시로 가져옵니다. 폴더 바로 아래의 글 파일 하나가 본능 층의 예시 하나(`.deeptwin/layers/examples/ex-NNNN.yaml`)가 됩니다. `--signature`를 주면 대표작(`grade: signature`)으로 표시하고, 주지 않으면 `grade: usual`입니다. 조립은 대표작만 예시로 넣습니다(아래 조립의 6단계).

```sh
deeptwin import <폴더> --skill <스킬 ID> [--signature]
```

- 확장자가 `.txt`, `.md`인 파일(대소문자 무관)을 파일 이름순으로 가져옵니다. 점으로 시작하는 파일과 하위 폴더는 보지 않습니다.
- 글은 UTF-8(BOM 허용)로 읽어 줄바꿈을 `\n`으로 바꾸고 앞뒤 공백을 뗀 것입니다. 예시는 `kind: good`, `tags: {}`, `source: past_work`, `status: active`, `approval: human`(사람이 직접 가져왔다)으로 씁니다.
- ID는 지금 있는 `ex-` 번호의 최댓값 + 1부터 4자리로 매깁니다(`ex-0004`).
- 같은 스킬에 글이 같은 예시가 이미 있거나 이번에 앞서 가져온 파일과 같으면 만들지 않고 `skipped`에 적습니다. 글은 앞뒤 공백을 떼고 견줍니다. 그래서 같은 폴더를 다시 가져와도 예시가 늘지 않습니다.
- 전부 아니면 전무입니다. 모든 파일을 먼저 읽고 검사한 뒤 한 잠금 안에서 번호를 정하고 씁니다. 비었거나(공백뿐이어도) UTF-8이 아닌 파일이 하나라도 있으면 아무것도 쓰지 않고, `invalid_file` 오류로 그런 파일마다 한 줄씩 경로, 줄, 이유를 알립니다. 글 파일이 없으면 `nothing_to_import`, 스킬이 없으면 `skill_not_found`입니다.
- `--json` 결과는 `skill`, `imported`, `skipped`입니다. 새로 쓴 예시만 `imported`에 들고 `--signature`의 등급을 받습니다. 건너뛴 파일은 예시를 만들지 않으므로, `same_as`가 가리키는 예시의 등급은 바뀌지 않습니다. `imported`는 `[{"id": "ex-0001", "file": "past/p1.txt"}, ...]`, `skipped`는 `[{"file": "past/p1.txt", "same_as": "ex-0001"}, ...]`이고 `same_as`는 글이 같은 예시의 ID입니다. `file`은 프로젝트 루트 기준 경로입니다(루트 밖이면 받은 경로 그대로).

```text
오류: past/p3.txt:1: 글이 비었습니다(공백뿐인 파일도 빈 글로 봅니다)
```

과제를 등록합니다. 과제 파일 하나가 과제 하나이고, 등록하면 `.deeptwin/tasks/<분할>/<ID>.yaml`에 쓰이고 원장(`.deeptwin/ledger.jsonl`)에 `task` 줄이 남습니다.

```sh
deeptwin task add <과제 파일>
```

```yaml
# 가상 인물의 문의. 예로 지어낸 것이다.
schema: 1
id: task-0101
skill: minimal
split: sealed            # train(학습), sealed(봉인), spare(예비)
input: 수강료를 알려 주세요.
context:                 # 선택. 축과 값은 스킬의 context_axes에 있어야 한다
  purpose: 문의
reference:               # 선택. 봉인 과제에는 꼭 있어야 한다
  kind: my_version       # my_version, edit이면 text, pick이면 picked와 rejected
  text: 수강료는 한 달에 십만 원입니다.
```

- 분할은 등록할 때 한 번 정하고 바꿀 수 없습니다. 같은 ID가 세 분할 폴더 어디에든 있거나 원장에 그 ID의 `task` 줄이 있으면 분할과 상관없이 `task_exists` 오류로 거부하고 아무것도 쓰지 않습니다. 과제 파일을 지워도 원장 줄이 남아 있으니 그 ID는 다시 쓸 수 없습니다.
- 봉인 과제는 결과물을 만들기 전에 받아 둔 기준(`reference`)이 있어야 합니다. 없으면 `reference_required`입니다. 원장의 `task` 줄에는 기준의 해시(`reference_hash`)가 남습니다. 기준을 정렬된 JSON으로 쓴 것의 SHA-256이고, 학습과 예비 과제는 `null`입니다. 기준의 내용은 출력하지 않습니다.
- 형식이 틀리면 `invalid_file`(파일과 줄), 스킬이 없으면 `skill_not_found`, 맥락이 스킬과 맞지 않으면 `invalid_context`입니다. `id`에는 영문자, 숫자, `.`, `_`, `-`만 씁니다.
- 원장을 먼저 덧붙이고 과제 파일을 씁니다. 원장의 마지막 줄이 깨졌으면 `ledger_broken`으로 멈추고 과제 파일도 생기지 않습니다.
- `--json` 결과는 `task`, `split`, `skill`, `path`(`.deeptwin/` 기준), `reference_hash`입니다.

봉인 과제는 평가에서만 씁니다. 저장 계층이 봉인 토큰 없이 봉인 과제를 읽지 않으므로, `deeptwin run`과 `deeptwin compose`에 봉인 과제를 주면 실행 폴더, 원장 줄, 모델 호출 없이 `sealed_access` 오류로 멈춥니다. 토큰은 평가 모듈만 만들고, 밖으로 내주는 함수는 `deeptwin.eval.open_sealed` 하나입니다. 봉인 과제로 결과물을 만드는 길은 `deeptwin eval pairs --split sealed`(아래 봉인 평가)뿐입니다.

```text
오류: 과제 task-0101은 봉인 과제라 읽을 수 없습니다. 봉인 과제는 평가에서만 씁니다.
```

쌓인 상태를 한 번에 봅니다. 아무 파일도 쓰지 않습니다.

```sh
deeptwin status
```

```text
층별 항목(active/전체): 예시 5/5(대표작 5), 판단 카드 0/0, 우선순위 0/0, 원칙 2/2
승인 대기 후보 1개. 과제: 학습 1, 봉인 0, 예비 0
```

- `--json` 결과는 `layers`, `candidates`, `tasks`입니다.
  - `layers`는 네 층(`instinct`, `tendency`, `priority`, `principle`)마다 `total`과 상태별 수(`active`, `candidate`, `dormant`, `retired`)입니다. `instinct`에는 대표작(`grade: signature`) 수 `signature`도 있고, 상태와 상관없이 셉니다.
  - `candidates.pending`은 후보 파일(`.deeptwin/candidates/`) 가운데 `status: pending`인 수입니다.
  - `tasks`는 분할(`train`, `sealed`, `spare`)마다의 과제 파일 수입니다.
- 과제는 파일 이름만 셉니다. 봉인 과제도 내용을 읽지 않습니다. 층과 후보 파일은 읽어서 세므로, 형식이 틀린 파일이 있으면 `invalid_file`입니다.

`deeptwin skill new`, `deeptwin import`, `deeptwin status`는 원장에 줄을 쓰지 않습니다. 원장에 남는 줄은 `task`(과제 등록)와 `run`(실행)뿐입니다.

스킬을 과제 하나로 돌립니다. 조립한 지침을 넣은 `SKILL.md` 사본과 결과물은 `.deeptwin/runs/<실행 ID>/`에 남습니다. 원본 `SKILL.md`와 층 파일(`layers/`)은 바뀌지 않고, 카드의 `stats`도 고치지 않습니다. 실행은 원장(`.deeptwin/ledger.jsonl`)에 한 줄로 남습니다.

실행 ID는 `run-NNNN`입니다. 번호는 `runs/`의 실행 폴더 번호와 원장 `run` 줄의 ID 번호 가운데 큰 것 + 1이라, 실행 폴더를 지워도 원장에 남은 실행 ID는 다시 쓰지 않습니다. 원장에서 읽을 수 없는 줄은 번호를 매길 때 건너뜁니다(원장이 깨졌는지는 아래 4단계와 `deeptwin verify`가 봅니다).

```sh
deeptwin run <스킬 ID> <과제 ID> [--context 축=값]... [--ablate 층]...
```

맥락과 뺄 층은 `deeptwin compose`와 같은 옵션, 같은 규칙으로 정합니다(아래 `compose` 참고). 같은 과제와 옵션이면 `compose`가 보여 준 조립이 그대로 실행에 쓰이고, 원장 `run` 줄의 `injected`, `rejected`, `no_hit`, `conflicts`, `guide_hash`, `context`가 `deeptwin compose --json`의 결과와 같습니다.

스킬의 `context_axes`에 축이 있는데 맥락이 비었으면 `context_required` 오류로 멈춥니다. 과제 파일에 `context`가 없거나 `context: {}`이고 `--context`도 주지 않은 경우입니다. 스킬에 축이 없으면 빈 맥락으로 돕니다. `deeptwin compose`는 미리 보기라 이 검사를 하지 않습니다.

```text
오류: 과제 task-0102에 맥락이 없습니다. 과제 파일의 context에 적거나 --context 축=값으로 주세요. 스킬 minimal의 축: purpose(문의, 상담, 기타)
```

`deeptwin run`은 아래 순서로 봅니다. 어느 단계에서 멈추든 실행 폴더, 원장 줄, 모델 호출이 생기지 않습니다.

1. 스킬과 과제(봉인 과제면 `sealed_access`), 과제와 스킬이 맞는지
2. 맥락: `--context`의 모양, `context_required`
3. 조립: `invalid_context`, `unknown_layer`, `over_budget` 등
4. 원장의 끝 줄: 이어 쓸 `hash`를 얻지 못하면 `ledger_broken`
5. 원칙의 검사 함수: `check_not_found`, 불러오다 실패하면 `check_failed`(아래 원칙 검사 참고)
6. 공급자: `claude_not_found`, `fake_answer_required`

실행 폴더를 만든 뒤 사본 쓰기나 생성이 실패하면(공급자 오류, 시간 초과, Ctrl-C) 방금 만든 그 실행 폴더를 지우고 원래 오류를 그대로 냅니다. Ctrl-C면 `interrupted`입니다(아래 출력 규칙 참고). 생성이 끝난 뒤의 실패(결과물 쓰기, 원장 덧붙이기)에는 실행 폴더를 남깁니다. 이미 비용을 낸 호출의 기록이 들어 있기 때문입니다.

`--json` 결과는 `run`, `task`, `split`, `context`, `ablate`, `injected`, `rejected`, `no_hit`, `conflicts`, `guide_hash`, `output`(`.deeptwin/` 기준), `violations` 순입니다. 글 모드는 마친 실행, 넣은 항목, 뺀 항목, 맞는 카드가 없던 판단 지점, 어긴 원칙, 결과물을 차례로 씁니다.

원칙 검사. 생성하고 원장에 기록한 뒤, 결과물을 원칙의 검사 함수로 봅니다. 원칙의 `check`에 함수 이름을 적고, 그 함수를 스킬 폴더의 `checks.py`에 둡니다. `skill.yaml`의 `checks`에는 그 파일의 경로를 스킬 폴더(`skill.yaml`이 든 폴더) 기준으로 적습니다(`checks: checks.py`). 스킬 폴더 밖(`..`, 절대 경로)은 가리킬 수 없습니다.

```yaml
# .deeptwin/layers/principles.yaml
- id: prin-01
  rule: 수치를 부풀리지 않는다
  kind: never
  check: no_inflated_numbers   # checks.py의 함수 이름. 없으면 null
  scope: []
  status: active
  approval: human
```

```python
# skills/<스킬 ID>/checks.py
import re


def no_inflated_numbers(output: str) -> bool:
    return not re.search(r"역대급|최고의|100%", output)
```

- 검사 함수는 `checks.py`의 모듈 수준 함수 `fn(output: str) -> bool`입니다. 결과물 글을 받아 지켰으면 `True`, 어겼으면 `False`를 돌려줍니다.
- 검사하는 원칙은 조립과 같은 범위입니다. `status: active`이고 `scope`가 비었거나 이 스킬을 담은 원칙을 `principles.yaml` 순서대로 봅니다. `check: null`인 원칙은 건너뜁니다. `--ablate`와 상관없이 모두 검사합니다.
- 어긴 원칙은 `--json` 결과의 `violations`에 `{"principle": "prin-01", "rule": "수치를 부풀리지 않는다", "check": "no_inflated_numbers"}` 꼴로 남고, 글 모드에는 한 줄씩 `어긴 원칙: prin-01 수치를 부풀리지 않는다`로 나옵니다. 없으면 `violations`는 `[]`이고 글 모드는 `어긴 원칙이 없습니다.`입니다. 검사할 원칙이 하나도 없을 때도 같습니다.
- 위반은 오류가 아닙니다. 종료 코드는 0이고, 실행 폴더와 원장 `run` 줄은 그대로 남습니다. 위반을 원장에 쓰지는 않습니다.
- 함수는 모델을 부르기 전에 찾아 둡니다. 검사할 원칙이 있는데 `skill.yaml`에 `checks`가 없거나, 파일이 없거나 스킬 폴더 밖이거나, 함수가 없거나 부를 수 없으면 `check_not_found`입니다. 파일을 불러오다 예외가 나면(문법 오류 등) `check_failed`입니다. 둘 다 실행 폴더, 원장 줄, 모델 호출 없이 멈춥니다. 검사할 원칙이 없으면 `checks.py`를 읽지 않습니다.
- 함수가 예외를 내거나 `bool`이 아닌 것을 돌려주면 `check_failed`입니다. 그때는 실행이 이미 원장에 남았으므로, 메시지 끝에 그 실행 ID와 결과물 경로가 나옵니다.
- `checks.py`는 파일 경로로 불러오고 `sys.modules`에 넣지 않으며 `sys.path`도 바꾸지 않습니다. 그래서 다른 스킬의 `checks.py`에 같은 이름의 함수가 있어도 섞이지 않습니다. 표준 라이브러리와 설치한 패키지는 import할 수 있지만, 같은 폴더의 다른 파일은 import할 수 없습니다. `__pycache__`를 남기지 않고, 고친 파일은 다음 실행에서 바로 읽힙니다.
- `checks.py`는 deeptwin이 그대로 실행하는 코드입니다. 남이 만든 스킬이면 `checks.py`를 먼저 읽어 보세요.

```text
오류: skills/minimal/checks.py에 원칙 prin-01의 검사 함수가 없습니다: no_inflated_numbers
```

Python에서는 `deeptwin.check(skill, output, deeptwin)`이 같은 검사를 하고 `Violation` 목록을 돌려줍니다(설계서 8.5).

기본 공급자는 `claude`입니다. Claude Code의 `claude` 명령을 헤드리스(`claude -p`)로 부릅니다. Claude Code를 설치하고 한 번 로그인해 두기만 하면 되고, API 키는 필요 없습니다. 다만 `claude -p`는 환경 변수 `ANTHROPIC_API_KEY`가 있으면 구독보다 그 키를 먼저 씁니다. 구독으로 돌리려면 그 변수 없이 실행하세요(예: `env -u ANTHROPIC_API_KEY deeptwin run ...`). 부를 때는 도구를 끄고(`--tools ""`) 사용자의 CLAUDE.md, 플러그인, 훅을 빼며(`--safe-mode`) 세션을 저장하지 않습니다. `claude`가 없으면 `claude_not_found` 오류로 멈춥니다.

```sh
deeptwin run <스킬 ID> <과제 ID> --provider fake --fake-answer answer.txt
```

`--provider fake`는 테스트와 예제 확인용입니다. 미리 적어 둔 답 파일을 결과물로 돌려줍니다.

모델을 부를 때마다 실행 폴더의 `calls.jsonl`에 한 줄이 남습니다. 어느 공급자로 불러도 같고, 실패한 호출은 남지 않습니다.

```json
{"provider": "claude", "model": "claude-opus-5-5", "version": "2.1.330 (Claude Code)", "prompt_version": null, "input_chars": 1234, "output_chars": 456, "seconds": 8.871, "cached": false}
```

| 필드 | 뜻 |
|------|----|
| `provider` | 공급자 이름(`claude`, `fake`) |
| `model` | 답한 모델 이름. 모르면 `null` |
| `version` | 공급자의 버전. claude는 `claude --version`의 출력. 모르면 `null` |
| `prompt_version` | 프롬프트의 버전. 지금은 늘 `null` |
| `input_chars` | 시스템 프롬프트(스킬 사본)와 과제 입력의 글자 수 합 |
| `output_chars` | 답의 글자 수 |
| `seconds` | 호출 하나에 걸린 시간(초, 소수 셋째 자리까지) |
| `cached` | 캐시에서 꺼낸 답인지. 지금은 늘 `false` |

조립한 지침만 보려면 `deeptwin compose`를 씁니다. 모델을 부르지 않고, 실행 폴더도 원장도 쓰지 않습니다. 같은 입력이면 출력이 바이트까지 같습니다.

```sh
deeptwin compose <스킬 ID> <과제 ID> [--context 축=값]... [--ablate 층]...
```

맥락은 과제 파일의 `context`입니다. `--context 축=값`을 주면 그 축만 덮어씁니다. 여러 번 줄 수 있지만 같은 축은 한 번만 줍니다. 축은 `skill.yaml`의 `context_axes`에 있어야 하고 값은 그 목록에 있어야 합니다. 아니면 `invalid_context` 오류로 멈춥니다. `deeptwin run`도 같습니다.

`--ablate 층`을 주면 그 층을 빼고 조립합니다. 한 층이 없을 때를 비교해 보는 용도입니다. 층 이름은 `instinct`(예시), `tendency`(판단 카드), `priority`(우선순위), `principle`(원칙) 넷입니다. 여러 번 줄 수 있고, 같은 층을 두 번 주면 한 번 준 것과 같습니다. 뺀 층의 항목은 지침에도, `injected`와 `rejected`에도 남지 않습니다. 다만 `principle`이나 `priority`를 빼도, `conflicts_with`에 `active`인 원칙이나 우선순위의 ID가 든 카드는 그대로 `lower_layer`로 빠집니다(`lower_layer`는 범위나 `ablate`와 상관없이 `active`인지만 봅니다). 모르는 이름을 주면 `unknown_layer` 오류로 멈춥니다. `--json` 결과의 `ablate`에는 준 층이 준 순서대로 한 번씩 남습니다. `deeptwin run`도 같습니다.

조립은 설계서 8.6의 순서를 따릅니다.

1. 원칙과 우선순위: `status: active`이고 `scope`가 비었거나 이 스킬을 담은 것을 파일 순서대로 모두 넣습니다. `principles_max`나 `priorities_max`보다 많으면 자르지 않고 `over_budget` 오류로 멈춥니다. 항목을 합쳐 줄이라는 뜻입니다.
2. 카드 후보: `skill.yaml`의 판단 지점마다, 이 스킬의 `active` 카드 가운데 `when`이 맥락과 맞는 것을 모읍니다. `when`에 적은 축은 모두 맞아야 하고, 적지 않은 축과 빈 목록인 축은 맞는 것으로 봅니다. 판단 지점이 `skill.yaml`에 없는 카드는 보지 않습니다.
3. 점수: 맞은 축의 수, 일치율 `(agreed + 1) / (injected + 2)`, `last_used` 순으로 큰 쪽이 먼저입니다. 모두 같으면 `id` 순입니다.
4. 충돌: `conflicts_with`에 `active`인 원칙이나 우선순위의 ID가 든 카드를 먼저 뺍니다. 남은 카드 가운데 `conflicts_with`로 묶인 둘은 점수가 높은 쪽만 남깁니다. 점수가 같으면 둘 다 빼고 그 쌍을 `conflicts`에 적습니다.
5. 상한: 판단 지점마다 `cards_per_point`장까지 넣습니다. 그래도 전체가 `cards_total`장을 넘으면 `weight`가 낮은 판단 지점(같으면 `skill.yaml`에서 뒤의 것)의 낮은 순위 카드부터 뺍니다.
6. 예시: `skill.yaml`의 `example_policy`가 기본값 `random_signature`이면, 이 스킬의 `active` 예시 가운데 대표작(`grade: signature`)인 `good`과 `avoid`에서 고릅니다. `usual`, `rushed` 등급과 `pair`는 넣지 않습니다. 종류마다 후보를 `sha256(과제 ID + "\n" + 예시 ID)`의 16진 글 순으로 줄 세워 앞에서부터 뽑습니다. 과제 ID가 씨앗이라 같은 과제면 운영체제와 Python 버전에 상관없이 같은 예시가 뽑히고, 다른 과제면 다른 예시가 뽑힐 수 있습니다.
   - 기본은 `good` 둘과 `avoid` 하나입니다. `budget.examples`는 둘을 합친 상한입니다. 상한이 3보다 작으면 `avoid`부터 줄이고(1이면 `good` 하나, 2면 `good` 둘), 더 커도 둘과 하나를 넘지 않습니다. 후보가 모자라면 있는 만큼만 넣고, `good`이 모자라 남은 자리에는 `avoid`가 들어갑니다.
   - 다른 정책(`similar`, `recent`)은 아직 없어 `unsupported_example_policy` 오류로 멈춥니다. 예시 층을 빼면(`--ablate instinct`) 이 검사를 하지 않습니다.
7. 표기: 원칙, 우선순위, 판단 지점별 카드, 예시(`이렇게 쓴다`, `이렇게는 쓰지 않는다`) 순으로 정해진 틀에 씁니다. 빈 섹션은 쓰지 않습니다. 원칙, 우선순위, 카드에 여러 줄로 적은 글은 한 줄로 이어 씁니다. 예시 글은 앞뒤의 빈 줄과 줄 끝 공백만 떼고 줄바꿈은 그대로 두며, 한 섹션에 예시가 둘이면 사이에 `---` 줄을 둡니다.

뺀 카드와 뽑히지 않은 예시 후보는 `rejected`에 이유와 함께 남습니다. 예시는 카드 뒤에 `good`, `avoid` 순으로 적힙니다. 맞는 카드가 하나도 없던 판단 지점은 `no_hit`에 남습니다.

| `rejected.reason` | 뜻 |
|------|----|
| `lower_layer` | `active`인 원칙이나 우선순위와 부딪친다 |
| `conflict` | 부딪치는 카드보다 점수가 낮거나 같다 |
| `budget` | 판단 지점 상한, 전체 카드 상한, 예시 상한(`examples`)을 넘었다 |

```text
## 이번 작업의 개인 기준

반드시 지킬 것
- 수치를 부풀리지 않는다
- 수업 날짜와 시간은 숫자로 쓴다

부딪칠 때의 순서
1. 정확함이 재미보다 먼저다
2. 빠짐없음이 짧음보다 먼저다

판단 지점별 기준
- [첫 문장] 첫 문장은 질문이 아니라 숫자가 든 단정문으로 쓴다.
  이유: 질문형 첫 문장은 넘겨 읽힌다고 본다. 예외: 마감이 사흘 안이면 마감일로 시작한다.
- [첫 문장] 첫 문장에 다음 기수 시작일을 쓴다.
  이유: 모집 글을 여는 사람은 날짜부터 찾는다고 본다.
- [말투] 존댓말로 쓰되 문장을 짧게 끊는다.

이렇게 쓴다
4기 수강생 여러분, 마지막 수업은 11월 22일 토요일 오전 10시입니다.
수료 과제는 수업 전날 밤 12시까지 올려 주세요.

---

이번 주 토요일 수업은 강사 사정으로 쉽니다.
보강은 다음 주 화요일 저녁 7시입니다.

자리는 그대로 두었습니다.

이렇게는 쓰지 않는다
역대급 혜택! 지금 아니면 기회가 없어요!!

넣은 항목: prin-01, prin-02, pri-01, pri-02, card-0002, card-0001, card-0004, ex-0003, ex-0002, ex-0005
뺀 항목: card-0008(lower_layer), card-0005(conflict), card-0007(budget), card-0003(budget), ex-0001(budget), ex-0004(budget)
맞는 카드가 없던 판단 지점: schedule
guide_hash: sha256:a9a026daed6fdcf1107edec5f7c2fcf79ba886a115502516999ed24753779fb7
```

원장의 `run` 줄은 설계서 8.4의 모양 그대로이고, 키는 아래 순서입니다(한 줄을 읽기 좋게 나눴습니다).

```json
{"id": "run-0001", "type": "run", "ts": "2026-11-22T09:12:00+09:00",
 "skill": "class-notice", "task": "task-0001", "split": "train",
 "context": {"purpose": "모집", "channel": "instagram"},
 "injected": ["prin-01", "prin-02", "pri-01", "pri-02", "card-0002", "card-0001", "card-0004", "ex-0003", "ex-0002", "ex-0005"],
 "rejected": [{"id": "card-0008", "reason": "lower_layer"}, {"id": "card-0005", "reason": "conflict"},
              {"id": "card-0007", "reason": "budget"}, {"id": "card-0003", "reason": "budget"},
              {"id": "ex-0001", "reason": "budget"}, {"id": "ex-0004", "reason": "budget"}],
 "no_hit": ["schedule"], "conflicts": [],
 "guide_hash": "sha256:a9a026da...", "prompt_version": null,
 "output": "runs/run-0001/output.md",
 "prev_hash": "sha256:...", "hash": "sha256:..."}
```

- `context`는 조립에 쓴 맥락입니다. 과제 파일의 `context` 위에 `--context`를 축마다 덮어쓴 것입니다.
- `prompt_version`은 지금 늘 `null`입니다. 생성은 아직 프롬프트 자산을 쓰지 않습니다. 키를 미리 두어 자산이 생겨도 줄의 모양이 바뀌지 않습니다.
- `--ablate`는 원장에 쓰지 않습니다. 뺀 층의 항목은 `injected`에 없고 `guide_hash`가 달라지므로 줄에서 드러납니다.

원장의 줄마다 끝에 `prev_hash`와 `hash`가 붙어 앞줄과 이어집니다. `hash`는 `prev_hash`와 그 줄의 나머지 필드(정렬된 JSON)를 이어 SHA-256으로 만들고, 첫 줄의 `prev_hash`는 `sha256:` 뒤에 0이 64개입니다. `deeptwin verify`는 체인을 처음부터 다시 계산해, 손상된 줄마다 줄 번호와 이유를 `ledger_broken` 오류로 알려 줍니다. 원장은 고치지 않습니다.

`deeptwin run`은 실행 폴더를 만들고 모델을 부르기 전에, 원장의 마지막 줄에서 이어 쓸 `hash`를 얻을 수 있는지 봅니다. 얻지 못하면(반쯤 잘린 줄, `hash`가 없는 줄 등) 덧붙일 때와 같은 `ledger_broken` 오류로 멈추고, 실행 폴더도 모델 호출도 생기지 않습니다. 원장에 남길 수 없는 실행은 돌리지 않습니다. 다만 확인한 뒤 덧붙이기 전에 다른 프로세스가 원장을 망가뜨리면, 줄을 덧붙이지 않고 같은 오류로 멈추며 그때는 실행 폴더가 남습니다.

```sh
deeptwin verify
```

```text
오류: .deeptwin/ledger.jsonl:2: hash가 내용과 맞지 않습니다
```

`deeptwin verify`는 체인 다음에 봉인 과제도 봅니다. 원장의 `task` 줄 가운데 봉인 과제마다 그 파일을 읽어 기준의 해시를 다시 계산하고 등록 때와 견줍니다. 파일이 없거나 읽을 수 없거나 기준이 바뀌었으면, 그리고 `tasks/sealed/`에 있는데 원장에 봉인 과제로 등록되지 않은 파일이 있으면 과제마다 한 줄씩 알립니다. 기준의 내용은 쓰지 않습니다. 해시는 기준(`reference`)만 보므로 `input`, `context`, 주석을 고치거나 기본값(`grade: usual` 등)을 지우는 것은 걸리지 않습니다. 체인은 멀쩡하고 봉인만 문제면 `sealed_changed`이고, 체인도 깨졌으면 `ledger_broken`에 체인 줄 다음으로 봉인 줄이 붙습니다. 통과하면 `--json` 결과에 `lines`, `head`와 함께 검사한 봉인 과제 수 `sealed`가 나옵니다.

```text
오류: .deeptwin/tasks/sealed/task-0101.yaml: 기준(reference)이 등록 때와 다릅니다
```

평가. 같은 스킬로 바탕만(`base`, 네 층을 모두 빼고 조립)과 바탕+딥트윈(`full`, 네 층을 다 넣고 조립)의 결과물을 과제마다 만들고, 어느 쪽인지 가린 채 둘씩 골라 보고서를 냅니다. 명령은 셋입니다.

```sh
deeptwin eval pairs <스킬 ID> --split <분할> [--task 과제 ID]... [--seed 글] [--provider 이름] [--fake-answer 파일]
deeptwin eval pairs --resume <평가 ID> [--provider 이름] [--fake-answer 파일]
deeptwin eval judge <평가 ID> [--web] [--port 번호] [--limit 수] [--daily-limit 수]
deeptwin eval report <평가 ID>
```

예제 복사본에서는 가짜 모델로 끝까지 돌려 볼 수 있습니다.

```sh
deeptwin eval pairs inquiry-reply --split spare --provider fake --fake-answer answers/keeps-principles.md
deeptwin eval judge eval-0001        # 브라우저로 고르려면 deeptwin eval judge eval-0001 --web
deeptwin eval report eval-0001
```

`deeptwin eval pairs`는 분할에서 이 스킬의 과제를 파일 이름순으로 모아 과제마다 두 조건의 결과물을 만듭니다. `--resume`이 없으면 스킬 ID와 `--split`을 꼭 주고, `--split`은 `train`, `sealed`, `spare` 가운데 하나입니다. 맥락은 과제 파일의 `context`입니다.

- 결과물은 `deeptwin run`과 같은 길로 만듭니다. 생성마다 실행 폴더(`SKILL.md` 사본, `output.md`, `calls.jsonl`)와 원장의 `run` 줄이 남고 원칙도 검사합니다. 원칙을 어긴 결과물도 그대로 쌍에 들고, 위반은 출력하지 않습니다.
- 모든 과제와 두 조건의 준비(맥락, 조립, 원장의 끝 줄, 검사 함수)를 모델 없이 마친 뒤에 공급자와 평가 폴더를 만듭니다. 그래서 그 전에 멈추면(`no_tasks`, `context_required`, `ledger_broken`, `check_not_found`, `fake_answer_required` 등) 평가 폴더, 실행 폴더, 원장 줄, 모델 호출이 생기지 않습니다.
- `--task 과제 ID`(여러 번 줄 수 있습니다)는 분할과 상관없이 과제를 좁힙니다. 순서는 그래도 파일 이름순이고, 겹친 ID는 하나로 칩니다. 그 분할에 이 스킬의 과제로 없는 ID가 하나라도 있으면 아무것도 쓰지 않고 `task_not_found`이며, 메시지에는 ID만 씁니다.
- 봉인 분할(`--split sealed`)은 생성 바로 앞에서 봉인 묶음을 열고 원장에 `seal_open` 줄을 남깁니다(아래 봉인 평가).
- `--provider fake --fake-answer 파일`이면 모든 생성에 그 파일을 답으로 줍니다.
- 평가 ID는 `eval-NNNN`이고, `.deeptwin/eval/`의 평가 폴더 번호 최댓값 + 1입니다.
- `--json` 결과는 `eval`, `skill`, `split`, `tasks`, `pairs`(쌍 수), `seed`, `reused`(다른 평가에서 이미 연 봉인 과제, 봉인이 아니면 `[]`)입니다. 어느 실행이 어느 조건인지는 출력하지 않습니다.
- 쌍은 과제마다 하나(바탕+딥트윈 대 바탕만)입니다. 쌍의 순서는 `sha256(씨앗 + "\n" + 과제 ID + "\n" + 상대 조건)`의 16진 글 순이고, 같은 글 뒤에 `"\nside"`를 붙인 해시의 첫 바이트가 짝수면 왼쪽이 바탕+딥트윈입니다. 쌍 ID(`pair-NNNN`)는 섞은 순서로 매깁니다. 씨앗의 기본은 평가 ID이고 `--seed`로 바꿉니다. 같은 씨앗이면 운영체제와 Python 버전에 상관없이 같은 순서, 같은 좌우입니다.

평가 폴더 `.deeptwin/eval/<평가 ID>/`에는 아래 파일이 이 순서로 생깁니다. JSON은 한글을 그대로 쓰고 원자적으로 씁니다.

| 파일 | 내용 |
|------|------|
| `eval.json` | `schema`, `id`, `ts`, `skill`, `split`, `tasks`, `against`(지금은 `["base"]`), `seed`, `seal_open`(봉인 평가의 원장 `seal_open` 줄 ID, 아니면 `null`), `reused`(재사용한 봉인 과제, 아니면 `[]`). 두 필드가 없는 예전 파일도 읽는다 |
| `outputs/<조건>/<과제 ID>.md` | 조건별 결과물. 그 실행의 `output.md`와 바이트까지 같다 |
| `key.json` | 대응표. `schema`, `eval`, `runs`(과제 ID -> 조건 -> 실행 ID), `pairs`(쌍 ID -> `task`, `left`, `right`의 조건). 생성마다 그때까지의 `runs`와 빈 `pairs`로 다시 쓰고, 다 만든 뒤 `pairs`를 채운다 |
| `pairs.jsonl` | 쌍 목록. 한 줄에 `id`, `task`, `left`, `right`(두 결과물의 글)뿐이다 |
| `choices.jsonl` | 선택 기록. 한 줄에 `pair`, `chosen`(`left`나 `right`), `seconds`(소수 셋째 자리), `ts` |
| `report.json`, `report.md` | 보고서. 모두 고른 뒤에만 생긴다 |

`pairs.jsonl`은 마지막에 씁니다. 생성이 중간에 실패하면 그때까지의 실행, 결과물, `key.json`(그때까지의 `runs`)은 남지만 `pairs.jsonl`은 생기지 않고, 그 평가로 고르거나 보고서를 내면 `eval_incomplete`입니다. 그때는 `deeptwin eval pairs --resume <평가 ID>`로 남은 것만 만듭니다.

- 이어 가기는 `eval.json`의 스킬, 분할, 과제, 씨앗을 그대로 쓰므로 스킬 ID, `--split`, `--task`, `--seed`를 함께 주면 인자 오류(종료 코드 2)이고 아무것도 읽거나 쓰지 않습니다. `--provider`와 `--fake-answer`는 줍니다. 없는 평가면 `eval_not_found`입니다.
- 끝난 생성은 `key.json`의 `runs`에 있고 `outputs/<조건>/<과제 ID>.md`도 있는 것입니다. 나머지만 새 평가와 같은 순서로 준비하고 만들며(`fake` 공급자는 남은 생성 수만큼 답을 줍니다), 쌍은 이전 결과물과 새 결과물을 합쳐 같은 씨앗, 같은 규칙으로 만듭니다. 검사 함수가 멈춘 생성은 `runs`에 넣지 않으므로 이어 갈 때 다시 만듭니다.
- `pairs.jsonl`이 이미 있으면 아무것도 만들거나 쓰지 않고 같은 결과를 냅니다.
- 글 모드는 `평가 eval-0001을 이어 만들었습니다. 이번에 만든 결과물 5개, 쌍 3개.`처럼 씁니다.

`deeptwin eval judge`는 남은 쌍(`choices.jsonl`에 없는 쌍)을 `pairs.jsonl` 순서로 하나씩 보여 줍니다. 기본은 터미널이고, `--web`이면 브라우저로 여는 웹 화면입니다(아래). 터미널 화면에는 몇 번째 쌍인지, 과제의 입력, `[1]`과 `[2]`의 두 글, 물음만 나옵니다.

```text
쌍 1/2
문의:
수강료를 두 번에 나눠 낼 수 있을까요?

[1]
(왼쪽 글)

[2]
(오른쪽 글)

어느 쪽이 더 나답고 그대로 보낼 만한가요? 1 또는 2를 입력하세요:
```

- 블라인드: 쌍 목록과 판정 화면에는 조건 ID와 이름, 실행 ID, 결과물 경로가 나오지 않습니다. 판정은 `key.json`을 읽지 않고, 대응표는 보고서를 낼 때 처음 합칩니다.
- `1`은 왼쪽(`left`), `2`는 오른쪽(`right`)이고 다른 입력은 다시 묻습니다. 비기기와 건너뛰기는 없습니다. 고를 때마다 바로 `choices.jsonl`에 남고, `seconds`는 쌍을 보여 준 때부터 고른 때까지의 초입니다.
- 이어 고르기: 입력이 끝나면(EOF) 멈추고 종료 코드는 0, Ctrl-C면 130입니다. 어느 쪽이든 그때까지 고른 것은 남고, 다음 `deeptwin eval judge`는 남은 쌍부터 잇습니다. 남은 쌍이 없으면 `고를 쌍이 남지 않았습니다.`를 씁니다.
- 한 번 몫과 하루 몫: 고르는 피로가 쌓이지 않게 한 번에 `--limit`쌍(기본 15), 한 평가에서 하루에 `--daily-limit`쌍(기본 30)까지만 보여 줍니다. 둘 다 1 이상이고 터미널과 웹에 똑같이 걸립니다. 하루 몫은 그 평가의 `choices.jsonl`에서 `ts`를 이 컴퓨터의 시간대로 바꾼 날짜가 오늘인 줄을 셉니다. 이번 몫을 다 골랐는데 상한 때문에 쌍이 남았으면 아래 두 문장 가운데 하나를 쓰고 멈춥니다(종료 코드 0). 두 상한에 함께 걸리면(하루에 남은 몫이 `--limit` 이하이면) 하루 문장입니다. 오늘 몫을 이미 다 골랐으면 묻지 않고(웹이면 서버도 열지 않고) 하루 문장만 씁니다.

  ```text
  한 번에 15쌍까지 보여 줍니다. 남은 쌍 15개는 다음에 이어 고릅니다.
  오늘은 이 평가에서 30쌍까지 고릅니다. 남은 쌍 2개는 내일 이어 고르세요.
  ```

- `--json`이면 보여 주는 글과 묻는 글(웹이면 주소와 안내 문장)은 stderr로 가고, stdout에는 끝난 뒤 결과 하나(`eval`, `chosen`(이번에 고른 수), `remaining`)를 씁니다. 글 모드는 모두 stdout이고 끝에 같은 내용의 요약 문장이 붙습니다.

`--web`이면 표준 라이브러리 `http.server`로 이 컴퓨터 안(`127.0.0.1`)에만 판정 화면을 열고 주소를 알려 줍니다. 브라우저는 스스로 열지 않으니 그 주소를 직접 엽니다.

```text
판정 화면을 열었습니다: http://127.0.0.1:53817/
브라우저로 열어 고르세요. 다 고르면 저절로 닫히고, 멈추려면 Ctrl-C를 누르세요.
```

- 쌍마다 HTML 한 장입니다. `쌍 1/2`, `문의:`와 과제의 입력, 나란히 놓인 `왼쪽`과 `오른쪽` 두 글, 물음, 버튼 둘(`왼쪽을 고릅니다`, `오른쪽을 고릅니다`)뿐이고, 쌍 ID를 담은 숨은 입력 하나 말고는 다른 입력이나 링크가 없습니다. 스크립트, 바깥 CSS·글꼴·이미지, 텔레메트리도 없고, 글은 모두 HTML 이스케이프해 넣습니다.
- 블라인드 규칙은 터미널과 같습니다. 화면, 응답 헤더, 주소 어디에도 조건 ID와 이름, 실행 ID, 결과물 경로가 나오지 않습니다.
- 버튼을 누르면 바로 `choices.jsonl`에 남고 다음 쌍으로 넘어갑니다. `seconds`는 서버가 그 쌍의 화면을 처음 보낸 때부터 버튼을 누른 때까지이고, 새로 고쳐도 다시 재지 않습니다.
- 이번 몫을 다 고르면 끝 화면(`다 골랐습니다.`, 요약 문장, 상한 문장이 있으면 그 문장, `이 창은 닫아도 됩니다.`)을 보여 주고 서버가 저절로 닫힙니다. 남은 쌍이 없거나 오늘 몫을 다 골랐으면 서버를 열지 않고 바로 끝납니다.
- Ctrl-C면 서버를 닫고 종료 코드 130으로 멈춥니다. 그때까지 고른 것은 남고, 다음에는 남은 쌍부터 잇습니다.
- `--port`로 포트(0~65535)를 정합니다. 주지 않으면 빈 포트를 쓰고, `--web` 없이 주면 인자 오류(종료 코드 2)입니다. 포트에 묶지 못하면(다른 프로그램이 쓰는 중 등) 서버를 열지 않고 `port_unavailable`로 멈추며, 메시지에 `127.0.0.1:<포트>`가 나옵니다.
- 다른 사이트가 이 화면을 읽거나 선택을 남기지 못하게, `Host`가 `127.0.0.1:<포트>`나 `localhost:<포트>`가 아니거나 POST의 `Origin`이 `http://127.0.0.1:<포트>`나 `http://localhost:<포트>`가 아니면 403으로 막습니다. 지금 화면의 쌍이 아닌 선택(이미 고른 쌍, 없는 쌍, 아직 보여 주지 않은 쌍)은 409, 모양이 틀린 선택(필드가 없거나, `side`가 `left`나 `right`가 아니거나, 본문이 4096바이트를 넘음)은 400, 다른 경로는 404입니다. 어느 쪽이든 기록하지 않고 서버는 계속 돕니다.

`deeptwin eval report`는 모든 쌍을 골랐을 때만 보고서를 씁니다. 남은 쌍이 있으면 그 수를 알리고 `judging_unfinished`로 멈추며 보고서 파일을 쓰지 않습니다.

- 상대마다 `against`, `pairs`, `wins`(고른 쪽이 바탕+딥트윈인 수), `selection_rate`(`wins / pairs`), `p_value`를 냅니다.
- `report.json`은 `schema`, `eval`, `skill`, `split`, `pairs`, `reused`, `reference_changed`, `comparisons`이고, `report.md`는 같은 값을 한국어 표로 씁니다(선택률은 %, p값은 소수 넷째 자리). 시각을 적지 않으므로 다시 내도 바이트까지 같습니다. `reused`와 `reference_changed`는 봉인 평가에만 값이 있고(아래 봉인 평가), 봉인이 아니면 `[]`입니다.
- `--json` 결과는 `report.json`에서 `schema`를 뺀 값과 `files`(`.deeptwin/` 기준 두 경로)입니다.
- 보고서는 잰 값만 적고, 어느 쪽이 낫다는 판정 문장은 쓰지 않습니다.

```markdown
# 판정 보고서 eval-0001

- 스킬: inquiry-reply, 분할: spare, 쌍: 2개(모두 골랐습니다)

| 비교 | 쌍 | 바탕+딥트윈이 이긴 횟수 | 선택률 | p값 |
|------|----|----|----|----|
| 바탕+딥트윈 대 바탕만 | 2 | 1 | 50.0% | 0.7500 |

p값은 한쪽 꼬리 이항 검정의 값입니다. 두 결과물을 반반으로 고른다고 할 때 이만큼 이상 이길 확률입니다.
```

p값은 한쪽 꼬리 이항 검정 P(X ≥ `wins`)입니다. 고르는 사람이 두 결과물을 동전 던지듯 반반으로 고른다고 할 때, 바탕+딥트윈이 `pairs`쌍 가운데 `wins`번 이상 이길 확률입니다. 값이 작을수록 반반으로 골랐다고 보기 어렵습니다. 표준 라이브러리 `math.comb`로 정확히 셉니다(예: 30쌍 중 20번이면 0.0494).

봉인 평가. `deeptwin eval pairs <스킬 ID> --split sealed`는 그 스킬의 봉인 과제 전부(`--task`로 좁힙니다)를 한 묶음으로 엽니다. 예제 복사본에서는 이렇게 돌립니다.

```sh
deeptwin eval pairs inquiry-reply --split sealed --provider fake --fake-answer answers/keeps-principles.md
deeptwin eval judge eval-0001
deeptwin eval report eval-0001
```

- 순서: 봉인 과제를 읽어 과제마다 두 조건을 준비하고(맥락, 조립, 원장의 끝 줄, 검사 함수) → 공급자를 만들고 → 평가 폴더와 `eval.json`(`seal_open: null`)을 쓰고 → 묶음을 열어 원장에 `seal_open` 줄을 남긴 뒤 `eval.json`에 그 줄 ID와 재사용을 적고 → 생성합니다. 그래서 공급자까지 어디서 멈춰도(`context_required`, `ledger_broken`, `no_tasks`, `fake_answer_required` 등) 평가 폴더, 실행 폴더, `seal_open` 줄, 모델 호출이 없습니다. 실행의 `run` 줄은 `split: sealed`로 남습니다.
- `seal_open` 줄은 평가 하나에 한 줄이고 키는 `id`(`seal-NNNN`, 원장 `seal_open` 줄 번호의 최댓값 + 1), `type`, `ts`, `eval`, `skill`, `tasks`, `reused` 순입니다. 같은 평가를 이어 가거나 판정하거나 보고서를 낼 때는 줄을 더 남기지 않습니다.

  ```json
  {"id": "seal-0002", "type": "seal_open", "ts": "2026-11-23T10:00:00+09:00", "eval": "eval-0002", "skill": "inquiry-reply", "tasks": ["task-0101", "task-0102", "task-0103"], "reused": ["task-0101", "task-0102", "task-0103"], "prev_hash": "sha256:...", "hash": "sha256:..."}
  ```

- 재사용(`reused`): 이 평가의 과제 가운데, 원장에서 이 평가의 `seal_open` 줄보다 앞선 다른 평가의 `seal_open` 줄에 든 과제입니다. 순서는 이 평가의 과제 순서입니다. 따로 상태 파일을 두지 않고 원장에서 계산하므로, 먼저 연 평가는 뒤 평가가 같은 과제를 열어도 재사용이 아닙니다. 다시 연 묶음도 결과는 그대로 만들고, `--json` 결과, `eval.json`, 보고서에 재사용으로 적습니다. 글 모드는 `다른 평가에서 이미 연 봉인 과제가 들어 있습니다: task-0101, task-0102, task-0103. 보고서에 재사용으로 적습니다.`를 더합니다. 이어 가기(`--resume`)는 같은 평가를 여는 것이라 다시 열기도 재사용도 아닙니다.
- 기준 알림: 판정을 시작할 때(`deeptwin eval judge`, 터미널과 웹)와 보고서를 낼 때마다 그 평가의 봉인 과제마다 기준을 원장에 등록한 해시와 견줍니다(`deeptwin verify`와 같은 검사). 다르면 판정은 가장 먼저(`고를 쌍이 남지 않았습니다.`보다도 앞에) 아래 문장을 화면 쪽 스트림(`--json`이면 stderr)에 쓰고, 막지 않고 그대로 고릅니다. 과제 ID만 쓰고 기준의 내용은 쓰지 않으며, 판정의 `--json` 결과 모양(`eval`, `chosen`, `remaining`)은 그대로입니다.

  ```text
  봉인 과제의 기준이 등록 때와 다릅니다: task-0101. 판정은 그대로 하고 보고서에 표시합니다.
  ```

- 보고서: `reused`는 원장에서 계산한 재사용, `reference_changed`는 보고서를 낼 때 다시 본 기준이 바뀐 과제입니다. 기준을 되돌린 뒤 다시 내면 `reference_changed`도 빕니다. `report.md`에는 비어 있지 않은 것만 머리 줄 아래에 한 줄씩 넣습니다.

  ```markdown
  # 판정 보고서 eval-0002

  - 스킬: inquiry-reply, 분할: sealed, 쌍: 3개(모두 골랐습니다)
  - 재사용: 다른 평가에서 이미 연 봉인 과제가 들어 있습니다(task-0101, task-0102, task-0103).
  - 기준이 등록 때와 다른 봉인 과제: task-0101
  ```

- 판정 화면에는 봉인 과제의 입력(문의)이 나옵니다. 기준(`reference`)과 입력은 그 밖의 출력, 오류, 알림에 쓰지 않습니다. 봉인 평가를 몇 번 해도 `deeptwin run`과 `deeptwin compose`는 봉인 과제를 계속 `sealed_access`로 막습니다.

평가 ID가 `eval-<숫자>`가 아니거나 그 폴더나 `eval.json`이 없으면 `eval_not_found`이고 아무 파일도 만들지 않습니다. `choices.jsonl`이나 `pairs.jsonl`에 읽을 수 없는 줄이 있으면(`ts`가 ISO 8601 시각으로 읽히지 않는 줄도) `invalid_file`이고, 메시지는 `.deeptwin/eval/eval-0001/choices.jsonl:2: …`처럼 파일과 줄로 시작합니다. 웹 판정에서는 이런 오류가 서버를 열기 전에 납니다. Python에서는 `deeptwin.eval`의 `prepare_pairs`, `prepare_resume`, `build_pairs`, `open_sealed`, `pending_pairs`, `record_choice`, `report`, `p_value`가 같은 일을 합니다. `prepare_pairs(deeptwin, skill_id, *, split, tasks=None)`는 새 평가를, `prepare_resume(deeptwin, eval_id)`는 멈춘 평가의 남은 생성을 모델 없이 준비하고, `build_pairs(deeptwin, plan, generate, *, seed=None)`가 만듭니다. `open_sealed(deeptwin, eval_id)`는 봉인 평가의 묶음을 열어 `eval`(평가 정보), `line`(`seal_open` 줄 ID), `reused`, `token`을 돌려줍니다. 그 평가에서 처음 부를 때만 원장에 줄을 남기고, 봉인 평가가 아니면 `ValueError`입니다. 토큰을 받는 `DeepTwin.changed_references(task_ids, *, token)`는 기준이 등록 때와 다른 과제의 ID만 돌려줍니다. `pending_pairs(deeptwin, eval_id, *, limit=None, daily_limit=None)`는 남은 쌍(`pending`), 이번에 보여 줄 쌍(`batch`), 오늘 고른 수(`chosen_today`), `batch`가 짧아진 까닭(`stop`: `"limit"`, `"daily_limit"`, 짧지 않으면 `None`)을 돌려주고 아무것도 쓰지 않습니다. 상한을 주지 않으면 걸지 않고, 1보다 작으면 `ValueError`입니다. `record_choice`에 쌍 목록에 없는 쌍이나 이미 고른 쌍을 주면 `invalid_choice`입니다.

해시 체인이 생기기 전 버전(PyPI의 0.0.1)이 쓴 원장 줄에는 `prev_hash`와 `hash`가 없습니다. 그 원장이 있으면 `deeptwin verify`는 손상으로 알리고, `deeptwin run`은 실행 폴더를 만들거나 모델을 부르기 전에 `ledger_broken`으로 멈춥니다. 그 `.deeptwin/ledger.jsonl`을 다른 이름으로 옮겨 두면(예: `ledger-old.jsonl`) 다음 실행부터 새 체인이 시작됩니다.

모든 명령은 `--json`을 받습니다. 켜면 stdout에 JSON 객체 하나만 씁니다. 성공하면 종료 코드 0, deeptwin이 알려 주는 오류면 1입니다. 인자가 틀리면 Click 기본 동작대로 종료 코드 2와 글로 된 안내를 내고, JSON은 쓰지 않습니다.

```json
{"ok": false, "command": "run", "error": {"code": "not_initialized", "message": "먼저 deeptwin init을 실행하세요."}}
```

명령 도중 Ctrl-C로 멈추면 종료 코드는 130입니다. `--json`이면 stdout에 오류 코드 `interrupted`의 JSON 하나를 쓰고, 끄면 stderr에 `오류: Ctrl-C로 멈췄습니다.`를 씁니다.

```json
{"ok": false, "command": "run", "error": {"code": "interrupted", "message": "Ctrl-C로 멈췄습니다."}}
```

## 예제

[`examples/inquiry-reply`](examples/inquiry-reply/README.md)는 가상의 강사가 교육 문의에 답장을 쓰는 예제입니다. 사람, 강의, 문의는 모두 지어낸 것입니다. 스킬과 검사 함수, 네 층의 항목, 세 분할의 과제 10개, 과제를 등록해 만든 원장, 가짜 모델의 답 파일이 들어 있어 폴더를 그대로 프로젝트 루트로 씁니다.

저장소 안의 예제 폴더는 고치지 말고 새로 만든 빈 폴더에 내용을 복사해서 돌립니다(테스트가 그 데이터에 기댑니다).

```sh
D=$(mktemp -d) && cp -R examples/inquiry-reply/. "$D" && cd "$D"
deeptwin run inquiry-reply task-0001 --provider fake --fake-answer answers/keeps-principles.md
deeptwin run inquiry-reply task-0001 --provider fake --fake-answer answers/breaks-promise.md
env -u ANTHROPIC_API_KEY deeptwin run inquiry-reply task-0001    # 실제 모델(claude CLI 구독)
deeptwin verify
deeptwin status
```

두 번째 실행은 원칙 `prin-01`을 어긴 답이라 `violations`에 그 원칙이 나옵니다. 어느 실행에서도 `skills/inquiry-reply/`의 파일은 바뀌지 않고 `deeptwin verify`가 통과합니다. 데이터 구성은 예제의 README에 있습니다.

## 폴더

```text
.deeptwin/                  # 개인 데이터. git에 올리지 않는다
  layers/                   # 기준의 네 층
    examples/<ID>.yaml      # 예시(본능). 한 건이 파일 하나
    cards/<ID>.yaml         # 판단 카드(경향). 한 장이 파일 하나
    priorities.yaml         # 우선순위 목록. 위에 있을수록 먼저다
    principles.yaml         # 원칙 목록
  candidates/<ID>.yaml      # 승인 전 후보. 하나가 파일 하나
  tasks/<분할>/<ID>.yaml    # 과제. 분할은 train, sealed, spare. sealed는 토큰 없이 읽지 않는다
  runs/                     # 실행마다 SKILL.md 사본, 결과물, 호출 기록(calls.jsonl)
  eval/<평가 ID>/           # 평가마다 eval.json, 조건별 결과물(outputs/), 대응표(key.json), 쌍 목록(pairs.jsonl), 선택(choices.jsonl), 보고서
  ledger.jsonl              # 원장. 추가만 하고 줄마다 해시로 잇는다
skills/<스킬 ID>/           # deeptwin skill new가 아래 세 파일을 만든다
  SKILL.md                  # 고정 영역과 유동 영역 표시
  skill.yaml                # 판단 지점, 맥락 축, 상한, 검사 파일(checks)
  checks.py                 # 원칙의 검사 함수. fn(output: str) -> bool, 이름이 원칙의 check
```

모든 파일과 목록 파일의 항목마다 `schema: 1`을 둡니다. 없으면 1로 읽고, 더 큰 값이면 읽지 않습니다. 폴더에 든 파일은 파일 이름이 `id`와 같아야 하고, 과제 파일의 `split`은 든 폴더와 같아야 합니다. 모르는 필드(`x_` 확장 필드 등)는 버리지 않습니다.

형식이 틀린 파일을 읽으면 `invalid_file` 오류로 멈춥니다. 틀린 곳마다 한 줄씩, 프로젝트 루트 기준 경로와 줄 번호를 앞에 붙여 알려 줍니다.

```text
오류: .deeptwin/layers/principles.yaml:5: kind: 쓸 수 있는 값은 'must', 'never'입니다(받은 값: 'nevr')
```

층(`layers/`), 과제(`tasks/`), 후보(`candidates/`) 파일은 `.deeptwin/.lock` 잠금을 잡고 원자적으로 쓰고, 원장(`ledger.jsonl`)도 이 잠금 안에서 덧붙입니다. 실행 폴더(`runs/`)의 파일은 그 실행만 쓰므로 잠그지 않습니다. 다른 쓰기가 30초 넘게 잠금을 쥐고 있으면 `store_locked` 오류로 멈춥니다. deeptwin이 다시 쓴 YAML 파일에는 사람이 단 주석이 남지 않습니다.

`SKILL.md`에는 유동 영역 자리를 한 번 표시합니다.

```markdown
<!-- deeptwin:fluid -->
<!-- /deeptwin:fluid -->
```

## 개발

```sh
uv sync
uv run ruff check && uv run ruff format --check && uv run mypy && uv run lint-imports
uv run pytest
```

검사, 조립, 모델, 저장, 가져오기, 상태, 실행(`deeptwin.runs`), 평가(`deeptwin.eval`)는 모델 호출 계층(`deeptwin.llm`)을 직접이든 거쳐서든(`llm`을 import하는 `deeptwin` 최상위 패키지 포함) import하지 않습니다(`uv run lint-imports`가 검사합니다). 공급자와 호출 기록기를 생성 함수로 묶어 넘기는 것은 명령줄입니다. 평가 모듈은 파일에 저장 계층으로만 닿습니다(`tests/test_eval.py`가 검사합니다).

명령줄(`src/deeptwin/cli/`)은 공개 API만 씁니다. 다른 deeptwin 모듈에서 `from deeptwin.<모듈> import <이름>`으로 가져오는 이름은 그 모듈의 `__all__`에 있어야 하고 `_`로 시작하지 않습니다. 쓰는 이름을 검사할 수 없으므로 `import deeptwin.<모듈>`로 모듈을 통째로 가져오지 않습니다(`tests/test_public_api.py`가 검사합니다).

테스트는 네트워크와 모델 없이 돌고, 가상 인물의 데이터만 씁니다. claude 공급자는 가짜 `claude` 스크립트로 확인합니다. 실제 모델을 부르는 테스트(예제를 실제 모델로 한 번 돌리는 것 포함)에는 `live` 표식을 달고 기본 실행에서 뺍니다. 로그인된 `claude`가 있으면 `uv run pytest -m live`로 따로 돌립니다.

예제 테스트는 `examples/inquiry-reply`를 임시 폴더에 복사해서 돌고, 예제의 두 학습 과제를 조립한 결과(`compose --json`)를 골든 파일(`tests/golden/inquiry-reply/`)과 견줍니다. 조립 규칙이나 예제 데이터를 일부러 바꿨다면 골든 파일을 다시 만들고, 바뀐 곳을 `git diff`로 읽은 뒤 함께 올립니다.

```sh
DEEPTWIN_UPDATE_GOLDEN=1 uv run pytest tests/test_example.py -k golden
```

텔레메트리는 없습니다.

## 라이선스

Apache-2.0
