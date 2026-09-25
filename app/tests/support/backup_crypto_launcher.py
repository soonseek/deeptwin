"""Test-only launcher: the production backup-crypto entrypoint over a relocated pair root (T070).

`python -m app.tests.support.backup_crypto_launcher <base> --service-config=... --attachment-config=...`

The parent test (root on Linux) starts this under the backup identity 20111:20111 with the
pair group 21109, inside a fresh network namespace where available. The only substitution
is the module-local profile resolution into ``<base>/cp-backup`` (``backup_profile``);
everything after that is the unmodified ``app.workers.backup_crypto_main.main`` with the
remaining argv: configuration parsing, the profile check, the network guard, the age
runtime, the key-root check, the listener bind, the serve loop, signals, logging and exit
codes.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path


def backup_profile(base: Path):
    """The production `cp-backup` profile relocated into `base` (pair root only)."""

    from app.workers import backup_channel
    from app.workers.ipc_root import PairRootSpec

    fixed_root, fixed_spec = backup_channel.backup_channel()
    root = PairRootSpec(pair_root=Path(base) / "cp-backup", responder_uid=fixed_root.responder_uid,
                        responder_gid=fixed_root.responder_gid, pair_gid=fixed_root.pair_gid)
    spec = dataclasses.replace(fixed_spec, pair_root=root.endpoint_path)
    return root, spec


def relocate(base: Path) -> None:
    from app.workers import backup_channel

    root, spec = backup_profile(base)
    backup_channel.backup_channel = lambda: (root, spec)  # module-local profile only


def die_with_parent() -> None:
    """A fixture-owned child ends when its supervisor does (Linux PR_SET_PDEATHSIG)."""

    import ctypes
    import signal

    ctypes.CDLL(None, use_errno=True).prctl(1, int(signal.SIGTERM), 0, 0, 0)


def main() -> int:
    import os

    from app.workers import backup_crypto_main

    if os.environ.get("DEEPTWIN_TEST_DIE_WITH_PARENT") == "1":
        die_with_parent()
    relocate(Path(sys.argv[1]))
    return backup_crypto_main.main([sys.argv[0], *sys.argv[2:]])


if __name__ == "__main__":
    raise SystemExit(main())
