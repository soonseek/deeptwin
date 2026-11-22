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


class ContextRequiredError(DeeptwinError):
    """스킬에 맥락 축이 있는데 실행에 줄 맥락이 없다. 과제 파일의 `context`도 `--context`도 없다."""

    def __init__(self, message: str) -> None:
        super().__init__("context_required", message)


class OverBudgetError(DeeptwinError):
    """범위가 맞는 원칙이나 우선순위가 상한보다 많다. 자르지 않고 합치라고 안내한다."""

    def __init__(self, message: str) -> None:
        super().__init__("over_budget", message)


class UnknownLayerError(DeeptwinError):
    """`ablate`에 네 층(`instinct`, `tendency`, `priority`, `principle`)이 아닌 이름이 있다."""

    def __init__(self, message: str) -> None:
        super().__init__("unknown_layer", message)


class UnsupportedExamplePolicyError(DeeptwinError):
    """스킬의 `example_policy`가 아직 만들지 않은 방식이다. 지금은 `random_signature`만 된다."""

    def __init__(self, message: str) -> None:
        super().__init__("unsupported_example_policy", message)


class FluidMarkerMissingError(DeeptwinError):
    def __init__(self, message: str) -> None:
        super().__init__("fluid_marker_missing", message)


class CheckNotFoundError(DeeptwinError):
    """원칙의 `check`가 가리키는 검사 함수를 찾지 못했다.

    스킬에 `checks`가 없거나, 검사 파일이 없거나 스킬 폴더 밖이거나, 그 파일에 함수가 없거나
    부를 수 없는 경우다.
    """

    def __init__(self, message: str) -> None:
        super().__init__("check_not_found", message)


class CheckFailedError(DeeptwinError):
    """검사 파일을 불러오다 예외가 났거나, 검사 함수가 예외를 냈거나 `bool`이 아닌 것을 돌려줬다."""

    def __init__(self, message: str) -> None:
        super().__init__("check_failed", message)


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


class SealedAccessError(DeeptwinError):
    """봉인 토큰 없이 봉인 과제를 읽으려 했다. 메시지에는 과제의 내용을 쓰지 않는다."""

    def __init__(self, message: str) -> None:
        super().__init__("sealed_access", message)


class TaskExistsError(DeeptwinError):
    """같은 ID의 과제가 이미 있다(분할 폴더의 파일이나 원장의 `task` 줄). 분할은 바꿀 수 없다."""

    def __init__(self, message: str) -> None:
        super().__init__("task_exists", message)


class ReferenceRequiredError(DeeptwinError):
    """봉인 과제를 기준(`reference`) 없이 등록하려 했다."""

    def __init__(self, message: str) -> None:
        super().__init__("reference_required", message)


class SealedChangedError(DeeptwinError):
    """봉인 과제의 파일이 없거나, 기준이 등록 때와 다르거나, 원장에 등록되지 않았다.

    메시지는 문제마다 `.deeptwin/tasks/sealed/<id>.yaml: <이유>`이고 기준의 내용은 쓰지 않는다.
    """

    def __init__(self, message: str) -> None:
        super().__init__("sealed_changed", message)
