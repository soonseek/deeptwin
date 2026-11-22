"""판정 보고서: 모든 쌍을 고른 뒤 대응표를 합쳐 상대마다 이긴 횟수, 선택률, p값을 낸다.

대응표(`key.json`)는 판정이 끝난 뒤에만 합친다. 남은 쌍이 있으면 보고서를 쓰지 않는다.
보고서에는 측정한 값만 쓰고 어느 쪽이 낫다는 판정 문장은 쓰지 않는다.
파일에는 저장 계층(`store.evals`)으로만 닿는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from deeptwin.errors import EvalIncompleteError, JudgingUnfinishedError
from deeptwin.eval.stats import p_value
from deeptwin.models import Choice, Comparison, Condition, EvalReport, Pair, PairKey
from deeptwin.store.evals import KEY_FILE, open_eval
from deeptwin.store.project import DeepTwin

__all__ = [
    "CONDITION_NAMES",
    "Report",
    "report",
]

CONDITION_NAMES: dict[Condition, str] = {
    "base": "바탕만",
    "full": "바탕+딥트윈",
}
"""보고서에만 쓰는 조건의 한국어 이름. 쌍 목록과 판정 화면에는 쓰지 않는다."""

_TARGET: Condition = "full"


@dataclass(frozen=True)
class Report:
    """`report`의 결과: 쓴 보고서와 두 파일의 경로(`.deeptwin/` 기준, json, md 순)."""

    report: EvalReport
    markdown: str
    files: tuple[str, str]


def report(deeptwin: DeepTwin, eval_id: str) -> Report:
    """모든 쌍을 골랐으면 보고서를 `report.json`과 `report.md`로 쓴다. 다시 내면 같은 바이트다.

    - 남은 쌍이 있으면 그 수를 알리고 `judging_unfinished`다. 보고서 파일은 쓰지 않는다.
    - 평가가 없으면 `eval_not_found`, 쌍 목록이나 대응표가 없으면 `eval_incomplete`다.
    - 상대마다 `wins`는 고른 쪽이 `full`인 쌍의 수, `selection_rate`는 `wins / pairs`,
      `p_value`는 한쪽 꼬리 이항 검정 P(X >= wins), p = 0.5다(`stats.p_value`).
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
    comparisons: list[Comparison] = []
    for against in info.against:
        wins = 0
        count = 0
        for pair in _pairs_against(pairs, key.pairs, against, folder.shown(KEY_FILE)):
            count += 1
            side = key.pairs[pair.id]
            winner = side.left if chosen[pair.id].chosen == "left" else side.right
            wins += winner == _TARGET
        comparisons.append(
            Comparison(
                against=against,
                pairs=count,
                wins=wins,
                selection_rate=wins / count if count else 0.0,
                p_value=p_value(wins, count),
            )
        )
    made = EvalReport(
        eval=folder.id,
        skill=info.skill,
        split=info.split,
        pairs=len(pairs),
        comparisons=comparisons,
    )
    markdown = render_markdown(made)
    return Report(report=made, markdown=markdown, files=folder.save_report(made, markdown))


def render_markdown(made: EvalReport) -> str:
    """보고서의 Markdown. `report.json`과 같은 값을 한국어 표로 쓴다."""
    target = CONDITION_NAMES[_TARGET]
    lines = [
        f"# 판정 보고서 {made.eval}",
        "",
        f"- 스킬: {made.skill}, 분할: {made.split}, 쌍: {made.pairs}개(모두 골랐습니다)",
        "",
        f"| 비교 | 쌍 | {target}이 이긴 횟수 | 선택률 | p값 |",
        "|------|----|----|----|----|",
    ]
    for c in made.comparisons:
        lines.append(
            f"| {target} 대 {CONDITION_NAMES[c.against]} | {c.pairs} | {c.wins} | "
            f"{c.selection_rate * 100:.1f}% | {c.p_value:.4f} |"
        )
    lines += [
        "",
        "p값은 한쪽 꼬리 이항 검정의 값입니다. "
        "두 결과물을 반반으로 고른다고 할 때 이만큼 이상 이길 확률입니다.",
    ]
    return "\n".join(lines) + "\n"


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
