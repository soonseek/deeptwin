"""보고서의 통계. 표준 라이브러리만 쓴다."""

from __future__ import annotations

import math

__all__ = [
    "p_value",
]


def p_value(wins: int, pairs: int) -> float:
    """한쪽 꼬리 이항 검정의 p값: X ~ B(pairs, 0.5)일 때 P(X >= wins).

    `math.comb`로 정확히 센 뒤 한 번만 나눈다. 30쌍 중 20승이면 약 0.0494, 0승이면 1.0,
    모두 이기면 2의 -pairs 제곱이다. `0 <= wins <= pairs`가 아니면 `ValueError`다.
    """
    if pairs < 0 or not 0 <= wins <= pairs:
        raise ValueError(f"0 <= wins <= pairs여야 합니다(wins: {wins}, pairs: {pairs})")
    # 정수끼리의 나눗셈은 가장 가까운 float로 반올림된다
    return sum(math.comb(pairs, k) for k in range(wins, pairs + 1)) / (1 << pairs)
