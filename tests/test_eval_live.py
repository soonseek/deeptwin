"""예제 `examples/inquiry-reply`의 봉인 평가를 실제 claude CLI로 끝까지 한 번 돈다.

`uv run pytest -m live tests/test_eval_live.py`로 따로 돈다. Claude Code가 설치되고 로그인돼 있어야
하고, claude가 없으면 건너뛴다. 모델을 9번 부른다(봉인 과제 3개, 조건 3개). 몇 분 걸린다.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from test_cli import calls, files_under, invoke, ok_json
from test_eval import EVAL, eval_dir, judge, pair_lines
from test_eval_examples import CONDITION_ORDER, SEALED_PAIRS, assert_blind_text, key_of
from test_eval_sealed import SEALED

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(shutil.which("claude") is None, reason="claude 실행 파일이 없다"),
]


def test_example_sealed_eval_runs_with_the_real_model(
    in_example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 구독 로그인으로 돌린다. ANTHROPIC_API_KEY가 있으면 claude가 구독보다 키를 먼저 쓴다
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    skills = files_under(in_example / "skills")

    made = ok_json(invoke(*SEALED_PAIRS, "--json"), "eval pairs")

    assert made["pairs"] == 6
    folder = eval_dir(in_example)
    outputs = {
        task: {
            condition: (folder / "outputs" / condition / f"{task}.md").read_bytes().decode("utf-8")
            for condition in CONDITION_ORDER
        }
        for task in SEALED
    }
    assert all(text.strip() for texts in outputs.values() for text in texts.values())
    key = key_of(in_example)
    for runs in key["runs"].values():
        for run_id in runs.values():
            [call] = calls(in_example, run_id)
            assert call["provider"] == "claude"
    pairs = pair_lines(in_example)
    assert len(pairs) == 6
    # 쌍마다 두 글은 그 과제의 결과물 가운데 두 개다
    for pair in pairs:
        side = key["pairs"][pair["id"]]
        assert pair["left"] == outputs[pair["task"]][side["left"]]
        assert pair["right"] == outputs[pair["task"]][side["right"]]

    judged = judge(EVAL, "--json", input="1\n2\n1\n2\n1\n2\n")

    assert ok_json(judged, "eval judge") == {"eval": EVAL, "chosen": 6, "remaining": 0}
    # 모델의 글에는 조건을 뜻하는 말이 들어갈 수 있으므로 그 글을 지운 나머지를 본다
    screen = judged.stderr
    for pair in pairs:
        for text in (pair["left"], pair["right"]):
            screen = screen.replace(text.rstrip("\n"), "")
    assert_blind_text(screen)

    report = ok_json(invoke("eval", "report", EVAL, "--json"), "eval report")

    assert [(c["against"], c["pairs"], c["judged"]) for c in report["comparisons"]] == [
        ("base", 3, 3),
        ("examples", 3, 3),
    ]
    assert [(c["condition"], c["calls"]) for c in report["costs"]] == [
        (condition, 3) for condition in CONDITION_ORDER
    ]
    assert (folder / "report.md").read_text("utf-8").strip()
    verified = ok_json(invoke("verify", "--json"), "verify")
    assert (verified["lines"], verified["sealed"]) == (20, 3)
    assert files_under(in_example / "skills") == skills
