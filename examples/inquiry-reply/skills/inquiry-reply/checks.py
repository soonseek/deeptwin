# 가상의 강사 서도윤의 원칙 검사 함수. 예제로 지어낸 것이다.
"""스킬 inquiry-reply의 원칙 검사 함수. 표준 라이브러리만 쓴다.

함수마다 답장 글을 받아 원칙을 지켰으면 True, 어겼으면 False를 돌려준다.
함수 이름이 `.deeptwin/layers/principles.yaml`에 적은 원칙의 `check`다.
"""

import re

_PROMISE = re.compile(
    r"보장(합니다|해\s?드립니다|해\s?드려요|됩니다)|100\s?%|반드시\s?(취업|합격|이직)"
)
"""성과를 장담하는 말. `보장하기 어렵습니다`처럼 장담하지 않는 말은 걸리지 않는다."""

_CONTACT = re.compile(r"https?://|www\.|[\w.+-]+@[\w-]+(\.[\w-]+)+|\d{2,4}-\d{3,4}-\d{4}")
"""링크, 메일 주소, 전화번호."""


def no_outcome_promise(output: str) -> bool:
    """원칙 prin-01: 취업이나 성과를 보장한다는 말이 없으면 True."""
    return _PROMISE.search(output) is None


def no_contact_details(output: str) -> bool:
    """원칙 prin-02: 링크, 메일 주소, 전화번호가 없으면 True. 연락은 메일 답장으로 받는다."""
    return _CONTACT.search(output) is None
