"""호출 기록기: 공급자를 감싸 호출마다 `calls.jsonl`에 한 줄을 남긴다(설계서 9.6).

기록을 모델 호출 계층에 두므로 어느 공급자로 부르든 같은 줄이 남는다.
"""

from __future__ import annotations

import time
from pathlib import Path

from deeptwin.llm.base import Provider
from deeptwin.models import Call
from deeptwin.store.files import append_jsonl

__all__ = [
    "CallRecorder",
]


class CallRecorder:
    """`provider`를 감싼 `Provider`. 호출이 성공하면 `path`에 `Call` 한 줄을 덧붙인다.

    - 호출이 예외로 끝나면 아무것도 쓰지 않는다.
    - `input_chars`는 `system`과 `user`의 글자 수의 합, `output_chars`는 응답의 글자 수다.
    - `seconds`는 `complete` 하나의 벽시계 시간이다(소수 셋째 자리까지).
    - `model`과 `version`은 감싼 공급자에 `str` 속성이 있으면 호출 뒤에 읽고, 없으면 `None`이다.
    - `cached`는 응답 캐시가 생길 때까지 늘 `False`다.
    """

    def __init__(
        self, provider: Provider, path: Path, *, prompt_version: str | None = None
    ) -> None:
        self.provider = provider
        self.path = path
        self.prompt_version = prompt_version
        self.name: str = provider.name

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        timeout: float = 120,
    ) -> str:
        start = time.perf_counter()
        output = self.provider.complete(system, user, temperature=temperature, timeout=timeout)
        seconds = time.perf_counter() - start
        call = Call(
            provider=self.name,
            model=_str_attr(self.provider, "model"),
            version=_str_attr(self.provider, "version"),
            prompt_version=self.prompt_version,
            input_chars=len(system) + len(user),
            output_chars=len(output),
            seconds=round(seconds, 3),
            cached=False,
        )
        append_jsonl(self.path, call.model_dump(mode="json"))
        return output


def _str_attr(provider: Provider, name: str) -> str | None:
    value = getattr(provider, name, None)
    return value if isinstance(value, str) else None
