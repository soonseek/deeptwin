"""deeptwin의 오류. 다른 deeptwin 모듈을 import하지 않는다.

모든 오류는 `code`(영어, 에이전트가 읽는다)와 `message`(한국어, 사람이 읽는다)를 가진다.
"""

from __future__ import annotations


class DeeptwinError(Exception):
    """deeptwin이 알고 내는 오류. CLI는 이 오류를 종료 코드 1로 바꾼다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NotInitializedError(DeeptwinError):
    def __init__(self, message: str) -> None:
        super().__init__("not_initialized", message)


class TaskNotFoundError(DeeptwinError):
    def __init__(self, message: str) -> None:
        super().__init__("task_not_found", message)


class SkillNotFoundError(DeeptwinError):
    def __init__(self, message: str) -> None:
        super().__init__("skill_not_found", message)


class TaskSkillMismatchError(DeeptwinError):
    def __init__(self, message: str) -> None:
        super().__init__("task_skill_mismatch", message)


class InvalidContextError(DeeptwinError):
    """맥락의 축이나 값이 스킬의 `context_axes`에 없거나, `--context`의 모양이 틀렸다."""

    def __init__(self, message: str) -> None:
        super().__init__("invalid_context", message)


class OverBudgetError(DeeptwinError):
    """범위가 맞는 원칙이나 우선순위가 상한보다 많다. 자르지 않고 합치라고 안내한다."""

    def __init__(self, message: str) -> None:
        super().__init__("over_budget", message)


class FluidMarkerMissingError(DeeptwinError):
    def __init__(self, message: str) -> None:
        super().__init__("fluid_marker_missing", message)


class UnknownProviderError(DeeptwinError):
    def __init__(self, message: str) -> None:
        super().__init__("unknown_provider", message)


class FakeAnswerRequiredError(DeeptwinError):
    def __init__(self, message: str) -> None:
        super().__init__("fake_answer_required", message)


class FakeAnswersExhaustedError(DeeptwinError):
    def __init__(self, message: str) -> None:
        super().__init__("fake_answers_exhausted", message)


class ClaudeNotFoundError(DeeptwinError):
    def __init__(self, message: str) -> None:
        super().__init__("claude_not_found", message)


class ProviderFailedError(DeeptwinError):
    def __init__(self, message: str) -> None:
        super().__init__("provider_failed", message)


class ProviderTimeoutError(DeeptwinError):
    def __init__(self, message: str) -> None:
        super().__init__("provider_timeout", message)


class InvalidFileError(DeeptwinError):
    """형식이 틀린 파일. 메시지는 줄마다 `<프로젝트 기준 경로>:<줄>: <설명>`이다."""

    def __init__(self, message: str) -> None:
        super().__init__("invalid_file", message)


class LedgerBrokenError(DeeptwinError):
    """원장의 해시 체인이 끊겼다. 메시지는 손상마다 `.deeptwin/ledger.jsonl:<줄>: <이유>`다."""

    def __init__(self, message: str) -> None:
        super().__init__("ledger_broken", message)


class StoreLockedError(DeeptwinError):
    """다른 쓰기가 `.deeptwin/.lock`을 쥐고 있어 정한 시간 안에 잠금을 잡지 못했다."""

    def __init__(self, message: str) -> None:
        super().__init__("store_locked", message)
