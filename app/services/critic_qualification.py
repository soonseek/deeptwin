"""Critic configuration qualification state (US2, T036; FR-006, Constitution VI).

A criticism verdict says what one critic configuration concluded about one
design; it never says whether that configuration may be trusted. Trust comes
only from a release qualification suite verdict under a frozen release design
(evals/deeptwin/qualification/release-v*/) whose independent-judge separation
was established. Calibration runs, a failed or incomplete suite, a suite whose
judge separation was not established, and the absence of any record are all
NOT qualified: an unknown critic qualification can never let a passed verdict
be approved. The state is an issued value, never constructed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CRITIC_QUALIFICATION_SCHEMA_VERSION = "critic-qualification-v1"
SUITE_RECORD_SCHEMA_VERSION = "q01-release-suite-verdict-v1"
# Only frozen release designs can qualify; calibration designs never do.
RELEASE_DESIGN_IDS = frozenset({"q01-release-v2"})
STATUSES = frozenset({"qualified", "unqualified", "unknown"})
_SUITE_KEYS = frozenset({
    "schema_version", "design_id", "configuration_digest", "sealed_set_sha256",
    "suite_verdict", "judge_separation_established", "record_sha256",
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
    _hex(record["sealed_set_sha256"], "sealed set sha256")
    if _hex(record["configuration_digest"], "suite configuration digest") != configuration_digest:
        # A suite qualifies exactly the configuration it ran; any change of
        # model, effort, prompt, lens set or judge is a new configuration.
        return _issue(configuration_digest, "unknown", "suite_is_for_another_configuration")
    design_id = record["design_id"]
    if type(design_id) is not str:
        raise CriticQualificationError("design id must be a string")
    if record["suite_verdict"] not in {"pass", "fail", "incomplete"}:
        raise CriticQualificationError("unknown suite verdict")
    if type(record["judge_separation_established"]) is not bool:
        raise CriticQualificationError("judge separation must be a boolean")
    if design_id not in RELEASE_DESIGN_IDS:
        return _issue(configuration_digest, "unqualified", "not_a_frozen_release_design", design_id, record_sha)
    if record["suite_verdict"] != "pass":
        return _issue(configuration_digest, "unqualified", f"suite_{record['suite_verdict']}", design_id, record_sha)
    if not record["judge_separation_established"]:
        return _issue(configuration_digest, "unqualified", "judge_separation_not_established", design_id, record_sha)
    return _issue(configuration_digest, "qualified", "release_suite_passed", design_id, record_sha)


def is_issued_critic_qualification(value: object) -> bool:
    return (
        type(value) is CriticQualification
        and getattr(value, "_issuer_token", None) is _ISSUE_TOKEN
    )


__all__ = [
    "CRITIC_QUALIFICATION_SCHEMA_VERSION",
    "RELEASE_DESIGN_IDS",
    "SUITE_RECORD_SCHEMA_VERSION",
    "CriticQualification",
    "CriticQualificationError",
    "critic_qualification_from_suite",
    "is_issued_critic_qualification",
    "unknown_critic_qualification",
]
