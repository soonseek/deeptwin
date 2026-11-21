# deeptwin

개인의 판단 기준을 층별 파일로 쌓고, 작업마다 맞는 기준만 모델 없이 조립해 스킬의 유동 영역에 넣는 Python 라이브러리입니다.

> 아직 초기 단계입니다(0.0.1). 지금은 과제를 등록하고, 원칙, 우선순위, 판단 카드, 예시를 조립해 스킬을 한 번 돌리는 길까지 있습니다. 함수 서명과 명령은 0.x 동안 바뀔 수 있습니다.

## 설치

```sh
pip install deeptwin
```

Python 3.11 이상이 필요합니다.

## 쓰는 법

프로젝트 폴더에서 개인 데이터 폴더를 만듭니다. `.deeptwin/`이 생기고 `.gitignore`에 `.deeptwin/` 줄이 더해집니다.

```sh
deeptwin init
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

봉인 과제는 평가에서만 씁니다. 저장 계층이 봉인 토큰 없이 봉인 과제를 읽지 않으므로, `deeptwin run`과 `deeptwin compose`에 봉인 과제를 주면 실행 폴더, 원장 줄, 모델 호출 없이 `sealed_access` 오류로 멈춥니다. 토큰을 내주는 평가 명령은 아직 없습니다.

```text
오류: 과제 task-0101은 봉인 과제라 읽을 수 없습니다. 봉인 과제는 평가에서만 씁니다.
```

스킬을 과제 하나로 돌립니다. 조립한 지침을 넣은 `SKILL.md` 사본과 결과물은 `.deeptwin/runs/<실행 ID>/`에 남습니다. 원본 `SKILL.md`와 층 파일(`layers/`)은 바뀌지 않고, 카드의 `stats`도 고치지 않습니다. 실행은 원장(`.deeptwin/ledger.jsonl`)에 한 줄로 남습니다.

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
5. 공급자: `claude_not_found`, `fake_answer_required`

실행 폴더를 만든 뒤 사본 쓰기나 생성이 실패하면(공급자 오류, 시간 초과, Ctrl-C) 방금 만든 그 실행 폴더를 지우고 원래 오류를 그대로 냅니다. 생성이 끝난 뒤의 실패(결과물 쓰기, 원장 덧붙이기)에는 실행 폴더를 남깁니다. 이미 비용을 낸 호출의 기록이 들어 있기 때문입니다.

`--json` 결과는 `run`, `task`, `split`, `context`, `ablate`, `injected`, `rejected`, `no_hit`, `conflicts`, `guide_hash`, `output`(`.deeptwin/` 기준) 순입니다. 글 모드는 마친 실행, 넣은 항목, 뺀 항목, 맞는 카드가 없던 판단 지점, 결과물을 차례로 씁니다.

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

해시 체인이 생기기 전 버전(PyPI의 0.0.1)이 쓴 원장 줄에는 `prev_hash`와 `hash`가 없습니다. 그 원장이 있으면 `deeptwin verify`는 손상으로 알리고, `deeptwin run`은 실행 폴더를 만들거나 모델을 부르기 전에 `ledger_broken`으로 멈춥니다. 그 `.deeptwin/ledger.jsonl`을 다른 이름으로 옮겨 두면(예: `ledger-old.jsonl`) 다음 실행부터 새 체인이 시작됩니다.

모든 명령은 `--json`을 받습니다. 켜면 stdout에 JSON 객체 하나만 씁니다. 성공하면 종료 코드 0, deeptwin이 알려 주는 오류면 1입니다. 인자가 틀리면 Click 기본 동작대로 종료 코드 2와 글로 된 안내를 내고, JSON은 쓰지 않습니다.

```json
{"ok": false, "command": "run", "error": {"code": "not_initialized", "message": "먼저 deeptwin init을 실행하세요."}}
```

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
  ledger.jsonl              # 원장. 추가만 하고 줄마다 해시로 잇는다
skills/<스킬 ID>/
  SKILL.md                  # 고정 영역과 유동 영역 표시
  skill.yaml                # 판단 지점, 맥락 축, 상한
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

테스트는 네트워크와 모델 없이 돌고, 가상 인물의 데이터만 씁니다. claude 공급자는 가짜 `claude` 스크립트로 확인합니다. 실제 모델을 부르는 테스트에는 `live` 표식을 달고 기본 실행에서 뺍니다. 로그인된 `claude`가 있으면 `uv run pytest -m live`로 따로 돌립니다.

텔레메트리는 없습니다.

## 라이선스

Apache-2.0
