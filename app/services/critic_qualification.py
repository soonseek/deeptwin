"""Critic configuration qualification state (US2, T036; FR-006, Constitution VI).

A criticism verdict says what one critic configuration concluded about one
design; it never says whether that configuration may be trusted. Trust comes
only from a suite record of a frozen release design
(evals/deeptwin/qualification/release-v4/suite_record.schema.json): its pass is
a *scoped pass* for one exact critic configuration digest. It could become a
qualification only under a design that is able to verify V3 error independence
(a generation path and an owner-set tolerance), and no such design exists:
``V3_VERIFYING_DESIGN_IDS`` is empty, so no production record reaches
``qualified`` (audit 3, BF1). A record's V3 field is never trusted on its own:
a design that cannot verify V3 is capped at ``scoped_pass`` whatever the record
says, and ``record_sha256`` is recomputed and a mismatch refused.

Calibration runs, a failed, incomplete or not_judged suite, a suite without
established judge separation, a scoped pass, and the absence of any record are
all NOT qualified: none of them lets a passed verdict be approved. The state is
an issued value, never constructed.

Open (audit 3): criticism verdicts do not yet carry the critic configuration
digest that produced them, so design approval cannot bind the qualification's
configuration digest to the verdict's critic; that binding is required before
any design that can verify V3 is admitted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256

CRITIC_QUALIFICATION_SCHEMA_VERSION = "critic-qualification-v1"
SUITE_RECORD_SCHEMA_VERSION = "q01-release-suite-verdict-v3"
# Only frozen release designs count; calibration designs never do. release-v2
# could not pass (audit 2, B3) and release-v3 trusted forged records (audit 3),
# so only release-v4 suite records are read.
RELEASE_DESIGN_IDS = frozenset({"q01-release-v4"})
# Designs able to verify V3 error independence. None exists: release-v4 (like
# v3) has no generation path, so it can never verify V3 and a pass under it is
# at most a scoped pass. Keep this empty until a frozen design with a
# generation path, an owner-set tolerance and verdict-to-configuration binding
# is audited.
V3_VERIFYING_DESIGN_IDS = frozenset()
# TEST-ACTOR HOOK. Never set by production code. Tests replace it (see
# app/tests/test_environments.py ``actor_v3_design``) with a test-only
# design id that no frozen design uses, so the approval path can be exercised
# without any production record ever yielding ``qualified``.
_TEST_ACTOR_V3_DESIGN_IDS: frozenset = frozenset()
STATUSES = frozenset({"qualified", "scoped_pass", "unqualified", "unknown"})
SUITE_OUTCOMES = frozenset({"pass", "fail", "incomplete", "not_judged"})
_SUITE_KEYS = frozenset({
    "schema_version", "design_id", "critic_configuration_digest",
    "pre_dispatch_manifest_sha256", "sealed_set_sha256", "attempt",
    "prior_outcomes", "suite_outcome", "independence_profile_sha256",
    "judge_separation_established", "v3_error_independence", "record_sha256",
})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ISSUE_TOKEN = object()


class CriticQualificationError(ValueError):
    """A critic qualification input is malformed."""


@dataclass(frozen=True, slots=True, init=False)
class CriticQualification:
    """Whether one exact critic configuration is qualified, and why."""

    configuration_digest: str
    status: str
    reason: str
    design_id: str | None
    record_sha256: str | None
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": CRITIC_QUALIFICATION_SCHEMA_VERSION,
            "configuration_digest": self.configuration_digest,
            "status": self.status,
            "reason": self.reason,
            "design_id": self.design_id,
            "record_sha256": self.record_sha256,
        }


def _hex(value, label):
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise CriticQualificationError(f"{label} is not a sha256 hex digest")
    return value


def _issue(configuration_digest, status, reason, design_id=None, record_sha256=None):
    value = object.__new__(CriticQualification)
    for name, item in (
        ("configuration_digest", configuration_digest),
        ("status", status),
        ("reason", reason),
        ("design_id", design_id),
        ("record_sha256", record_sha256),
        ("_issuer_token", _ISSUE_TOKEN),
    ):
        object.__setattr__(value, name, item)
    return value


def suite_record_sha256(record: dict) -> str:
    """sha256 of the canonical JSON of ``record`` without its ``record_sha256`` key.

    Canonical JSON: sorted keys, separators (",", ":"), ensure_ascii False,
    allow_nan False, UTF-8 (the same encoding the release verifier uses).
    """
    body = {key: value for key, value in record.items() if key != "record_sha256"}
    try:
        data = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        raise CriticQualificationError("the suite record is not canonical JSON") from None
    return sha256(data).hexdigest()


def unknown_critic_qualification(configuration_digest) -> CriticQualification:
    """No suite record exists for this configuration: never qualified."""

    return _issue(_hex(configuration_digest, "configuration digest"), "unknown", "no_suite_record")


def critic_qualification_from_suite(record, configuration_digest) -> CriticQualification:
    """Derive the state of one configuration from one release suite record."""

    configuration_digest = _hex(configuration_digest, "configuration digest")
    if type(record) is not dict or set(record) != _SUITE_KEYS:
        raise CriticQualificationError("expected the exact suite verdict record")
    if record["schema_version"] != SUITE_RECORD_SCHEMA_VERSION:
        raise CriticQualificationError("unknown suite verdict record schema")
    record_sha = _hex(record["record_sha256"], "record sha256")
    if suite_record_sha256(record) != record_sha:
        # A record whose content does not hash to its own record_sha256 was
        # edited or fabricated after it was built (audit 3, BF1).
        raise CriticQualificationError("record sha256 does not match the record")
    for name in ("sealed_set_sha256", "pre_dispatch_manifest_sha256", "independence_profile_sha256"):
        _hex(record[name], name.replace("_", " "))
    attempt, prior = record["attempt"], record["prior_outcomes"]
    if type(attempt) is not int or attempt < 1 or type(prior) is not list or len(prior) != attempt - 1:
        raise CriticQualificationError("the attempt number must match its listed prior outcomes")
    if any(outcome not in SUITE_OUTCOMES for outcome in prior):
        raise CriticQualificationError("unknown prior suite outcome")
    if _hex(record["critic_configuration_digest"], "suite configuration digest") != configuration_digest:
        # A suite speaks for exactly the critic configuration it ran; any change of
        # model, effort, prompt, contract, parser, chains, deadlines or lens set is
        # another configuration (the dataset and judge are run identity, not this).
        return _issue(configuration_digest, "unknown", "suite_is_for_another_configuration")
    design_id = record["design_id"]
    if type(design_id) is not str:
        raise CriticQualificationError("design id must be a string")
    outcome = record["suite_outcome"]
    if outcome not in SUITE_OUTCOMES:
        raise CriticQualificationError("unknown suite outcome")
    if type(record["judge_separation_established"]) is not bool:
        raise CriticQualificationError("judge separation must be a boolean")
    if record["v3_error_independence"] not in {"unverified", "verified"}:
        raise CriticQualificationError("unknown V3 status")
    v3_capable = V3_VERIFYING_DESIGN_IDS | _TEST_ACTOR_V3_DESIGN_IDS
    if design_id not in RELEASE_DESIGN_IDS | v3_capable:
        return _issue(configuration_digest, "unqualified", "not_a_frozen_release_design", design_id, record_sha)
    if outcome != "pass":
        return _issue(configuration_digest, "unqualified", f"suite_{outcome}", design_id, record_sha)
    if not record["judge_separation_established"]:
        return _issue(configuration_digest, "unqualified", "judge_separation_not_established", design_id, record_sha)
    if design_id not in v3_capable:
        # The design has no generation path, so it cannot verify V3: whatever
        # the record's V3 field says, a pass is at most a scoped pass.
        return _issue(configuration_digest, "scoped_pass", "design_cannot_verify_v3", design_id, record_sha)
    if record["v3_error_independence"] != "verified":
        return _issue(configuration_digest, "scoped_pass", "v3_error_independence_unverified", design_id, record_sha)
    return _issue(configuration_digest, "qualified", "release_suite_passed_v3_verified", design_id, record_sha)


def is_issued_critic_qualification(value: object) -> bool:
    return (
        type(value) is CriticQualification
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


__all__ = [
    "CRITIC_QUALIFICATION_SCHEMA_VERSION",
    "RELEASE_DESIGN_IDS",
    "SUITE_OUTCOMES",
    "SUITE_RECORD_SCHEMA_VERSION",
    "V3_VERIFYING_DESIGN_IDS",
    "CriticQualification",
    "CriticQualificationError",
    "critic_qualification_from_suite",
    "is_issued_critic_qualification",
    "suite_record_sha256",
    "unknown_critic_qualification",
]
