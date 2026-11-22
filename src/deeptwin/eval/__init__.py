"""평가: 세 조건의 결과물을 만들어 조건 이름 없이 둘씩 고르고 보고서를 낸다.

조건은 바탕만(`base`), 바탕+예시(`examples`), 바탕+딥트윈(`full`)이다(`CONDITIONS`). `full`과
견줄 상대는 `AGAINST`에서 고르고, 쌍은 과제마다 상대 하나에 하나다.

- `prepare_pairs`, `prepare_resume`, `build_pairs`: 조건별 결과물과 쌍 목록, 대응표(`eval pairs`).
  `prepare_resume`는 생성이 멈춘 평가의 남은 생성만 준비한다(`eval pairs --resume`).
- `open_sealed`: 봉인 평가의 묶음을 열어 토큰을 준다. 처음 열 때만 원장에 `seal_open` 줄을 남긴다.
- `pending_pairs`, `record_choice`: 남은 쌍과 선택 기록(`eval judge`)
- `report`, `p_value`: 상대마다 이긴 횟수, 선택률, p값, 고르는 데 걸린 시간, 조건마다 실행 비용,
  패키지 버전, 커밋, 프롬프트 버전(`eval report`)

봉인 토큰을 만드는 곳은 `sealing` 모듈뿐이다. 모델 호출은 생성 함수로 주입받고 모델 호출
계층(`deeptwin.llm`)을 import하지 않는다. 파일에는 저장 계층(`deeptwin.store.evals`,
`DeepTwin`)으로만 닿는다.
"""

from deeptwin.eval.judging import pending_pairs, record_choice
from deeptwin.eval.pairs import AGAINST, CONDITIONS, build_pairs, prepare_pairs, prepare_resume
from deeptwin.eval.reporting import report
from deeptwin.eval.sealing import open_sealed
from deeptwin.eval.stats import p_value

__all__ = [
    "AGAINST",
    "CONDITIONS",
    "build_pairs",
    "open_sealed",
    "p_value",
    "pending_pairs",
    "prepare_pairs",
    "prepare_resume",
    "record_choice",
    "report",
]
