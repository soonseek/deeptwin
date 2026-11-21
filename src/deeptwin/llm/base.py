"""모델 호출 계층의 자리: `Provider` 프로토콜(설계서 9.6)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Provider(Protocol):
    """모델 공급자. `complete(system, user)`가 응답 글을 돌려준다."""

    name: str

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        timeout: float = 120,
    ) -> str: ...
