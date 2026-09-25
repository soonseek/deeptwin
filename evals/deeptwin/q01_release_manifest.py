"""Release-v5 pre-dispatch manifest and dispatch-journal checks, shared by the harness and the sealed verifier.

``evals/deeptwin/qualification/release-v5/qualification_design.json`` (``pre_dispatch``)
requires a manifest, frozen by sha256 before the first dispatch, that fixes the
critic configuration and its digest, the run identity (including the planned
(case, repetition) slot list and the path of the manifest's dispatch journal),
the attempt number and every prior attempt (with its sealed set and sealed
expectations sha256), the author/reviewer/sealing attestations and, for a
lens-effect run, every arm's critic configuration, text digest and attempt entry
and the arm x case order (``pre_dispatch_manifest.schema.json``, schema v3). The
harness refuses to dispatch unless the manifest it loads hashes to the committed
value; the verifier checks the same value.

The dispatch journal (``read_journal``) is an append-only JSON-lines file, one
per manifest: a header entry binding the manifest sha256, the commit reference and
the planned slot list, then one ``dispatch`` entry per trial, written by the
harness before the trial's first call. Each entry carries ``prev`` (the previous
entry's ``entry_sha256``; 64 zeros for the header) and ``entry_sha256`` (sha256 of
the canonical JSON of the entry without that key); every line is exactly the
canonical JSON of its entry. The harness writes it (``q01_harness``); this module
only reads and checks it, so the verifier never imports the harness.

Canonical JSON (used for ``critic_configuration_digest``, lens digests and journal
entries)::

    json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
               allow_nan=False).encode("utf-8")

The manifest's own sha256 is over the exact file bytes that were committed,
never over a re-serialization. This module holds no expectations and reads no
case materials; it imports neither the harness nor any verifier.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

DESIGN_DIR = Path(__file__).resolve().parent / "qualification" / "release-v5"
MANIFEST_SCHEMA_FILE = DESIGN_DIR / "pre_dispatch_manifest.schema.json"
DESIGN_ID = "q01-release-v5"
EFFECT_DESIGN_ID = "lens-effects-v5"
REPETITIONS_PER_CASE = 3  # release-v5 execution.repetitions_per_case; never caller-supplied
# lens-effects-v5 arms that are dispatched; strong_existing_procedure is a
# duplicate of no_lens and user_construct is not runnable, so neither appears.
BASELINE_ARM = "no_lens"
TEXT_ARMS = frozenset({"general_multi_perspective", "single_L-P050-01", "single_L-P033-02", "mix"})
# The lens rules each lens arm must carry, in order (lens-effects-v5 ``arms``). The
# general checklist carries rules of its own, never one of these lenses.
LENS_ARM_RULES = {"single_L-P050-01": ["L-P050-01"], "single_L-P033-02": ["L-P033-02"],
                  "mix": ["L-P050-01", "L-P033-02"]}
COMMIT_REF_KINDS = frozenset({"git_commit", "external_timestamp"})
JOURNAL_SCHEMA = "q01-dispatch-journal-1"
JOURNAL_GENESIS = "0" * 64
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{7,64}\Z")
_TOKEN = re.compile(r"[^0-9a-z]+")


def canonical_bytes(value) -> bytes:
    """The canonical JSON encoding named in the release designs."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def critic_configuration_digest(configuration: dict) -> str:
    return sha256(canonical_bytes(configuration)).hexdigest()


def lens_refs_and_digests(pack: dict) -> dict:
    """The ``critic_configuration.lens_refs_and_digests`` value of one lens pack.

    The pack is critic configuration, never dataset material: its id, version and
    canonical sha256, and each rule's id, version and canonical sha256 in order. The
    digests equal the ``lens_pack`` / ``lens_rules`` entries of the product's prepared
    input manifest for the same pack.
    """
    if type(pack) is not dict or type(pack.get("rules")) is not list:
        raise ValueError("a lens pack object is required")
    return {"pack_id": pack["id"], "pack_version": pack["version"],
            "pack_sha256": sha256(canonical_bytes(pack)).hexdigest(),
            "rules": [{"lens_id": rule["id"], "version": rule["version"],
                       "sha256": sha256(canonical_bytes(rule)).hexdigest()} for rule in pack["rules"]]}


def prepared_lens_refs(prepared_manifest: dict) -> dict | None:
    """The same value, read back from a prepared input manifest (``None`` without a pack)."""
    pack = prepared_manifest.get("lens_pack")
    if pack is None:
        return None
    return {"pack_id": pack["id"], "pack_version": pack["version"], "pack_sha256": pack["sha256"],
            "rules": [{"lens_id": rule["id"], "version": rule["version"], "sha256": rule["sha256"]}
                      for rule in prepared_manifest.get("lens_rules", [])]}


def is_sha256(value) -> bool:
    return type(value) is str and _HEX.fullmatch(value) is not None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError("nonfinite JSON constant")


def strict_json(data: bytes):
    """Parse UTF-8 JSON bytes, refusing duplicate keys and NaN/Infinity."""
    return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_nonfinite)


def _schema_validator(path: Path) -> Draft202012Validator:
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@dataclass(frozen=True)
class ManifestCheck:
    """Outcome of one pre-dispatch manifest check. ``ok`` only when ``errors`` is empty."""

    manifest_sha256: str | None
    manifest: dict | None
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def _attempt_errors(attempt, prior, label):
    if attempt != len(prior) + 1:
        return [f"{label}attempt_does_not_follow_prior_attempts"]
    if [item["attempt"] for item in prior] != list(range(1, len(prior) + 1)):
        return [f"{label}prior_attempts_not_numbered_in_order"]
    return []


def _spent_errors(current, prior, label):
    """Audit 4, B2: a sealed set (materials or expectations) spent by a prior attempt is never rerun."""
    spent = {item[name] for item in prior for name in ("sealed_dataset_sha256", "sealed_expectations_sha256")}
    if set(current) & spent:
        return [f"{label}sealed_set_already_spent_by_a_prior_attempt"]
    return []


def planned_slots(case_order) -> list[dict]:
    """``run_identity.planned_slots``: case_order x 3 repetitions, case-major and in order."""
    return [{"case_id": case_id, "repetition": repetition} for case_id in case_order
            for repetition in range(1, REPETITIONS_PER_CASE + 1)]


def normalized_name(value: str) -> str:
    """Case- and whitespace-normalized identity name used for every separation comparison."""
    return " ".join(value.casefold().split())


def judge_shares_critic(judge_identity: str, configuration: dict) -> bool:
    """The judge identity names the critic's provider family or its model string.

    Normalized (``normalized_name``): the critic's model string occurring anywhere in the
    judge identity, or the first token of the critic's provider (its family, e.g. the
    part before ``/``) occurring as a token of the judge identity.
    """
    judge = normalized_name(judge_identity)
    tokens = {token for token in _TOKEN.split(judge) if token}
    model = normalized_name(configuration["model"])
    family = [token for token in _TOKEN.split(normalized_name(configuration["provider"])) if token]
    return bool(model and model in judge) or bool(family and family[0] in tokens)


def _lens_effect_errors(manifest) -> list[str]:
    """lens-effects-v5: one sealed effect set, one run covering every arm."""
    effect = manifest["lens_effect"]
    if effect is None:
        return []
    errors = []
    identity, configuration = manifest["run_identity"], manifest["critic_configuration"]
    arms = effect["arms"]
    ids = [arm["id"] for arm in arms]
    if len(set(ids)) != len(ids):
        errors.append("lens_effect:duplicate_arm")
    if BASELINE_ARM not in ids:
        errors.append("lens_effect:no_baseline_arm")
    if effect["effect_set_sha256"] != identity["sealed_dataset_sha256"]:
        errors.append("lens_effect:effect_set_is_not_the_sealed_dataset")
    qualification = {item[name] for item in effect["qualification_sets"]
                     for name in ("sealed_dataset_sha256", "sealed_expectations_sha256")}
    if {effect["effect_set_sha256"], identity["sealed_expectations_sha256"]} & qualification:
        errors.append("lens_effect:effect_set_is_a_qualification_set")
    packs = [arm["critic_configuration"]["lens_refs_and_digests"]["pack_sha256"] for arm in arms]
    if len(set(packs)) != len(packs):
        errors.append("lens_effect:identical_lens_pack_on_different_arms")
    held = {name: value for name, value in configuration.items() if name != "lens_refs_and_digests"}
    current = (identity["sealed_dataset_sha256"], identity["sealed_expectations_sha256"])
    for arm in arms:
        label = f"lens_effect:{arm['id']}:"
        arm_configuration = arm["critic_configuration"]
        if critic_configuration_digest(arm_configuration) != arm["critic_configuration_digest"]:
            errors.append(label + "critic_configuration_digest_mismatch")
        if {name: value for name, value in arm_configuration.items() if name != "lens_refs_and_digests"} != held:
            errors.append(label + "differs_from_the_run_configuration_beyond_its_lens_set")
        lenses = arm_configuration["lens_refs_and_digests"]
        rule_ids = [rule["lens_id"] for rule in lenses["rules"]]
        if arm["id"] == BASELINE_ARM:
            if arm["text_sha256"] is not None or lenses["rules"]:
                errors.append(label + "baseline_carries_lens_text")
            if arm["critic_configuration_digest"] != manifest["critic_configuration_digest"]:
                errors.append(label + "baseline_is_not_the_run_configuration")
            if (arm["attempt"], arm["prior_attempts"]) != (manifest["attempt"], manifest["prior_attempts"]):
                errors.append(label + "baseline_attempt_differs_from_the_run_attempt")
        elif arm["id"] in TEXT_ARMS:
            if arm["text_sha256"] is None:
                errors.append(label + "text_digest_not_fixed_before_dispatch")
            elif arm["text_sha256"] != lenses["pack_sha256"]:
                errors.append(label + "text_digest_is_not_the_sent_lens_pack")
            expected = LENS_ARM_RULES.get(arm["id"])
            if expected is not None and rule_ids != expected:
                errors.append(label + "lens_rules_do_not_match_the_arm")
            if expected is None and (not rule_ids or set(rule_ids) & {lens for rules in LENS_ARM_RULES.values()
                                                                      for lens in rules}):
                errors.append(label + "lens_rules_do_not_match_the_arm")
        errors += _attempt_errors(arm["attempt"], arm["prior_attempts"], label)
        errors += _spent_errors(current, arm["prior_attempts"], label)
    order = [(item["arm"], item["case_id"]) for item in effect["arm_case_order"]]
    case_order = identity["case_order"]["order"]
    planned = {(arm_id, case_id) for arm_id in ids for case_id in case_order}
    if len(order) != len(set(order)) or set(order) != planned:
        errors.append("lens_effect:arm_case_order_is_not_every_arm_on_every_case_once")
    else:
        width = len(ids)
        blocks = [order[index:index + width] for index in range(0, len(order), width)]
        if [{case_id for _arm, case_id in block} for block in blocks] != [{case_id} for case_id in case_order]:
            errors.append("lens_effect:arm_case_order_is_not_interleaved_per_case_order")
    return errors


def _attestation_errors(manifest) -> list[str]:
    """Author, reviewer, sealer and judge, compared case- and whitespace-normalized."""
    attestations = manifest["attestations"]
    judge = normalized_name(manifest["run_identity"]["judge_identity"])
    author, reviewer, sealer = (normalized_name(attestations[role]["name"])
                                for role in ("author", "reviewer", "sealing"))
    errors = []
    if author == reviewer:
        errors.append("attestation:author_is_reviewer")
    if judge in {author, reviewer}:
        errors.append("attestation:judge_is_author_or_reviewer")
    if judge == sealer:
        errors.append("attestation:judge_is_sealer")
    return errors


def check_pre_dispatch_manifest(data: bytes | Path, *, committed_sha256: str | None,
                                harness: dict | None = None, verifier: dict | None = None) -> ManifestCheck:
    """Check one pre-dispatch manifest; never raises for a bad manifest.

    * the bytes hash to ``committed_sha256`` (``None`` or a non-hex value is an error:
      there is no dispatch without a committed value);
    * strict JSON that validates against ``pre_dispatch_manifest.schema.json`` (v3);
    * ``critic_configuration_digest`` recomputes from ``critic_configuration``;
    * ``attempt == len(prior_attempts) + 1`` and the prior attempts are numbered 1..k-1;
    * neither the sealed dataset nor the sealed expectations sha256 is one a prior
      attempt already spent (audit 4, B2);
    * ``planned_slots`` is exactly ``case_order`` x 3, case-major and in order;
    * the author and reviewer differ, and the judge is none of author, reviewer and
      sealer (names compared case- and whitespace-normalized);
    * the judge identity does not name the critic's provider or model;
    * a lens-effect section satisfies ``_lens_effect_errors``;
    * optionally, ``run_identity.harness`` / ``run_identity.verifier`` equal the given
      ``{"version", "sha256"}`` of the code that is about to run.
    """
    errors: list[str] = []
    if isinstance(data, Path):
        try:
            data = data.read_bytes()
        except OSError:
            return ManifestCheck(None, None, ("manifest_unreadable",))
    if type(data) is not bytes:
        return ManifestCheck(None, None, ("manifest_not_bytes",))
    digest = sha256(data).hexdigest()
    if not is_sha256(committed_sha256):
        errors.append("no_committed_manifest_sha256")
    elif digest != committed_sha256:
        errors.append("manifest_sha256_differs_from_committed")
    try:
        manifest = strict_json(data)
    except (ValueError, UnicodeDecodeError):
        return ManifestCheck(digest, None, (*errors, "manifest_not_strict_json"))
    schema_error = best_match(_schema_validator(MANIFEST_SCHEMA_FILE).iter_errors(manifest))
    if schema_error is not None:
        errors.append("manifest_schema:/" + "/".join(map(str, schema_error.absolute_path)))
        return ManifestCheck(digest, manifest if type(manifest) is dict else None, tuple(errors))
    if critic_configuration_digest(manifest["critic_configuration"]) != manifest["critic_configuration_digest"]:
        errors.append("critic_configuration_digest_mismatch")
    identity = manifest["run_identity"]
    errors += _attempt_errors(manifest["attempt"], manifest["prior_attempts"], "")
    errors += _spent_errors((identity["sealed_dataset_sha256"], identity["sealed_expectations_sha256"]),
                            manifest["prior_attempts"], "")
    order = identity["case_order"]["order"]
    if len(set(order)) != len(order):
        errors.append("case_order_repeats_a_case")
    if identity["planned_slots"] != planned_slots(order):
        errors.append("planned_slots_are_not_case_order_times_three")
    errors += _attestation_errors(manifest)
    if judge_shares_critic(identity["judge_identity"], manifest["critic_configuration"]):
        errors.append("judge:shares_the_critic_provider_or_model")
    errors += _lens_effect_errors(manifest)
    if harness is not None and identity["harness"] != harness:
        errors.append("harness_identity_mismatch")
    if verifier is not None and identity["verifier"] != verifier:
        errors.append("verifier_identity_mismatch")
    return ManifestCheck(digest, manifest, tuple(errors))


def schema_valid(check: ManifestCheck) -> bool:
    return check.manifest is not None and not any(
        error.startswith(("manifest_schema", "manifest_not")) for error in check.errors)


def commit_ref_errors(commit_ref) -> list[str]:
    """``PreDispatch.commit_ref``: where the manifest sha256 was committed before the first dispatch."""
    if (type(commit_ref) is not dict or set(commit_ref) != {"kind", "ref"}
            or commit_ref["kind"] not in COMMIT_REF_KINDS or type(commit_ref["ref"]) is not str
            or not commit_ref["ref"].strip() or len(commit_ref["ref"]) > 256):
        return ["commit_ref_malformed"]
    if commit_ref["kind"] == "git_commit" and _COMMIT.fullmatch(commit_ref["ref"]) is None:
        return ["commit_ref_malformed"]
    return []


def file_set_sha256(root: Path, relatives) -> str:
    """sha256 of the canonical JSON ``{relative path: file sha256}`` of a set of source files."""
    root = Path(root)
    return sha256(canonical_bytes({relative: sha256((root / relative).read_bytes()).hexdigest()
                                   for relative in relatives})).hexdigest()


# ---------------------------------------------------------------- dispatch journal (read side)


_HEADER_KEYS = frozenset({"schema", "seq", "kind", "manifest_sha256", "commit_ref", "planned_slots_sha256",
                          "prev", "entry_sha256"})
_DISPATCH_KEYS = frozenset({"seq", "kind", "trial_id", "case_id", "repetition", "prev", "entry_sha256"})


def journal_entry_sha256(entry: dict) -> str:
    """sha256 of the canonical JSON of a journal entry without its ``entry_sha256`` key."""
    return sha256(canonical_bytes({key: value for key, value in entry.items() if key != "entry_sha256"})).hexdigest()


def journal_line(entry: dict) -> bytes:
    return canonical_bytes(entry) + b"\n"


def planned_slots_sha256(slots) -> str:
    return sha256(canonical_bytes(list(slots))).hexdigest()


@dataclass(frozen=True)
class JournalState:
    """A dispatch journal as read and chain-checked (``read_journal``). ``ok`` only without errors."""

    path: Path
    header: dict | None
    dispatches: tuple[dict, ...]
    head: str | None
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def by_trial(self) -> dict:
        return {entry["trial_id"]: entry for entry in self.dispatches}


def parse_journal(data: bytes, path: Path | None = None) -> JournalState:
    """Check journal bytes: canonical lines, a header, a hash chain, unique trial ids."""
    path = Path(path) if path is not None else None
    if not data:
        return JournalState(path, None, (), None, ())
    if not data.endswith(b"\n"):
        return JournalState(path, None, (), None, ("journal_torn_tail",))
    header, dispatches, prev, seen = None, [], JOURNAL_GENESIS, set()
    for seq, line in enumerate(data[:-1].split(b"\n")):
        try:
            entry = strict_json(line)
        except (ValueError, UnicodeDecodeError):
            return JournalState(path, header, tuple(dispatches), None, ("journal_line_not_strict_json",))
        if type(entry) is not dict or journal_line(entry) != line + b"\n":
            return JournalState(path, header, tuple(dispatches), None, ("journal_line_not_canonical",))
        keys = _HEADER_KEYS if seq == 0 else _DISPATCH_KEYS
        if set(entry) != keys or entry["seq"] != seq or entry["kind"] != ("open" if seq == 0 else "dispatch"):
            return JournalState(path, header, tuple(dispatches), None, ("journal_entry_shape",))
        if entry["prev"] != prev or entry["entry_sha256"] != journal_entry_sha256(entry):
            return JournalState(path, header, tuple(dispatches), None, ("journal_chain_broken",))
        if seq == 0:
            if (entry["schema"] != JOURNAL_SCHEMA or not is_sha256(entry["manifest_sha256"])
                    or commit_ref_errors(entry["commit_ref"]) or not is_sha256(entry["planned_slots_sha256"])):
                return JournalState(path, None, (), None, ("journal_header_shape",))
            header = entry
        else:
            if (type(entry["trial_id"]) is not str or type(entry["case_id"]) is not str
                    or type(entry["repetition"]) is not int or entry["trial_id"] in seen):
                return JournalState(path, header, tuple(dispatches), None, ("journal_entry_shape",))
            seen.add(entry["trial_id"])
            dispatches.append(entry)
        prev = entry["entry_sha256"]
    return JournalState(path, header, tuple(dispatches), prev, ())


def read_journal(path: Path) -> JournalState:
    """Read and check the dispatch journal at ``path``; never raises. A missing file is an error."""
    path = Path(path)
    try:
        if path.is_symlink():
            return JournalState(path, None, (), None, ("journal_symlink_refused",))
        data = path.read_bytes()
    except FileNotFoundError:
        return JournalState(path, None, (), None, ("journal_missing",))
    except OSError:
        return JournalState(path, None, (), None, ("journal_unreadable",))
    state = parse_journal(data, path)
    if state.ok and state.header is None:
        return JournalState(path, None, (), None, ("journal_has_no_header",))
    return state


def journal_problems(state: JournalState, manifest_sha256: str | None, planned) -> list[str]:
    """Why a journal is not the complete, in-order dispatch record of this manifest."""
    if not state.ok:
        return [f"dispatch_journal:{error}" for error in state.errors]
    problems = []
    header = state.header
    if header["manifest_sha256"] != manifest_sha256:
        problems.append("dispatch_journal:is_for_another_manifest")
    if header["planned_slots_sha256"] != planned_slots_sha256(planned):
        problems.append("dispatch_journal:planned_slots_differ_from_manifest")
    slots = [{"case_id": entry["case_id"], "repetition": entry["repetition"]} for entry in state.dispatches]
    if len(slots) > len(planned):
        problems.append("dispatch_journal:unplanned_slot")
    if slots[:len(planned)] != list(planned)[:len(slots)]:
        problems.append("dispatch_journal:out_of_planned_order")
    return problems


__all__ = [
    "DESIGN_ID",
    "EFFECT_DESIGN_ID",
    "JOURNAL_GENESIS",
    "JOURNAL_SCHEMA",
    "REPETITIONS_PER_CASE",
    "JournalState",
    "ManifestCheck",
    "canonical_bytes",
    "check_pre_dispatch_manifest",
    "commit_ref_errors",
    "critic_configuration_digest",
    "file_set_sha256",
    "is_sha256",
    "journal_entry_sha256",
    "journal_line",
    "journal_problems",
    "judge_shares_critic",
    "lens_refs_and_digests",
    "normalized_name",
    "parse_journal",
    "planned_slots",
    "planned_slots_sha256",
    "prepared_lens_refs",
    "read_journal",
    "schema_valid",
    "strict_json",
]
