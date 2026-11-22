"""웹 판정 화면: 127.0.0.1에만 서버를 열어 이번 몫의 쌍을 HTML 한 장씩 보여 주고 버튼 둘로 고른다.

표준 라이브러리(`http.server`)만 쓴다. 시작과 끝(남은 쌍, 한 번 몫과 하루 몫, 상한 문장, 요약)은
터미널과 같이 `session`이 맡고, 선택은 터미널과 같은 `record_choice`로 남긴다.

- 순서: 공용 시작 -> 이번 몫이 비었으면 서버 없이 끝 -> `127.0.0.1:<포트>`에 묶기(못 묶으면
  `port_unavailable`) -> 주소와 안내를 화면 쪽 스트림에 쓰기 -> 이번 몫을 다 지나면 서버를 닫고
  공용 끝. 브라우저는 스스로 열지 않는다.
- `GET /`는 지금 쌍의 화면이고 `POST /choose`(form `pair`, `side`)는 선택이다. 지금 쌍이 아니면
  409, 모양이 틀리면 400, 다른 경로는 404이고 기록하지 않는다.
- 걸린 초는 이 서버가 그 쌍의 화면을 처음 보낸 때부터 그 쌍의 POST를 받을 때까지다. 새로 고쳐도
  시작 시각은 그대로다.
- 블라인드: 응답에는 쌍의 번호, 과제의 입력, 두 결과물, 물음, 쌍 ID만 들고 조건을 되짚을 값은
  들지 않는다. 데이터는 모두 `html.escape`로 넣고, 스크립트와 바깥 자원은 없다.
- 다른 사이트가 화면을 읽거나(DNS 재바인딩) 선택을 남기지 못하게 `Host`와 `Origin`을 본다.
- 요청은 요청마다 스레드에서 처리한다. 지금 쌍, 보여 준 시각, 고른 수는 잠금 하나 안에서만 바꾼다.
- Ctrl-C는 `KeyboardInterrupt`로 그대로 올라가고 서버는 닫는다. 그때까지 고른 것은 남는다.
"""

from __future__ import annotations

import html
import socketserver
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import typer

from deeptwin.cli.session import (
    ASK,
    INPUT_LABEL,
    Judged,
    end_of,
    finish_judging,
    start_judging,
    summary,
)
from deeptwin.errors import DeeptwinError, PortUnavailableError
from deeptwin.eval import record_choice
from deeptwin.eval.judging import Judging, PendingPair
from deeptwin.models import Side
from deeptwin.store.project import DeepTwin

__all__ = [
    "judge_in_web",
]

HOST = "127.0.0.1"
"""서버를 묶는 주소. 이 컴퓨터 밖에서는 닿지 않는다."""
MAX_BODY = 4096
"""`POST /choose` 본문의 최대 바이트 수. 넘으면 400이다."""

_DRAIN_LIMIT = 1 << 20
"""너무 긴 본문을 버리려고 읽어 들이는 최대 바이트 수. 읽지 않은 채 연결을 닫으면 응답이 끊긴다."""
_SIDES: dict[str, Side] = {"left": "left", "right": "right"}
"""form의 `side` -> 고른 쪽."""
_STYLE = ".sides{display:grid;grid-template-columns:1fr 1fr;gap:1rem}.text{white-space:pre-wrap}"
_HEADERS = (
    ("Content-Type", "text/html; charset=utf-8"),
    ("Cache-Control", "no-store"),
    ("X-Frame-Options", "DENY"),
    (
        "Content-Security-Policy",
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
    ),
)
"""모든 응답에 붙이는 헤더(`Content-Length` 말고). 다른 사이트가 화면을 틀에 넣지 못하게 한다."""


def judge_in_web(
    deeptwin: DeepTwin,
    eval_id: str,
    *,
    port: int | None = None,
    limit: int | None = None,
    daily_limit: int | None = None,
    err: bool,
) -> Judged:
    """이번 몫의 쌍을 웹 화면으로 고르게 하고, 다 지나면 서버를 닫는다.

    `port`가 `None`이면 빈 포트를 쓴다. 이번 몫이 비었으면 서버를 열지 않는다. 포트에 묶지
    못하면 아무것도 기록하지 않고 `port_unavailable`이다.
    """
    judging = start_judging(deeptwin, eval_id, limit=limit, daily_limit=daily_limit, err=err)
    if not judging.batch:
        return finish_judging(judging, 0, err=err)
    desk = _Desk(deeptwin, judging)
    server = _bind(0 if port is None else port, desk)
    serving = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
    )
    try:
        serving.start()
        typer.echo(f"판정 화면을 열었습니다: http://{HOST}:{server.server_port}/", err=err)
        typer.echo(
            "브라우저로 열어 고르세요. 다 고르면 저절로 닫히고, 멈추려면 Ctrl-C를 누르세요.",
            err=err,
        )
        wait_until_done(desk.done)
    finally:
        if serving.is_alive():
            server.shutdown()
        server.server_close()
        desk.close()
    return finish_judging(judging, desk.chosen, err=err, handled=desk.handled)


def wait_until_done(done: threading.Event) -> None:
    """이번 몫을 다 지날 때까지 기다린다. 짧게 끊어 기다려 어느 OS에서든 Ctrl-C로 깬다."""
    while not done.wait(0.2):
        pass


def pair_page(item: PendingPair, total: int) -> str:
    """쌍 하나의 화면. 문의, 좌우 두 글, 물음, 버튼 둘과 숨은 `pair` 입력 하나뿐이다."""
    title = f"쌍 {item.number}/{total}"
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f"<title>{title}</title><style>{_STYLE}</style></head>"
        f"<body><h1>{title}</h1><h2>{INPUT_LABEL}</h2>"
        f'<div class="text">{_text(item.input)}</div>'
        '<div class="sides">'
        f'<section><h2>왼쪽</h2><div class="text">{_text(item.pair.left)}</div></section>'
        f'<section><h2>오른쪽</h2><div class="text">{_text(item.pair.right)}</div></section>'
        "</div>"
        f'<form method="post" action="/choose"><p>{html.escape(ASK)}</p>'
        f'<input type="hidden" name="pair" value="{html.escape(item.pair.id)}">'
        '<button name="side" value="left">왼쪽을 고릅니다</button>'
        '<button name="side" value="right">오른쪽을 고릅니다</button>'
        "</form></body></html>"
    )


def end_page(judged: Judged) -> str:
    """이번 몫을 다 지났을 때의 화면. 요약 문장과 상한 문장(있으면)이 든다."""
    return _page("다 골랐습니다.", _ending_lines(judged))


@dataclass(frozen=True)
class _Reply:
    """응답 하나. 본문은 언제나 HTML이다."""

    status: int
    body: str
    location: str | None = None


class _Desk:
    """판정 화면의 상태. 지금 쌍, 보여 준 시각, 고른 수는 `lock` 안에서만 바꾼다."""

    def __init__(self, deeptwin: DeepTwin, judging: Judging) -> None:
        self.deeptwin = deeptwin
        self.judging = judging
        self.lock = threading.Lock()
        self.done = threading.Event()
        """이번 몫을 다 지났다. 마지막 응답을 보낸 뒤에 세운다."""
        self.handled = 0
        """이번 몫에서 지나간 쌍의 수(고른 쌍과 기록하지 못해 뺀 쌍). 지금 쌍의 자리이기도 하다."""
        self.chosen = 0
        self.shown_at: float | None = None
        """지금 쌍의 화면을 처음 보낸 때(`time.perf_counter`). 아직 보내지 않았으면 `None`이다."""
        self.closed = False
        """서버를 닫았다. 그 뒤에 처리가 끝난 요청은 기록하지 않는다."""

    def show(self) -> _Reply:
        """`GET /`: 지금 쌍의 화면. 처음 보낼 때 시각을 적는다. 다 지났으면 끝 화면이다."""
        with self.lock:
            if self.handled >= len(self.judging.batch):
                return _Reply(200, end_page(self._ending()))
            item = self.judging.batch[self.handled]
            if self.shown_at is None:
                self.shown_at = time.perf_counter()
            return _Reply(200, pair_page(item, self.judging.total))

    def choose(self, pair_id: str, side: Side, received: float) -> tuple[_Reply, bool]:
        """`POST /choose`: 지금 보여 준 쌍이면 바로 기록하고 다음 쌍으로 넘어간다.

        돌려주는 참거짓은 이번 몫을 다 지났는지다. 지금 쌍이 아니면 기록하지 않고 409다.
        `record_choice`가 `DeeptwinError`를 내면 기록 없이 409에 그 메시지를 보이고, 그 쌍은 이번
        판정에서 빼고 넘어간다.
        """
        with self.lock:
            batch = self.judging.batch
            current = None if self.handled >= len(batch) else batch[self.handled]
            if (
                self.closed
                or current is None
                or self.shown_at is None
                or current.pair.id != pair_id
            ):
                back = not self.closed and current is not None
                return _Reply(409, _not_current(back=back)), False
            failure: str | None = None
            try:
                record_choice(
                    self.deeptwin,
                    self.judging.eval,
                    pair_id,
                    side,
                    seconds=received - self.shown_at,
                )
            except DeeptwinError as error:
                failure = error.message
            else:
                self.chosen += 1
            self.handled += 1
            self.shown_at = None
            finished = self.handled >= len(batch)
            ending = self._ending() if finished else None
        if failure is not None:
            lines = [failure, "이 쌍은 이번 판정에서 빼고 넘어갑니다."]
            if ending is not None:
                lines += _ending_lines(ending)
            return _Reply(409, _page("기록하지 못했습니다.", lines, back=ending is None)), finished
        if ending is not None:
            return _Reply(200, end_page(ending)), True
        return _Reply(303, _page("다음 쌍으로 넘어갑니다.", [], back=True), location="/"), False

    def close(self) -> None:
        """서버를 닫은 뒤에 부른다. 기록 중인 요청이 있으면 끝나기를 기다린다."""
        with self.lock:
            self.closed = True

    def _ending(self) -> Judged:
        return end_of(self.judging, self.chosen, handled=self.handled)


class _Server(ThreadingHTTPServer):
    """127.0.0.1에만 묶는 서버. 요청마다 daemon 스레드에서 처리하고, 닫을 때 기다리지 않는다."""

    daemon_threads = True
    block_on_close = False
    """쉬는 연결의 스레드가 있어도 `server_close`가 기다리지 않는다(daemon 스레드와 겹쳐 둔다)."""
    allow_reuse_address = sys.platform != "win32"
    """Windows의 `SO_REUSEADDR`는 다른 소켓이 듣고 있는 포트에도 묶어 버린다."""

    def __init__(self, port: int, desk: _Desk) -> None:
        self.desk = desk
        super().__init__((HOST, port), _Handler)

    def server_bind(self) -> None:
        # HTTPServer.server_bind는 socket.getfqdn을 불러 느릴 수 있다
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = HOST, int(self.server_address[1])

    def handle_error(self, request: Any, client_address: Any) -> None:
        # 브라우저가 응답 전에 연결을 끊었거나 본문이 오지 않아 시간이 다 된 것은 알리지 않는다
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def _bind(port: int, desk: _Desk) -> _Server:
    try:
        return _Server(port, desk)
    except OSError:
        raise PortUnavailableError(
            f"판정 화면을 {HOST}:{port}에 열지 못했습니다. 다른 프로그램이 이 포트를 쓰고 있을 수 "
            "있습니다. --port로 다른 번호를 주거나 --port를 빼고 빈 포트를 쓰세요."
        ) from None


class _Handler(BaseHTTPRequestHandler):
    """요청 하나. 응답은 모두 HTML이고 요청 기록은 쓰지 않는다."""

    server: _Server
    server_version = "judge"
    timeout = 60
    """요청을 보내지 않는 연결은 이만큼(초) 지나면 닫는다."""

    def version_string(self) -> str:
        return self.server_version

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if not self._same_host():
            return
        if urlsplit(self.path).path != "/":
            self._send(_Reply(404, _not_found()))
            return
        self._send(self.server.desk.show())

    def do_POST(self) -> None:
        received = time.perf_counter()
        body = self._read_body()
        if not self._same_host():
            return
        if urlsplit(self.path).path != "/choose":
            self._send(_Reply(404, _not_found()))
            return
        if not self._same_origin():
            return
        form = None if body is None else _form(body)
        if form is None:
            self._send(_Reply(400, _bad_form()))
            return
        reply, finished = self.server.desk.choose(*form, received)
        try:
            self._send(reply)
        finally:
            if finished:
                self.server.desk.done.set()

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        # 요청 줄이 틀렸거나 받지 않는 메서드다. 기본 화면(영어) 대신 한국어 HTML을 보낸다
        self.close_connection = True
        text = (
            "판정 화면은 GET과 POST만 받습니다."
            if code == 501
            else "판정 화면이 읽을 수 없는 요청입니다."
        )
        self._send(_Reply(int(code), _page("처리할 수 없는 요청입니다.", [text])))

    def _same_host(self) -> bool:
        """`Host`가 있으면 이 서버의 주소여야 한다. 아니면 403을 보낸다."""
        port = self.server.server_port
        allowed = {f"{HOST}:{port}", f"localhost:{port}"}
        if port == 80:
            allowed |= {HOST, "localhost"}
        if all(host.strip().lower() in allowed for host in self.headers.get_all("Host", [])):
            return True
        self._send(_Reply(403, _forbidden()))
        return False

    def _same_origin(self) -> bool:
        """`Origin`이 있으면 이 서버의 출처여야 한다. 아니면 403을 보낸다."""
        port = self.server.server_port
        allowed = {f"http://{HOST}:{port}", f"http://localhost:{port}"}
        if port == 80:
            allowed |= {f"http://{HOST}", "http://localhost"}
        if all(origin.strip().lower() in allowed for origin in self.headers.get_all("Origin", [])):
            return True
        self._send(_Reply(403, _forbidden()))
        return False

    def _read_body(self) -> bytes | None:
        """본문. 길이가 틀렸거나 `MAX_BODY`를 넘으면 `None`이다(넘는 본문은 읽어서 버린다)."""
        text = self.headers.get("Content-Length")
        if text is None:
            return b""
        text = text.strip()
        if not (text.isascii() and text.isdigit()):
            return None
        length = int(text)
        if length > MAX_BODY:
            left = min(length, _DRAIN_LIMIT)
            while left > 0:
                chunk = self.rfile.read(min(left, 1 << 16))
                if not chunk:
                    break
                left -= len(chunk)
            return None
        return self.rfile.read(length)

    def _send(self, reply: _Reply) -> None:
        body = reply.body.encode("utf-8")
        self.send_response(reply.status)
        for name, value in _HEADERS:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        if reply.location is not None:
            self.send_header("Location", reply.location)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.wfile.flush()


def _form(body: bytes) -> tuple[str, Side] | None:
    """`pair=<쌍 ID>&side=<left|right>`. 필드가 없거나 겹치거나 더 있으면 `None`이다."""
    try:
        fields = parse_qs(
            body.decode("ascii"),
            keep_blank_values=True,
            strict_parsing=True,
            errors="strict",
            max_num_fields=4,
        )
    except ValueError:
        return None
    if set(fields) != {"pair", "side"} or any(len(values) != 1 for values in fields.values()):
        return None
    [pair], [side] = fields["pair"], fields["side"]
    if not pair or side not in _SIDES:
        return None
    return pair, _SIDES[side]


def _text(value: str) -> str:
    """글 하나를 HTML에 넣는다. 끝의 줄바꿈은 뺀다(터미널 화면과 같다)."""
    return html.escape(value.rstrip("\n"))


def _ending_lines(judged: Judged) -> list[str]:
    lines = [summary(judged)]
    if judged.notice is not None:
        lines.append(judged.notice)
    lines.append("이 창은 닫아도 됩니다.")
    return lines


def _page(title: str, lines: list[str], *, back: bool = False) -> str:
    """끝 화면과 오류 화면. 제목과 문장들, 그리고 `back`이면 지금 쌍으로 돌아가는 링크다."""
    paragraphs = "".join(f"<p>{html.escape(line)}</p>" for line in lines)
    link = '<p><a href="/">지금 쌍으로 돌아갑니다</a></p>' if back else ""
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title></head>"
        f"<body><h1>{html.escape(title)}</h1>{paragraphs}{link}</body></html>"
    )


def _not_current(*, back: bool) -> str:
    return _page(
        "지금 고를 쌍이 아닙니다.",
        [
            "이미 골랐거나, 없는 쌍이거나, 아직 화면에 보여 주지 않은 쌍입니다.",
            "기록하지 않았습니다.",
        ],
        back=back,
    )


def _bad_form() -> str:
    return _page(
        "받을 수 없는 선택입니다.",
        ["쌍과 고른 쪽(왼쪽이나 오른쪽)이 함께 와야 합니다. 기록하지 않았습니다."],
        back=True,
    )


def _not_found() -> str:
    return _page("없는 화면입니다.", ["판정 화면은 첫 화면 하나뿐입니다."], back=True)


def _forbidden() -> str:
    return _page(
        "열 수 없는 주소입니다.",
        [f"판정 화면은 이 컴퓨터의 주소({HOST} 또는 localhost)로만 엽니다. 기록하지 않았습니다."],
    )
