"""Finite test-owned supported app over a durable US6 chain (T067).

First start (`--owned-dir DIR`, DIR new and empty): the supported app is created
over DIR/data and the whole chain is seeded through the real services
(app/tests/growth_chain_fixture.py) — every fact synthetic, authored by the vault's
test actor. Restart (`--owned-dir DIR --resume --port PORT`): the same app is
created over the same store and session root, nothing is seeded, and before it
serves, the restart's recovery obligations are checked over the stored chain: each
lineage's newest loop revision resumes exactly; a late duplicate of an applied round
is refused; a second writer advancing from an older revision collides with the
stored one; no round or loop record is added. The facts are written to
DIR/growth-seed.json and DIR/growth-resume.json. No model, tool or paid call.
"""
import argparse
import base64
import os
import socket
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.domain.refs import EntityRef
from app.operations.session_root import initialize_session_root
from app.operations.setup import (
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.server import create_app
from app.services.growth import GrowthLoopError, apply_round
from app.services.growth_store import (
    GrowthStoreError,
    persist_loop_state,
    resume_loop,
)
from app.tests import growth_chain_fixture as chain


def resume_checks(domain, seeded):
    before = {"growth_records": chain.growth_record_count(domain), "rounds": chain.round_record_count(domain)}
    lineages = {}
    for lineage, facts in seeded["lineages"].items():
        heads = [EntityRef.from_dict(item) for item in facts["loop_heads"]]
        state = resume_loop(domain, heads[-1])
        entry = {"resumed": state.as_dict()}
        # a late duplicate of the last applied round (a result arriving again after the restart)
        if state.status == "running" and state.completed_round_ids:
            try:
                apply_round(state, {"round_id": state.completed_round_ids[-1], "validity": "valid",
                                    "utility": "0.99", "mandatory_passed": True, "regression_ok": True,
                                    "consumed": {}})
                entry["late_duplicate"] = "applied"
            except GrowthLoopError as error:
                entry["late_duplicate"] = f"refused: {error}"
            # a second writer that advanced from the older revision (a re-dispatched request)
            older = resume_loop(domain, heads[-2])
            forked = apply_round(older, {"round_id": "re-dispatched-after-restart", "validity": "valid",
                                         "utility": "0.99", "mandatory_passed": True, "regression_ok": True,
                                         "consumed": {"isolated_runs": 2}})
            try:
                persist_loop_state(domain, forked, parent_ref=heads[-2],
                                   **chain.marks(domain))
                entry["fork"] = "persisted"
            except GrowthStoreError as error:
                entry["fork"] = f"refused: {error}"
        lineages[lineage] = entry
    after = {"growth_records": chain.growth_record_count(domain), "rounds": chain.round_record_count(domain)}
    return {"evidence_label": chain.LABEL, "before": before, "after": after, "lineages": lineages}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-dir", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    owned = args.owned_dir.resolve(strict=True)
    if not owned.is_dir() or (not args.resume and any(owned.iterdir())):
        raise RuntimeError("Fixture requires its newly owned empty directory")
    if args.resume and not (owned / "growth-seed.json").is_file():
        raise RuntimeError("A resume needs the store this fixture seeded")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", args.port))
    sock.listen(128)  # accept (queue) before the URL is announced
    profile = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=sock.getsockname()[1])
    capability = base64.urlsafe_b64encode(b"T" * 32).rstrip(b"=").decode()
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=derive_capability_verifier(capability))
    initialize_session_root(owned / "root", profile=profile, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid())
    domain = app.state.domain_store
    if args.resume:
        import json

        seeded = json.loads((owned / "growth-seed.json").read_text(encoding="utf-8"))
        (owned / "growth-resume.json").write_text(chain.dumps(resume_checks(domain, seeded)), encoding="utf-8")
    else:
        seeded = chain.seed(domain, owned / "reset")
        (owned / "growth-seed.json").write_text(chain.dumps(seeded), encoding="utf-8")
    print(f"GROWTH_PORT={profile.port}", flush=True)
    print(f"GROWTH_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
