"""T084: every tracked file carries copyright and license information (REUSE 3.3)."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_the_repository_is_reuse_compliant():
    reuse = shutil.which("reuse") or str(Path(sys.executable).with_name("reuse"))
    if not Path(reuse).exists():
        pytest.skip("reuse is not installed (dev group)")
    result = subprocess.run([reuse, "--root", str(ROOT), "lint"], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout[-4000:]


def test_upstream_files_are_never_relicensed_as_first_party():
    config = (ROOT / "REUSE.toml").read_text()
    assert '"deploy/locks/licenses/**"' in config
    assert 'SPDX-License-Identifier = "LicenseRef-Upstream-Terms"' in config
    assert "not relicensed under Apache-2.0" in (ROOT / "LICENSES/LicenseRef-Upstream-Terms.txt").read_text()
