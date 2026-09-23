"""T045: what a run produced, read by the owner through the supported server.

A run's artifacts are exactly the registered blobs its accepted result names
(a result record of kind `artifact` carrying an `artifacts` list, as the
attempt transports seal them). The owner lists them, reads one original whole
or as one bounded byte range, and asks for a derived preview: bounded text,
JSON and CSV previews carry their own digest, fidelity note and disclosed
coverage; images are left to the browser; PDF/DOCX are disclosed as needing
the artifact codec worker and are never parsed in this process.
"""

import json
from hashlib import sha256
from uuid import uuid4

from app.domain.schemas import ImmutableRecord
from app.services.run_artifacts import (
    PREVIEW_TABLE_ROWS,
    PREVIEW_TEXT_BYTES,
    artifact_identity,
)
from app.tests.test_graph_execution import linear_graph
from app.tests.test_runs_api import Executor, command, graph_record, owner_app, post
from app.tests.test_web_owner_integration import headers

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
       b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
       b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def sealed_result(subject, outputs):
    """A result record sealed as the transports seal one: blobs registered first."""

    domain = subject.domain
    roots = domain.roots()
    artifacts = []
    for index, (role, media, data) in enumerate(outputs):
        blob = domain.put_blob(data, purpose="operational")
        artifacts.append({"ordinal": index, "role": role, "media_type": media,
                          "blob": blob.as_dict()})
    record = ImmutableRecord.create(
        kind="artifact", id=str(uuid4()), version=1,
        created_at_utc="2026-09-23T00:00:00.000000Z", actor_ref=roots.actor, parent_refs=(),
        purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        content={"schema_version": "fixture-output-v1", "output": {}, "artifacts": artifacts},
    )
    domain.put(record)
    return record.ref


def started(subject, executor, outputs):
    executor.result = sealed_result(subject, outputs)
    created = post(subject, command(subject, graph_record(subject, linear_graph())))
    assert created.status_code == 201, created.text
    return created.json()["run_id"], executor.result


def get(subject, path, **extra):
    return subject.client.get(subject.path + path, headers={**headers(subject.profile), **extra})


def test_the_owner_lists_a_runs_artifacts_and_reads_each_original(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        outputs = [("report", "text/plain", "보고서 본문\n".encode()),
                   ("chart", "image/png", PNG)]
        run_id, ref = started(subject, executor, outputs)
        listing = get(subject, f"/{run_id}/artifacts")
        assert listing.status_code == 200, listing.text
        items = listing.json()["artifacts"]
        # every node visit returned the same result here: its artifacts list once
        assert [item["ordinal"] for item in items] == [0, 1]
        first = items[0]
        assert first["artifact_id"] == artifact_identity(ref, 0)
        assert first["declared_media_type"] == "text/plain" and first["availability"] == "available"
        assert first["sha256"] == sha256(outputs[0][2]).hexdigest()
        assert first["node_id"] in {"intake", "writer", "publish"}
        one = get(subject, f"/{run_id}/artifacts/{first['artifact_id']}")
        assert one.status_code == 200 and one.json()["role"] == "report"
        body = get(subject, f"/{run_id}/artifacts/{first['artifact_id']}/content")
        assert body.status_code == 200 and body.content == outputs[0][2]
        # never served under a type the browser would render or execute
        assert body.headers["content-type"] == "application/octet-stream"
        assert body.headers["content-disposition"].startswith("attachment")
        assert body.headers["x-content-type-options"] == "nosniff"
        image = get(subject, f"/{run_id}/artifacts/{artifact_identity(ref, 1)}/content")
        assert image.headers["content-type"] == "image/png" and image.content == PNG


def test_a_byte_range_is_served_exactly_and_bounded(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        data = bytes(range(256)) * 16
        run_id, ref = started(subject, executor, [("blob", "application/octet-stream", data)])
        path = f"/{run_id}/artifacts/{artifact_identity(ref, 0)}/content"
        part = get(subject, path, Range="bytes=10-19")
        assert part.status_code == 206 and part.content == data[10:20]
        assert part.headers["content-range"] == f"bytes 10-19/{len(data)}"
        tail = get(subject, path, Range="bytes=4090-")
        assert tail.status_code == 206 and tail.content == data[4090:]
        assert get(subject, path, Range="bytes=9999-").status_code == 416
        assert get(subject, path, Range="bytes=1-2,4-5").status_code == 400
        assert get(subject, path, Range="items=1-2").status_code == 400


def test_text_json_and_csv_previews_are_derived_and_disclose_coverage(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        long_text = ("가" * (PREVIEW_TEXT_BYTES // 3 + 10)).encode()
        rows = "\n".join(f"{i},=cmd|' /C calc'!A0" for i in range(PREVIEW_TABLE_ROWS + 5))
        outputs = [("note", "text/markdown", b"<script>alert(1)</script>\n# title"),
                   ("data", "application/json", json.dumps({"b": [1, 2], "a": "x"}).encode()),
                   ("table", "text/csv", rows.encode()),
                   ("long", "text/plain", long_text)]
        run_id, ref = started(subject, executor, outputs)

        def preview(ordinal):
            response = get(subject, f"/{run_id}/artifacts/{artifact_identity(ref, ordinal)}/preview")
            assert response.status_code == 200, response.text
            return response.json()["preview"]

        note = preview(0)
        assert note["kind"] == "text" and note["derived"] is True
        assert note["body"]["text"] == "<script>alert(1)</script>\n# title"  # data, never markup
        assert note["coverage"] == {"original_bytes": len(outputs[0][2]),
                                    "covered": [[0, len(outputs[0][2])]], "omissions": []}
        encoded = json.dumps(note["body"], ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()
        assert note["sha256"] == sha256(encoded).hexdigest()  # the preview's own digest
        data = preview(1)
        assert data["kind"] == "json" and json.loads(data["body"]["text"]) == {"b": [1, 2], "a": "x"}
        table = preview(2)
        assert table["kind"] == "table" and len(table["body"]["rows"]) == PREVIEW_TABLE_ROWS
        assert table["body"]["truncated"] is True
        assert table["body"]["rows"][0] == ["0", "=cmd|' /C calc'!A0"]  # never evaluated
        long = preview(3)
        shown = long["coverage"]["covered"][0][1]
        assert shown <= PREVIEW_TEXT_BYTES and long["coverage"]["omissions"] == [[shown, len(long_text)]]
        assert long["body"]["text"] == long_text[:shown].decode()  # cut on a character boundary


def test_images_documents_and_unknown_bytes_are_disclosed_not_parsed(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        outputs = [("chart", "image/png", PNG),
                   ("report", "application/pdf", b"%PDF-1.7\n/OpenAction <</JS (x)>>"),
                   ("draft", ("application/vnd.openxmlformats-officedocument"
                              ".wordprocessingml.document"), b"PK\x03\x04garbage"),
                   ("raw", "application/octet-stream", b"\x00\xff\x00\xfe"),
                   # declared as an image, but the bytes are HTML: the bytes decide
                   ("fake", "image/png", b"<html><script>alert(1)</script></html>")]
        run_id, ref = started(subject, executor, outputs)

        def preview(ordinal):
            return get(subject, f"/{run_id}/artifacts/{artifact_identity(ref, ordinal)}/preview"
                       ).json()["preview"]

        assert preview(0)["kind"] == "image" and preview(0)["body"]["media_type"] == "image/png"
        for ordinal, fmt in ((1, "pdf"), (2, "zip_container")):
            disclosed = preview(ordinal)
            assert disclosed["kind"] == "codec_required" and disclosed["body"]["format"] == fmt
            assert disclosed["coverage"]["covered"] == []
        assert preview(3)["kind"] == "unsupported"
        assert preview(4)["kind"] == "text"  # shown as text, never as an image or a page
        fake = get(subject, f"/{run_id}/artifacts/{artifact_identity(ref, 4)}/content")
        assert fake.headers["content-type"] == "application/octet-stream"


def test_vanished_bytes_fail_closed_and_foreign_ids_are_not_found(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        run_id, ref = started(subject, executor, [("report", "text/plain", b"hello")])
        artifact = artifact_identity(ref, 0)
        assert get(subject, f"/{run_id}/artifacts/{uuid4()}").status_code == 404
        assert get(subject, f"/{uuid4()}/artifacts").status_code == 404
        assert get(subject, f"/{run_id}/artifacts/not-a-uuid").status_code == 400
        assert get(subject, f"/{run_id}/artifacts/{artifact}/raw").status_code == 404
        # the registered content file disappears from the store: the store verifies
        # every blob a record names, so nothing is listed as if it were still there
        stored = [path for path in (tmp_path / "data").rglob("*")
                  if path.is_file() and path.read_bytes() == b"hello"]
        assert stored
        for path in stored:
            path.unlink()
        for suffix in ("", f"/{artifact}", f"/{artifact}/content", f"/{artifact}/preview"):
            assert get(subject, f"/{run_id}/artifacts{suffix}").status_code == 503


def test_artifact_reads_require_the_owner_session(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        run_id, ref = started(subject, executor, [("report", "text/plain", b"hello")])
        subject.client.cookies.clear()
        for suffix in ("", f"/{artifact_identity(ref, 0)}", f"/{artifact_identity(ref, 0)}/content",
                       f"/{artifact_identity(ref, 0)}/preview"):
            assert get(subject, f"/{run_id}/artifacts{suffix}").status_code == 401
