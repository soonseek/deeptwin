"""웹 판정 화면(`eval judge --web`). 데이터는 모두 가상이다.

예제(`examples/inquiry-reply`)의 복사본에서 가짜 모델로 만든 평가(쌍 2개)를 127.0.0.1의 서버로
고른다. 명령은 daemon 스레드에서 돌리고, 요청은 표준 라이브러리 `urllib`의 프록시 없는 opener로
루프백에만 보낸다. 바깥 네트워크와 모델은 쓰지 않는다.
"""

from __future__ import annotations

import html
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, Any, NoReturn

import pytest
from typer.testing import Result

from deeptwin.cli import main, web
from test_cli import error_json, jsonl, ok_json, parsed, runner
from test_eval import EVAL, SPARE, choice_lines, eval_dir, judge, make_eval, pair_lines, task_input

ASK = "어느 쪽이 더 나답고 그대로 보낼 만한가요?"
BLIND = ("base", "full", "examples", "바탕", "딥트윈", "run-", "outputs")
"""웹 판정의 응답(헤더와 본문)에 소문자로 바꿔도 나오면 안 되는 말."""
NOTHING_LEFT = "고를 쌍이 남지 않았습니다."
START_WAIT = 10.0
"""서버가 응답할 때까지 기다리는 최대 초."""
FINISH_WAIT = 5.0
"""마지막 선택 뒤 명령이 끝나기를 기다리는 최대 초."""


def free_port() -> int:
    """127.0.0.1의 빈 포트 하나. 묶었다가 바로 놓는다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """303을 따라가지 않고 그대로 본다."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> None:
        return None


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
"""프록시를 거치지 않는 opener."""
NO_REDIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
"""프록시를 거치지 않고 리다이렉트를 따르지 않는 opener. POST에 쓴다."""


@dataclass(frozen=True)
class Response:
    status: int
    headers: list[tuple[str, str]]
    body: str
    size: int
    """본문의 바이트 수."""

    def header(self, name: str) -> str | None:
        found = [value for key, value in self.headers if key.lower() == name.lower()]
        return found[0] if found else None

    def text(self) -> str:
        """상태, 헤더, 본문을 한 글로. 블라인드 검사에 쓴다."""
        lines = [str(self.status), *(f"{key}: {value}" for key, value in self.headers)]
        return "\n".join([*lines, "", self.body])


class Judge:
    """daemon 스레드에서 도는 `deeptwin eval judge <평가> --web --port P` 한 번."""

    def __init__(self, *options: str, port: int | None = None) -> None:
        self.port = free_port() if port is None else port
        self.args = ["eval", "judge", EVAL, "--web", "--port", str(self.port), *options]
        self.result: Result | None = None
        self.responses: list[Response] = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        self.result = runner.invoke(main.app, self.args)

    def start(self) -> Judge:
        """명령을 띄우고 포트가 연결을 받을 때까지 기다린다(요청은 보내지 않는다)."""
        self.thread.start()
        deadline = time.monotonic() + START_WAIT
        while True:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                return self
            except OSError:
                if not self.thread.is_alive():
                    output = self.result.output if self.result is not None else ""
                    pytest.fail(f"서버가 뜨기 전에 명령이 끝났습니다:\n{output}")
                if time.monotonic() > deadline:
                    pytest.fail(f"{START_WAIT}초 안에 127.0.0.1:{self.port}가 열리지 않았습니다")
                time.sleep(0.05)

    def url(self, path: str = "/") -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def request(
        self, path: str = "/", *, data: bytes | None = None, headers: dict[str, str] | None = None
    ) -> Response:
        method = "GET" if data is None else "POST"
        request = urllib.request.Request(
            self.url(path), data=data, headers=headers or {}, method=method
        )
        opener = OPENER if data is None else NO_REDIRECT
        try:
            with opener.open(request, timeout=10) as raw:
                response = _response(raw.status, raw.headers.items(), raw.read())
        except urllib.error.HTTPError as error:
            with error:
                response = _response(error.code, error.headers.items(), error.read())
        self.responses.append(response)
        return response

    def get(self, path: str = "/", headers: dict[str, str] | None = None) -> Response:
        return self.request(path, headers=headers)

    def post(self, form: dict[str, str], headers: dict[str, str] | None = None) -> Response:
        return self.request("/choose", data=urllib.parse.urlencode(form).encode(), headers=headers)

    def choose(self, pair: str, side: str, headers: dict[str, str] | None = None) -> Response:
        return self.post({"pair": pair, "side": side}, headers=headers)

    def finish(self, within: float = FINISH_WAIT) -> Result:
        """명령이 `within`초 안에 끝나야 한다. 그 결과를 돌려준다."""
        self.thread.join(within)
        assert not self.thread.is_alive(), f"{within}초 안에 명령이 끝나지 않았습니다"
        assert self.result is not None
        return self.result


def _response(status: int, headers: Any, body: bytes) -> Response:
    return Response(status, list(headers), body.decode("utf-8"), len(body))


@pytest.fixture
def serve(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Judge]]:
    """`serve(*옵션)`이 웹 판정을 띄운다. 테스트가 실패해도 끝에서 서버를 닫고 스레드를 거둔다.

    기다리는 함수(`web.wait_until_done`)는 그대로 쓰되, 넘겨받은 사건을 적어 두었다가 끝에서 세운다.
    """
    judges: list[Judge] = []
    waiting: list[threading.Event] = []
    real = web.wait_until_done

    def wait(done: threading.Event) -> None:
        waiting.append(done)
        real(done)

    monkeypatch.setattr(web, "wait_until_done", wait)

    def start(*options: str, port: int | None = None) -> Judge:
        found = Judge(*options, port=port)
        judges.append(found)
        return found.start()

    yield start
    for done in waiting:
        done.set()
    for found in judges:
        found.thread.join(10)


@pytest.fixture
def no_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """서버를 열어 기다리면 멈춰 서지 않고 바로 실패한다."""

    def wait(done: object) -> NoReturn:
        raise AssertionError("서버를 열지 않아야 합니다")

    monkeypatch.setattr(web, "wait_until_done", wait)


def rewrite_pair(root: Path, index: int, left: str, right: str) -> None:
    """`pairs.jsonl`의 `index`번째(0부터) 쌍의 두 글을 바꾼다."""
    path = eval_dir(root) / "pairs.jsonl"
    rows = jsonl(path)
    rows[index].update(left=left, right=right)
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8", newline="\n")


def pair_ids(root: Path) -> list[str]:
    return [pair["id"] for pair in pair_lines(root)]


def address_line(port: int) -> str:
    return f"판정 화면을 열었습니다: http://127.0.0.1:{port}/"


def korean_html(response: Response) -> bool:
    return '<html lang="ko">' in response.body and re.search("[가-힣]", response.body) is not None


def assert_blind(responses: list[Response]) -> None:
    for response in responses:
        text = response.text().lower()
        for word in BLIND:
            assert word not in text, (word, response.text())


def assert_headers(response: Response) -> None:
    assert response.header("Content-Type") == "text/html; charset=utf-8"
    assert response.header("Content-Length") == str(response.size)
    assert response.header("Cache-Control") == "no-store"
    server = response.header("Server") or ""
    assert "basehttp" not in server.lower()
    assert "python" not in server.lower()


# 화면


def test_page_shows_the_inquiry_and_both_texts_side_by_side(
    in_example: Path, serve: Callable[..., Judge]
) -> None:
    make_eval()
    first, second = pair_ids(in_example)
    rewrite_pair(
        in_example, 0, "가상의 첫째 답장입니다.\n둘째 줄입니다.\n", "가상의 다른 답장입니다.\n"
    )
    session = serve()

    page = session.get()

    assert page.status == 200
    assert page.header("Content-Type") == "text/html; charset=utf-8"
    body = page.body
    assert '<html lang="ko">' in body
    assert "쌍 1/2" in body
    assert "문의:" in body
    assert html.escape(task_input(in_example, pair_lines(in_example)[0]["task"])) in body
    assert ASK in body
    assert "왼쪽" in body
    assert "오른쪽" in body
    assert "가상의 첫째 답장입니다.\n둘째 줄입니다." in body
    assert body.index("가상의 첫째 답장입니다.") < body.index("가상의 다른 답장입니다.")
    assert body.count("<button") == 2
    assert '<button name="side" value="left">왼쪽을 고릅니다</button>' in body
    assert '<button name="side" value="right">오른쪽을 고릅니다</button>' in body
    assert body.count("<input") == 1
    assert f'<input type="hidden" name="pair" value="{first}">' in body
    assert second not in body
    assert "grid" in body
    assert "pre-wrap" in body
    for forbidden in ("<script", "http://", "https://", "<a ", "<link", "<img", "src="):
        assert forbidden not in body.lower()

    session.choose(first, "left")
    session.get()
    session.choose(second, "right")
    result = session.finish()
    assert result.exit_code == 0, result.output
    assert address_line(session.port) in result.stdout.splitlines()


@pytest.mark.acceptance
def test_acceptance_web_judging_records_each_pick_and_closes_by_itself(
    in_example: Path, serve: Callable[..., Judge]
) -> None:
    make_eval()
    first, second = pair_ids(in_example)
    session = serve()

    assert "쌍 1/2" in session.get().body
    moved = session.choose(first, "left")
    assert len(choice_lines(in_example)) == 1
    following = session.get()
    done = session.choose(second, "right")
    result = session.finish()

    assert moved.status == 303
    assert moved.header("Location") == "/"
    assert "쌍 2/2" in following.body
    assert f'value="{second}"' in following.body
    assert done.status == 200
    assert "다 골랐습니다." in done.body
    assert "이번에 고른 쌍 2개, 남은 쌍 0개" in done.body
    assert "이 창은 닫아도 됩니다." in done.body
    assert result.exit_code == 0, result.output
    choices = choice_lines(in_example)
    assert [(c["pair"], c["chosen"]) for c in choices] == [(first, "left"), (second, "right")]
    for choice in choices:
        assert list(choice) == ["pair", "chosen", "seconds", "ts"]
        assert choice["seconds"] >= 0
        assert datetime.fromisoformat(choice["ts"]).utcoffset() is not None
    assert "이번에 고른 쌍 2개, 남은 쌍 0개" in result.stdout.rstrip("\n").splitlines()[-1]
    assert result.stderr == ""
    # 다시 띄우면 고른 쌍은 나오지 않는다
    again = runner.invoke(main.app, ["eval", "judge", EVAL, "--web", "--json"])
    assert ok_json(again, "eval judge") == {"eval": EVAL, "chosen": 0, "remaining": 0}


def test_no_response_names_a_condition_a_run_or_an_output(
    in_example: Path, serve: Callable[..., Judge]
) -> None:
    make_eval()
    first, second = pair_ids(in_example)
    session = serve()

    session.get()
    session.get("/favicon.ico")
    session.choose(second, "left")
    session.post({"pair": first})
    session.choose(first, "left")
    session.get()
    session.choose(second, "right")
    assert session.finish().exit_code == 0

    assert [r.status for r in session.responses] == [200, 404, 409, 400, 303, 200, 200]
    assert_blind(session.responses)
    for response in session.responses:
        assert_headers(response)
        assert korean_html(response)


def test_json_mode_writes_the_address_to_stderr_and_one_object_to_stdout(
    in_example: Path, serve: Callable[..., Judge]
) -> None:
    make_eval()
    first, second = pair_ids(in_example)
    session = serve("--json")

    session.get()
    session.choose(first, "right")
    session.get()
    session.choose(second, "left")
    result = session.finish()

    assert parsed(result) == {
        "ok": True,
        "command": "eval judge",
        "result": {"eval": EVAL, "chosen": 2, "remaining": 0},
    }
    assert address_line(session.port) in result.stderr.splitlines()
    assert "Ctrl-C" in result.stderr
    assert "http://" not in result.stdout


def test_seconds_run_from_the_first_time_the_page_was_sent(
    in_example: Path, serve: Callable[..., Judge]
) -> None:
    make_eval()
    first, second = pair_ids(in_example)
    session = serve()

    session.get()
    time.sleep(0.3)
    session.get()
    session.choose(first, "left")
    session.get()
    session.choose(second, "left")
    assert session.finish().exit_code == 0

    seconds = choice_lines(in_example)[0]["seconds"]
    assert 0.3 <= seconds < 30


# 틀린 요청과 다른 출처


def test_wrong_requests_record_nothing_and_keep_the_server_running(
    in_example: Path, serve: Callable[..., Judge]
) -> None:
    make_eval()
    first, second = pair_ids(in_example)
    session = serve()

    before_page = session.choose(first, "left")
    session.get()
    other_pair = session.choose(second, "left")
    unknown = session.choose("pair-9999", "left")
    middle = session.choose(first, "middle")
    no_fields = session.post({})
    icon = session.get("/favicon.ico")
    too_long = session.request(
        "/choose",
        data=urllib.parse.urlencode({"pair": first, "side": "left", "x": "가" * 2000}).encode(),
    )
    twice = session.request("/choose", data=f"pair={first}&side=left&side=right".encode())
    root_post = session.request("/", data=f"pair={first}&side=left".encode())

    replies = [
        before_page,
        other_pair,
        unknown,
        middle,
        no_fields,
        icon,
        too_long,
        twice,
        root_post,
    ]
    assert [r.status for r in replies] == [409, 409, 409, 400, 400, 404, 400, 400, 404]
    assert all(korean_html(r) for r in replies)
    assert not (eval_dir(in_example) / "choices.jsonl").exists()

    assert session.choose(first, "left").status == 303
    session.get()
    assert session.choose(second, "right").status == 200
    assert session.finish().exit_code == 0
    assert [c["chosen"] for c in choice_lines(in_example)] == ["left", "right"]
    assert_blind(session.responses)


def test_other_hosts_and_origins_are_refused(in_example: Path, serve: Callable[..., Judge]) -> None:
    make_eval()
    first, second = pair_ids(in_example)
    session = serve()
    port = session.port

    other_host = session.get(headers={"Host": f"evil.example:{port}"})
    session.get()
    other_origin = session.choose(first, "left", headers={"Origin": "http://evil.example"})
    null_origin = session.choose(first, "left", headers={"Origin": "null"})
    by_name = session.get(headers={"Host": f"localhost:{port}"})

    assert other_host.status == 403
    assert "쌍 1/2" not in other_host.body
    assert korean_html(other_host)
    assert other_origin.status == 403
    assert null_origin.status == 403
    assert not (eval_dir(in_example) / "choices.jsonl").exists()
    assert by_name.status == 200
    assert "쌍 1/2" in by_name.body

    same = session.choose(first, "left", headers={"Origin": f"http://127.0.0.1:{port}"})
    session.get()
    by_name_origin = session.choose(second, "left", headers={"Origin": f"http://localhost:{port}"})
    assert (same.status, by_name_origin.status) == (303, 200)
    assert session.finish().exit_code == 0
    assert len(choice_lines(in_example)) == 2


def test_texts_are_escaped(in_example: Path, serve: Callable[..., Judge]) -> None:
    make_eval()
    first, second = pair_ids(in_example)
    rewrite_pair(in_example, 0, "<script>alert(1)</script>", "A & B")
    session = serve()

    page = session.get()

    assert "&lt;script&gt;" in page.body
    assert "A &amp; B" in page.body
    assert "<script" not in page.body
    session.choose(first, "left")
    session.get()
    session.choose(second, "left")
    assert session.finish().exit_code == 0


def test_an_idle_connection_blocks_neither_requests_nor_the_end(
    in_example: Path, serve: Callable[..., Judge]
) -> None:
    make_eval()
    first, second = pair_ids(in_example)
    session = serve()

    with socket.create_connection(("127.0.0.1", session.port), timeout=5):
        assert session.get().status == 200
        session.choose(first, "left")
        assert session.get().status == 200
        assert session.choose(second, "right").status == 200
        ended = time.monotonic()
        result = session.finish(FINISH_WAIT)

    assert time.monotonic() - ended < FINISH_WAIT
    assert result.exit_code == 0, result.output
    assert len(choice_lines(in_example)) == 2


# 이어 가기와 몫


def test_limit_shows_one_pair_and_the_next_session_continues(
    in_example: Path, serve: Callable[..., Judge]
) -> None:
    make_eval()
    first, second = pair_ids(in_example)
    first_input = task_input(in_example, pair_lines(in_example)[0]["task"])
    sentence = "한 번에 1쌍까지 보여 줍니다. 남은 쌍 1개는 다음에 이어 고릅니다."

    once = serve("--limit", "1")
    assert "쌍 1/2" in once.get().body
    done = once.choose(first, "left")
    result = once.finish()

    assert done.status == 200
    assert "다 골랐습니다." in done.body
    assert sentence in done.body
    assert "이번에 고른 쌍 1개, 남은 쌍 1개" in done.body
    assert result.exit_code == 0, result.output
    assert sentence in result.stdout
    assert "이번에 고른 쌍 1개, 남은 쌍 1개" in result.stdout
    assert len(choice_lines(in_example)) == 1

    later = serve()
    page = later.get()
    assert "쌍 2/2" in page.body
    assert "쌍 1/2" not in page.body
    assert first not in page.body
    assert html.escape(first_input) not in page.body
    assert later.choose(second, "right").status == 200
    final = later.finish()
    assert final.exit_code == 0, final.output
    assert "이번에 고른 쌍 1개, 남은 쌍 0개" in final.stdout
    assert "한 번에" not in final.stdout


def test_nothing_left_opens_no_server(in_example: Path, no_server: None) -> None:
    make_eval()
    assert judge(EVAL, input="1\n2\n").exit_code == 0
    port = free_port()

    text = runner.invoke(main.app, ["eval", "judge", EVAL, "--web", "--port", str(port)])
    as_json = runner.invoke(main.app, ["eval", "judge", EVAL, "--web", "--json"])

    assert text.exit_code == 0, text.output
    assert NOTHING_LEFT in text.stdout
    assert "http://" not in text.output
    assert "이번에 고른 쌍 0개, 남은 쌍 0개" in text.stdout
    assert ok_json(as_json, "eval judge") == {"eval": EVAL, "chosen": 0, "remaining": 0}
    assert NOTHING_LEFT in as_json.stderr
    assert "http://" not in as_json.stderr


# 서버를 열기 전과 연 뒤의 실패


def test_a_port_in_use_is_port_unavailable(in_example: Path, no_server: None) -> None:
    make_eval()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]

        result = runner.invoke(
            main.app, ["eval", "judge", EVAL, "--web", "--port", str(port), "--json"]
        )

    message = error_json(result, "eval judge", "port_unavailable")
    assert f"127.0.0.1:{port}" in message
    assert "판정 화면을 열었습니다" not in result.stderr
    assert not (eval_dir(in_example) / "choices.jsonl").exists()


def _break_second_choice_line(root: Path) -> None:
    assert judge(EVAL, input="1\n").exit_code == 0
    path = eval_dir(root) / "choices.jsonl"
    path.write_bytes(path.read_bytes() + b'{"pair": "pair-0002", "cho\n')


def _remove_pair_list(root: Path) -> None:
    (eval_dir(root) / "pairs.jsonl").unlink()


def _leave_alone(root: Path) -> None:
    pass


@pytest.mark.parametrize(
    ("prepare", "eval_id", "code"),
    [
        (_leave_alone, "eval-0099", "eval_not_found"),
        (_remove_pair_list, EVAL, "eval_incomplete"),
        (_break_second_choice_line, EVAL, "invalid_file"),
    ],
    ids=["no-eval", "no-pairs", "broken-choices"],
)
def test_failures_before_the_server_opens_show_no_address(
    in_example: Path,
    no_server: None,
    prepare: Callable[[Path], None],
    eval_id: str,
    code: str,
) -> None:
    make_eval()
    prepare(in_example)

    result = runner.invoke(main.app, ["eval", "judge", eval_id, "--web", "--json"])

    error_json(result, "eval judge", code)
    assert "http://" not in result.output
    assert "판정 화면을 열었습니다" not in result.stderr


def test_ctrl_c_closes_the_server_and_keeps_the_choice(
    in_example: Path, monkeypatch: pytest.MonkeyPatch, serve: Callable[..., Judge]
) -> None:
    make_eval()
    first, second = pair_ids(in_example)
    waiting = web.wait_until_done
    chose = threading.Event()

    def interrupt_after_the_first_choice(done: threading.Event) -> None:
        chose.wait(10)
        raise KeyboardInterrupt

    monkeypatch.setattr(web, "wait_until_done", interrupt_after_the_first_choice)
    session = serve("--json")
    session.get()
    assert session.choose(first, "left").status == 303
    chose.set()
    result = session.finish()

    assert result.exit_code == 130, result.output
    assert parsed(result)["error"] == {"code": "interrupted", "message": "Ctrl-C로 멈췄습니다."}
    assert [(c["pair"], c["chosen"]) for c in choice_lines(in_example)] == [(first, "left")]
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", session.port), timeout=10).close()

    monkeypatch.setattr(web, "wait_until_done", waiting)
    later = serve()
    page = later.get()
    assert "쌍 2/2" in page.body
    assert f'value="{second}"' in page.body
    assert later.choose(second, "right").status == 200
    assert later.finish().exit_code == 0
    assert [c["pair"] for c in choice_lines(in_example)] == [first, second]


def test_waiting_ends_when_the_batch_is_done() -> None:
    done = threading.Event()
    timer = threading.Timer(0.3, done.set)
    timer.start()
    started = time.monotonic()

    web.wait_until_done(done)

    assert time.monotonic() - started >= 0.25
    timer.join()


def test_spare_tasks_are_the_two_pairs(in_example: Path) -> None:
    """이 파일의 테스트가 기대는 평가의 모양: 예비 과제 둘, 쌍 둘."""
    make_eval()

    assert sorted(p["task"] for p in pair_lines(in_example)) == SPARE
    assert pair_ids(in_example) == ["pair-0001", "pair-0002"]
