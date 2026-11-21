# deeptwin

개인의 판단 기준을 층별 파일로 쌓고, 작업마다 맞는 기준만 모델 없이 조립해 스킬의 유동 영역에 넣는 Python 라이브러리입니다.

> 아직 초기 단계입니다(0.0.1). 지금은 원칙 하나를 조립해 스킬을 한 번 돌리는 가장 얇은 길만 있습니다. 함수 서명과 명령은 0.x 동안 바뀔 수 있습니다.

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

스킬을 과제 하나로 돌립니다. 조립한 지침을 넣은 `SKILL.md` 사본과 결과물은 `.deeptwin/runs/<실행 ID>/`에 남고, 원본 `SKILL.md`는 바뀌지 않습니다. 실행은 원장(`.deeptwin/ledger.jsonl`)에 한 줄로 남습니다.

```sh
deeptwin run <스킬 ID> <과제 ID>
```

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

모든 명령은 `--json`을 받습니다. 켜면 stdout에 JSON 객체 하나만 씁니다. 성공하면 종료 코드 0, deeptwin이 알려 주는 오류면 1입니다. 인자가 틀리면 Click 기본 동작대로 종료 코드 2와 글로 된 안내를 내고, JSON은 쓰지 않습니다.

```json
{"ok": false, "command": "run", "error": {"code": "not_initialized", "message": "먼저 deeptwin init을 실행하세요."}}
```

## 폴더

```text
.deeptwin/            # 개인 데이터. git에 올리지 않는다
  layers/             # 기준의 네 층(예시, 판단 카드, 우선순위, 원칙)
  candidates/         # 승인 전 후보
  tasks/              # 과제(train, sealed, spare)
  runs/               # 실행마다 SKILL.md 사본, 결과물, 호출 기록(calls.jsonl)
  ledger.jsonl        # 원장. 추가만 한다
skills/<스킬 ID>/
  SKILL.md            # 고정 영역과 유동 영역 표시
  skill.yaml          # 판단 지점, 맥락 축, 상한
```

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
