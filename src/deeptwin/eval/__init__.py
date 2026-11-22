"""평가: 두 조건의 결과물을 만들어 조건 이름 없이 둘씩 고르고 보고서를 낸다.

- `prepare_pairs`, `build_pairs`: 조건별 결과물과 쌍 목록, 대응표(`eval pairs`)
- `pending_pairs`, `record_choice`: 남은 쌍과 선택 기록(`eval judge`)
- `report`, `p_value`: 상대마다 이긴 횟수, 선택률, p값(`eval report`)

모델 호출은 생성 함수로 주입받고 모델 호출 계층(`deeptwin.llm`)을 import하지 않는다. 파일에는
저장 계층(`deeptwin.store.evals`, `DeepTwin`)으로만 닿는다.
"""

from deeptwin.eval.judging import pending_pairs, record_choice
from deeptwin.eval.pairs import CONDITIONS, build_pairs, prepare_pairs
from deeptwin.eval.reporting import report
from deeptwin.eval.stats import p_value

__all__ = [
    "CONDITIONS",
    "build_pairs",
    "p_value",
    "pending_pairs",
    "prepare_pairs",
    "record_choice",
    "report",
]
