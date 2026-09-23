"""Resolve one actual accepted staged-provider journal item into a closed subject."""

import threading
from contextlib import contextmanager
from hashlib import sha256

from ..deployment.prepare_contracts import DeploymentPrepareError
from ..deployment.prepare_service import PersistentDeploymentPrepare
from ..deployment import provider_receipt_records
from ..domain.refs import EntityRef, canonical_json, parse_canonical
from .provider_conformance_contracts import ConformanceError, ConformanceSubject, ConformanceVerifiedAdmission


def _error(code="conflict"):
    raise ConformanceError(code)


_MEMO = threading.local()


@contextmanager
def journal_once(prepare_service, db):
    """Verify the deployment journal once for a read-only pass over history.

    `verify_history` resolves every retained conformance run's subject inside
    one transaction that writes nothing between them; each resolution used to
    re-read and re-verify the whole deployment journal, so a pass over n runs
    cost n full verifications (about half an hour at the 64-run lifetime
    capacity on a slower host). Inside this scope, and only for this service and
    this very transaction, the first verified journal is reused, and so is each
    installation's resolved historical subject (retained runs of one
    installation share it).
    """

    previous = getattr(_MEMO, "entry", None)
    _MEMO.entry = [prepare_service, db, None, {}]
    try:
        yield
    finally:
        _MEMO.entry = previous


def _journal(prepare_service, db):
    entry = getattr(_MEMO, "entry", None)
    if entry is None or entry[0] is not prepare_service or entry[1] is not db:
        return prepare_service._journal(db)
    if entry[2] is None:
        entry[2] = prepare_service._journal(db)
    return entry[2]


def _select(prepare_service, db, installation_ref):
    if type(prepare_service) is not PersistentDeploymentPrepare:
        _error("unavailable")
    if (type(installation_ref) is not EntityRef
            or installation_ref.kind != "extension_installation" or installation_ref.version != 1):
        _error("invalid_input")
    journal = _journal(prepare_service, db)
    matches = [item for item in journal["requests"].values()
               if item.get("installation") is not None
               and item["installation"].get("ref") == installation_ref]
    if len(matches) != 1:
        _error("conflict")
    return journal, matches[0]


def _subject_from_verified_item(prepare_service, db, item):
    prepare_service._domain._assert_write_transaction(db)
    try:
        installation = item["installation"]
        installation_ref = installation["ref"]
        request_ref = item["ref"]
        receipt_ref = item["receipt"]["ref"]
        candidate_ref = EntityRef.from_dict(item["anchor"]["candidate_ref"])
        anchor = installation["anchor"]
        head = installation["head"]
        consumption = item["consumption"]
        if (item.get("provider_row") is None or len(item["history"]) != 3
                or item["history"][-1]["state"] != "accepted"
                or item["receipt"]["value"]["outcome"] != "succeeded"
                or consumption["anchor"]["effect_ref"] != installation_ref.as_dict()
                or anchor["staging_authority"] != "deployment-provider-receipt-v1"
                or anchor["state"] != "staged" or anchor["revision"] != 1
                or head["revision"] != 1
                or head["installation_anchor_digest"] != installation_ref.sha256
                or item["receipt"]["record"].body["parent_refs"] != [request_ref.as_dict()]
                or installation["record"].body["parent_refs"] != [request_ref.as_dict(), receipt_ref.as_dict()]
                or consumption["record"].body["parent_refs"] != [request_ref.as_dict(), receipt_ref.as_dict(),
                                                                  installation_ref.as_dict()]):
            _error("conflict")
        expected = provider_receipt_records.expected_stage_identity(
            prepare_service._domain, db, prepare_service._profile, item)
        request = item["request"]
        stage = request["effect_payload"]
        context = item["context"]
        control = item["control"]
        if (stage["source_context"]["sha256"] != context["row"]["context_sha256"]
                or stage["source_context"]["size_bytes"] != context["row"]["context_size"]
                or stage["geometry"]["size_bytes"] <= 0
                or anchor["source_context_sha256"] != stage["source_context"]["sha256"]
                or expected.platform != anchor["platform"]
                or expected.service_identity != anchor["service_identity"]):
            _error("conflict")
        values = {
            "vault_id": control["vault_id"], "instance_id": control["instance_id"],
            "origin_digest": control["origin_digest"], "topology_id": item["anchor"]["topology_id"],
            "source_context_sha256": stage["source_context"]["sha256"],
            "provider_geometry_sha256": stage["geometry"]["sha256"],
            "installation_ref": installation_ref, "candidate_ref": candidate_ref,
            "request_ref": request_ref, "receipt_ref": receipt_ref, "platform": anchor["platform"],
            "selected_platform_entry_digest": anchor["selected_platform_entry_digest"],
            "image_manifest_digest": anchor["image_manifest_digest"],
            "service_descriptor_digest": anchor["service_descriptor_digest"],
            "service_identity": anchor["service_identity"], "slot_id": item["row"]["slot_id"],
            "build_identity_digest": expected.build_identity_digest,
            "port_schema_set_digest": expected.port_schema_set_digest,
            "port_contract_version": expected.port_contract_version,
            "worker_profile": expected.worker_profile,
            "implemented_transforms": tuple(expected.implemented_transforms),
            "uid": expected.uid, "gid": expected.gid,
        }
        subject = object.__new__(ConformanceSubject)
        for name, value in values.items():
            object.__setattr__(subject, name, value)
        # Exercise the durable projection now; this also detects incomplete allocation.
        if sha256(canonical_json(subject.as_dict())).hexdigest() != sha256(
                canonical_json({key: value.as_dict() if type(value) is EntityRef
                    else list(value) if type(value) is tuple else value
                    for key, value in values.items() if key not in {"uid", "gid"}})).hexdigest():
            _error("unavailable")
        return subject
    except ConformanceError:
        raise
    except (KeyError, TypeError, ValueError, DeploymentPrepareError):
        _error("conflict")


def resolve_subject(prepare_service, db, installation_ref):
    prepare_service._domain._assert_write_transaction(db)
    try:
        _, item = _select(prepare_service, db, installation_ref)
        if item['installation_current']['ref'] != installation_ref:
            _error('conflict')
        context = prepare_service._provider_context
        if context is None:
            _error("unavailable")
        current = context.read_current()
        if current != item["context"]["files"]:
            _error("conflict")
        return _subject_from_verified_item(prepare_service, db, item)
    except ConformanceError:
        raise
    except DeploymentPrepareError as exc:
        _error("conflict" if exc.code == "conflict" else "unavailable")
    except (OSError, ValueError, TypeError, KeyError):
        _error("unavailable")


def require_current_subject(prepare_service, db, subject, source_context):
    if (type(subject) is not ConformanceSubject
            or source_context is not prepare_service._provider_context):
        _error("unavailable")
    _, item = _select(prepare_service, db, subject.installation_ref)
    if item['installation_current']['ref'] != subject.installation_ref:
        _error('source_changed')
    current = _subject_from_verified_item(prepare_service, db, item)
    if current != subject:
        _error("source_changed")
    try:
        source_context.recheck_current()
        if source_context.read_current() != item["context"]["files"]:
            _error("source_changed")
    except ConformanceError:
        raise
    except Exception:
        _error("source_changed")


def historical_subject(prepare_service, db, installation_ref):
    """Verified retained history only; deliberately performs no live source read."""
    prepare_service._domain._assert_write_transaction(db)
    entry = getattr(_MEMO, "entry", None)
    scoped = entry is not None and entry[0] is prepare_service and entry[1] is db
    if scoped and type(installation_ref) is EntityRef and installation_ref in entry[3]:
        return entry[3][installation_ref]
    _, item = _select(prepare_service, db, installation_ref)
    subject = _subject_from_verified_item(prepare_service, db, item)
    if scoped:
        entry[3][installation_ref] = subject
    return subject


def _verified_admission(prepare_service,db,item,expected):
    current = item['installation_current']
    if (type(expected) is not EntityRef or expected.kind != 'extension_installation' or expected.version != 2
            or current['ref'] != expected or current.get('verification') is None
            or current['anchor']['stage_ref'] != item['installation']['ref'].as_dict()):
        _error('conflict')
    subject = _subject_from_verified_item(prepare_service,db,item)
    values = {'stage_subject':subject,'stage_context_sha256':sha256(canonical_json(subject.as_dict())).hexdigest(),
        'staged_installation_ref':subject.installation_ref,'verified_installation_ref':expected,
        'installation_head_hash':current['head']['hash'],
        'release_review_sha256':current['anchor']['release_review_sha256'],
        'verification_source_context_sha256':current['anchor']['release_source_context_sha256']}
    result = object.__new__(ConformanceVerifiedAdmission)
    for name,value in values.items(): object.__setattr__(result,name,value)
    return result


def resolve_verified_admission(prepare_service,db,staged_ref,expected_verified_ref):
    prepare_service._domain._assert_write_transaction(db)
    try:
        _,item = _select(prepare_service,db,staged_ref)
        if prepare_service._provider_context is None: _error('unavailable')
        if prepare_service._provider_context.read_current() != item['context']['files']: _error('conflict')
        return _verified_admission(prepare_service,db,item,expected_verified_ref)
    except ConformanceError: raise
    except Exception: _error('unavailable')


def require_current_verified_admission(prepare_service,db,admission,source_context):
    if type(admission) is not ConformanceVerifiedAdmission or source_context is not prepare_service._provider_context:
        _error('unavailable')
    try:
        current = resolve_verified_admission(prepare_service,db,admission.staged_installation_ref,admission.verified_installation_ref)
        if current != admission: _error('source_changed')
        source_context.recheck_current()
    except Exception: _error('source_changed')


def historical_verified_admission(prepare_service,db,admission_bytes):
    prepare_service._domain._assert_write_transaction(db)
    try:
        if type(admission_bytes) is not bytes or not 1 <= len(admission_bytes) <= 8192: _error('unavailable')
        value = parse_canonical(admission_bytes)
        _,item = _select(prepare_service,db,EntityRef.from_dict(value['staged_installation_ref']))
        result = _verified_admission(prepare_service,db,item,EntityRef.from_dict(value['verified_installation_ref']))
        if result.as_dict() != value: _error('unavailable')
        return result
    except ConformanceError: raise
    except Exception: _error('unavailable')
