"""T073: what this instance keeps, and the owner's explicit cleanup (`retention-v1`).

`GET /api/v1/retention` states per category what is kept, for how long, what is eligible
for owner-initiated cleanup and what is never deleted and why, from what the server
actually holds. A cleanup is a two-step human act mirroring source deletion: a preview
computed by the server (exact items, bytes, what goes, what stays, what it cannot
reach) with its digest, then the cleanup with `confirmed: true` and that exact digest,
recomputed under the backup lock. Each removed item leaves a tombstone, the core
`retention.deleted` event is recorded, a cleanup receipt is kept, and core records stay
readable. The newest backup, core records, tombstones and originals are never offered.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from app.tests.test_backups_api import (
    begin_restore,
    confirm,
    get,
    needs_age,
    preview,
    upload,
    with_worker,
)
from app.tests.test_web_owner_integration import headers
from app.tests.test_works_api import create, owner_app


def rpath(subject, tail=""):
    return subject.profile.base_path + "api/v1/retention" + tail


def rget(subject):
    return subject.client.get(rpath(subject), headers=headers(subject.profile))


def rpost(subject, tail, body):
    return subject.client.post(rpath(subject, tail), json=body, headers=headers(subject.profile, subject.csrf))


def shown(subject, item_ids, reason="user_requested", request_id=None):
    return rpost(subject, "/cleanup/preview", {"schema_version": "retention-cleanup-preview-v1",
                                               "request_id": request_id or str(uuid4()),
                                               "item_ids": item_ids, "reason_code": reason})


def clean(subject, view, **changes):
    body = {"schema_version": "retention-cleanup-v1", "request_id": view["request_id"],
            "item_ids": [item["item_id"] for item in view["items"]], "reason_code": view["reason_code"],
            "preview_sha256": view["preview_sha256"], "confirmed": True, **changes}
    return rpost(subject, "/cleanup", body)


def categories(state):
    return {entry["category"]: entry for entry in state["categories"]}


def test_the_state_says_what_is_kept_and_nothing_is_eligible_on_a_fresh_instance(tmp_path):
    with owner_app(tmp_path) as subject:
        work = create(subject, text="보존 상태를 볼 작업").json()
        response = rget(subject)
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["policy"]["core_mode"] == "manual_only"
        assert state["policy"]["automatic_deletion"] == "none"
        assert state["policy"]["policy_ref"]["kind"] == "retention_policy"
        by = categories(state)
        assert set(by) == {"core_records", "deletion_tombstones", "originals", "backups", "staged_restores",
                           "regenerable_caches", "raw_audio"}
        core = by["core_records"]
        assert core["kept"] == "forever" and core["automatic_deletion"] == "never"
        assert core["owner_cleanup"] == "not_offered" and core["reason"] == "append_only_history"
        assert core["count"] > 0 and core["events"] > 0
        assert by["deletion_tombstones"]["owner_cleanup"] == "not_offered"
        assert by["originals"]["owner_cleanup"] == "work_screen"
        assert by["backups"]["automatic_deletion"] == "never" and by["backups"]["count"] == 0
        assert by["regenerable_caches"]["kept"] == "not_stored"
        assert by["raw_audio"]["reason"] == "ephemeral_only"
        assert all(entry["automatic_deletion"] == "never" for entry in state["categories"])
        assert state["items"] == [] and state["cleanups"] == []
        assert "보존 상태를 볼" not in response.text  # counts, never content
        # an unknown or kept item is never cleaned
        missing = shown(subject, [f"backup:{uuid4()}"])
        assert missing.status_code == 404
        assert subject.client.get(subject.path + "/" + work["work_id"],
                                  headers=headers(subject.profile)).status_code == 200


def test_the_wire_is_exact_and_consent_is_never_implicit(tmp_path):
    with owner_app(tmp_path) as subject:
        item = f"backup:{uuid4()}"
        for body in ({"schema_version": "other", "request_id": str(uuid4()), "item_ids": [item],
                      "reason_code": "user_requested"},
                     {"schema_version": "retention-cleanup-preview-v1", "request_id": str(uuid4()),
                      "item_ids": [], "reason_code": "user_requested"},
                     {"schema_version": "retention-cleanup-preview-v1", "request_id": str(uuid4()),
                      "item_ids": ["core:" + str(uuid4())], "reason_code": "user_requested"},
                     {"schema_version": "retention-cleanup-preview-v1", "request_id": str(uuid4()),
                      "item_ids": [item, item], "reason_code": "user_requested"},
                     {"schema_version": "retention-cleanup-preview-v1", "request_id": str(uuid4()),
                      "item_ids": [item], "reason_code": "because"}):
            assert rpost(subject, "/cleanup/preview", body).status_code == 400, body
        unconfirmed = {"schema_version": "retention-cleanup-v1", "request_id": str(uuid4()), "item_ids": [item],
                       "reason_code": "user_requested", "preview_sha256": "0" * 64, "confirmed": False}
        assert rpost(subject, "/cleanup", unconfirmed).status_code == 400
        assert rpost(subject, "/cleanup", {**unconfirmed, "confirmed": True, "extra": 1}).status_code == 400
        subject.client.cookies.clear()
        assert rget(subject).status_code == 401


@needs_age
def test_owner_cleanup_previews_binds_consent_tombstones_and_keeps_core_records(tmp_path):
    with owner_app(tmp_path) as subject, with_worker(tmp_path, subject):
        work = create(subject, text="정리 후에도 남을 작업").json()
        older = confirm(subject, preview(subject).json()).json()["receipt"]
        newer = confirm(subject, preview(subject).json()).json()["receipt"]
        data = bytearray(get(subject, f"/{newer['backup_id']}/ciphertext").content)
        data[len(data) // 2] ^= 0x01
        failed_id = begin_restore(subject, newer)["restore_id"]
        assert upload(subject, failed_id, bytes(data)).json()["state"] == "failed"
        staged_id = begin_restore(subject, newer)["restore_id"]
        good = get(subject, f"/{newer['backup_id']}/ciphertext").content
        assert upload(subject, staged_id, good).json()["state"] == "restored_review"
        waiting_id = begin_restore(subject, newer)["restore_id"]

        state = rget(subject).json()
        items = {item["item_id"]: item for item in state["items"]}
        assert items[f"backup:{newer['backup_id']}"]["eligible"] is False
        assert items[f"backup:{newer['backup_id']}"]["reason"] == "newest_backup_kept"
        assert items[f"backup:{older['backup_id']}"]["eligible"] is True
        assert items[f"restore:{failed_id}"]["eligible"] is True
        assert items[f"restore:{staged_id}"]["eligible"] is True and items[f"restore:{staged_id}"]["bytes"] > 0
        assert items[f"restore:{waiting_id}"]["eligible"] is False  # another tab may be mid-upload
        by = categories(state)
        assert by["backups"]["count"] == 2 and by["backups"]["eligible_count"] == 1
        assert by["staged_restores"]["eligible_count"] == 2
        records_before = by["core_records"]["count"]

        # the newest backup and a fresh restore are never offered
        assert shown(subject, [f"backup:{newer['backup_id']}"]).status_code == 409
        assert shown(subject, [f"restore:{waiting_id}"]).status_code == 409
        scope = [f"backup:{older['backup_id']}", f"restore:{failed_id}", f"restore:{staged_id}"]
        view = shown(subject, scope).json()
        assert view["item_count"] == 3
        assert view["byte_count"] == sum(items[item]["bytes"] for item in scope)
        assert "copies_already_downloaded" in view["not_reached"]
        assert "core_records" in view["never_deleted"] and "newest_backup" in view["never_deleted"]
        data_dir = Path(subject.domain.data_dir)
        assert (data_dir / "backups" / f"{older['backup_id']}.age").is_file()  # a preview removes nothing
        assert shown(subject, scope, request_id=view["request_id"]).json()["preview_sha256"] == view["preview_sha256"]
        assert clean(subject, view, confirmed=False).status_code == 400
        assert clean(subject, view, preview_sha256="0" * 64).status_code == 409

        done = clean(subject, view)
        assert done.status_code == 200, done.text
        receipt = done.json()
        assert receipt["confirmed"] is True and receipt["preview_sha256"] == view["preview_sha256"]
        assert all(item["bytes_removed"] is True for item in receipt["removed"])
        # the older ciphertext is gone; its receipt, consent and tombstone stay
        backups = data_dir / "backups"
        assert not (backups / f"{older['backup_id']}.age").exists()
        tombstone = json.loads((backups / f"{older['backup_id']}.deleted.json").read_bytes())
        assert tombstone["deletion_request_id"] == view["request_id"]
        assert tombstone["ciphertext_sha256"] == older["ciphertext_sha256"]
        assert (backups / f"{older['backup_id']}.receipt.json").is_file()
        assert (backups / f"{older['backup_id']}.consent.json").is_file()
        assert get(subject, f"/{older['backup_id']}/ciphertext").status_code == 404
        assert json.loads(get(subject, f"/{older['backup_id']}/receipt").content) == older
        assert (backups / f"{newer['backup_id']}.age").is_file()
        # the staged copy is gone; the restore's status and receipt remain as its record
        for restore_id in (failed_id, staged_id):
            left = sorted(item.name for item in (data_dir / "restores" / restore_id).iterdir())
            assert left == ["receipt.json", "status.json"]
            assert get(subject, f"/restores/{restore_id}").json()["state"] == "discarded"
        assert (data_dir / "restores" / waiting_id).is_dir()
        listed = {item["backup_id"]: item for item in get(subject).json()["backups"]}
        assert listed[older["backup_id"]]["ciphertext_state"] == "deleted"
        assert listed[newer["backup_id"]]["ciphertext_state"] == "stored"

        after = rget(subject).json()
        assert after["cleanups"][0]["request_id"] == view["request_id"]
        assert after["cleanups"][0]["item_count"] == 3
        assert categories(after)["core_records"]["count"] >= records_before  # core records stay
        assert categories(after)["backups"]["deleted_count"] == 1
        assert subject.client.get(subject.path + "/" + work["work_id"],
                                  headers=headers(subject.profile)).json()["text"] == "정리 후에도 남을 작업"
        events = subject.client.get(subject.profile.base_path + "api/v1/events",
                                    params={"limit": "100"}, headers=headers(subject.profile)).json()["events"]
        deleted = [event for event in events if event["event_type"] == "retention.deleted"]
        assert len(deleted) == 1 and deleted[0]["status"] == "succeeded"
        assert deleted[0]["public_metadata"] == {"object_count": 3, "byte_count": view["byte_count"]}
        # the same request replays its receipt; a removed item is never cleaned twice
        assert clean(subject, view).json() == receipt
        assert shown(subject, [f"backup:{older['backup_id']}"]).status_code == 404


@needs_age
def test_a_cleanup_whose_scope_changed_after_its_preview_is_refused(tmp_path):
    with owner_app(tmp_path) as subject, with_worker(tmp_path, subject):
        older = confirm(subject, preview(subject).json()).json()["receipt"]
        middle = confirm(subject, preview(subject).json()).json()["receipt"]
        view = shown(subject, [f"backup:{older['backup_id']}"]).json()
        # another cleanup takes the same item first
        other = shown(subject, [f"backup:{older['backup_id']}"]).json()
        assert clean(subject, other).status_code == 200
        assert clean(subject, view).status_code == 404
        # a newer backup makes the middle one eligible; a preview taken before it is stale
        stale = shown(subject, [f"backup:{middle['backup_id']}"])
        assert stale.status_code == 409  # still the newest: kept
        confirm(subject, preview(subject).json())
        fresh = shown(subject, [f"backup:{middle['backup_id']}"])
        assert fresh.status_code == 200
        body = fresh.json()
        assert clean(subject, {**body, "reason_code": "policy_cleanup"}).status_code == 409
        assert (Path(subject.domain.data_dir) / "backups" / f"{middle['backup_id']}.age").is_file()
