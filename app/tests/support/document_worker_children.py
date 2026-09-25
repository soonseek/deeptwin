"""Test-only children for the real-UDS document service qualification (T045).

`python -m app.tests.support.document_worker_children serve <base> --attachment-config=...`
runs the unmodified production entrypoint `app.workers.document_worker_main.main`;
`python -m app.tests.support.document_worker_children request <base>` reads a JSON plan on
stdin and renders through `DocumentCodecClient.for_worker`, printing one JSON line.

The parent test (root on Linux) starts each under a fixed numeric identity, so the kernel —
not a seam — supplies every peer credential. The only substitution in either child is the
module-local relocation of the fixed `cp-document` profile into an owned temporary pair
root, exactly as the credential gateway's children do.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path


def profile(base: Path):
    from app.workers import document_channel
    from app.workers.ipc_root import PairRootSpec

    fixed_root, fixed_spec = document_channel.document_channel()
    root = PairRootSpec(pair_root=base / "cp-document", responder_uid=fixed_root.responder_uid,
                        responder_gid=fixed_root.responder_gid, pair_gid=fixed_root.pair_gid)
    return root, dataclasses.replace(fixed_spec, pair_root=root.endpoint_path)


def _relocate(base: Path) -> None:
    from app.workers import document_channel

    root, spec = profile(base)
    document_channel.document_channel = lambda: (root, spec)  # module-local profile only


def _request(base: Path) -> int:
    from hashlib import sha256

    from app.workers.document_channel import (
        DocumentCodecClient,
        DocumentCodecError,
        DocumentWorkerConfiguration,
    )

    plan = json.loads(sys.stdin.read())
    client = DocumentCodecClient.for_worker(DocumentWorkerConfiguration(
        pair_root=str(base / "cp-document"), requester_boot_id=plan["boot"]))
    data = Path(plan["document"]).read_bytes()
    try:
        page = client.render_page(data, page=plan["page"], max_edge_px=plan["edge"])
        value = {"ok": True, "sha256": page.sha256, "digest_matches": sha256(page.png).hexdigest() == page.sha256,
                 "page_count": page.page_count, "width": page.width, "height": page.height}
    except DocumentCodecError as error:
        value = {"ok": False, "code": error.code, "sent": error.sent, "page_count": error.page_count}
    sys.stdout.write(json.dumps(value, sort_keys=True) + "\n")
    sys.stdout.flush()
    return 0


def main() -> int:
    role, base = sys.argv[1], Path(sys.argv[2])
    _relocate(base)
    if role == "serve":
        from app.workers import document_worker_main

        return document_worker_main.main([sys.argv[0], *sys.argv[3:]])
    return _request(base)


if __name__ == "__main__":
    raise SystemExit(main())
