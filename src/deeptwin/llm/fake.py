"""미리 정한 답을 차례로 돌려주는 가짜 공급자. 테스트와 예제 확인용이다."""

from __future__ import annotations

from collections.abc import Sequence

from deeptwin.errors import FakeAnswersExhaustedError


class FakeProvider:
    """`answers`를 부른 순서대로 하나씩 돌려준다. 다 쓰면 오류를 낸다.

    받은 `(system, user)`는 `calls`에 차례로 남는다.
    """

    name: str = "fake"

    def __init__(self, answers: Sequence[str]) -> None:
        self._answers = list(answers)
        self.calls: list[tuple[str, str]] = []

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        timeout: float = 120,
    ) -> str:
        if len(self.calls) >= len(self._answers):
            raise FakeAnswersExhaustedError(
                f"fake 공급자의 답 {len(self._answers)}개를 다 썼습니다."
            )
        self.calls.append((system, user))
        return self._answers[len(self.calls) - 1]
