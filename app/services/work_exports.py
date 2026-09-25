"""The owner's export of one work: actual-content preview, bound consent, sealed bundle
(US7, T073 server half; operations.md export flow, FR-028/029, UX-AC08).

`preview` reads what the export would ACTUALLY contain right now — every revision
of the work (raw text only when the owner explicitly asks for raw originals,
otherwise metadata only), the work's revision history, its runs (start, every stop
with its reason, the consent each ran under, the approvals recorded on it), the
owner's frozen alternatives, and the sources its revisions name — and states
every selected category this server does not collect yet as `unavailable` and
every unselected one as `not_selected`, never as an empty success. The preview
is not stored: its `preview_sha` digests the request id, the selection and every
item's exact bytes, so `confirm` recomputes it and a work that changed in between
(a new revision, run, stop or approval) refuses (`conflict`) instead of exporting
something the owner never saw. Confirmation must be explicit (`confirmed: true`) and binds
the exact digest; it seals the owner's consent, the raw-inclusion artifacts, the
manifest (through `app.operations.export`, which never carries the archive's own
hash) and the bundle, and returns the external receipt. Nothing is transmitted:
the bundle is downloaded only by the owner through `download`.

T074 additions (both inside the same preview digest and confirmation):
- `evaluation_evidence` now carries the work's design records (requests, candidates,
  verdicts AS RECORDED with the critic identities, owner derivations, design approvals),
  the lens definitions they reference and the growth rounds scoped by the environment
  this work's runs ran in (`work_export_records`), metadata only; a run's own completion
  evaluation is still stated as not collected.
- `include_source_originals` (only with `include_raw`) adds the work's attached
  originals, scanned for secrets; an attached PDF is read and, on an unconfirmed
  finding, redacted only by the isolated document worker (`work_export_sources`), and
  what cannot be scanned or safely redacted is left out with its stated reason.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from uuid import uuid4

from ..domain.public_events import EventEnvelope
from ..domain.refs import EntityRef, canonical_json, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import BlobRef, _writer
from ..operations.export import (
    EXPORT_CATEGORIES,
    ExportError,
    build_export_manifest,
    create_export_request,
    seal_export,
)
from ..workers.document_channel import DocumentCodecClient
from .export_secret_scan import findings_digest, scan_text
from .owner_auth import OwnerAuthError
from .run_approvals import _authenticate_owner, _owner_actor_ref
from .work_export_records import collect_design_records, collect_rounds, lens_view
from .work_export_sources import _Cache, assess, load_sources, materialize
from .works import PersistentWorks, WorkServiceError

__all__ = ["CONFIRM_SCHEMA", "PREVIEW_SCHEMA", "PersistentWorkExports"]

PREVIEW_SCHEMA = "work-export-preview-v1"
CONFIRM_SCHEMA = "work-export-confirm-v1"
MAX_REVISIONS = 512
APP_RELEASE = "deeptwin-dev"
RUN_MANIFEST_SCHEMA = "run-manifest-v1"
# selected categories whose records this server does not yet collect into an export
# (evaluation evidence is collected for design and growth records only; a run's own
# completion evaluation is still stated as not collected)
UNCOLLECTED = frozenset({"model_final_responses", "tool_observations",
                         "evaluation_evidence"})
# the owner's explicit choice to include attached originals (only with raw originals)
SOURCES_FIELD = "include_source_originals"
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
# the owner's explicit confirmation of the exact secret-finding set shown in a preview
ACK_FIELD = "acknowledged_findings_sha"
_HEX64 = re.compile(r"[0-9a-f]{64}")
MAX_CANARIES = 64


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (WorkServiceError, OwnerAuthError):
            raise
        except ExportError:
            raise WorkServiceError("invalid_input") from None
        except Exception:  # noqa: BLE001 - storage errors must not disclose detail
            raise WorkServiceError("unavailable") from None

    return invoke


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _selection(payload, *, confirm):
    fields = {"schema_version", "request_id", "categories", "include_raw"}
    if confirm:
        fields |= {"preview_sha", "confirmed"}
    if type(payload) is not dict or set(payload) - {ACK_FIELD, SOURCES_FIELD} != fields:
        raise WorkServiceError("invalid_input")
    sources = payload.get(SOURCES_FIELD, False)
    if type(sources) is not bool:
        raise WorkServiceError("invalid_input")
    if sources and payload.get("include_raw") is not True:
        raise WorkServiceError("invalid_input")  # attached originals are a raw inclusion
    acknowledged = payload.get(ACK_FIELD)
    if ACK_FIELD in payload and (type(acknowledged) is not str or not _HEX64.fullmatch(acknowledged)):
        raise WorkServiceError("invalid_input")
    if payload["schema_version"] != (CONFIRM_SCHEMA if confirm else PREVIEW_SCHEMA):
        raise WorkServiceError("invalid_input")
    try:
        request_id = uuid_string(payload["request_id"])
    except (TypeError, ValueError):
        raise WorkServiceError("invalid_input") from None
    categories = payload["categories"]
    if (type(categories) is not list or not 1 <= len(categories) <= len(EXPORT_CATEGORIES)
            or len(set(categories)) != len(categories)
            or any(item not in EXPORT_CATEGORIES for item in categories)):
        raise WorkServiceError("invalid_input")
    if type(payload["include_raw"]) is not bool:
        raise WorkServiceError("invalid_input")
    if payload["include_raw"] and "originals" not in categories:
        raise WorkServiceError("invalid_input")  # raw inclusion is a choice about originals
    if acknowledged is not None and not payload["include_raw"]:
        raise WorkServiceError("invalid_input")  # a finding confirmation is about raw originals
    return request_id, tuple(sorted(categories)), payload["include_raw"], acknowledged, sources


class PersistentWorkExports:
    """Owner-authenticated export of one work over the actual domain store."""

    def __init__(self, works, *, codec=None):
        if type(works) is not PersistentWorks:
            raise TypeError("Exact PersistentWorks required")
        if codec is not None and type(codec) is not DocumentCodecClient:
            raise TypeError("Exact DocumentCodecClient required")
        self._works = works
        self._domain = works._domain
        self._owner = works._owner
        self._codec = codec  # the isolated document worker; None: attached PDFs are never read
        self._cache = _Cache()

    # --- what the export actually contains ---------------------------------------

    def _revisions(self, db, roots, work_id):
        latest = self._works._latest(db, roots, work_id)
        if latest is None:
            raise WorkServiceError("not_found")
        if latest.ref.version > MAX_REVISIONS:
            raise WorkServiceError("too_large")
        return [self._works._version(db, roots, work_id, version)
                for version in range(1, latest.ref.version + 1)]

    def _alternatives(self, db, roots, work_id):
        """The owner's frozen alternatives over runs of this work, oldest first."""

        found = []
        for row in db.execute(
                "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind='own_alternative' "
                "AND instr(body, ?) > 0 ORDER BY id", (roots.genesis.id, work_id.encode())).fetchall():
            record = self._domain._load(db, EntityRef("own_alternative", row["id"], row["version"],
                                                      row["sha256"]), roots)[0]
            content = record.body["content"]
            if content.get("boundary_work_revision_ref", {}).get("id") == work_id:
                found.append(record)
        if len(found) > MAX_REVISIONS:
            raise WorkServiceError("too_large")
        return sorted(found, key=lambda record: (record.body["created_at_utc"], record.ref.id))

    def _manifests(self, db, roots, work_id):
        manifests = []
        for row in db.execute(
                "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind='run_manifest' "
                "AND version=1 AND instr(body, ?) > 0 ORDER BY id",
                (roots.genesis.id, work_id.encode())).fetchall():
            record = self._domain._load(db, EntityRef("run_manifest", row["id"], row["version"],
                                                      row["sha256"]), roots)[0]
            content = record.body["content"]
            if (content.get("schema_version") == RUN_MANIFEST_SCHEMA
                    and content["inputs"]["work_revision_ref"]["id"] == work_id):
                manifests.append(record)
        if len(manifests) > MAX_REVISIONS:
            raise WorkServiceError("too_large")
        return manifests

    def _environments(self, db, roots, work_id):
        """The exact environments this work's runs ran in (the growth-round scope)."""

        found = {}
        for record in self._manifests(db, roots, work_id):
            ref = record.body["content"]["inputs"]["environment_ref"]
            found[canonical_json(ref)] = ref
        return [found[key] for key in sorted(found)]

    def _runs(self, db, roots, work_id):
        """The owner's runs of this work, oldest first: each run's start, every
        `run.stopped` with its reason (a failed execution is `infrastructure_failure`),
        the consent it ran under and the action approvals recorded on it. Identities,
        times and closed codes only — never graph, artifact or model content."""

        manifests = self._manifests(db, roots, work_id)
        if not manifests:
            return []
        stops = {}
        for row in db.execute(
                "SELECT envelope FROM api_event_envelopes WHERE vault_id=? AND event_type='run.stopped' "
                "ORDER BY sequence", (roots.genesis.id,)).fetchall():
            envelope = EventEnvelope.from_bytes(bytes(row["envelope"]))
            stops.setdefault(envelope.correlation_id, []).append(envelope)
        runs = []
        for record in manifests:
            content = record.body["content"]
            consent_ref = EntityRef.from_dict(content["inputs"]["consent_ref"])
            consent = self._domain._load(db, consent_ref, roots)[0]
            revoked = None
            for row in db.execute(
                    "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind='decision_record' "
                    "AND instr(body, ?) > 0", (roots.genesis.id, consent_ref.id.encode())).fetchall():
                decision = self._domain._load(db, EntityRef("decision_record", row["id"], row["version"],
                                                            row["sha256"]), roots)[0].body["content"]
                if decision.get("consent_ref", {}).get("id") == consent_ref.id:
                    revoked = decision["revoked_at_utc"]
            approvals = []
            for row in db.execute(
                    "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind='action_approval' "
                    "AND instr(body, ?) > 0 ORDER BY id",
                    (roots.genesis.id, content["run_id"].encode())).fetchall():
                approval = self._domain._load(db, EntityRef("action_approval", row["id"], row["version"],
                                                            row["sha256"]), roots)[0].body["content"]
                if approval.get("run_id") == content["run_id"]:
                    approvals.append({name: approval[name] for name in (
                        "node_id", "approval_scope", "decision", "decided_at_utc")})
            runs.append({
                "run_id": content["run_id"], "started_at_utc": record.body["created_at_utc"],
                "work_revision": content["inputs"]["work_revision_ref"]["version"],
                "stops": [{"reason_code": event.public_metadata["reason_code"],
                           "observed_at_utc": event.observed_at_utc}
                          for event in stops.get(content["command_id"], ())
                          if event.sequence > content["event_sequence"]],
                "consent": {"consent_id": consent_ref.id,
                            "decided_at_utc": consent.body["content"].get("decided_at_utc"),
                            "revoked_at_utc": revoked},
                "approvals": sorted(approvals, key=lambda item: (item["decided_at_utc"], item["node_id"])),
            })
        return sorted(runs, key=lambda run: (run["started_at_utc"], run["run_id"]))

    @staticmethod
    def _collect(revisions, categories, include_raw, alternatives=(), runs=(), withheld=frozenset(),
                 sources=(), evaluation=None):
        """(items with their exact bytes, missing entries), deterministically ordered.
        A revision in `withheld` (a raw original with an unconfirmed secret finding) is
        exported as metadata only, and the omission is stated. `sources` are the attached
        originals' (item, missing) pairs when the owner asked for them; `evaluation` the
        design/lens/round records of this work (work_export_records)."""

        items, missing = [], []

        def add(category, path, media_type, data, *, mode, label, source_ref=None):
            items.append({"category": category, "relative_path": path, "media_type": media_type,
                          "data": data, "content_mode": mode, "label": label, "source_ref": source_ref})

        if "originals" in categories:
            for record in revisions:
                content = record.body["content"]
                number = record.ref.version
                if include_raw and number not in withheld:
                    add("originals", f"originals/revision-{number}.txt", "text/plain; charset=utf-8",
                        content["text"].encode("utf-8"), mode="raw", label=f"작업 설명 {number}판 원문")
                else:
                    add("originals", f"originals/revision-{number}.json", "application/json",
                        _json({"revision": number, "created_at_utc": record.body["created_at_utc"],
                               "characters": len(content["text"]), "text": "원문 미포함"}),
                        mode="metadata_only", label=(
                            f"작업 설명 {number}판 (비밀로 보이는 값이 있어 원문 제외)" if number in withheld
                            else f"작업 설명 {number}판 (원문 제외)"))
            if withheld:
                missing.append({"category": "originals", "reason": "redacted",
                                "claim": f"비밀로 보이는 값이 있어 작업 설명 원문 {len(withheld)}개를 제외했다."})
            for item, entry in sources:
                if item is not None:
                    add(item["category"], item["relative_path"], item["media_type"], item["data"],
                        mode=item["content_mode"], label=item["label"], source_ref=item["source_ref"])
                if entry is not None:
                    missing.append(entry)
        if "events" in categories:
            add("events", "events/work-history.json", "application/json", _json([
                {"revision": record.ref.version, "created_at_utc": record.body["created_at_utc"],
                 "input_origin": record.body["content"].get("input_origin", "owner_text"),
                 "source_count": len(record.body["content"].get("source_refs", []))}
                for record in revisions]), mode="metadata_only", label="작업 개정 기록")
            if runs:
                failed = sum(any(stop["reason_code"] == "infrastructure_failure" for stop in run["stops"])
                             for run in runs)
                decided = sum(len(run["approvals"]) for run in runs)
                add("events", "events/runs.json", "application/json", _json(list(runs)),
                    mode="metadata_only",
                    label=f"실행 {len(runs)}개 (실패 {failed}개) · 실행 동의 {len(runs)}개 · 승인 결정 {decided}개")
        if "artifacts_metadata" in categories:
            sources = sorted({json.dumps(ref, sort_keys=True) for record in revisions
                              for ref in record.body["content"].get("source_refs", [])})
            if sources:
                add("artifacts_metadata", "artifacts/sources.json", "application/json",
                    _json([{"kind": json.loads(item)["kind"], "id": json.loads(item)["id"],
                            "version": json.loads(item)["version"]} for item in sources]),
                    mode="metadata_only", label=f"첨부 자료 {len(sources)}개의 목록")
            else:
                missing.append({"category": "artifacts_metadata", "reason": "not_recorded",
                                "claim": "이 작업에는 첨부 자료가 없다."})
        if "alternatives" in categories:
            if alternatives:
                add("alternatives", "alternatives/own-versions.json", "application/json", _json([
                    {"alternative_id": record.ref.id, "created_at_utc": record.body["created_at_utc"],
                     "run_id": record.body["content"]["run_id"],
                     "original_artifact_id": record.body["content"]["original_artifact_id"],
                     "coverage": record.body["content"]["coverage"],
                     "selectors": record.body["content"]["selectors"],
                     "unreviewed_scope": record.body["content"]["unreviewed_scope"],
                     "content": "내 버전 내용 미포함"}
                    for record in alternatives]), mode="metadata_only",
                    label=f"내 버전 {len(alternatives)}개 (범위·선택 영역만, 내용 제외)")
            else:
                missing.append({"category": "alternatives", "reason": "not_recorded",
                                "claim": "이 작업의 실행에 대해 고정한 내 버전이 없다."})
        collected_evaluation = False
        if "evaluation_evidence" in categories and evaluation is not None:
            requests, lenses, rounds, experiments, scope = (
                evaluation["requests"], evaluation["lenses"], evaluation["rounds"], evaluation["experiments"],
                evaluation["scope"])
            if requests:
                candidates = sum(len(item["candidates"]) for item in requests)
                verdicts = sum(item["verdict"] is not None for request in requests for item in request["candidates"])
                derivations = sum(len(item["derivations"]) for item in requests)
                approvals = sum(len(item["design_approvals"]) for item in requests)
                critics = sorted({model for request in requests for item in request["candidates"]
                                  if item["verdict"] for model in item["verdict"]["critic"]["model_ids"]})
                add("evaluation_evidence", "evaluation/design-requests.json", "application/json", _json({
                    "scope_rule": ("설계 요청의 작업 모델이 이 작업의 수정본에서 만든 작업 모델일 때만 포함한다."),
                    "verdict_basis": ("기록된 평가를 기록된 그대로 옮긴다. 평가자 이름은 평가 호출 기록에서 읽고, "
                                      "내보내기는 평가를 다시 검증하지 않는다."),
                    "requests": requests}), mode="metadata_only",
                    label=(f"설계 요청 {len(requests)}개 · 후보 {candidates}개 · 기록된 평가 {verdicts}개"
                           f"(평가자 {', '.join(critics) or '없음'}, 다시 검증하지 않음) · 파생 {derivations}개"
                           f" · 설계 승인 {approvals}개"))
                collected_evaluation = True
            if lenses:
                add("evaluation_evidence", "evaluation/lenses.json", "application/json", _json(lenses),
                    mode="metadata_only", label=f"참조한 렌즈 정의 {len(lenses)}개 (판본·검토 상태)")
                collected_evaluation = True
            if rounds:
                add("evaluation_evidence", "evaluation/rounds.json", "application/json", _json({
                    "scope_rule": ("비교 라운드는 작업이 아니라 기준 환경에 묶인다. 비교 계획의 기준 환경이 이 작업의 "
                                   "실행이 쓴 환경과 정확히 같을 때만 포함한다."),
                    "environments": [{"id": ref["id"], "version": ref["version"]} for ref in scope["environments"]],
                    "outside_scope_round_count": scope["outside_scope"],
                    "unreadable_round_count": scope["unreadable"],
                    "rounds": rounds, "experiments": experiments}), mode="metadata_only",
                    label=(f"이 작업의 실행 환경에서 한 비교 {len(rounds)}개 · 실험 {len(experiments)}개 "
                           f"(판정·지표·항목 결과만, 산출물 내용 제외 · 다른 환경의 비교 {scope['outside_scope']}개는 범위 밖)"))
                collected_evaluation = True
        for category in sorted(EXPORT_CATEGORIES):
            if category not in categories:
                missing.append({"category": category, "reason": "not_selected",
                                "claim": "내보내기에서 선택하지 않았다."})
            elif category == "evaluation_evidence" and collected_evaluation:
                missing.append({"category": category, "reason": "unavailable",
                                "claim": "실행의 완료 판정 근거는 이 서버의 내보내기가 아직 모으지 않는다."})
            elif category == "evaluation_evidence" and evaluation is not None:
                missing.append({"category": category, "reason": "unavailable",
                                "claim": ("이 서버의 내보내기는 실행의 완료 판정 근거를 아직 모으지 않고, "
                                          "이 작업에는 설계 평가·비교 기록이 없다.")})
            elif category in UNCOLLECTED:
                missing.append({"category": category, "reason": "unavailable",
                                "claim": "이 서버의 내보내기는 아직 이 범주를 모으지 않는다."})
        for index, item in enumerate(items):
            item["export_id"] = f"item-{index + 1}"
            item["size_bytes"] = len(item["data"])
            item["export_sha256"] = sha256(item["data"]).hexdigest()
        return items, missing

    @staticmethod
    def _preview_value(work_id, request_id, categories, include_raw, items, missing, scan=None, sources=False):
        shown = [{name: item[name] for name in ("export_id", "category", "relative_path",
                                                 "media_type", "size_bytes", "export_sha256",
                                                 "content_mode", "label")} for item in items]
        bound = {"work_id": work_id, "request_id": request_id, "categories": list(categories),
                 "include_raw": include_raw, "items": shown, "missing": missing, "secret_scan": scan}
        if sources:
            bound[SOURCES_FIELD] = True
        digest = sha256(canonical_json(bound)).hexdigest()
        value = {"request_id": request_id, "work_id": work_id, "preview_sha": digest,
                 "categories": list(categories), "include_raw": include_raw,
                 "items": shown, "missing": missing, "exportable": bool(shown), "secret_scan": scan}
        if sources:
            value[SOURCES_FIELD] = True
        return value

    def _known(self, db):
        def known(candidate):
            return self._owner.recognizes_secret(db, candidate)

        return known

    def _scan(self, db, work_id, revisions, acknowledged, assessed=()):
        """The secret scan over every raw original the export would carry: (the scan
        shown in the preview, withheld revision numbers, matched values for canaries,
        whether the owner confirmed this exact finding set). Only the kind and location
        of a finding is ever shown; a raw original with a finding is withheld (an
        attached PDF: redacted or excluded) unless the owner confirmed exactly this
        finding set. `assessed` are the attached originals the worker already scanned."""

        findings, truncated, values, flagged = [], False, [], set()
        known = self._known(db)
        for record in revisions:
            number = record.ref.version
            found, cut, matched = scan_text(record.body["content"]["text"], known=known)
            if found:
                flagged.add(number)
                values.extend(matched)
                truncated = truncated or cut
                findings.extend({"relative_path": f"originals/revision-{number}.txt", **item.as_dict()}
                                for item in found)
        for entry in assessed:
            findings.extend(entry["findings"])
            values.extend(entry["values"])
        digest = findings_digest(work_id, findings) if findings else None
        if acknowledged is not None and acknowledged != digest:
            raise WorkServiceError("conflict")  # the owner confirmed a finding set that is not this one
        confirmed = digest is not None and acknowledged == digest
        scan = {"findings": findings, "truncated": truncated, "findings_sha": digest,
                "confirmed": confirmed}
        withheld = frozenset() if confirmed else frozenset(flagged)
        canaries = [] if confirmed else sorted({value for value in values if value})[:MAX_CANARIES]
        return scan, withheld, canaries, confirmed

    def _evaluation(self, db, roots, work_id):
        requests, lens_keys = collect_design_records(self._domain, db, roots, work_id)
        environments = self._environments(db, roots, work_id)
        rounds, experiments, counts = (collect_rounds(self._domain, db, roots, environments)
                                       if environments else ([], [], {"outside_scope": 0, "unreadable": 0}))
        return {"requests": requests, "lenses": lens_view(lens_keys) if lens_keys else [],
                "rounds": rounds, "experiments": experiments, "scope": {"environments": environments, **counts}}

    def _current(self, db, roots, work_id, request_id, categories, include_raw, acknowledged=None,
                 include_sources=False):
        revisions = self._revisions(db, roots, work_id)
        alternatives = self._alternatives(db, roots, work_id) if "alternatives" in categories else ()
        runs = self._runs(db, roots, work_id) if "events" in categories else ()
        evaluation = self._evaluation(db, roots, work_id) if "evaluation_evidence" in categories else None
        assessed = []
        if include_sources:
            known = self._known(db)
            assessed = [assess(source, codec=self._codec, known=known, cache=self._cache)
                        for source in load_sources(self._domain, db, roots, revisions, with_bytes=True)]
        scan, withheld, canaries, confirmed = (self._scan(db, work_id, revisions, acknowledged, assessed)
                                               if include_raw else (None, frozenset(), [], False))
        sources = [materialize(entry, confirmed=confirmed, codec=self._codec, known=self._known(db),
                               cache=self._cache) for entry in assessed]
        items, missing = self._collect(revisions, categories, include_raw, alternatives, runs, withheld,
                                       sources, evaluation)
        # a redacted copy must never carry what it painted over
        for item in items:
            if item["content_mode"] == "redacted" and any(value.encode("utf-8") in item["data"]
                                                           for value in canaries):
                raise WorkServiceError("unavailable")
        preview = self._preview_value(work_id, request_id, categories, include_raw, items, missing, scan,
                                      include_sources)
        return revisions, items, missing, preview, canaries

    @_closed
    def preview(self, request, work_id, payload) -> dict:
        """What the export would contain now; reads only, stores nothing."""

        work_id = uuid_string(work_id)
        request_id, categories, include_raw, acknowledged, sources = _selection(payload, confirm=False)
        _authenticate_owner(self._owner, request)
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            return self._current(db, roots, work_id, request_id, categories, include_raw, acknowledged,
                                 sources)[3]

    # --- the explicit, bound confirmation ------------------------------------------

    @staticmethod
    def _bundle(manifest_dict, items) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in (("manifest.json", _json(manifest_dict)),
                               *((item["relative_path"], item["data"]) for item in items)):
                info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, data)
        return buffer.getvalue()

    def _record(self, db, roots, actor_ref, kind, content, parents, *, record_id=None):
        record = ImmutableRecord.create(
            kind=kind, id=record_id or str(uuid4()), version=1, created_at_utc=_stamp(),
            actor_ref=actor_ref, parent_refs=tuple(parents), purpose="operational",
            access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
            content=content,
        )
        self._domain._put_in_transaction(db, record)
        return record.ref

    @_closed
    def confirm(self, request, work_id, payload) -> dict:
        work_id = uuid_string(work_id)
        request_id, categories, include_raw, acknowledged, sources = _selection(payload, confirm=True)
        if payload["confirmed"] is not True:
            raise WorkServiceError("invalid_input")  # consent is never implicit
        shown = payload["preview_sha"]
        _authenticate_owner(self._owner, request)
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            if self._for_request(db, roots, request_id):
                raise WorkServiceError("conflict")  # one bundle per request id
            _revisions, items, _missing, preview, _canaries = self._current(
                db, roots, work_id, request_id, categories, include_raw, acknowledged, sources)
        if not preview["exportable"]:
            raise WorkServiceError("invalid_input")  # nothing selected exists to export
        if preview["preview_sha"] != shown:
            # the work (or the selection) differs from what the owner saw and consented to
            raise WorkServiceError("conflict")
        created_at = _stamp()
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            if self._for_request(db, roots, request_id):
                raise WorkServiceError("conflict")
            revisions, items, missing, again, canaries = self._current(
                db, roots, work_id, request_id, categories, include_raw, acknowledged, sources)
            if again["preview_sha"] != shown:
                raise WorkServiceError("conflict")
            latest = revisions[-1].ref
            consent = self._record(db, roots, actor_ref, "run_consent", {
                "export_consent": {"work_id": work_id, "request_id": request_id,
                                   "preview_sha": shown, "categories": list(categories),
                                   "include_raw": include_raw, SOURCES_FIELD: sources,
                                   "confirmed_secret_findings_sha": acknowledged}}, (latest,))
            raw_refs, by_revision = [], {record.ref.version: record.ref for record in revisions}
            for item in items:
                if item["content_mode"] == "raw" and item["source_ref"] is not None:
                    # an attached original the owner chose to include as it is
                    raw_refs.append(self._record(db, roots, actor_ref, "artifact", {
                        "export_original": {"source_id": item["source_ref"].id,
                                            "export_sha256": item["export_sha256"],
                                            "media_type": item["media_type"]}},
                        (item["source_ref"], consent)))
                elif item["content_mode"] == "raw":
                    number = int(item["relative_path"].rsplit("-", 1)[1].split(".")[0])
                    raw_refs.append(self._record(db, roots, actor_ref, "artifact", {
                        "export_original": {"revision": number, "export_sha256": item["export_sha256"],
                                            "media_type": item["media_type"]}},
                        (by_revision[number], consent)))
            export_request = create_export_request({
                "request_id": request_id, "scope": f"work:{work_id}",
                "selected_categories": list(categories),
                "include_raw_refs": [ref.as_dict() for ref in raw_refs],
                "redaction_policy_ref": roots.access_policy.as_dict(),
                "author_consent_ref": consent.as_dict(), "created_at": created_at,
            })
            manifest = build_export_manifest(
                export_request,
                [{"export_id": item["export_id"], "kind": item["category"],
                  "relative_path": item["relative_path"], "media_type": item["media_type"],
                  "size_bytes": item["size_bytes"], "export_sha256": item["export_sha256"],
                  "linked_export_ids": [], "content_mode": item["content_mode"],
                  "source_hash_included": False, "source_sha256": None,
                  "license_or_share_basis": None} for item in items],
                [{"export_ref": entry["category"], "reason": entry["reason"],
                  "affected_claims": [entry["claim"]],
                  "recoverable_by_user": entry["reason"] == "not_selected"} for entry in missing],
                secret_canaries=canaries, created_at=created_at, app_release=APP_RELEASE,
                pseudonym_map_scope=f"work:{work_id}",
                reproduction_limits=["모델·도구 실행 기록은 이 내보내기에 포함되지 않았다."] + (
                    ["가림 사본은 원본과 같지 않아 원본을 재현하지 않는다."]
                    if any(item["content_mode"] == "redacted" for item in items) else []),
            )
            manifest_dict = manifest.as_dict()
            bundle = self._bundle(manifest_dict, items)
        blob = self._domain.put_blob(bundle, purpose="operational")
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            if self._for_request(db, roots, request_id):
                raise WorkServiceError("conflict")  # one bundle per request id
            bundle_id = manifest.bundle_id
            artifact = self._record(db, roots, actor_ref, "artifact", {
                "export_bundle": {"bundle_id": bundle_id, "media_type": "application/zip"},
                "blob": blob.as_dict()}, (consent,))
            receipt = seal_export(manifest, bundle_sha256=blob.sha256, size_bytes=blob.size,
                                  completed_at=_stamp(), artifact_ref=artifact.as_dict())
            receipt_value = {
                "bundle_id": receipt.bundle_id, "manifest_sha256": receipt.manifest_sha256,
                "bundle_sha256": receipt.bundle_sha256, "size_bytes": receipt.size_bytes,
                "completed_at": receipt.completed_at,
            }
            self._record(db, roots, actor_ref, "export_manifest", {
                # the manifest's own `export_ref` names an entry, not a record: kept as its
                # exact canonical text, so the store never reads it as a reference
                "work_id": work_id, "request_id": request_id, "manifest_json": _json(manifest_dict).decode("utf-8"),
                "manifest_sha256": manifest.manifest_sha, "receipt": receipt_value,
                "bundle_artifact_ref": artifact.as_dict()}, (artifact,), record_id=bundle_id)
        return {**receipt_value, "work_id": work_id, "request_id": request_id,
                "item_count": len(items), "missing": [
                    {"category": entry["category"], "reason": entry["reason"]} for entry in missing]}

    # --- the owner's download ------------------------------------------------------

    def _for_request(self, db, roots, request_id) -> bool:
        # the canonical body escapes every quote inside a string, so the needle can only
        # be the top-level key itself; a match is read back and checked
        needle = f'"request_id":"{request_id}"'.encode()
        for row in db.execute(
                "SELECT id, sha256 FROM domain_records WHERE vault_id=? AND kind='export_manifest' "
                "AND version=1 AND instr(body, ?) > 0", (roots.genesis.id, needle)).fetchall():
            record = self._domain._load(db, EntityRef("export_manifest", row["id"], 1, row["sha256"]),
                                        roots)[0]
            if record.body["content"].get("request_id") == request_id:
                return True
        return False

    def _stored(self, db, roots, bundle_id):
        row = db.execute(
            "SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='export_manifest' "
            "AND id=? AND version=1", (roots.genesis.id, bundle_id)).fetchone()
        if row is None:
            return None
        return self._domain._load(db, EntityRef("export_manifest", bundle_id, 1, row["sha256"]),
                                  roots)[0]

    @_closed
    def download(self, request, work_id, bundle_id):
        """(receipt, bundle bytes) — the store verifies the blob on read."""

        work_id, bundle_id = uuid_string(work_id), uuid_string(bundle_id)
        with self._domain._connection() as db:
            self._owner.authenticate_bound(request.session)
            roots = self._domain._read_roots(db)
            record = self._stored(db, roots, bundle_id)
            if record is None or record.body["content"]["work_id"] != work_id:
                raise WorkServiceError("not_found")
            content = record.body["content"]
            artifact = self._domain._load(
                db, EntityRef.from_dict(content["bundle_artifact_ref"]), roots)[0]
        blob = BlobRef.from_dict(artifact.body["content"]["blob"])
        data = self._domain.read_blob(blob, purpose=blob.purpose)
        receipt = content["receipt"]
        if sha256(data).hexdigest() != receipt["bundle_sha256"]:
            raise WorkServiceError("unavailable")
        return receipt, data
