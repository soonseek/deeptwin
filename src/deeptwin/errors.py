"""deeptwin의 오류. 다른 deeptwin 모듈을 import하지 않는다.

모든 오류는 `code`(영어, 에이전트가 읽는다)와 `message`(한국어, 사람이 읽는다)를 가진다.
"""

from __future__ import annotations

__all__ = [
    "CheckFailedAfterRunError",
    "CheckFailedError",
    "CheckNotFoundError",
    "ClaudeNotFoundError",
    "ContextRequiredError",
    "DeeptwinError",
    "EvalIncompleteError",
    "EvalNotFoundError",
    "FakeAnswerRequiredError",
    "FakeAnswersExhaustedError",
    "FluidMarkerMissingError",
    "InitBlockedError",
    "InvalidChoiceError",
    "InvalidContextError",
    "InvalidFileError",
    "InvalidIdError",
    "JudgingUnfinishedError",
    "LedgerBrokenError",
    "NoTasksError",
    "NotInitializedError",
    "NothingToImportError",
    "OverBudgetError",
    "ProviderFailedError",
    "ProviderTimeoutError",
    "ReferenceRequiredError",
    "SealedAccessError",
    "SealedChangedError",
    "SkillExistsError",
    "SkillNotFoundError",
    "StoreLockedError",
    "TaskExistsError",
    "TaskNotFoundError",
    "TaskSkillMismatchError",
    "UnknownLayerError",
    "UnknownProviderError",
    "UnsupportedExamplePolicyError",
]


class DeeptwinError(Exception):
    """deeptwin이 알고 내는 오류. CLI는 이 오류를 종료 코드 1로 바꾼다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NotInitializedError(DeeptwinError):
    def __init__(self, message: str) -> None:
        super().__init__("not_initialized", message)


class InitBlockedError(DeeptwinError):
    """`deeptwin init`이 쓸 자리가 막혔다. 아무것도 만들거나 바꾸지 않았다.

    만들 폴더 자리에 폴더가 아닌 것이 있거나, `.gitignore` 자리에 파일이 아닌 것이 있다.
    """

    def __init__(self, message: str) -> None:
        super().__init__("init_blocked", message)


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


class CheckFailedAfterRunError(CheckFailedError):
    """실행을 원장에 남긴 뒤 검사 함수가 실패했다. 코드는 `check_failed` 그대로다.

    `detail`은 실행 ID를 붙이기 전의 메시지(원칙과 검사 함수의 문제), `output`은 그 실행의
    결과물이다. 실행 ID를 내보이면 안 되는 곳(평가)이 `detail`만으로 다시 알린다.
    """

    def __init__(self, message: str, *, detail: str, output: str) -> None:
        super().__init__(message)
        self.detail = detail
        self.output = output


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


class InvalidIdError(DeeptwinError):
    """새로 만들 항목의 ID가 ID 규칙(영문자, 숫자, `.`, `_`, `-`)에 맞지 않는다."""

    def __init__(self, message: str) -> None:
        super().__init__("invalid_id", message)


class SkillExistsError(DeeptwinError):
    """만들려는 스킬 폴더(`skills/<id>/`)가 이미 있다. 그 안의 파일은 건드리지 않는다."""

    def __init__(self, message: str) -> None:
        super().__init__("skill_exists", message)


class NothingToImportError(DeeptwinError):
    """가져오기에 준 폴더 바로 아래에 글 파일(`.txt`, `.md`)이 없다."""

    def __init__(self, message: str) -> None:
        super().__init__("nothing_to_import", message)


class SealedChangedError(DeeptwinError):
    """봉인 과제의 파일이 없거나, 기준이 등록 때와 다르거나, 원장에 등록되지 않았다.

    메시지는 문제마다 `.deeptwin/tasks/sealed/<id>.yaml: <이유>`이고 기준의 내용은 쓰지 않는다.
    """

    def __init__(self, message: str) -> None:
        super().__init__("sealed_changed", message)


class NoTasksError(DeeptwinError):
    """평가에 쓸 과제가 없다. 그 분할에 `skill`이 그 스킬인 과제 파일이 하나도 없다."""

    def __init__(self, message: str) -> None:
        super().__init__("no_tasks", message)


class EvalNotFoundError(DeeptwinError):
    """평가를 찾지 못했다. ID가 `eval-<숫자>`가 아니거나, 그 폴더나 `eval.json`이 없다."""

    def __init__(self, message: str) -> None:
        super().__init__("eval_not_found", message)


class EvalIncompleteError(DeeptwinError):
    """평가 폴더에 쌍 목록(`pairs.jsonl`)이나 대응표(`key.json`)가 없다. 쌍을 다 만들지 못했다."""

    def __init__(self, message: str) -> None:
        super().__init__("eval_incomplete", message)


class JudgingUnfinishedError(DeeptwinError):
    """고르지 않은 쌍이 남아 보고서를 내지 않았다. 대응표는 모든 쌍을 고른 뒤에만 합친다."""

    def __init__(self, message: str) -> None:
        super().__init__("judging_unfinished", message)


class InvalidChoiceError(DeeptwinError):
    """선택을 기록할 수 없다. 쌍 목록에 없는 쌍이거나, 이미 고른 쌍이거나, 고른 쪽이 틀렸다."""

    def __init__(self, message: str) -> None:
        super().__init__("invalid_choice", message)
