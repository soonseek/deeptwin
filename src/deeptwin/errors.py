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
