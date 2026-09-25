"""T023 wording guard: nothing the supported product serves carries the loopback
prototype's device claims ("이 컴퓨터에 저장됨", "이 컴퓨터의 Codex 로그인과 공유",
native-app / install-launcher copy). Storage is named as this DeepTwin instance's, an
unsaved draft as this browser's only, and the provider connection as the instance's.

Scope: every asset the supported factory serves (`app.api.assets.MODULES`) and the
user-facing strings of the supported services. The historical control prototype
(`control-prototype/`) is not served by the product and is not rewritten.
"""

import re
from pathlib import Path

from app.api.assets import MODULES, STATIC

FORBIDDEN = re.compile(
    r"이 컴퓨터|이 기기에 저장|Codex 로그인과 공유|네이티브 앱|설치 실행기|설치 런처|런처를 설치|"
    r"native app|install launcher|installer app|this computer",
    re.IGNORECASE,
)
SERVICES = Path(__file__).resolve().parents[1] / "services"


def test_no_served_asset_implies_the_browser_device_or_a_local_app_is_the_host():
    offenders = {}
    for name in MODULES:
        text = (STATIC / name).read_text(encoding="utf-8")
        found = sorted(set(FORBIDDEN.findall(text)))
        if found:
            offenders[name] = found
    assert offenders == {}


def test_the_work_screen_names_instance_storage_and_browser_only_drafts():
    page = (STATIC / "work.html").read_text(encoding="utf-8")
    work = (STATIC / "work.mjs").read_text(encoding="utf-8")
    assert "이 인스턴스" in page and "이 브라우저" in page
    assert "이 인스턴스에 저장" in work and "이 브라우저에만 임시 보관" in work
    chat = (STATIC / "chat.mjs").read_text(encoding="utf-8")
    assert "이 인스턴스에 기록됩니다" in chat and "이 브라우저에만 임시 보관됩니다" in chat


def test_supported_service_messages_carry_no_device_claims():
    offenders = {}
    for path in sorted(SERVICES.glob("*.py")):
        found = sorted(set(FORBIDDEN.findall(path.read_text(encoding="utf-8"))))
        if found:
            offenders[path.name] = found
    assert offenders == {}


def test_backups_carry_readings_and_messages_but_never_open_approval_challenges():
    from app.operations.backup import classify_table

    assert classify_table("source_readings_v1") is None
    assert classify_table("conversation_v1_messages") is None
    assert classify_table("conversation_v1_proposals") is None
    assert classify_table("conversation_v1_challenges") == "pending_challenges"
