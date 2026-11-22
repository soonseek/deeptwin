"""판정 보고서: 모든 쌍을 고른 뒤 대응표를 합쳐 상대마다 이긴 횟수, 선택률, p값을 낸다.

대응표(`key.json`)는 판정이 끝난 뒤에만 합친다. 남은 쌍이 있으면 보고서를 쓰지 않는다.
보고서에는 측정한 값만 쓰고 어느 쪽이 낫다는 판정 문장은 쓰지 않는다. 상대마다 고르는 데 걸린
시간, 조건마다 실행 비용(`calls.jsonl`의 합), 그리고 어느 코드와 프롬프트로 쟀는지(패키지 버전,
커밋, 원장의 `prompt_version`)도 적는다. 토큰 수는 재지 않으므로 적지 않는다.
봉인 평가면 재사용한 과제와 기준이 등록 때와 다른 과제도 적는다. 평가를 시작한 뒤 바탕 스킬이나
패키지가 바뀌었으면 그것도 적는다(모두 막지 않는다).
파일에는 저장 계층(`store.evals`, `DeepTwin`)으로만 닿고, 버전과 커밋은 `provenance`로 읽는다.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from deeptwin.errors import EvalIncompleteError, JudgingUnfinishedError
from deeptwin.eval.pairs import CONDITIONS, base_skill_changed
from deeptwin.eval.sealing import open_sealed
from deeptwin.eval.stats import p_value
from deeptwin.models import (
    Choice,
    Comparison,
    Condition,
    ConditionCost,
    EvalInfo,
    EvalKey,
    EvalReport,
    Pair,
    PairKey,
)
from deeptwin.provenance import package_commit, package_version
from deeptwin.store.evals import KEY_FILE, open_eval, run_calls, run_entries
from deeptwin.store.project import DeepTwin

__all__ = [
    "CONDITION_NAMES",
    "Report",
    "report",
]

CONDITION_NAMES: dict[Condition, str] = {
    "base": "바탕만",
    "examples": "바탕+예시",
    "full": "바탕+딥트윈",
}
"""보고서에만 쓰는 조건의 한국어 이름. 쌍 목록과 판정 화면에는 쓰지 않는다."""

_TARGET: Condition = "full"
_UNKNOWN = "알 수 없음"
"""알 수 없는 커밋과 프롬프트 버전을 `report.md`에 쓰는 말."""
_NO_TIME = "-"
_NO_RECORD = "기록 없음"


@dataclass(frozen=True)
class Report:
    """`report`의 결과: 쓴 보고서와 두 파일의 경로(`.deeptwin/` 기준, json, md 순)."""

    report: EvalReport
    markdown: str
    files: tuple[str, str]


def report(deeptwin: DeepTwin, eval_id: str) -> Report:
    """모든 쌍을 골랐으면 보고서를 `report.json`과 `report.md`로 쓴다. 다시 내면 같은 바이트다.

    - 남은 쌍이 있으면 그 수를 알리고 `judging_unfinished`다. 보고서 파일은 쓰지 않는다. 이 검사가
      맨 먼저이고, 아래 값을 모두 계산한 뒤에야 파일을 쓴다. 그래서 중간에 오류가 나면 이번 보고서
      파일은 생기지 않는다.
    - 평가가 없으면 `eval_not_found`, 쌍 목록이나 대응표가 없으면 `eval_incomplete`다.
    - 상대마다 `wins`는 고른 쪽이 `full`인 쌍의 수, `selection_rate`는 `wins / pairs`,
      `p_value`는 한쪽 꼬리 이항 검정 P(X >= wins), p = 0.5다(`stats.p_value`). `judged`는 그
      쌍 가운데 선택이 있는 수이고, `mean_seconds`와 `median_seconds`는 그 쌍들의 첫 선택의
      `seconds`의 평균과 중앙값(소수 셋째 자리)이다. 판정한 쌍이 없으면 `None`이다.
    - 봉인 평가면 `reused`는 `open_sealed`가 원장에서 계산한 값이고(같은 평가라 원장에는 쓰지
      않는다), `reference_changed`는 낼 때마다 그 평가의 모든 과제의 기준을 등록 때 해시와 다시
      견준 값이다. 봉인이 아니면 둘 다 비었다.
    - `skill_changed`는 낼 때마다 `base_skill_changed`로 정한다(`eval.json`의 `skill_changed`이거나
      지금 바탕 스킬의 해시가 `skill_hash`와 다르다).
    - `package_version`과 `commit`은 보고서를 낼 때의 값이다(`provenance`). `package_changed`는
      `eval.json`의 `package_version`이 있으면서 (버전, 커밋)이 지금과 다를 때 참이다(`None`끼리는
      같다). `package_version`이 없는 예전 평가는 견주지 않는다. 막지 않는다.
    - `prompt_versions`는 대응표의 `runs` 순서(과제 순, 과제마다 `CONDITIONS` 순)로 실행마다 원장의
      `run` 줄(`run_entries`)의 `prompt_version`을 처음 나온 순서로 모은 것이다. 원장에 줄이 없는
      실행은 건너뛴다.
    - `comparisons`는 `eval.json`의 `against` 순서로 상대마다 하나다. `costs`는 대응표의 `runs`에
      든 조건마다 `CONDITIONS` 순서로 하나다(`_cost`).
    """
    folder = open_eval(deeptwin, eval_id)
    info = folder.info()
    pairs = folder.pairs()
    chosen = _first_choices(folder.choices())
    left = [pair for pair in pairs if pair.id not in chosen]
    if left:
        raise JudgingUnfinishedError(
            f"평가 {folder.id}에 고르지 않은 쌍이 {len(left)}개 남았습니다. "
            f"deeptwin eval judge {folder.id}로 마저 고른 뒤 보고서를 내세요."
        )
    key = folder.key()
    reused: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    if info.split == "sealed":
        opening = open_sealed(deeptwin, folder.id)
        reused = opening.reused
        changed = deeptwin.changed_references(opening.eval.tasks, token=opening.token)
    comparisons: list[Comparison] = []
    for against in info.against:
        found = _pairs_against(pairs, key.pairs, against, folder.shown(KEY_FILE))
        judged = [chosen[pair.id] for pair in found if pair.id in chosen]
        wins = 0
        for choice in judged:
            side = key.pairs[choice.pair]
            winner = side.left if choice.chosen == "left" else side.right
            wins += winner == _TARGET
        seconds = [choice.seconds for choice in judged]
        comparisons.append(
            Comparison(
                against=against,
                pairs=len(found),
                judged=len(judged),
                wins=wins,
                selection_rate=wins / len(found) if found else 0.0,
                p_value=p_value(wins, len(found)),
                mean_seconds=round(statistics.fmean(seconds), 3) if seconds else None,
                median_seconds=round(statistics.median(seconds), 3) if seconds else None,
            )
        )
    runs = _key_runs(key)
    costs = [
        _cost(deeptwin, condition, [run_id for made_by, run_id in runs if made_by == condition])
        for condition in CONDITIONS
        if any(made_by == condition for made_by, _ in runs)
    ]
    run_ids = [run_id for _, run_id in runs]
    entries = run_entries(deeptwin, run_ids)
    prompt_versions = list(
        dict.fromkeys(entries[run_id].prompt_version for run_id in run_ids if run_id in entries)
    )
    now_version = package_version()
    now_commit = package_commit()
    made = EvalReport(
        eval=folder.id,
        skill=info.skill,
        split=info.split,
        pairs=len(pairs),
        reused=list(reused),
        reference_changed=list(changed),
        skill_changed=base_skill_changed(deeptwin, info),
        package_version=now_version,
        commit=now_commit,
        package_changed=(
            info.package_version is not None
            and (info.package_version, info.commit) != (now_version, now_commit)
        ),
        prompt_versions=prompt_versions,
        comparisons=comparisons,
        costs=costs,
    )
    markdown = render_markdown(made, info)
    return Report(report=made, markdown=markdown, files=folder.save_report(made, markdown))


def render_markdown(made: EvalReport, info: EvalInfo) -> str:
    """보고서의 Markdown. `report.json`과 같은 값을 한국어 표로 쓴다. `info`는 `eval.json`이다.

    재사용한 과제와 기준이 바뀐 과제는 비어 있지 않을 때만, 바탕 스킬이 바뀐 것은 `skill_changed`가
    참일 때만, 패키지가 바뀐 것은 `package_changed`가 참일 때만(시작할 때의 값은 `info`에서) 머리
    줄 아래에 이 순서로 한 줄씩 쓴다. 비교 표와 p값 문장 뒤에 실행 비용과 패키지와 프롬프트 절을
    붙인다. 초는 소수 셋째 자리, 글자 수는 정수이고, 값이 없으면 시간 칸은 `-`, 비용 칸은
    `기록 없음`, 커밋은 `알 수 없음`이다.
    """
    target = CONDITION_NAMES[_TARGET]
    lines = [
        f"# 판정 보고서 {made.eval}",
        "",
        f"- 스킬: {made.skill}, 분할: {made.split}, 쌍: {made.pairs}개(모두 골랐습니다)",
    ]
    if made.reused:
        lines.append(
            f"- 재사용: 다른 평가에서 이미 연 봉인 과제가 들어 있습니다({', '.join(made.reused)})."
        )
    if made.reference_changed:
        lines.append(f"- 기준이 등록 때와 다른 봉인 과제: {', '.join(made.reference_changed)}")
    if made.skill_changed:
        lines.append(
            "- 바탕 스킬이 평가를 시작한 뒤 바뀌었습니다(SKILL.md, skill.yaml, checks.py)."
        )
    if made.package_changed:
        lines.append(
            "- 평가를 시작할 때와 패키지가 다릅니다("
            f"시작할 때 deeptwin {info.package_version}, 커밋 {_commit_text(info.commit)}. "
            f"지금 deeptwin {made.package_version}, 커밋 {_commit_text(made.commit)})."
        )
    lines += [
        "",
        f"| 비교 | 판정한 쌍 | 전체 쌍 | {target}이 이긴 횟수 | 선택률 | p값 | "
        "고르는 데 걸린 초(평균) | 고르는 데 걸린 초(중앙값) |",
        "|------|----|----|----|----|----|----|----|",
    ]
    for c in made.comparisons:
        lines.append(
            f"| {target} 대 {CONDITION_NAMES[c.against]} | {c.judged} | {c.pairs} | {c.wins} | "
            f"{c.selection_rate * 100:.1f}% | {c.p_value:.4f} | "
            f"{_seconds_text(c.mean_seconds, _NO_TIME)} | "
            f"{_seconds_text(c.median_seconds, _NO_TIME)} |"
        )
    lines += [
        "",
        "p값은 한쪽 꼬리 이항 검정의 값입니다. "
        "두 결과물을 반반으로 고른다고 할 때 이만큼 이상 이길 확률입니다.",
        "",
        "## 실행 비용",
        "",
        "| 조건 | 호출 수 | 호출에 걸린 초 | 입력 글자 수 | 출력 글자 수 |",
        "|------|----|----|----|----|",
    ]
    for cost in made.costs:
        lines.append(
            f"| {CONDITION_NAMES[cost.condition]} | {_count_text(cost.calls)} | "
            f"{_seconds_text(cost.seconds, _NO_RECORD)} | {_count_text(cost.input_chars)} | "
            f"{_count_text(cost.output_chars)} |"
        )
    lines += [
        "",
        "조건마다 이 평가의 실행 폴더에 남은 calls.jsonl의 줄 수와 합입니다. "
        "토큰 수는 재지 않으므로 적지 않습니다.",
        "",
        "## 패키지와 프롬프트",
        "",
        f"- 패키지: deeptwin {made.package_version}",
        f"- 커밋: {_commit_text(made.commit)}",
        f"- 프롬프트 버전: {_prompt_text(made.prompt_versions)}",
    ]
    return "\n".join(lines) + "\n"


def _key_runs(key: EvalKey) -> list[tuple[Condition, str]]:
    """대응표의 실행을 (조건, 실행 ID)로 늘어놓는다. 과제는 `runs`의 순서, 과제마다 `CONDITIONS`
    순서다."""
    return [
        (condition, runs[condition])
        for runs in key.runs.values()
        for condition in CONDITIONS
        if condition in runs
    ]


def _cost(deeptwin: DeepTwin, condition: Condition, run_ids: Sequence[str]) -> ConditionCost:
    """조건 하나의 실행들의 `calls.jsonl`을 더한다.

    `calls`는 줄 수, `seconds`는 `round(합, 3)`, 글자 수는 합이다. 실행 가운데 하나라도
    `calls.jsonl`이 없으면(실행 ID의 모양이 틀렸을 때도) 네 값이 모두 `None`이다. 읽을 수 없는 줄이
    있으면 `invalid_file`이다(`store.evals.run_calls`).
    """
    found = [run_calls(deeptwin, run_id) for run_id in run_ids]
    if any(calls is None for calls in found):
        return ConditionCost(
            condition=condition, calls=None, seconds=None, input_chars=None, output_chars=None
        )
    every = [call for calls in found if calls is not None for call in calls]
    return ConditionCost(
        condition=condition,
        calls=len(every),
        seconds=round(sum(call.seconds for call in every), 3),
        input_chars=sum(call.input_chars for call in every),
        output_chars=sum(call.output_chars for call in every),
    )


def _commit_text(commit: str | None) -> str:
    return _UNKNOWN if commit is None else commit


def _seconds_text(seconds: float | None, missing: str) -> str:
    return missing if seconds is None else f"{seconds:.3f}"


def _count_text(count: int | None) -> str:
    return _NO_RECORD if count is None else str(count)


def _prompt_text(versions: list[str | None]) -> str:
    """프롬프트 버전 줄의 값. `[None]`이면 프롬프트 자산을 쓰지 않았다는 말, 비었으면 알 수 없음,
    그 밖에는 값을 `, `로 잇고 `None`은 `없음`으로 쓴다."""
    if versions == [None]:
        return "없음(이 평가의 실행은 프롬프트 자산을 쓰지 않았습니다)"
    if not versions:
        return f"{_UNKNOWN}(원장에서 이 평가의 실행 줄을 찾지 못했습니다)"
    return ", ".join("없음" if version is None else version for version in versions)


def _first_choices(choices: list[Choice]) -> dict[str, Choice]:
    """쌍마다 처음 기록된 선택. 한 쌍은 한 번만 기록되지만, 손으로 겹친 줄은 처음 것만 센다."""
    first: dict[str, Choice] = {}
    for choice in choices:
        first.setdefault(choice.pair, choice)
    return first


def _pairs_against(
    pairs: list[Pair], keys: dict[str, PairKey], against: Condition, shown: str
) -> list[Pair]:
    """상대가 `against`인 쌍. 대응표에 없는 쌍이 있으면 `eval_incomplete`다."""
    found: list[Pair] = []
    for pair in pairs:
        key = keys.get(pair.id)
        if key is None:
            raise EvalIncompleteError(f"{shown}에 쌍 {pair.id}의 대응이 없습니다.")
        if {key.left, key.right} == {_TARGET, against}:
            found.append(pair)
    return found
