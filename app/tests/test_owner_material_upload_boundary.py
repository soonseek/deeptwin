"""Real ASGI receive admission: authentication, deadlines, disconnect and commit cancellation."""
import asyncio
import base64
import json
import threading

import pytest

from app.services.owner_material_upload_lock import UploadLock
from app.services.works import WorkServiceError
from app.tests.test_owner_material_intake import material_work, metadata, upload
from app.tests.test_web_owner_integration import headers
from app.tests.test_works_api import owner_app


def scope_for(subject, work, meta, extras=()):
    path = subject.path + "/" + work["work_id"] + "/sources"
    auth = subject.app.state.owner_authority
    encoded = base64.urlsafe_b64encode(json.dumps(meta, ensure_ascii=False).encode()).rstrip(b"=")
    return {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
            "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"",
            "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 4193),
            "headers": [(b"host", subject.profile.http_origin.split("://")[1].encode()),
                (b"origin", subject.profile.http_origin.encode()), (b"sec-fetch-site", b"same-origin"),
                (b"cookie", f"{auth.cookie_name}={subject.client.cookies[auth.cookie_name]}".encode()),
                (b"x-deeptwin-csrf", subject.csrf.encode()), (b"content-type", b"application/octet-stream"),
                (b"x-deeptwin-source-metadata", encoded), *extras]}


async def invoke(subject, scope, receive):
    sent = []
    async def send(message):
        sent.append(message)
    await subject.app(scope, receive, send)
    return sent


@pytest.mark.parametrize("change", ["cookie", "csrf", "metadata_duplicate", "length_duplicate", "encoded", "length_mismatch"])
def test_bad_upload_is_rejected_before_receiving_bytes(tmp_path, change):
    with owner_app(tmp_path) as subject:
        work = material_work(subject).json()
        scope = scope_for(subject, work, metadata())
        if change in {"cookie", "csrf"}:
            key = b"cookie" if change == "cookie" else b"x-deeptwin-csrf"
            scope["headers"] = [(k, v) for k, v in scope["headers"] if k != key]
        elif change == "metadata_duplicate":
            scope["headers"].append((b"X-DeepTwin-Source-Metadata", b"duplicate"))
        elif change == "length_duplicate":
            scope["headers"].extend([(b"content-length", b"8"), (b"Content-Length", b"8")])
        elif change == "encoded":
            scope["headers"].append((b"content-encoding", b"gzip"))
        else:
            scope["headers"].append((b"content-length", b"999"))
        async def forbidden():
            pytest.fail("rejected request consumed original bytes")
        sent = asyncio.run(invoke(subject, scope, forbidden))
        assert sent[0]["status"] in {400, 401, 403}


@pytest.mark.parametrize("case,status", [("overflow", 413), ("short", 400), ("digest", 400), ("slow", 503), ("disconnect", None)])
def test_actual_receive_bounds_and_deadline_release_lock(tmp_path, monkeypatch, case, status):
    from app.api import owner_material_upload
    monkeypatch.setattr(owner_material_upload, "RECEIVE_SECONDS", .04)
    with owner_app(tmp_path) as subject:
        work = material_work(subject).json()
        scope = scope_for(subject, work, metadata())
        async def receive():
            if case == "slow":
                await asyncio.sleep(.03)
                return {"type": "http.request", "body": b"", "more_body": True}
            if case == "disconnect":
                return {"type": "http.disconnect"}
            body = {"overflow": b"x" * 9, "short": b"x", "digest": b"x" * 8}[case]
            return {"type": "http.request", "body": body}
        if case == "disconnect":
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(invoke(subject, scope, receive))
        else:
            sent = asyncio.run(invoke(subject, scope, receive))
            assert sent[0]["status"] == status
        UploadLock(subject.domain.data_dir).close()
        assert subject.client.get(subject.path + "/" + work["work_id"], headers=headers(subject.profile)).json()["revision"] == 1


def test_revoked_session_during_receive_never_publishes(tmp_path):
    with owner_app(tmp_path) as subject:
        work = material_work(subject).json()
        scope = scope_for(subject, work, metadata())
        async def receive():
            from uuid import uuid4
            result = await asyncio.to_thread(subject.client.post, subject.profile.base_path + "session/logout",
                json={"command_id": str(uuid4())}, headers=headers(subject.profile, subject.csrf))
            assert result.status_code == 200
            return {"type": "http.request", "body": b"original"}
        sent = asyncio.run(invoke(subject, scope, receive))
        assert sent[0]["status"] == 401
        with subject.domain._connection() as db:
            assert db.execute("SELECT count(*) FROM domain_blobs").fetchone()[0] == 0


def test_cancelled_http_keeps_lock_until_real_publication_and_receipt_finish(tmp_path, monkeypatch):
    from app.domain.store import DomainStore
    with owner_app(tmp_path) as subject:
        work = material_work(subject).json()
        meta = metadata()
        started, release = threading.Event(), threading.Event()
        original = DomainStore.put_blob
        def delayed(self, *args, **kwargs):
            started.set()
            assert release.wait(5), "finite publication release expired"
            return original(self, *args, **kwargs)
        monkeypatch.setattr(DomainStore, "put_blob", delayed)
        async def exercise():
            async def receive():
                return {"type": "http.request", "body": b"original"}
            task = asyncio.create_task(invoke(subject, scope_for(subject, work, meta), receive))
            assert await asyncio.to_thread(started.wait, 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(WorkServiceError, match="capacity"):
                UploadLock(subject.domain.data_dir)
            receipt = await asyncio.to_thread(subject.client.get, subject.path + "/commands/" + meta["command_id"], headers=headers(subject.profile))
            assert receipt.status_code == 404  # not a rollback: publication still owns the command
            release.set()
            for _ in range(100):
                result = await asyncio.to_thread(subject.client.get, subject.path + "/commands/" + meta["command_id"], headers=headers(subject.profile))
                if result.status_code == 200:
                    break
                await asyncio.sleep(.02)
            assert result.status_code == 200 and result.json()["revision"] == 2
            await asyncio.sleep(.02)
            UploadLock(subject.domain.data_dir).close()
        try:
            asyncio.run(exercise())
        finally:
            release.set()
        assert upload(subject, work, meta=meta).status_code == 201


def test_text_revision_during_receive_wins_cas_and_upload_cannot_overwrite(tmp_path):
    from uuid import uuid4

    from app.tests.test_owner_material_intake import events
    from app.tests.test_works_api import post
    with owner_app(tmp_path) as subject:
        work = material_work(subject, "before").json()
        meta = metadata()
        async def receive():
            revised = await asyncio.to_thread(post, subject, {"schema_version": "work-revise-command-v2",
                "command_id": str(uuid4()), "expected_revision": 1, "text": "other tab"},
                subject.path + "/" + work["work_id"] + "/revisions")
            assert revised.status_code == 201
            return {"type": "http.request", "body": b"original"}
        sent = asyncio.run(invoke(subject, scope_for(subject, work, meta), receive))
        assert sent[0]["status"] == 409
        latest = subject.client.get(subject.path + "/" + work["work_id"], headers=headers(subject.profile)).json()
        assert latest["revision"] == 2 and latest["text"] == "other tab" and latest["source_refs"] == []
        assert not any(kind == "source.stored" for kind, _ in events(subject))


def test_lock_contention_is_immediate429_with_retry_after_and_no_body_read(tmp_path):
    with owner_app(tmp_path) as subject:
        work = material_work(subject).json()
        lease = UploadLock(subject.domain.data_dir)
        async def forbidden():
            pytest.fail("contended upload consumed original bytes")
        try:
            sent = asyncio.run(invoke(subject, scope_for(subject, work, metadata()), forbidden))
            assert sent[0]["status"] == 429
            assert dict(sent[0]["headers"])[b"retry-after"] == b"1"
        finally:
            lease.close()


@pytest.mark.parametrize("case", ["json_duplicate", "padded", "oversized", "nested", "duplicate_encoding"])
def test_ambiguous_or_unbounded_metadata_never_reaches_receive(tmp_path, case):
    with owner_app(tmp_path) as subject:
        work = material_work(subject).json()
        meta = metadata()
        scope = scope_for(subject, work, meta)
        if case == "duplicate_encoding":
            scope["headers"].extend([(b"content-encoding", b"gzip"), (b"Content-Encoding", b"gzip")])
        else:
            raw = json.dumps(meta)
            if case == "json_duplicate":
                raw = raw[:-1] + ', "size": 8}'
            elif case == "nested":
                raw = json.dumps({**meta, "name": {"nested": {"value": "bad"}}})
            encoded = base64.urlsafe_b64encode(raw.encode()).rstrip(b"=")
            if case == "padded":
                encoded += b"="
            elif case == "oversized":
                encoded = b"a" * 2049
            scope["headers"] = [(k, encoded if k == b"x-deeptwin-source-metadata" else v) for k, v in scope["headers"]]
        async def forbidden():
            pytest.fail("invalid metadata consumed original bytes")
        assert asyncio.run(invoke(subject, scope, forbidden))[0]["status"] == 400
