"""테스트용 가짜 claude. `ClaudeCLIProvider(command=(sys.executable, <이 파일>))`로 부른다.

네트워크와 모델 없이 돈다. 환경 변수로 동작을 고른다.

- `CLAUDE_STUB_MODE`: `success`(기본), `is_error`, `exit1`, `not_json`, `slow`,
  `error_subtype`, `result_not_text`. `--version`으로 부르면 모드와 관계없이 버전을 쓴다.
- `CLAUDE_STUB_LOG`: 주면 부를 때마다 argv, stdin, 시스템 프롬프트 파일 내용, 작업 폴더와
  그 안의 파일, pid를 이 파일에 JSON 한 줄로 덧붙인다.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, TextIO

VERSION = "2.1.330 (Claude Code)"
RESULT = "가짜 claude의 답장입니다.\n수강료는 확인해 알려 드리겠습니다.\n"
MAIN_MODEL = "claude-opus-5-5"
STDERR = "Error: 가짜 claude가 실패했습니다"
IS_ERROR_RESULT = "Not logged in · Please run /login"


def main(argv: list[str]) -> int:
    version = argv == ["--version"]
    stdin = "" if version else sys.stdin.buffer.read().decode("utf-8")
    log(argv, stdin)
    if version:
        write(sys.stdout, VERSION + "\n")
        return 0
    mode = os.environ.get("CLAUDE_STUB_MODE", "success")
    if mode == "exit1":
        write(sys.stderr, STDERR + "\n")
        return 1
    if mode == "not_json":
        write(sys.stdout, "JSON이 아닌 출력\n")
        return 0
    if mode == "slow":
        time.sleep(60)
    reply: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": RESULT,
        "modelUsage": {
            "claude-haiku-4-5": {"inputTokens": 300, "outputTokens": 12},
            MAIN_MODEL: {"inputTokens": 1200, "outputTokens": 345},
        },
    }
    if mode == "is_error":
        reply.update(is_error=True, result=IS_ERROR_RESULT)
    elif mode == "error_subtype":
        reply.update(subtype="error_max_turns")
        del reply["result"]
    elif mode == "result_not_text":
        reply.update(result=None)
    write(sys.stdout, json.dumps(reply, ensure_ascii=False))
    return 0


def write(stream: TextIO, text: str) -> None:
    """운영체제의 기본 인코딩과 관계없이 UTF-8 바이트로 쓴다."""
    stream.buffer.write(text.encode("utf-8"))
    stream.flush()


def log(argv: list[str], stdin: str) -> None:
    path = os.environ.get("CLAUDE_STUB_LOG")
    if not path:
        return
    system_prompt = None
    if "--system-prompt-file" in argv:
        prompt_file = Path(argv[argv.index("--system-prompt-file") + 1])
        system_prompt = prompt_file.read_bytes().decode("utf-8")
    entry = {
        "argv": argv,
        "stdin": stdin,
        "system_prompt": system_prompt,
        "cwd": os.getcwd(),
        "cwd_files": sorted(os.listdir()),
        "pid": os.getpid(),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
