"""T073 server half: the owner's backup and staged restore routes (`backups-v1`).

`GET /api/v1/backups` states whether a backup-crypto worker is attached and ready;
`POST …/preview` shows the ACTUAL included content (categories and counts, originals,
every excluded category with its closed reason) and stores nothing; `POST
/api/v1/backups` requires `confirmed: true` and that preview's digest and refuses a
stale one; the encrypted bundle and its external receipt download separately; a restore
begins from the receipt, takes the bundle as `application/octet-stream`, and stages a
`restored_review` vault beside — never over — the active one.

Without a worker the routes answer honestly (`not_configured`, 503
`backup_worker_unavailable`). With a worker, these in-process route tests put the real
worker dialogue code (`BackupCryptoService.run`, the locked age runtime and a real
backup-key volume) behind the same crypto-port methods; the real process boundary is
app/tests/test_backup_crypto_worker.py and the real-browser case
app/tests/browser-backup.test.mjs.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from app.tests.test_web_owner_integration import headers
from app.tests.test_works_api import create, owner_app

AGE_ROOT = os.environ.get("DEEPTWIN_AGE_RUNTIME_ROOT")
needs_age = pytest.mark.skipif(
    not AGE_ROOT, reason="DEEPTWIN_AGE_RUNTIME_ROOT (the verified locked age 1.3.2) is not set")


class InProcessWorker:
    """The worker's own dialogue code behind the client's port methods (tests only)."""

    def __init__(self, runtime, key_root: Path):
        from app.workers.backup_crypto_service import BackupCryptoService

        self.service = BackupCryptoService(runtime, key_root)

    def _run(self, **request):
        from app.workers import backup_stream as stream
        from app.workers.backup_crypto_client import BackupWorkerError

        body = request.pop("body", b"")
        value = {"schema": stream.REQUEST_SCHEMA, "recipient": None, "identity": None, "size": len(body),
                 "sha256": hashlib.sha256(body).hexdigest(), **request}
        try:
            return self.service.run(stream.check_request(value), body)
        except stream.BackupStreamError as error:
            raise BackupWorkerError(error.code) from None

    def describe(self):
        _body, recipient = self._run(op="describe", key_mode="instance_backup_key")
        return {"key_mode": "instance_backup_key", "recipient": recipient, "key": "present"}

    def encrypt(self, archive, *, key_mode, recipient=None):
        return self._run(op="encrypt", key_mode=key_mode, body=archive, recipient=recipient)[0]

    def decrypt(self, ciphertext, *, key_mode, identity=None):
        # as BackupCryptoClient.decrypt: a portable identity crosses as its ASCII text, once
        text = identity.decode("ascii").strip() if key_mode == "portable_recovery" else None
        return self._run(op="decrypt", key_mode=key_mode, body=ciphertext, identity=text)[0]


def path(subject, tail=""):
    return subject.profile.base_path + "api/v1/backups" + tail


def post(subject, tail, body):
    return subject.client.post(path(subject, tail), json=body, headers=headers(subject.profile, subject.csrf))


def get(subject, tail=""):
    return subject.client.get(path(subject, tail), headers=headers(subject.profile))


def preview(subject):
    return post(subject, "/preview", {"schema_version": "backup-preview-request-v1", "request_id": str(uuid4())})


def confirm(subject, shown, **changes):
    body = {"schema_version": "backup-create-v1", "request_id": shown["request_id"],
            "preview_sha": shown["preview_sha"], "confirmed": True, **changes}
    return post(subject, "", body)


def upload(subject, restore_id, data, content_type="application/octet-stream"):
    return subject.client.post(path(subject, f"/restores/{restore_id}/bundle"), content=data,
                               headers={**headers(subject.profile, subject.csrf), "Content-Type": content_type})


@contextmanager
def with_worker(tmp_path, subject, *, key=True):
    from app.operations.backup import age_keygen
    from app.operations.backup_key import initialize_backup_key
    from app.workers.backup_crypto import AgeRuntime

    runtime = AgeRuntime.open(AGE_ROOT)
    key_root = tmp_path / "backup-key"
    key_root.mkdir()
    if key:
        initialize_backup_key(key_root, keygen=age_keygen(runtime))
    os.chmod(key_root, 0o500)
    service = subject.app.state.first_party_exports["backups.service"]
    service._client = InProcessWorker(runtime, key_root)
    try:
        yield key_root
    finally:
        os.chmod(key_root, 0o700)


def test_without_a_worker_the_state_is_honest_and_nothing_is_created(tmp_path):
    with owner_app(tmp_path) as subject:
        create(subject, text="백업 미리보기용 작업")
        state = get(subject)
        assert state.status_code == 200, state.text
        value = state.json()
        assert value["worker"] == "not_configured" and value["backups"] == [] and value["restores"] == []
        assert value["recoverable_after_host_or_volume_loss"] is False
        shown = preview(subject)
        assert shown.status_code == 200, shown.text
        shown = shown.json()
        included = {entry["category"]: entry for entry in shown["included"]}
        assert included["records_and_lineage"]["rows"] > 0 and included["originals"]["count"] == 0
        excluded = {entry["category"]: entry["reason"] for entry in shown["excluded"]}
        assert excluded["owner_authenticators_sessions_and_bootstrap_verifiers"] == "authenticator_never_restored"
        assert excluded["provider_credential_root"] == "separate_private_root"
        assert excluded["backup_key_volume"] == "separate_private_root"
        assert "백업 미리보기용" not in json.dumps(shown)  # counts, never content
        refused = confirm(subject, shown)
        assert refused.status_code == 503 and refused.json()["code"] == "backup_worker_unavailable"
        begin = post(subject, "/restores", {"schema_version": "backup-restore-v1", "request_id": str(uuid4()),
                                            "receipt": {"backup_id": str(uuid4()), "ciphertext_sha256": "0" * 64,
                                                        "ciphertext_size": 10, "encryption_profile_ref": "age-x25519-v1",
                                                        "key_mode": "instance_backup_key"}})
        assert begin.status_code == 503 and begin.json()["code"] == "backup_worker_unavailable"
        assert not (Path(subject.domain.data_dir) / "backups").exists()


def test_the_wire_is_exact(tmp_path):
    with owner_app(tmp_path) as subject:
        for tail, body in (("/preview", {"schema_version": "other", "request_id": str(uuid4())}),
                           ("", {"schema_version": "backup-create-v1", "request_id": str(uuid4()),
                                 "preview_sha": "0" * 64, "confirmed": True, "key": "x"}),
                           ("/restores", {"schema_version": "backup-restore-v1", "request_id": "x"})):
            assert post(subject, tail, body).status_code == 400
        assert upload(subject, str(uuid4()), b"x", content_type="application/json").status_code == 400
        assert get(subject, "/not-a-uuid/ciphertext").status_code in (400, 404)
        subject.client.cookies.clear()  # no owner session: nothing about backups is readable
        assert subject.client.get(path(subject), headers=headers(subject.profile)).status_code == 401


@needs_age
def test_backup_create_binds_consent_downloads_and_restores_into_staged_review(tmp_path):
    with owner_app(tmp_path) as subject, with_worker(tmp_path, subject):
        create(subject, text="복원될 작업 설명")
        state = get(subject).json()
        assert state["worker"] == "ready" and state["recipient"].startswith("age1")
        shown = preview(subject).json()
        assert confirm(subject, shown, confirmed=False).status_code == 400  # consent is never implicit
        stale = confirm(subject, shown, preview_sha="0" * 64)
        assert stale.status_code == 409 and "preview" in stale.json()["detail"]
        again = preview(subject).json()
        assert again["preview_sha"] == shown["preview_sha"]  # a preview stores nothing
        made = confirm(subject, shown)
        assert made.status_code == 200, made.text
        receipt = made.json()["receipt"]
        assert made.json()["states"][-1] == "ready"
        assert receipt["recoverable_after_host_or_volume_loss"] is False
        listed = get(subject).json()["backups"]
        assert [item["backup_id"] for item in listed] == [receipt["backup_id"]]
        assert listed[0]["consented_preview_sha"] == shown["preview_sha"]
        bundle = get(subject, f"/{receipt['backup_id']}/ciphertext")
        assert bundle.status_code == 200 and bundle.content.startswith(b"age-encryption.org/v1\n")
        assert hashlib.sha256(bundle.content).hexdigest() == receipt["ciphertext_sha256"]
        assert "복원될 작업".encode() not in bundle.content
        assert json.loads(get(subject, f"/{receipt['backup_id']}/receipt").content) == receipt
        begin = post(subject, "/restores", {"schema_version": "backup-restore-v1", "request_id": str(uuid4()),
                                            "receipt": receipt})
        assert begin.status_code == 200, begin.text
        restore_id = begin.json()["restore_id"]
        assert begin.json()["state"] == "awaiting_bundle"
        staged = upload(subject, restore_id, bundle.content)
        assert staged.status_code == 200, staged.text
        view = staged.json()
        assert view["state"] == "restored_review"
        assert view["review"]["dispatch"] == "blocked"
        assert view["review"]["requires"] == ["new_owner_bootstrap", "recreate_connections_and_service_clients",
                                              "review_and_activate_exact_environment"]
        assert view["review"]["environment_reactivation"] == "explicit_required"
        assert view["review"]["active_vault_changed"] is False
        assert "owner_authenticators_sessions_and_bootstrap_verifiers" in view["review"]["not_restored"]
        assert get(subject, f"/restores/{restore_id}").json() == view
        assert upload(subject, restore_id, bundle.content).status_code == 409  # one bundle per restore
        vault = Path(subject.domain.data_dir) / "restores" / restore_id / "staged" / "vault" / "intake.sqlite3"
        with sqlite3.connect(vault) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not any(name.startswith("owner_auth_") for name in tables)
        # the active vault keeps serving the same owner
        assert get(subject).status_code == 200


@needs_age
def test_a_corrupt_bundle_or_a_lost_key_is_stated_and_stages_nothing(tmp_path):
    with owner_app(tmp_path) as subject, with_worker(tmp_path, subject) as key_root:
        shown = preview(subject).json()
        receipt = confirm(subject, shown).json()["receipt"]
        data = bytearray(get(subject, f"/{receipt['backup_id']}/ciphertext").content)
        data[len(data) // 2] ^= 0x01

        def begin():
            return post(subject, "/restores", {"schema_version": "backup-restore-v1", "request_id": str(uuid4()),
                                               "receipt": receipt}).json()["restore_id"]

        restore_id = begin()
        corrupt = upload(subject, restore_id, bytes(data)).json()
        assert corrupt["state"] == "failed" and corrupt["failure_code"] == "restore_failed"
        assert "external receipt" in corrupt["failure"]
        assert not (Path(subject.domain.data_dir) / "restores" / restore_id / "staged").exists()
        # key/volume loss: the worker answers key_unavailable; nothing is made or staged
        os.chmod(key_root, 0o700)
        for item in key_root.iterdir():
            item.unlink()
        assert get(subject).json()["worker"] == "key_unavailable"
        lost = confirm(subject, preview(subject).json())
        assert lost.status_code == 503 and lost.json()["code"] == "backup_key_unavailable"
        original = get(subject, f"/{receipt['backup_id']}/ciphertext").content
        restore_id = begin()
        lost_restore = upload(subject, restore_id, original).json()
        assert lost_restore["state"] == "failed" and lost_restore["failure_code"] == "backup_key_unavailable"


def interrupted_upload(subject, restore_id, data, *, sent, csrf=None):
    """Drive the real ASGI app with a bundle upload whose client disconnects after `sent`
    bytes of the declared body (what an aborted browser upload looks like to the server)."""
    import asyncio

    base = subject.profile.base_path + f"api/v1/backups/restores/{restore_id}/bundle"
    cookie = "; ".join(f"{name}={value}" for name, value in subject.client.cookies.items())
    fields = {**headers(subject.profile, subject.csrf if csrf is None else csrf),
              "Host": subject.profile.http_origin.split("://", 1)[1], "Cookie": cookie,
              "Content-Type": "application/octet-stream", "Content-Length": str(len(data))}
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
             "scheme": subject.profile.http_origin.split("://", 1)[0], "path": base, "raw_path": base.encode(),
             "root_path": "", "query_string": b"", "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 80),
             "headers": [(name.lower().encode(), value.encode()) for name, value in fields.items()]}
    messages = [{"type": "http.request", "body": data[:sent], "more_body": True}, {"type": "http.disconnect"}]
    sent_back = []

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent_back.append(message)

    asyncio.run(subject.app(scope, receive, send))
    return sent_back


@needs_age
def test_an_upload_cut_mid_stream_fails_its_restore_stages_nothing_and_a_fresh_restore_works(tmp_path):
    with owner_app(tmp_path) as subject, with_worker(tmp_path, subject):
        create(subject, text="중단 복원 확인 작업")
        receipt = confirm(subject, preview(subject).json()).json()["receipt"]
        bundle = get(subject, f"/{receipt['backup_id']}/ciphertext").content
        restore_id = begin_restore(subject, receipt)["restore_id"]
        active = sorted(p.name for p in Path(subject.domain.data_dir).iterdir())
        # a disconnect from a request without the owner's CSRF value marks nothing
        interrupted_upload(subject, restore_id, bundle, sent=len(bundle) // 2, csrf="0" * 43)
        assert get(subject, f"/restores/{restore_id}").json()["state"] == "awaiting_bundle"
        # the owner's upload is cut halfway: nothing answers, the restore is failed and empty
        assert interrupted_upload(subject, restore_id, bundle, sent=len(bundle) // 2) == []
        view = get(subject, f"/restores/{restore_id}").json()
        assert view["state"] == "failed" and view["failure_code"] == "restore_failed"
        assert view["failure"].startswith("the bundle upload was interrupted")
        assert view["interrupted_after_bytes"] == len(bundle) // 2
        restore_dir = Path(subject.domain.data_dir) / "restores" / restore_id
        assert sorted(p.name for p in restore_dir.iterdir()) == ["receipt.json", "status.json"]
        # cleanable at once on the retention screen, not after the hour an abandoned one waits
        [item] = [entry for entry in subject.app.state.first_party_exports["backups.service"].cleanup_candidates()
                  if entry["item_id"] == f"restore:{restore_id}"]
        assert item["eligible"] is True and item["reason"] == "failed_restore"
        # the same restore cannot be resumed; a fresh one stages for review; the vault is unchanged
        assert upload(subject, restore_id, bundle).status_code == 409
        fresh = begin_restore(subject, receipt)["restore_id"]
        staged = upload(subject, fresh, bundle).json()
        assert staged["state"] == "restored_review" and staged["review"]["active_vault_changed"] is False
        assert sorted(p.name for p in Path(subject.domain.data_dir).iterdir()) == active


def portable_backup(tmp_path):
    """A `portable_recovery` backup made elsewhere: its bundle, receipt and the kept identity."""

    from app.operations.backup import OneShotIdentity, create_backup
    from app.tests.test_backup import populated_vault
    from app.workers.backup_crypto import AgeRuntime

    runtime = AgeRuntime.open(AGE_ROOT)
    identity, recipient = runtime.generate()
    vault = tmp_path / "elsewhere"
    populated_vault(vault)
    out = tmp_path / "portable-out"
    out.mkdir()
    outcome = create_backup(vault, out, runtime=runtime, key_mode="portable_recovery", server_release="1.0.0",
                            recipient=recipient, recovery_identity=OneShotIdentity(identity))
    assert outcome.state == "ready", outcome.failure
    return outcome.ciphertext_path.read_bytes(), outcome.receipt, identity.strip(), runtime


def begin_restore(subject, receipt):
    begun = post(subject, "/restores", {"schema_version": "backup-restore-v1", "request_id": str(uuid4()),
                                        "receipt": receipt})
    assert begun.status_code == 200, begun.text
    return begun.json()


def test_a_portable_receipt_begins_but_never_stages_without_the_kept_identity(tmp_path):
    with owner_app(tmp_path) as subject:
        service = subject.app.state.first_party_exports["backups.service"]
        service._client = object()  # attached; nothing below reaches it
        receipt = {"backup_id": str(uuid4()), "ciphertext_sha256": "0" * 64, "ciphertext_size": 10,
                   "encryption_profile_ref": "age-x25519-v1", "key_mode": "portable_recovery"}
        begun = begin_restore(subject, receipt)
        assert begun["state"] == "awaiting_bundle" and begun["key_mode"] == "portable_recovery"
        restore_id = begun["restore_id"]
        # the plain bundle route takes no identity: a portable restore refuses it
        assert upload(subject, restore_id, b"age-encryption.org/v1\n").status_code == 400
        # a malformed identity line refuses before the worker is asked
        for body in (b"no line break at all", b"\nage-encryption.org/v1\n", b"NOT-AN-AGE-KEY\nage"):
            refused = subject.client.post(path(subject, f"/restores/{restore_id}/portable-bundle"), content=body,
                                          headers={**headers(subject.profile, subject.csrf),
                                                   "Content-Type": "application/octet-stream"})
            assert refused.status_code == 400, body
            assert b"NOT-AN-AGE-KEY" not in refused.content
        assert get(subject, f"/restores/{restore_id}").json()["state"] == "awaiting_bundle"


@needs_age
def test_portable_recovery_restores_once_with_the_kept_identity_and_stores_none_of_it(tmp_path):
    bundle, receipt, identity, runtime = portable_backup(tmp_path)
    with owner_app(tmp_path) as subject, with_worker(tmp_path, subject):
        # a wrong identity: the worker cannot decrypt; nothing is staged
        wrong, _ = runtime.generate()
        first = begin_restore(subject, receipt)["restore_id"]
        failed = subject.client.post(path(subject, f"/restores/{first}/portable-bundle"),
                                     content=wrong.strip() + b"\n" + bundle,
                                     headers={**headers(subject.profile, subject.csrf),
                                              "Content-Type": "application/octet-stream"})
        assert failed.status_code == 200 and failed.json()["state"] == "failed"
        assert failed.json()["failure_code"] == "restore_failed"
        assert not (Path(subject.domain.data_dir) / "restores" / first / "staged").exists()
        # the kept identity: staged for review, blocked, the active vault unchanged
        second = begin_restore(subject, receipt)["restore_id"]
        staged = subject.client.post(path(subject, f"/restores/{second}/portable-bundle"),
                                     content=identity + b"\n" + bundle,
                                     headers={**headers(subject.profile, subject.csrf),
                                              "Content-Type": "application/octet-stream"})
        assert staged.status_code == 200, staged.text
        view = staged.json()
        assert view["state"] == "restored_review" and view["key_mode"] == "portable_recovery"
        assert view["review"]["dispatch"] == "blocked" and view["review"]["active_vault_changed"] is False
        assert view["review"]["backup_id"] == receipt["backup_id"]
        # one bundle per restore: the identity is never taken twice
        again = subject.client.post(path(subject, f"/restores/{second}/portable-bundle"),
                                    content=identity + b"\n" + bundle,
                                    headers={**headers(subject.profile, subject.csrf),
                                             "Content-Type": "application/octet-stream"})
        assert again.status_code == 409
        # the identity is nowhere: not in a response, not in any file this instance wrote
        for response in (failed, staged, again, get(subject)):
            assert identity not in response.content
        for item in Path(subject.domain.data_dir).rglob("*"):
            if item.is_file():
                assert identity not in item.read_bytes(), item
        # an instance-key restore never takes an identity
        instance = confirm(subject, preview(subject).json()).json()["receipt"]
        other = begin_restore(subject, instance)["restore_id"]
        mine = get(subject, f"/{instance['backup_id']}/ciphertext").content
        refused = subject.client.post(path(subject, f"/restores/{other}/portable-bundle"),
                                      content=identity + b"\n" + mine,
                                      headers={**headers(subject.profile, subject.csrf),
                                               "Content-Type": "application/octet-stream"})
        assert refused.status_code == 400
