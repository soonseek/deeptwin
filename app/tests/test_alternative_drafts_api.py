"""T052 server half: the owner edits their own version of a run artifact.

Drafts are revision-safe (two screens saving from the same revision: the second
is a conflict, never an overwrite), idempotent per command, and need no reason.
A freeze turns one exact revision into an `own_alternative` against the run's
recorded boundary; the changed lines or cells are the evidence scope unless the
owner explicitly says they reviewed the whole, and what the server does not
trace is stated as observation gaps. An unchanged copy is not an alternative.
"""

from uuid import uuid4

from app.domain.refs import EntityRef
from app.services.run_artifacts import artifact_identity
from app.tests.test_run_artifacts_api import get, started
from app.tests.test_runs_api import Executor, owner_app, post

SAVE = "alternative-draft-save-v1"
FREEZE = "alternative-freeze-v1"
TEXT = "첫 줄\n둘째 줄\n셋째 줄\n".encode()
CSV = "이름,값\n가,1\n나,2\n".encode()


def drafts_path(run_id, artifact_id):
    return f"/{run_id}/artifacts/{artifact_id}/drafts"


def save(subject, run_id, artifact_id, *, draft_id=None, expected=0, command_id=None, **content):
    body = {"schema_version": SAVE, "command_id": command_id or str(uuid4()), "draft_id": draft_id,
            "expected_revision": expected, **content}
    return post(subject, body, subject.path + drafts_path(run_id, artifact_id))


def freeze(subject, run_id, artifact_id, draft_id, expected, *, whole=False, command_id=None):
    return post(subject, {"schema_version": FREEZE, "command_id": command_id or str(uuid4()),
                          "expected_revision": expected, "reviewed_whole": whole},
                subject.path + drafts_path(run_id, artifact_id) + f"/{draft_id}/freeze")


def test_text_drafts_are_revision_safe_and_idempotent(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        run_id, ref = started(subject, executor, [("report", "text/plain", TEXT)])
        artifact_id = artifact_identity(ref, 0)
        command_id = str(uuid4())
        first = save(subject, run_id, artifact_id, command_id=command_id, format="text",
                     text="첫 줄\n고친 둘째 줄\n셋째 줄\n")
        assert first.status_code == 201, first.text
        draft = first.json()
        assert draft["revision"] == 1 and draft["format"] == "text"
        # a replay of the same command is the same revision; different content is a conflict
        again = save(subject, run_id, artifact_id, command_id=command_id, format="text",
                     text="첫 줄\n고친 둘째 줄\n셋째 줄\n")
        assert again.status_code == 201 and again.json()["revision"] == 1
        reused = save(subject, run_id, artifact_id, command_id=command_id, format="text", text="다른")
        assert reused.status_code == 409
        second = save(subject, run_id, artifact_id, draft_id=draft["draft_id"], expected=1,
                      format="text", text="첫 줄\n다시 고친 둘째 줄\n셋째 줄\n")
        assert second.status_code == 201 and second.json()["revision"] == 2
        # a stale tab saving from revision 1 never overwrites revision 2
        stale = save(subject, run_id, artifact_id, draft_id=draft["draft_id"], expected=1,
                     format="text", text="낡은 화면의 내용")
        assert stale.status_code == 409 and stale.json()["code"] == "conflict"
        read = get(subject, drafts_path(run_id, artifact_id) + f"/{draft['draft_id']}")
        assert read.status_code == 200
        assert read.json()["text"] == "첫 줄\n다시 고친 둘째 줄\n셋째 줄\n"
        assert read.json()["revision"] == 2 and read.json()["frozen_revisions"] == []
        listed = get(subject, drafts_path(run_id, artifact_id)).json()
        assert listed["original"] == {"format": "text", "sha256": listed["original"]["sha256"],
                                      "media_type": "text/plain", "text": TEXT.decode()}
        assert [item["draft_id"] for item in listed["drafts"]] == [draft["draft_id"]]
        # the original is untouched
        assert get(subject, f"/{run_id}/artifacts/{artifact_id}/content").content == TEXT


def test_a_freeze_records_the_changed_lines_as_partial_evidence(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        run_id, ref = started(subject, executor, [("report", "text/plain", TEXT)])
        artifact_id = artifact_identity(ref, 0)
        draft = save(subject, run_id, artifact_id, format="text",
                     text="첫 줄\n고친 둘째 줄\n셋째 줄\n").json()
        wrong = freeze(subject, run_id, artifact_id, draft["draft_id"], 2)
        assert wrong.status_code == 409  # freeze exactly the revision the owner saw
        frozen = freeze(subject, run_id, artifact_id, draft["draft_id"], 1)
        assert frozen.status_code == 201, frozen.text
        value = frozen.json()
        assert value["coverage"] == "partial"
        assert value["selectors"] == [{"kind": "text_span", "locator": {
            "unit": "line", "start": 2, "end": 2, "operation": "replace"},
            "source_hash": ref.sha256, "alignment": "proposed"}]
        assert value["unreviewed_scope"] == f"outside_selectors:{ref.sha256}"
        assert value["impact_scope"] == "pending_investigation"
        assert value["observation_gaps"]
        record = subject.domain.get(EntityRef.from_dict(value["alternative_ref"]))
        content = record.body["content"]
        assert content["schema_version"] == "own-alternative-v1" and content["synthetic"] is False
        assert content["original_artifact_ref"] == ref.as_dict()
        assert content["alternative_artifact_ref"]["id"] == draft["draft_id"]
        read = get(subject, drafts_path(run_id, artifact_id) + f"/{draft['draft_id']}").json()
        assert read["frozen_revisions"] == [1]


def test_whole_coverage_only_when_the_owner_says_so(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        run_id, ref = started(subject, executor, [("table", "text/csv", CSV)])
        artifact_id = artifact_identity(ref, 0)
        draft = save(subject, run_id, artifact_id, format="table",
                     rows=[["이름", "값"], ["가", "10"], ["나", "2"]])
        assert draft.status_code == 201, draft.text
        draft_id = draft.json()["draft_id"]
        read = get(subject, drafts_path(run_id, artifact_id) + f"/{draft_id}").json()
        assert read["rows"] == [["이름", "값"], ["가", "10"], ["나", "2"]]
        partial = freeze(subject, run_id, artifact_id, draft_id, 1).json()
        assert partial["selectors"][0]["kind"] == "table_range"
        assert partial["selectors"][0]["locator"] == {"row": 2, "first_column": 2, "last_column": 2}
        whole = freeze(subject, run_id, artifact_id, draft_id, 1, whole=True).json()
        assert whole["coverage"] == "whole" and whole["selectors"] == []
        assert whole["unreviewed_scope"] == "none"


def test_unchanged_copies_wrong_formats_and_closed_wire_are_refused(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        run_id, ref = started(subject, executor, [("report", "text/plain", TEXT),
                                                  ("blob", "application/octet-stream", b"\x00\x01")])
        artifact_id = artifact_identity(ref, 0)
        same = save(subject, run_id, artifact_id, format="text", text=TEXT.decode()).json()
        assert freeze(subject, run_id, artifact_id, same["draft_id"], 1).status_code == 400
        assert save(subject, run_id, artifact_id, format="table", rows=[["x"]]).status_code == 400
        binary = artifact_identity(ref, 1)
        assert save(subject, run_id, binary, format="text", text="x").status_code == 400
        # a new draft starts at revision 0; an existing one must name itself
        assert save(subject, run_id, artifact_id, expected=1, format="text", text="x").status_code == 400
        both = post(subject, {"schema_version": SAVE, "command_id": str(uuid4()), "draft_id": None,
                              "expected_revision": 0, "format": "text", "text": "x", "rows": []},
                    subject.path + drafts_path(run_id, artifact_id))
        assert both.status_code == 400
        missing = get(subject, drafts_path(run_id, artifact_id) + f"/{uuid4()}")
        assert missing.status_code == 404
        big = save(subject, run_id, artifact_id, format="text", text="가" * 100_000)
        assert big.status_code == 413


# --- T053: a whole alternative file with formal selectors on the original -----------

import base64  # noqa: E402

from app.tests.test_run_artifacts_api import PNG  # noqa: E402

FILE = "alternative-file-v1"


def upload(subject, run_id, artifact_id, data, *, media="image/png", selectors=(), whole=False,
           command_id=None, name="내 버전.png"):
    return post(subject, {"schema_version": FILE, "command_id": command_id or str(uuid4()),
                          "media_type": media, "name": name,
                          "content_b64": base64.b64encode(data).decode(), "selectors": list(selectors),
                          "reviewed_whole": whole},
                subject.path + f"/{run_id}/artifacts/{artifact_id}/alternative-files")


def region(**locator):
    return {"kind": "image_region", "locator": {"x": 0, "y": 0, "width": 5000, "height": 5000, **locator}}


def test_an_image_alternative_binds_regions_with_unresolved_alignment(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        run_id, ref = started(subject, executor, [("chart", "image/png", PNG)])
        artifact_id = artifact_identity(ref, 0)
        mine = PNG + b"\x00mine"
        command_id = str(uuid4())
        done = upload(subject, run_id, artifact_id, mine, selectors=[region(x=100)], command_id=command_id)
        assert done.status_code == 201, done.text
        value = done.json()
        assert value["coverage"] == "partial"
        assert value["selectors"] == [{"kind": "image_region", "locator": {
            "x": 100, "y": 0, "width": 5000, "height": 5000}, "source_hash": ref.sha256,
            "alignment": "unresolved"}]
        assert "unresolved" in value["alignment_note"]
        stored = subject.domain.get(EntityRef.from_dict(value["file_ref"]))
        assert stored.body["content"]["alternative_file"]["media_type"] == "image/png"
        # the same command replays; different bytes under it are a conflict
        again = upload(subject, run_id, artifact_id, mine, selectors=[region(x=100)], command_id=command_id)
        assert again.status_code == 201 and again.json()["alternative_ref"] == value["alternative_ref"]
        other = upload(subject, run_id, artifact_id, mine + b"x", selectors=[region(x=100)],
                       command_id=command_id)
        assert other.status_code == 409
        whole = upload(subject, run_id, artifact_id, mine, whole=True)
        assert whole.status_code == 201 and whole.json()["coverage"] == "whole"


def test_selectors_must_fit_the_original_format_and_bounds(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        run_id, ref = started(subject, executor, [
            ("chart", "image/png", PNG), ("doc", "application/pdf", b"%PDF-1.7\n..."),
            ("data", "application/json", b'{"a": [1, 2]}'), ("blob", "application/octet-stream", b"\x01")])
        png, pdf, data, blob = (artifact_identity(ref, index) for index in range(4))
        mine = b"alternative bytes"
        for bad in ([region(x=6000)], [region(width=0)], [{"kind": "page_region", "locator": {}}],
                    [{"kind": "image_region", "locator": {"x": 0.5, "y": 0, "width": 1, "height": 1}}], []):
            assert upload(subject, run_id, png, mine, selectors=bad).status_code == 400, bad
        page = {"kind": "page_region", "locator": {"page": 2, "x": 0, "y": 0, "width": 10000, "height": 2500}}
        assert upload(subject, run_id, pdf, mine, media="application/pdf", selectors=[page]).status_code == 201
        pointer = {"kind": "structured_path", "locator": {"pointer": "/a/1"}}
        assert upload(subject, run_id, data, mine, media="application/json", selectors=[pointer]).status_code == 201
        bad_pointer = {"kind": "structured_path", "locator": {"pointer": "a~2"}}
        assert upload(subject, run_id, data, mine, media="application/json",
                      selectors=[bad_pointer]).status_code == 400
        # a format with no formal selector is answered whole, or not at all
        assert upload(subject, run_id, blob, mine, selectors=[region()]).status_code == 400
        assert upload(subject, run_id, blob, mine, whole=True).status_code == 201
        assert upload(subject, run_id, png, PNG, whole=True).status_code == 400  # the same bytes
        assert upload(subject, run_id, png, b"", whole=True).status_code == 400
        assert upload(subject, run_id, png, mine, whole=True, name="../x").status_code == 400
