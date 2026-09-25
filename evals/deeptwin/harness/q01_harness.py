"""Isolated Q01 harness: frozen case -> four critic stages -> audited trial record.

The harness drives exactly one trial of one frozen development case through a
caller-supplied transport of the shape ``(system, user) -> str``. It reuses
the reviewed product paths rather than re-implementing them:

* ``app.critic_contract.prepare_input`` projects each stage's visible input;
* ``app.services.design_criticism_live.render_criticism_prompt`` renders the
  product ``(system, user)`` pair, to which the stage section of
  ``instruction.md`` is appended;
* ``app.critic_trial.OfflineRunner`` freezes, journals, dispatches, times out,
  cancels and classifies each call over a fresh ``app.critic_audit.Ledger``,
  with exact-hash lineage between stages.

The harness never scores. It reads agent-visible material only through
``TaskReader`` (an allowlist of the environment manifest and instruction), scans
every agent input for control-plane content before dispatch and records a
content-hash manifest for every call. Type and path checks prevent accidental
use; they are not an OS or hostile-Python sandbox.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.critic_audit import Ledger
from app.critic_contract import (
    CONTRACT_VERSION,
    PARSER_VERSION,
    InputContractError,
    PreparedInput,
    ValidityEvidence,
    prepare_input,
)
from app.critic_trial import OfflineRunner, OfflineTransport, freeze_call
from app.generation_profiles import GenerationPurpose, profile_for
from app.services.design_criticism_live import _CITATION_RULE, render_criticism_prompt
from evals.deeptwin.q01_release_manifest import (
    JOURNAL_GENESIS,
    JOURNAL_SCHEMA,
    REPETITIONS_PER_CASE,
    JournalState,
    canonical_bytes,
    check_pre_dispatch_manifest,
    commit_ref_errors,
    file_set_sha256,
    journal_entry_sha256,
    journal_line,
    journal_problems,
    lens_refs_and_digests,
    parse_journal,
    planned_slots_sha256,
    prepared_lens_refs,
    schema_valid,
)

from . import q01_cases
from .q01_cases import (
    CASE_SCHEMA,
    ENVIRONMENT_MANIFEST,
    ENVIRONMENT_SCHEMA,
    INSTRUCTION_FILE,
    TASK_DIR,
    canonical,
    digest,
)

RECORD_SCHEMA = "q01-trial-record-1"
REPO_ROOT = Path(__file__).resolve().parents[3]
P = GenerationPurpose
STAGES = (P.REVIEW, P.COUNTEREXAMPLE_PROPOSAL, P.COUNTEREXAMPLE_VALIDITY, P.CANDIDATE_RESPONSE)
MODEL_IDENTITY = "selection_declared_not_transport_reported"
# The reviewed agent instruction (instruction.md); a change must be re-reviewed and re-pinned.
INSTRUCTION_SHA256 = "ecc745601415ae49293c88a2abc530bbcde0bbea875325083bcfd1876e537762"
VALIDITY_FIELDS = tuple(ValidityEvidence.model_fields)
# Control-plane files that must never reach an agent input (relative to the repo root).
CONTROL_PLANE_FILES = (
    "evals/deeptwin/tasks/v01-q01/Task.md",
    "evals/deeptwin/tasks/v01-q01/task.toml",
    ".agents/skills/deeptwin-eval-world/SKILL.md",
    "evals/deeptwin/verifiers/critic.py",
    "evals/deeptwin/verifiers/q01_core.py",
    "evals/deeptwin/verifiers/sealed_critic.py",
    "evals/deeptwin/tests/test_critic_verifier.py",
    "evals/deeptwin/tests/test_q01_harness.py",
    "evals/deeptwin/verifiers/claude_judge.py",
    "evals/deeptwin/qualification/calibration/run_plan.json",
    "evals/deeptwin/qualification/calibration/independence_profile.json",
    "evals/deeptwin/qualification/calibration/run_calibration.py",
)
_FRAGMENT_MIN = 24
_SPLIT = re.compile(r"[|`*#>\[\]()]+")
_CODE_FILES = (
    "app/critic_contract.py", "app/critic_trial.py", "app/critic_audit.py",
    "app/services/design_criticism_live.py", "app/generation_profiles.py",
    "evals/deeptwin/q01_materials.py", "evals/deeptwin/q01_lenses.json",
    "evals/deeptwin/harness/q01_cases.py", "evals/deeptwin/harness/q01_harness.py",
)
HARNESS_VERSION = "q01-harness-3"
# The frozen case's source keys a release trial accepts (audit 4, non-blocking 7): the
# agent-visible originals, criteria and candidate only. Anything else (a lens pack under
# another key, a lens rule list, extra metadata) is refused, never silently dropped.
SOURCE_KEYS = frozenset({"originals", "criteria", "candidate"})
# The harness's source files; their file-set sha256 is the harness sha256 that a
# pre-dispatch manifest fixes (``run_identity.harness``).
HARNESS_FILES = (*_CODE_FILES, "evals/deeptwin/q01_release_manifest.py")
# Critic-configuration fields the offline transport cannot observe at dispatch.
UNCHECKABLE_FIELDS = ("max_tokens",)


def harness_identity() -> dict:
    """``{"version", "sha256"}`` of this harness, as a pre-dispatch manifest must fix it."""
    return {"version": HARNESS_VERSION, "sha256": file_set_sha256(REPO_ROOT, HARNESS_FILES)}


def critic_prompt_digest(task_dir: Path = TASK_DIR) -> str:
    """``critic_configuration.critic_prompt_digest``: the pinned stage instruction plus the
    product renderer and generation profiles that compose each call's system prompt."""
    parts = {INSTRUCTION_FILE: digest((Path(task_dir) / INSTRUCTION_FILE).read_bytes())}
    parts.update({relative: digest((REPO_ROOT / relative).read_bytes()) for relative in (
        "app/services/design_criticism_live.py", "app/generation_profiles.py")})
    return sha256(canonical_bytes(parts)).hexdigest()


class ReaderRefusal(PermissionError):
    """A path outside the agent-visible allowlist was requested."""


class TaskReader:
    """The single agent-material read path; every read is logged.

    Only ``instruction.md``, ``environment/manifest.json`` and the case files it
    lists (with matching hashes) are readable. Task.md, task.toml, verifiers,
    tests, the World Skill, absolute paths, traversal and symlinks are refused.
    """

    def __init__(self, task_dir: Path = TASK_DIR):
        self.task_dir = Path(task_dir).resolve()
        self.log: list[dict] = []
        self._allowed = {INSTRUCTION_FILE: None, ENVIRONMENT_MANIFEST: None}

    def _path(self, relative: str) -> Path:
        if type(relative) is not str or not relative or relative.startswith("/") or "\\" in relative:
            raise ReaderRefusal("only relative allowlisted paths are readable")
        parts = relative.split("/")
        if any(part in {"", ".", ".."} for part in parts) or relative not in self._allowed:
            raise ReaderRefusal("path is outside the agent-visible allowlist")
        path = self.task_dir.joinpath(*parts)
        for component in (path, *path.parents):
            if component == self.task_dir.parent:
                break
            if component.is_symlink():
                raise ReaderRefusal("symlinked agent material is refused")
        return path

    def read_bytes(self, relative: str) -> bytes:
        try:
            path = self._path(relative)
            data = path.read_bytes()
            expected = self._allowed[relative]
            if expected is not None and digest(data) != expected:
                raise ReaderRefusal("agent material hash differs from the environment manifest")
        except ReaderRefusal:
            self.log.append({"path": relative if type(relative) is str else repr(relative), "outcome": "refused"})
            raise
        except OSError:
            self.log.append({"path": relative, "outcome": "missing"})
            raise ReaderRefusal("agent material is missing") from None
        self.log.append({"path": relative, "outcome": "read", "sha256": digest(data)})
        return data

    def manifest(self) -> dict:
        manifest = json.loads(self.read_bytes(ENVIRONMENT_MANIFEST))
        if type(manifest) is not dict or manifest.get("schema") != ENVIRONMENT_SCHEMA:
            raise ReaderRefusal("unsupported environment manifest")
        for entry in manifest["cases"]:
            self._allowed[entry["path"]] = entry["sha256"]
        return manifest

    def case(self, case_id: str) -> tuple[dict, str]:
        manifest = self.manifest()
        entry = next((item for item in manifest["cases"] if item["case_id"] == case_id), None)
        if entry is None:
            raise ReaderRefusal("unknown case id")
        data = self.read_bytes(entry["path"])
        case = json.loads(data)
        if (type(case) is not dict or case.get("schema") != CASE_SCHEMA or case.get("case_id") != case_id
                or set(case) != {"schema", "case_id", "source", "authored_counterexamples"}):
            raise ReaderRefusal("frozen case shape mismatch")
        return case, digest(data)

    def instructions(self) -> dict[str, str]:
        data = self.read_bytes(INSTRUCTION_FILE)
        if digest(data) != INSTRUCTION_SHA256:
            self.log.append({"path": INSTRUCTION_FILE, "outcome": "refused"})
            raise ReaderRefusal("instruction differs from the reviewed, pinned instruction")
        text = data.decode("utf-8")
        sections, current = {}, None
        for line in text.splitlines():
            if line.startswith("## "):
                current = line[3:].strip()
                sections[current] = []
            elif current is not None:
                sections[current].append(line)
        result = {name: "\n".join(lines).strip() for name, lines in sections.items()}
        if set(result) != {stage.value for stage in STAGES} or not all(result.values()):
            raise ReaderRefusal("instruction must have exactly one nonempty section per stage")
        return result


# ---------------------------------------------------------------- isolation


def _strings(value):
    if type(value) is str:
        yield value
    elif type(value) is dict:
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif type(value) is list:
        for item in value:
            yield from _strings(item)


def _fragments(text: str):
    for line in text.splitlines():
        for piece in _SPLIT.split(line):
            piece = piece.strip(" -:.,\t\"'")
            if len(piece) >= _FRAGMENT_MIN:
                yield piece


@dataclass(frozen=True)
class LeakScanner:
    """Fragments of control-plane files and case ids that no agent input may contain."""

    fragments: tuple[str, ...]
    case_ids: tuple[str, ...]

    @classmethod
    def build(cls, allowed_corpus: str, case_ids, repo_root: Path = REPO_ROOT) -> LeakScanner:
        fragments = set()
        for relative in CONTROL_PLANE_FILES:
            path = repo_root / relative
            if path.exists():  # a missing control-plane file cannot leak
                fragments.update(_fragments(path.read_text(encoding="utf-8")))
        # Material the agent is allowed to see (instruction, frozen cases,
        # product profiles) is not control-plane content even if quoted there.
        return cls(tuple(sorted(item for item in fragments if item not in allowed_corpus)),
                   tuple(sorted(case_ids)))

    def scan(self, *texts: str, case_ids: bool = True) -> list[str]:
        joined = "\n".join(texts)
        hits = [("case_id", item) for item in self.case_ids if case_ids and item in joined]
        hits += [("control_plane", item) for item in self.fragments if item in joined]
        return [f"{kind}:{sha256(item.encode('utf-8')).hexdigest()[:16]}" for kind, item in hits]


def allowed_corpus(instructions: dict[str, str]) -> str:
    """Agent-visible text from trusted sources only (never from the loaded case file).

    The pinned instruction, the product profiles and a fresh materialization
    of ``q01_materials`` may legitimately overlap control-plane prose; nothing
    read from a (possibly altered) frozen case can widen this corpus.
    """
    # The public materials path labels authored counterexamples; it is not answer content.
    parts = list(instructions.values()) + [_CITATION_RULE, q01_cases.AUTHORED_SOURCE]
    for stage in STAGES:
        profile = profile_for(stage)
        parts += [profile.base_instructions, profile.developer_instructions]
    for case in q01_cases.materialize_all():
        parts += list(_strings(case["source"]))
        for item in case["authored_counterexamples"]:
            parts += list(_strings(item["counterexample"]))
    return "\n".join(parts)


# ---------------------------------------------------------------- stages


def stage_input(purpose: GenerationPurpose, case: dict, *, counterexample=None, validity=None) -> PreparedInput:
    source = deepcopy(case["source"])
    if counterexample is not None:
        source["counterexample"] = deepcopy(counterexample)
    if validity is not None:
        source["validity"] = deepcopy(validity)
    return prepare_input(purpose, source)


def render_stage(prepared: PreparedInput, instructions: dict[str, str]) -> tuple[str, str]:
    """Product rendering, plus the exact Task instruction for this stage."""
    system, user = render_criticism_prompt(prepared)
    return system + "\n" + instructions[prepared.purpose.value], user


def validity_evidence(parsed: dict) -> dict:
    return {name: deepcopy(parsed[name]) for name in VALIDITY_FIELDS}


def _sha(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def code_hashes(instructions: dict[str, str], case_sha: str) -> dict[str, str]:
    hashes = {relative: digest((REPO_ROOT / relative).read_bytes()) for relative in _CODE_FILES}
    hashes.update({f"instruction:{name}": _sha(text) for name, text in instructions.items()})
    hashes["case"] = case_sha
    return hashes


class _CallableTransport(OfflineTransport):
    """Adapts a caller ``(system, user) -> str`` to the OfflineRunner boundary.

    The adapter refuses a prompt other than the rendered user payload. The
    callable reports no model identity, so the selected model is declared by
    the harness (``MODEL_IDENTITY``), not attested by the transport.
    """

    def __init__(self, turn, system: str, user: str):
        self._turn, self._system, self._user = turn, system, user

    def generate(self, prompt, schema, cancel_event, *, selection):
        if prompt != self._user:
            raise ValueError("dispatched prompt differs from the rendered user payload")
        return {"text": self._turn(self._system, self._user), "model": selection["model"]}


@dataclass(frozen=True)
class TrialConfig:
    selections: object
    work_id: str
    selection_version: int
    call_seconds: float = 120.0
    run_seconds: float = 3600.0
    max_proposed_chains: int = 16


@dataclass(frozen=True)
class PreDispatch:
    """One release trial's committed pre-dispatch manifest and fixed slot (release-v5 ``pre_dispatch``).

    ``committed_sha256`` is the value committed to the repository (or externally
    timestamped) before the first dispatch, and ``commit_ref`` says where:
    ``{"kind": "git_commit" | "external_timestamp", "ref": ...}`` (the commit id, or
    the timestamp authority's reference). It is written into the dispatch journal
    header and every trial record, and audited after the verdict. ``harness``
    (mandatory) is the ``{"version", "sha256"}`` the operator expects to run; it must
    equal both ``run_identity.harness`` and ``harness_identity()`` of the code actually
    running. ``lens_pack`` is the critic configuration's lens pack (never read from the
    sealed bundle): it must hash to ``critic_configuration.lens_refs_and_digests``.
    ``repetition`` fixes this trial's slot ``(case id, repetition)`` before dispatch:
    the harness journals the trial id with that slot before the first call, and only
    when it is the next slot of ``run_identity.planned_slots`` (audit 4, B1).
    """

    manifest_path: Path
    committed_sha256: str
    harness: dict
    lens_pack: dict
    repetition: int
    commit_ref: dict


def _journal_path(manifest: dict) -> Path:
    return Path(manifest["run_identity"]["dispatch_journal"]["path"])


def slot_errors(state: JournalState, planned: list, case_id: str, repetition: int) -> list[str]:
    """The trial's slot must be the next planned slot not yet in the journal."""
    used = len(state.dispatches)
    if used >= len(planned):
        return ["no_planned_slot_left"]
    if planned[used] != {"case_id": case_id, "repetition": repetition}:
        return ["slot_is_not_the_next_planned_slot"]
    return []


class DispatchJournal:
    """Writer of one manifest's append-only, hash-chained dispatch journal (release-v5, audit 4 B1).

    The file is JSON lines (``q01_release_manifest.parse_journal`` reads and checks it):
    a header binding the manifest sha256, the commit reference and the planned slot
    list, then one ``dispatch`` entry ``{seq, trial_id, case_id, repetition, prev,
    entry_sha256}`` per trial. Under an exclusive ``flock`` the writer re-reads and
    chain-checks the whole file, refuses a trial whose slot is not the next planned
    slot, appends with ``O_APPEND`` and fsyncs the file (and its directory when
    it creates it) before returning, so the entry is durable before the trial's first
    call. It never rewrites or truncates an entry.
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def dispatch(self, *, manifest_sha256: str, commit_ref: dict, planned: list, trial_id: str, case_id: str,
                 repetition: int) -> tuple[dict | None, list[str]]:
        path = self.path
        if not path.is_absolute():
            return None, ["dispatch_journal:path_not_absolute"]
        try:
            if path.is_symlink():
                return None, ["dispatch_journal:journal_symlink_refused"]
            created = not path.exists()
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except OSError:
            return None, ["dispatch_journal:journal_unwritable"]
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            chunks = []
            while chunk := os.pread(fd, 1 << 20, sum(len(item) for item in chunks)):
                chunks.append(chunk)
            state = parse_journal(b"".join(chunks), path)
            if not state.ok:
                return None, [f"dispatch_journal:{error}" for error in state.errors]
            pending = []
            if state.header is None:
                header = {"schema": JOURNAL_SCHEMA, "seq": 0, "kind": "open", "manifest_sha256": manifest_sha256,
                          "commit_ref": deepcopy(commit_ref), "planned_slots_sha256": planned_slots_sha256(planned),
                          "prev": JOURNAL_GENESIS}
                header["entry_sha256"] = journal_entry_sha256(header)
                state = JournalState(path, header, (), header["entry_sha256"], ())
                pending.append(header)
            errors = journal_problems(state, manifest_sha256, planned)
            if state.header["commit_ref"] != commit_ref:
                errors.append("commit_ref_differs_from_dispatch_journal")
            errors = errors or slot_errors(state, planned, case_id, repetition)
            if errors:
                return None, errors
            entry = {"seq": len(state.dispatches) + 1, "kind": "dispatch", "trial_id": trial_id,
                     "case_id": case_id, "repetition": repetition, "prev": state.head}
            entry["entry_sha256"] = journal_entry_sha256(entry)
            pending.append(entry)
            data = b"".join(journal_line(item) for item in pending)
            while data:
                data = data[os.write(fd, data):]
            os.fsync(fd)
        except OSError:
            return None, ["dispatch_journal:journal_unwritable"]
        finally:
            os.close(fd)
        if created:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return entry, []


def pre_dispatch_errors(pre_dispatch: PreDispatch, case_id: str, config: TrialConfig,
                        task_dir: Path = TASK_DIR) -> tuple[dict, list[str], dict | None]:
    """Why dispatch must be refused (empty when the manifest verifies and binds this trial).

    Besides the manifest itself, the trial must match it: the harness identity is the
    running code's, the environment manifest the harness is about to read hashes to
    ``run_identity.sealed_dataset_sha256``, the case is in ``case_order``, the slot's
    repetition is a planned one, the commit reference is well formed, and every
    critic-configuration field observable before dispatch equals the running
    configuration (contract and parser version, prompt digest, chain limit, call and run
    deadlines, lens pack digests). Provider, mode, model and effort are checked per call
    against the frozen selection; ``max_tokens`` is not observable offline and is listed
    as unchecked. The dispatch journal is checked and written afterwards
    (``DispatchJournal``), immediately before the first read.
    """
    try:
        environment_sha = digest((Path(task_dir) / ENVIRONMENT_MANIFEST).read_bytes())
    except OSError:
        environment_sha = None
    errors = []
    running = harness_identity()
    if type(pre_dispatch.harness) is not dict or pre_dispatch.harness != running:
        errors.append("harness_is_not_the_running_code")
    repetition = pre_dispatch.repetition
    if type(repetition) is not int or not 1 <= repetition <= REPETITIONS_PER_CASE:
        errors.append("repetition_is_not_a_planned_repetition")
    errors += commit_ref_errors(pre_dispatch.commit_ref)
    check = check_pre_dispatch_manifest(Path(pre_dispatch.manifest_path),
                                        committed_sha256=pre_dispatch.committed_sha256, harness=running)
    errors += list(check.errors)
    configuration = None
    if schema_valid(check):
        manifest = check.manifest
        configuration = manifest["critic_configuration"]
        if (configuration["contract_version"], configuration["parser_version"]) != (CONTRACT_VERSION,
                                                                                    PARSER_VERSION):
            errors.append("contract_or_parser_version_differs_from_manifest")
        try:
            prompt_digest = critic_prompt_digest(task_dir)
        except OSError:
            prompt_digest = None
        if configuration["critic_prompt_digest"] != prompt_digest:
            errors.append("critic_prompt_digest_differs_from_manifest")
        if configuration["max_proposed_chains"] != config.max_proposed_chains:
            errors.append("max_proposed_chains_differs_from_manifest")
        deadlines = configuration["call_and_run_deadlines"]
        for name in ("call_seconds", "run_seconds"):
            if deadlines[name] != getattr(config, name):
                errors.append(f"{name}_differs_from_manifest")
        try:
            lens_refs = lens_refs_and_digests(pre_dispatch.lens_pack)
        except (ValueError, KeyError, TypeError):
            lens_refs = None
        if lens_refs != configuration["lens_refs_and_digests"]:
            errors.append("lens_pack_differs_from_configuration")
        if case_id not in manifest["run_identity"]["case_order"]["order"]:
            errors.append("case_not_in_manifest_case_order")
        if environment_sha != manifest["run_identity"]["sealed_dataset_sha256"]:
            errors.append("environment_differs_from_sealed_dataset_sha256")
    return ({"manifest_sha256": check.manifest_sha256, "committed_sha256": pre_dispatch.committed_sha256,
             "commit_ref": deepcopy(pre_dispatch.commit_ref),
             "slot": {"case_id": case_id, "repetition": repetition},
             "environment_manifest_sha256": environment_sha, "harness": running,
             "unchecked_configuration_fields": list(UNCHECKABLE_FIELDS), "journal": None, "errors": errors},
            errors, configuration)


def journal_dispatch(pre_dispatch: PreDispatch, case_id: str, trial_id: str) -> tuple[dict | None, list[str]]:
    """Write this trial's slot to the manifest's dispatch journal (before any read or call)."""
    check = check_pre_dispatch_manifest(Path(pre_dispatch.manifest_path),
                                        committed_sha256=pre_dispatch.committed_sha256)
    if not schema_valid(check):
        return None, ["dispatch_journal:manifest_unverified"]
    manifest = check.manifest
    journal = DispatchJournal(_journal_path(manifest))
    entry, errors = journal.dispatch(manifest_sha256=check.manifest_sha256, commit_ref=pre_dispatch.commit_ref,
                                     planned=manifest["run_identity"]["planned_slots"], trial_id=trial_id,
                                     case_id=case_id, repetition=pre_dispatch.repetition)
    if entry is None:
        return None, errors
    return {"path": str(journal.path), "seq": entry["seq"], "entry_sha256": entry["entry_sha256"],
            "prev_sha256": entry["prev"]}, []


class _Stop(Exception):
    def __init__(self, status, cause=None, output_contract=None):
        super().__init__(cause)
        self.status, self.cause, self.output_contract = status, cause, output_contract


_TERMINAL_CAUSES = {"cancelled": "cancelled", "timed_out": "timed_out", "interrupted": "interrupted"}


class Q01Trial:
    """One fresh trial of one frozen case. Not reusable."""

    def __init__(self, case_id: str, turn, *, base_dir: Path, config: TrialConfig, task_dir: Path = TASK_DIR,
                 pre_dispatch: PreDispatch | None = None):
        if not callable(turn):
            raise ValueError("a callable (system, user) -> str transport is required")
        if type(config) is not TrialConfig:
            raise ValueError("an explicit TrialConfig is required")
        if type(config.max_proposed_chains) is not int or not 0 <= config.max_proposed_chains <= 16:
            raise ValueError("max_proposed_chains must be an integer from 0 to 16")
        if pre_dispatch is not None and (type(pre_dispatch) is not PreDispatch
                                         or type(pre_dispatch.harness) is not dict
                                         or type(pre_dispatch.lens_pack) is not dict):
            raise TypeError("pre_dispatch must be a PreDispatch with a harness identity and a lens pack")
        self.case_id, self.turn, self.config = case_id, turn, config
        self.pre_dispatch = pre_dispatch
        self._configuration = None  # the manifest's critic configuration (release trials)
        self._journal_entry = None  # this trial's dispatch journal entry (release trials)
        self.task_dir = Path(task_dir)
        self.trial_id = "t" + uuid4().hex
        base = Path(base_dir)
        if not base.is_absolute():
            raise ValueError("an absolute base directory is required")
        self.trial_dir = base / self.trial_id
        self.trial_dir.mkdir(mode=0o700, parents=False, exist_ok=False)  # fresh state per trial
        self._lock = Lock()
        self._active_request = None
        self._runner = None
        self._started = False

    def cancel(self) -> bool:
        """Cancel the active call, if any (commit first, then signal)."""
        with self._lock:
            runner, request = self._runner, self._active_request
        if runner is None or request is None:
            return False
        return runner.cancel(request)

    # -------------------------------------------------------------- driving

    def run(self) -> dict:
        if self._started:
            raise RuntimeError("a Q01Trial runs once; create a new trial for fresh state")
        self._started = True
        reader = TaskReader(self.task_dir)
        record = {"schema": RECORD_SCHEMA, "trial_id": self.trial_id, "run_id": self.trial_id,
                  "case_id": self.case_id, "status": None, "output_contract": None, "cause": None,
                  "semantic": "not_checked", "score": None, "model_identity": MODEL_IDENTITY,
                  "ledger_path": None, "case_sha256": None, "calls": [], "leak_scan": None,
                  "stages": {"review": None, "proposal": None, "authored_chains": [], "proposed_chains": [],
                             "proposed_not_driven": 0},
                  "access_log": reader.log}
        if self.pre_dispatch is not None:
            # release runs: no read and no dispatch unless the committed manifest verifies
            # and this trial's (case, repetition) slot is journalled as the next planned slot
            record["slot"] = {"case_id": self.case_id, "repetition": self.pre_dispatch.repetition}
            record["pre_dispatch"], errors, self._configuration = pre_dispatch_errors(
                self.pre_dispatch, self.case_id, self.config, self.task_dir)
            errors = list(errors)
            if not errors:
                self._journal_entry, journal_errors = journal_dispatch(self.pre_dispatch, self.case_id,
                                                                       self.trial_id)
                errors += journal_errors
                record["pre_dispatch"]["journal"] = self._journal_entry
            record["pre_dispatch"]["errors"] = errors
            if errors:
                record["status"], record["cause"] = "invalid", "pre_dispatch_manifest_unverified"
                (self.trial_dir / "trial-record.json").write_text(canonical(record), encoding="utf-8")
                return record
        try:
            case, case_sha = reader.case(self.case_id)
            if self.pre_dispatch is not None:
                if type(case["source"]) is not dict or "lens_pack" in case["source"]:
                    # the lens pack is critic configuration, never sealed dataset material
                    raise _Stop("invalid", "sealed_case_carries_a_lens_pack")
                if set(case["source"]) != SOURCE_KEYS:
                    raise _Stop("invalid", "sealed_case_source_keys_not_allowlisted")
                case = {**case, "source": {**case["source"], "lens_pack": deepcopy(self.pre_dispatch.lens_pack)}}
            instructions = reader.instructions()
            manifest = reader.manifest()
            record["case_sha256"] = case_sha
            scanner = LeakScanner.build(allowed_corpus(instructions),
                                        [entry["case_id"] for entry in manifest["cases"]])
            record["leak_scan"] = {"fragments": len(scanner.fragments), "case_ids": len(scanner.case_ids),
                                   "hits": []}
            self._drive(case, case_sha, instructions, scanner, record)
            record["status"], record["output_contract"] = "completed", "valid"
        except _Stop as stop:
            record["status"], record["cause"] = stop.status, stop.cause
            record["output_contract"] = stop.output_contract
        except ReaderRefusal:
            record["status"], record["cause"] = "invalid", "environment_read_refused"
        except InputContractError:
            record["status"], record["cause"] = "invalid", "input_contract"
        record["access_log"] = list(reader.log)
        (self.trial_dir / "trial-record.json").write_text(canonical(record), encoding="utf-8")
        return record

    def _drive(self, case, case_sha, instructions, scanner, record):
        authored = case["authored_counterexamples"]
        max_calls = 2 + 2 * (len(authored) + self.config.max_proposed_chains)
        ledger_path = self.trial_dir / "audit" / "eval.sqlite3"
        record["ledger_path"] = str(ledger_path)
        try:
            ledger = Ledger(ledger_path)
            ledger.open_run(self.trial_id, max_calls=max_calls, max_seconds=self.config.run_seconds)
            runner = OfflineRunner(ledger, self.trial_dir / "runtime", self.config.selections)
        except (ValueError, TypeError, OSError):
            raise _Stop("invalid", "trial_setup_refused") from None
        with self._lock:
            self._runner = runner
        hashes = code_hashes(instructions, case_sha)
        if self._journal_entry is not None:
            # binds every frozen call of this trial to its dispatch journal entry
            hashes["dispatch_journal_entry"] = self._journal_entry["entry_sha256"]
        counter = iter(range(1, 10_000))

        def call(prepared, lineage):
            return self._call(ledger, runner, prepared, lineage, instructions, scanner, hashes,
                              case_sha, next(counter), record)

        review_request, review = call(stage_input(P.REVIEW, case), None)
        record["stages"]["review"] = review
        proposal_request, proposal = call(stage_input(P.COUNTEREXAMPLE_PROPOSAL, case), (review_request, None))
        record["stages"]["proposal"] = proposal
        candidate = case["source"]["candidate"]

        def chain(counterexample, lineage):
            validity_request, validity = call(
                stage_input(P.COUNTEREXAMPLE_VALIDITY, case, counterexample=counterexample), lineage)
            item = {"counterexample_id": counterexample["id"], "validity": validity, "response": None}
            evidence = validity_evidence(validity)
            try:
                (evidence_sha,) = ledger.register_result_evidence(validity_request, [evidence])
            except ValueError:
                raise _Stop("invalid", "lineage_refused") from None
            _, item["response"] = call(stage_input(P.CANDIDATE_RESPONSE, case, counterexample=counterexample,
                                                   validity=evidence), (validity_request, evidence_sha))
            return item

        for entry in authored:
            counterexample = entry["counterexample"]
            try:
                sha = ledger.register_authored_evidence(
                    self.trial_id, candidate_id=candidate["id"], candidate_version=candidate["version"],
                    item=counterexample, source=entry["source"])
            except ValueError:
                raise _Stop("invalid", "lineage_refused") from None
            record["stages"]["authored_chains"].append(chain(counterexample, (None, sha)))

        proposed = proposal["counterexamples"][: self.config.max_proposed_chains]
        record["stages"]["proposed_not_driven"] = len(proposal["counterexamples"]) - len(proposed)
        if proposed:
            try:
                shas = ledger.register_result_evidence(proposal_request, proposed)
            except ValueError:
                raise _Stop("invalid", "lineage_refused") from None
            for counterexample, sha in zip(proposed, shas):
                record["stages"]["proposed_chains"].append(chain(counterexample, (proposal_request, sha)))

    def _check_call_configuration(self, prepared, frozen):
        """Release trials: this exact call runs the manifest's critic configuration."""
        configuration = self._configuration
        manifest = json.loads(prepared.manifest_json)
        if (manifest["contract_version"], manifest["parser_version"]) != (configuration["contract_version"],
                                                                          configuration["parser_version"]):
            raise _Stop("invalid", "contract_differs_from_configuration")
        if (prepared.purpose is P.COUNTEREXAMPLE_PROPOSAL
                and prepared_lens_refs(manifest) != configuration["lens_refs_and_digests"]):
            # the lens pack actually sent must hash to critic_configuration.lens_refs_and_digests
            raise _Stop("invalid", "lens_pack_differs_from_configuration")
        selection = json.loads(frozen.selection_json)
        if any(selection.get(name) != configuration[name] for name in ("provider", "mode", "model", "effort")):
            raise _Stop("invalid", "selection_differs_from_configuration")

    def _call(self, ledger, runner, prepared, lineage, instructions, scanner, hashes, case_sha, index, record):
        system, user = render_stage(prepared, instructions)
        request_id = f"{self.trial_id}-s{index:02d}-{prepared.purpose.value.replace('_', '-')}"
        manifest = {
            "index": index, "purpose": prepared.purpose.value, "request_id": request_id,
            "lineage": (None if lineage is None else
                        {"kind": "authored" if lineage[0] is None else "request",
                         "parent_request_id": lineage[0], "evidence_sha256": lineage[1]}),
            "system_sha256": _sha(system), "user_sha256": _sha(user),
            "schema_sha256": _sha(prepared.schema_json),
            "instruction_sha256": _sha(instructions[prepared.purpose.value]),
            "prepared_manifest": json.loads(prepared.manifest_json),
            "visible_inputs": sorted(json.loads(prepared.prompt)["input"]),
            "system_bytes": len(system.encode("utf-8")), "user_bytes": len(user.encode("utf-8")),
            "case_sha256": case_sha, "model_identity": MODEL_IDENTITY,
        }
        entry = {"manifest": manifest, "ledger": None}
        record["calls"].append(entry)
        hits = scanner.scan(system, user)
        if hits:
            record["leak_scan"]["hits"].extend(hits)
            raise _Stop("invalid", "isolation_boundary")
        config = self.config
        try:
            frozen = freeze_call(prepared, config.selections, config.work_id, config.selection_version,
                                 run_id=self.trial_id, request_id=request_id, call_seconds=config.call_seconds,
                                 code_hashes=hashes)
        except InputContractError:
            raise _Stop("invalid", "input_contract") from None
        except (ValueError, RuntimeError, KeyError):
            raise _Stop("invalid", "selection_or_freeze_refused") from None
        if self._configuration is not None:
            self._check_call_configuration(prepared, frozen)
        with self._lock:
            self._active_request = request_id
        try:
            result = runner.run(frozen, prepared, lambda _context: _CallableTransport(self.turn, system, user),
                                lineage=lineage)
        except InputContractError:
            raise _Stop("invalid", "input_contract") from None
        except ValueError:
            raise _Stop("invalid", "reservation_refused") from None
        except RuntimeError:
            raise _Stop("invalid", "audit_fault") from None
        finally:
            with self._lock:
                self._active_request = None
        entry["ledger"] = result
        state, details = result["state"], result["details"]
        if state == "completed":
            if details.get("output_contract") == "valid":
                return request_id, details["parsed"]
            raise _Stop("completed", "model_output_invalid", "model_output_invalid")
        if state == "invalid":
            raise _Stop("invalid", details.get("reason", "transport_invalid"))
        raise _Stop("invalid", _TERMINAL_CAUSES.get(state, "unknown_terminal_state"))


def run_trial(case_id: str, turn, *, base_dir: Path, config: TrialConfig, task_dir: Path = TASK_DIR) -> dict:
    return Q01Trial(case_id, turn, base_dir=base_dir, config=config, task_dir=task_dir).run()


def run_release_trial(case_id: str, turn, *, base_dir: Path, config: TrialConfig, pre_dispatch: PreDispatch,
                      task_dir: Path = TASK_DIR) -> dict:
    """A release-v5 trial: refuses to dispatch without a verifying committed pre-dispatch manifest and
    journals its (case, repetition) slot before the first call."""
    if type(pre_dispatch) is not PreDispatch:
        raise TypeError("a release trial requires its committed pre-dispatch manifest")
    if type(pre_dispatch.harness) is not dict or type(pre_dispatch.lens_pack) is not dict:
        raise TypeError("a release trial requires the expected harness identity and the configuration's lens pack")
    return Q01Trial(case_id, turn, base_dir=base_dir, config=config, task_dir=task_dir,
                    pre_dispatch=pre_dispatch).run()


# ---------------------------------------------------------------- readiness


REFUSAL_PROBES = (
    "Task.md", "task.toml", "../../verifiers/critic.py", "../../verifiers/sealed_critic.py",
    "../../tests/test_critic_verifier.py",
    "../../../../.agents/skills/deeptwin-eval-world/SKILL.md", "/etc/passwd", "environment/../Task.md",
    "environment/cases/../../Task.md",
)


def readiness(task_dir: Path = TASK_DIR) -> dict:
    """Prove completeness and isolation with the same read path trials use."""
    checks = []

    def check(name, ok, detail=None):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    reader = TaskReader(task_dir)
    try:
        manifest = reader.manifest()
        instructions = reader.instructions()
        cases = [reader.case(entry["case_id"])[0] for entry in manifest["cases"]]
    except (ReaderRefusal, ValueError, KeyError) as exc:
        check("environment_readable", False, type(exc).__name__)
        return {"ready": False, "checks": checks, "access_log": reader.log}
    check("environment_readable", True, len(cases))
    expected = q01_cases.materialize_all()
    check("cases_match_materials", canonical(cases) == canonical(expected),
          "frozen cases equal a fresh materialization from q01_materials")
    check("case_shape_has_no_labels", all(set(case) == {"schema", "case_id", "source", "authored_counterexamples"}
                                          for case in cases))
    refused = []
    for probe in REFUSAL_PROBES:
        try:
            reader.read_bytes(probe)
        except ReaderRefusal:
            refused.append(probe)
    check("control_plane_refused", refused == list(REFUSAL_PROBES), len(refused))
    scanner = LeakScanner.build(allowed_corpus(instructions), [case["case_id"] for case in cases])
    check("scanner_has_control_plane_fragments", len(scanner.fragments) > 50, len(scanner.fragments))
    # The agent-material part of each case file (the wrapper keys and case id are harness-only;
    # ids are checked on the rendered agent inputs below).
    environment_text = "\n".join(canonical([case["source"], [item["counterexample"] for item in
                                                              case["authored_counterexamples"]]])
                                 for case in cases)
    check("environment_files_clean",
          not scanner.scan(environment_text, "\n".join(instructions.values()), case_ids=False))
    leaks, keys_ok = [], True
    allowed_keys = {P.REVIEW: {"originals", "criteria", "candidate"},
                    P.COUNTEREXAMPLE_PROPOSAL: {"originals", "criteria", "candidate", "lens_pack"},
                    P.COUNTEREXAMPLE_VALIDITY: {"originals", "criteria", "candidate", "counterexample"}}
    for case in cases:
        prepared = [stage_input(P.REVIEW, case), stage_input(P.COUNTEREXAMPLE_PROPOSAL, case)]
        prepared += [stage_input(P.COUNTEREXAMPLE_VALIDITY, case, counterexample=item["counterexample"])
                     for item in case["authored_counterexamples"]]
        for item in prepared:
            system, user = render_stage(item, instructions)
            leaks += scanner.scan(system, user)
            keys_ok &= set(json.loads(item.prompt)["input"]) == allowed_keys[item.purpose]
    check("stage_inputs_clean", not leaks, len(leaks))
    check("stage_inputs_allowlisted", keys_ok)
    return {"ready": all(item["ok"] for item in checks), "checks": checks, "access_log": reader.log}
