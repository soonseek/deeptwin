"""Test-only launcher: the production gateway entrypoint over a relocated pair root (T090).

`python -m app.tests.support.credential_gateway_launcher <base> --service-config=... --attachment-config=...`

The parent test (root on Linux) starts this under the provider identity. The only
substitution is the module-local profile resolution into ``<base>/cp-provider``, exactly
as the other real-UDS children do (``credential_peercred_child.profile``); everything
after that is the unmodified ``app.workers.credential_gateway_main.main`` with the
remaining argv: configuration parsing, the profile check, the vault open, the listener
bind, the serve loop, signal handling, logging and exit codes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.tests.support.credential_peercred_child import profile


def main() -> int:
    from app.workers import credential_gateway_main, gateway_channel

    root, spec = profile(Path(sys.argv[1]))
    gateway_channel.gateway_channel = lambda: (root, spec)  # module-local profile only
    return credential_gateway_main.main([sys.argv[0], *sys.argv[2:]])


if __name__ == "__main__":
    raise SystemExit(main())
