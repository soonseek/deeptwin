"""T077 run dispatcher for release-v7 manifests (control plane; never agent-visible).

``evals/deeptwin/qualification/release-v7/qualification_design.json`` names a dispatcher
that "authorizes and sequences the trials of a manifest" and enforces the USD hard stop
(``pre_dispatch.dispatch_journal.stop``). release-v7 pins the harness, the verifier and the
gate but not this module: it is new code that only CALLS the pinned modules
(``q01_harness.run_release_trial`` / ``journal_stop``, ``sealed_critic.verify_trial`` /
``verify_suite`` / ``build_suite_record`` and the product gate
``critic_qualification_from_suite``); it re-implements none of their checks. Until a later
design version pins it, no run it drives is a release run (the design says so in ``open``).

What it does, in order (``Dispatcher.run``):

1. **Refuses** a manifest that does not verify: ``check_pre_dispatch_manifest`` against the
   committed sha256, the running harness and the running verifier; a commit reference that
   is malformed or (for ``git_commit``, when a repository is given) whose commit does not
   contain the manifest sha256; a dispatch journal that belongs to another manifest.
2. **Attempt ledger** (``AttemptLedger``, persisted outside the repository): the manifest's
   ``attempt`` and ``prior_attempts`` must equal what the ledger holds for its critic
   configuration digest, and no other manifest recorded in the ledger (any configuration)
   may have used this sealed dataset, these expectations, or any of its case ids or case
   sha256s. The ledger closes the gap of manifests that list no prior attempt only for
   manifests that go through the same ledger (the design's second-manifest item stays
   organizational).
3. **Marks the sealed set spent** in the ledger (durably) before the first dispatch; the
   entry's outcome is ``incomplete`` until a suite verdict replaces it.
4. **Dispatches** the planned slots in journal order, one at a time (concurrency 1, no retry,
   no model fallback): the next slot is always ``planned_slots[len(journal dispatches)]``,
   so a restarted dispatcher resumes after the last journalled trial and never re-dispatches
   one (a trial journalled but without a record stays missing: the suite is incomplete).
   Before each trial the USD reservation (spent + judge reserve of every dispatched,
   not-yet-judged trial + the next trial's worst case) is compared with
   ``run_identity.usd_hard_stop``; when it could cross, the stop entry is journalled through
   ``q01_harness.journal_stop`` and nothing more is dispatched. The ``SpendMeter`` is the
   rig's per-call guard as well: a call whose worst case would cross the stop is never sent,
   the trial ends invalid, and the stop is journalled. An optional owner cap
   (``max_slots``) also ends the run with a journalled stop (e.g. a rehearsal subset).
5. **Verifies** every journalled trial exactly once, in journal order, in this process
   (``verify_trial`` with the run's judge; results are recognised in-process only), then the
   suite (``verify_suite``), the suite record (``build_suite_record``) and the product gate.
6. **Records** the outcome in the attempt ledger and writes the report sections the design's
   ``reporting`` list requires (``build_report``).

The two phases are deliberate: judging happens after the last dispatch, so a crash during
dispatch loses nothing (the new process verifies every trial once); a crash during judging
leaves judged trials that cannot be judged again (``trial_already_judged``), which makes the
suite incomplete, as the design requires.

Spend is an estimate from provider-reported token usage and the per-million-token prices the
caller supplies (``Pricing``); a dispatched call without observed usage is charged at its
pre-call worst case. The secret never reaches this module.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from app.services.critic_qualification import CriticQualificationError, critic_qualification_from_suite
from evals.deeptwin.harness.q01_harness import (
    PreDispatch,
    harness_identity,
    journal_stop,
    run_release_trial,
)
from evals.deeptwin.q01_release_manifest import (
    canonical_bytes,
    check_pre_dispatch_manifest,
    commit_ref_errors,
    read_journal,
    schema_valid,
)
from evals.deeptwin.verifiers.sealed_critic import (
    build_suite_record,
    load_release_run,
    load_sealed_expectations,
    load_sealed_materials_dir,
    read_judge_log,
    verifier_identity,
    verify_suite,
    verify_trial,
)

DISPATCHER_VERSION = "q01-t077-dispatcher-1"
LEDGER_SCHEMA = "q01-t077-attempt-ledger-1"
SPEND_SCHEMA = "q01-t077-spend-1"
REPORT_SCHEMA = "q01-t077-run-report-1"
# The pre-call bound on input tokens: the UTF-8 bytes of system and user plus this margin
# (the calibration plan's rule, reused).
INPUT_MARGIN_TOKENS = 256


class DispatchRefused(RuntimeError):
    """The dispatcher refuses to dispatch (nothing was sent)."""

    def __init__(self, errors):
        self.errors = tuple(errors)
        super().__init__("dispatch refused: " + ", ".join(self.errors))


class UsdHardStopReached(RuntimeError):
    """A call's worst case would cross the USD hard stop; it is never sent."""


# ---------------------------------------------------------------- spend


@dataclass(frozen=True)
class Pricing:
    """USD per million tokens; cache tokens are counted as input."""

    input_usd_per_million_tokens: float
    output_usd_per_million_tokens: float

    def worst(self, entry: dict) -> float:
        tokens_in = entry["system_bytes"] + entry["user_bytes"] + INPUT_MARGIN_TOKENS
        return (tokens_in * self.input_usd_per_million_tokens
                + entry["max_tokens"] * self.output_usd_per_million_tokens) / 1_000_000

    def charge(self, entry: dict) -> float:
        if entry.get("dispatched") is False:
            return 0.0
        if not entry.get("usage_observed"):
            return self.worst(entry)
        tokens_in = sum(entry.get(name) or 0 for name in ("input_tokens", "cache_creation_input_tokens",
                                                           "cache_read_input_tokens"))
        return (tokens_in * self.input_usd_per_million_tokens
                + (entry.get("output_tokens") or 0) * self.output_usd_per_million_tokens) / 1_000_000


_SPEND_KEYS = ("index", "role", "call_id", "model", "effort", "max_tokens", "system_bytes", "user_bytes",
               "dispatched", "provider_message_id", "observed_model", "request_id", "input_tokens",
               "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "usage_observed",
               "stop_reason", "state", "failure")


class SpendMeter:
    """The Claude rig's ``guard``: refuses a call that could cross the hard stop, charges every call.

    Every finished call is appended (and fsynced) to ``path`` as one JSON line, so a restarted
    dispatcher starts from the spend already incurred. ``arm`` sets the hard stop from the
    manifest; an unarmed meter refuses every call.
    """

    def __init__(self, pricing: Pricing, path: Path):
        self.pricing, self.path = pricing, Path(path)
        self.hard_stop: float | None = None
        self.tripped: str | None = None
        self.entries: list[dict] = []
        if self.path.exists():
            for line in self.path.read_bytes().splitlines():
                if line.strip():
                    self.entries.append(json.loads(line))

    @property
    def spent(self) -> float:
        return sum(entry["estimated_usd"] for entry in self.entries)

    def arm(self, hard_stop: float) -> None:
        if type(hard_stop) not in (int, float) or not hard_stop > 0:
            raise ValueError("a positive USD hard stop is required")
        self.hard_stop = float(hard_stop)

    def before_call(self, entry: dict) -> None:
        if self.hard_stop is None:
            raise UsdHardStopReached("the spend meter is not armed")
        worst = self.pricing.worst(entry)
        if self.spent + worst > self.hard_stop:
            self.tripped = (f"usd_hard_stop {self.hard_stop:.2f}: a {entry['role']} call's worst case "
                            f"{worst:.4f} would cross it at {self.spent:.4f} spent")
            raise UsdHardStopReached(self.tripped)

    def after_call(self, entry: dict) -> None:
        line = {key: entry.get(key) for key in _SPEND_KEYS}
        line["estimated_usd"] = round(self.pricing.charge(entry), 6)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, canonical_bytes({"schema": SPEND_SCHEMA, **line}) + b"\n")
            os.fsync(fd)
        finally:
            os.close(fd)
        self.entries.append({"schema": SPEND_SCHEMA, **line})
        if self.hard_stop is not None and self.spent > self.hard_stop and self.tripped is None:
            self.tripped = f"usd_hard_stop {self.hard_stop:.2f} crossed at {self.spent:.4f} spent"


@dataclass(frozen=True)
class Reservation:
    """Worst-case USD of one trial before it is dispatched, and of judging one trial afterwards.

    ``critic_calls`` is the harness's call bound for the case (2 + 2 x (authored
    counterexamples + max_proposed_chains)); each call is bounded by ``input_bytes_bound``
    (system + user) and the critic's ``max_tokens``. ``judge_calls`` x the judge bounds is the
    reserve held for judging a dispatched trial later.
    """

    pricing: Pricing
    critic_max_tokens: int
    max_proposed_chains: int
    input_bytes_bound: int = 32_000
    judge_calls: int = 0
    judge_max_tokens: int = 0
    judge_input_bytes_bound: int = 24_000

    def _call(self, input_bytes, max_tokens):
        return self.pricing.worst({"system_bytes": input_bytes, "user_bytes": 0, "max_tokens": max_tokens})

    def trial(self, authored: int) -> float:
        calls = 2 + 2 * (authored + self.max_proposed_chains)
        return calls * self._call(self.input_bytes_bound, self.critic_max_tokens)

    def judging(self) -> float:
        return self.judge_calls * self._call(self.judge_input_bytes_bound, self.judge_max_tokens)


# ---------------------------------------------------------------- attempt ledger


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class AttemptLedger:
    """Every attempt this ledger has seen, across critic configurations, sets and design versions.

    ``{"schema", "attempts": [{critic_configuration_digest, attempt, design_id, manifest_sha256,
    sealed_dataset_sha256, sealed_expectations_sha256, case_ids, case_sha256s, suite_outcome,
    state, spent_at, decided_at}]}``. An entry is written when the set is marked spent (before
    the first dispatch, ``state: spent``, outcome ``incomplete``) and updated once with the
    suite outcome (``state: decided``). Writes are atomic and made under an exclusive lock.
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def _read(self) -> dict:
        if not self.path.exists():
            return {"schema": LEDGER_SCHEMA, "attempts": []}
        data = json.loads(self.path.read_bytes())
        if type(data) is not dict or data.get("schema") != LEDGER_SCHEMA or type(data.get("attempts")) is not list:
            raise DispatchRefused(["attempt_ledger:unreadable"])
        return data

    def _locked(self, mutate):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = os.open(self.path.with_name(self.path.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self._read()
            result = mutate(data)
            _atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8"))
            return result
        finally:
            os.close(lock)

    def attempts(self) -> list[dict]:
        return deepcopy(self._read()["attempts"])

    def entry(self, manifest_sha256: str) -> dict | None:
        return next((item for item in self.attempts() if item["manifest_sha256"] == manifest_sha256), None)

    def prior_attempts(self, configuration_digest: str) -> list[dict]:
        """The ``prior_attempts`` list a new manifest for this configuration digest must carry."""
        return [{"attempt": item["attempt"], "design_id": item["design_id"],
                 "sealed_dataset_sha256": item["sealed_dataset_sha256"],
                 "sealed_expectations_sha256": item["sealed_expectations_sha256"],
                 "case_ids": list(item["case_ids"]), "case_sha256s": list(item["case_sha256s"]),
                 "suite_outcome": item["suite_outcome"]}
                for item in sorted(self.attempts(), key=lambda value: value["attempt"])
                if item["critic_configuration_digest"] == configuration_digest]

    def problems(self, manifest: dict, manifest_sha256: str) -> list[str]:
        """Why this manifest may not dispatch under this ledger (empty: new attempt or a resume)."""
        own = self.entry(manifest_sha256)
        if own is not None:
            return [] if own["state"] == "spent" else ["attempt_ledger:attempt_already_decided"]
        digest = manifest["critic_configuration_digest"]
        problems = []
        if manifest["prior_attempts"] != self.prior_attempts(digest):
            problems.append("attempt_ledger:prior_attempts_differ_from_ledger")
        identity = manifest["run_identity"]
        cases = identity["sealed_case_sha256s"]
        for item in self.attempts():
            if ({identity["sealed_dataset_sha256"], identity["sealed_expectations_sha256"]}
                    & {item["sealed_dataset_sha256"], item["sealed_expectations_sha256"]}
                    or set(cases) & set(item["case_ids"]) or set(cases.values()) & set(item["case_sha256s"])):
                problems.append("attempt_ledger:sealed_set_already_spent")
                break
        return problems

    def mark_spent(self, manifest: dict, manifest_sha256: str) -> dict:
        identity = manifest["run_identity"]
        entry = {"critic_configuration_digest": manifest["critic_configuration_digest"],
                 "attempt": manifest["attempt"], "design_id": manifest["design_id"],
                 "manifest_sha256": manifest_sha256,
                 "sealed_dataset_sha256": identity["sealed_dataset_sha256"],
                 "sealed_expectations_sha256": identity["sealed_expectations_sha256"],
                 "case_ids": sorted(identity["sealed_case_sha256s"]),
                 "case_sha256s": [identity["sealed_case_sha256s"][key] for key in sorted(identity["sealed_case_sha256s"])],
                 "suite_outcome": "incomplete", "state": "spent", "spent_at": _now(), "decided_at": None}

        def mutate(data):
            if any(item["manifest_sha256"] == manifest_sha256 for item in data["attempts"]):
                return None
            data["attempts"].append(entry)
            return entry
        self._locked(mutate)
        return entry

    def record_outcome(self, manifest_sha256: str, outcome: str) -> None:
        def mutate(data):
            for item in data["attempts"]:
                if item["manifest_sha256"] == manifest_sha256 and item["state"] == "spent":
                    item.update(suite_outcome=outcome, state="decided", decided_at=_now())
        self._locked(mutate)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def git_commit_contains(repo: Path, ref: str, needle: str) -> bool:
    """Whether the tree of commit ``ref`` in ``repo`` contains the string ``needle`` (the manifest sha256)."""
    try:
        result = subprocess.run(["git", "-C", str(repo), "grep", "-q", "-F", needle, ref], capture_output=True,
                                timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


# ---------------------------------------------------------------- dispatcher


@dataclass
class DispatchPlan:
    """Everything one attempt needs; nothing here is taken from the trials' outputs."""

    manifest_path: Path
    committed_sha256: str
    commit_ref: dict
    task_dir: Path          # the sealed environment the harness reads (instruction.md + environment/)
    expectations_path: Path  # read only by the verifier, at verify time
    profile_path: Path       # the independence profile the manifest pins
    lens_pack: dict          # the critic configuration's lens pack
    ledger: AttemptLedger
    meter: SpendMeter
    reservation: Reservation
    run_dir: Path            # where the dispatcher writes its report
    max_slots: int | None = None  # owner cap: journal a stop once this many trials are dispatched
    commit_repo: Path | None = None  # for git_commit refs: check the commit contains the manifest sha256
    labels: dict = field(default_factory=dict)  # free-form labels copied into the report (e.g. simulated)


@dataclass
class TrialRun:
    slot: dict
    trial_id: str | None
    record_path: Path | None
    status: str | None
    cause: str | None
    wall_seconds: float
    calls: list


class Dispatcher:
    """Sequences the trials of one committed release-v7 manifest (see the module docstring)."""

    def __init__(self, plan: DispatchPlan, *, turn, config, judge=None, after_trial: Callable | None = None):
        self.plan, self.turn, self.config, self.judge = plan, turn, config, judge
        self.after_trial = after_trial  # test hook: called with each TrialRun (e.g. to simulate a crash)
        self.trials: list[TrialRun] = []
        self.verification_calls: list = []
        self.manifest = None
        self.manifest_sha256 = None

    # ------------------------------------------------------------ checks

    def _load(self) -> dict:
        plan = self.plan
        data = Path(plan.manifest_path).read_bytes()
        check = check_pre_dispatch_manifest(data, committed_sha256=plan.committed_sha256,
                                            harness=harness_identity(), verifier=verifier_identity())
        errors = list(check.errors) + commit_ref_errors(plan.commit_ref)
        if not schema_valid(check):
            raise DispatchRefused(errors or ["manifest_unverified"])
        if (not errors and plan.commit_ref["kind"] == "git_commit" and plan.commit_repo is not None
                and not git_commit_contains(plan.commit_repo, plan.commit_ref["ref"], check.manifest_sha256)):
            errors.append("commit_ref:commit_does_not_contain_manifest_sha256")
        if errors:
            raise DispatchRefused(errors)
        self.manifest, self.manifest_sha256 = check.manifest, check.manifest_sha256
        return check.manifest

    def _pre_dispatch(self, repetition: int) -> PreDispatch:
        plan = self.plan
        return PreDispatch(Path(plan.manifest_path), plan.committed_sha256, harness_identity(),
                           deepcopy(plan.lens_pack), repetition, deepcopy(plan.commit_ref))

    def _journal(self):
        return read_journal(Path(self.manifest["run_identity"]["dispatch_journal"]["path"]))

    def _authored(self, case_id: str) -> int:
        environment = json.loads((Path(self.plan.task_dir) / "environment" / "manifest.json").read_bytes())
        entry = next(item for item in environment["cases"] if item["case_id"] == case_id)
        case = json.loads((Path(self.plan.task_dir) / entry["path"]).read_bytes())
        return len(case["authored_counterexamples"])

    def _stop(self, reason: str) -> dict:
        entry, errors = journal_stop(self._pre_dispatch(1), reason[:200])
        if entry is None:
            raise DispatchRefused(errors)
        return entry

    # ------------------------------------------------------------ phase 1

    def dispatch(self) -> dict:
        """Dispatch the remaining planned slots (resumes after the last journalled trial)."""
        manifest = self._load()
        identity = manifest["run_identity"]
        plan = self.plan
        ledger_problems = plan.ledger.problems(manifest, self.manifest_sha256)
        if ledger_problems:
            raise DispatchRefused(ledger_problems)
        journal_path = Path(identity["dispatch_journal"]["path"])
        state = read_journal(journal_path) if journal_path.exists() else None
        if state is not None and (not state.ok or state.header["manifest_sha256"] != self.manifest_sha256):
            raise DispatchRefused(["dispatch_journal:not_this_manifests_journal"])
        plan.meter.arm(identity["usd_hard_stop"])
        Path(identity["trial_base_dir"]["path"]).mkdir(parents=True, exist_ok=True)
        planned = identity["planned_slots"]
        if plan.ledger.entry(self.manifest_sha256) is None:
            # the first dispatched trial marks the set spent forever: recorded before it is sent
            plan.ledger.mark_spent(manifest, self.manifest_sha256)
        stop_reason = None
        while True:
            state = self._journal() if journal_path.exists() else None
            if state is not None and state.stopped:
                stop_reason = state.stop["reason"]
                break
            done = len(state.dispatches) if state is not None else 0
            if done >= len(planned):
                break
            if plan.max_slots is not None and done >= plan.max_slots:
                stop_reason = f"owner cap: {plan.max_slots} of {len(planned)} planned slots dispatched"
                self._stop(stop_reason)
                break
            slot = planned[done]
            reserve = (plan.meter.spent + plan.reservation.judging() * (done + 1)
                       + plan.reservation.trial(self._authored(slot["case_id"])))
            if reserve > identity["usd_hard_stop"]:
                stop_reason = (f"usd_hard_stop {identity['usd_hard_stop']:.2f}: slot {done + 1} could cross it "
                               f"(reserved {reserve:.4f}, spent {plan.meter.spent:.4f})")
                self._stop(stop_reason)
                break
            self._run_slot(slot)
            if plan.meter.tripped is not None:
                stop_reason = plan.meter.tripped
                self._stop(stop_reason)
                break
        return {"dispatched": len(self._journal().dispatches) if journal_path.exists() else 0,
                "planned": len(planned), "stop_reason": stop_reason}

    def _run_slot(self, slot: dict) -> TrialRun:
        identity = self.manifest["run_identity"]
        before = len(self.plan.meter.entries)
        started = time.monotonic()
        record = run_release_trial(slot["case_id"], self.turn, base_dir=Path(identity["trial_base_dir"]["path"]),
                                   config=self.config, pre_dispatch=self._pre_dispatch(slot["repetition"]),
                                   task_dir=Path(self.plan.task_dir))
        trial = TrialRun(dict(slot), record.get("trial_id"),
                         Path(identity["trial_base_dir"]["path"]) / record["trial_id"] / "trial-record.json",
                         record.get("status"), record.get("cause"), round(time.monotonic() - started, 3),
                         self.plan.meter.entries[before:])
        self.trials.append(trial)
        if record.get("cause") == "pre_dispatch_manifest_unverified":
            raise DispatchRefused(record["pre_dispatch"]["errors"])
        if self.after_trial is not None:
            self.after_trial(trial)
        return trial

    # ------------------------------------------------------------ phase 2

    def verify(self) -> dict:
        """Verify every journalled trial once, then the suite, the record and the gate."""
        manifest = self.manifest or self._load()
        identity = manifest["run_identity"]
        plan = self.plan
        plan.meter.arm(identity["usd_hard_stop"])
        expectations = load_sealed_expectations(Path(plan.expectations_path), identity["sealed_expectations_sha256"])
        materials = load_sealed_materials_dir(Path(plan.task_dir), identity["sealed_dataset_sha256"])
        run = load_release_run(Path(plan.manifest_path).read_bytes(), committed_sha256=plan.committed_sha256,
                               profile_bytes=Path(plan.profile_path).read_bytes())
        journal = self._journal()
        base = Path(identity["trial_base_dir"]["path"])
        results, missing, verification = [], [], []
        for entry in journal.dispatches:
            path = base / entry["trial_id"] / "trial-record.json"
            if not path.is_file():
                missing.append({"trial_id": entry["trial_id"], "case_id": entry["case_id"],
                                "repetition": entry["repetition"]})
                continue
            record = json.loads(path.read_bytes())
            before = len(plan.meter.entries)
            started = time.monotonic()
            result = verify_trial(record, expectations=expectations, materials=materials, run=run, judge=self.judge,
                                  task_dir=Path(plan.task_dir))
            verification.append({"trial_id": entry["trial_id"], "wall_seconds": round(time.monotonic() - started, 3),
                                 "calls": plan.meter.entries[before:]})
            results.append(result)
        if plan.meter.tripped is not None and not self._journal().stopped:
            self._stop(plan.meter.tripped)  # crossed while judging: the run is stopped
        suite = verify_suite(results, expectations=expectations, run=run)
        record = build_suite_record(suite, run=run)
        try:
            gate = critic_qualification_from_suite(record, record["critic_configuration_digest"]).as_dict()
        except CriticQualificationError as error:
            gate = {"status": "refused", "reason": str(error)}
        plan.ledger.record_outcome(self.manifest_sha256, record["suite_outcome"])
        self.verification_calls = verification
        report = build_report(self, expectations=expectations, results=results, suite=suite, record=record,
                              gate=gate, missing=missing)
        Path(plan.run_dir).mkdir(parents=True, exist_ok=True)
        (Path(plan.run_dir) / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        (Path(plan.run_dir) / "suite-record.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        return {"results": results, "suite": suite, "record": record, "gate": gate, "report": report}

    def run(self) -> dict:
        outcome = self.dispatch()
        verified = self.verify()
        verified["dispatch"] = outcome
        return verified


# ---------------------------------------------------------------- report (design ``reporting``)


def _classify(check, expectation):
    """(kind, check id) of one failed rule check.

    ``miss``: a required fail (or a valid counterexample) not found; ``false_rejection``: a
    fail where the expectation allows none; ``abstention``: unresolved where the expectation
    does not allow it; ``evidence_rule``: the status was right but its citations were not;
    ``wrong_status``: any other status mismatch.
    """
    name, observed = check["id"], check.get("detail")
    parts = name.split(":")
    if parts[0] == "review" and parts[-1] == "status":
        allowed = expectation.review[parts[1]]
    elif name == "response:status":
        allowed = expectation.response
    elif name == "validity:status":
        allowed = frozenset({expectation.validity})
    else:
        return "evidence_rule", name
    if observed == "unresolved" and "unresolved" not in allowed:
        return "abstention", name
    if observed == "fail" and "fail" not in allowed:
        return "false_rejection", name
    if allowed == frozenset({"fail"}) or allowed == frozenset({"valid"}):
        return "miss", name
    return "wrong_status", name


def _usage(calls):
    return {"calls": len(calls),
            "input_tokens": sum((c.get("input_tokens") or 0) + (c.get("cache_creation_input_tokens") or 0)
                                + (c.get("cache_read_input_tokens") or 0) for c in calls),
            "output_tokens": sum(c.get("output_tokens") or 0 for c in calls),
            "estimated_usd": round(sum(c.get("estimated_usd") or 0 for c in calls), 6)}


def build_report(dispatcher: Dispatcher, *, expectations, results, suite, record, gate, missing) -> dict:
    """The design's ``reporting`` sections for one attempt (release-v7 ``reporting``)."""
    manifest, identity = dispatcher.manifest, dispatcher.manifest["run_identity"]
    journal = dispatcher._journal()
    by_trial = {trial.trial_id: trial for trial in dispatcher.trials}
    verification = {item["trial_id"]: item for item in dispatcher.verification_calls}
    per_case, disagreements, same_item = {}, [], []
    for case_id, sealed in sorted(expectations.cases.items()):
        per_case[case_id] = {"boundary": sealed.expectation.boundary,
                             "case_key": {"candidate_id": sealed.candidate_id,
                                          "counterexample_id": sealed.counterexample_id},
                             "repetitions": 0, "passes": 0, "fails": 0, "invalid": 0, "not_judged": 0,
                             "misses": 0, "false_rejections": 0, "abstentions": 0, "not_judged_items": 0}
    for result in results:
        case_id = result.get("case_id")
        if case_id not in per_case:
            continue
        row = per_case[case_id]
        row["repetitions"] += 1
        row[{"pass": "passes", "fail": "fails", "invalid": "invalid", "not_judged": "not_judged"}[result["verdict"]]] += 1
        expectation = expectations.cases[case_id].expectation
        for check in result["rule_checks"]:
            if not check["ok"]:
                kind, name = _classify(check, expectation)
                if kind in {"miss", "false_rejection", "abstention"}:
                    row[kind + ("es" if kind == "miss" else "s")] += 1
                    same_item.append({"case_id": case_id, "repetition": result["repetition"], "kind": kind,
                                      "check": name, "observed": check.get("detail")})
        for item in result["judge_items"]:
            if item["status"] == "not_judged":
                row["not_judged_items"] += 1
            elif item["status"] != "supported":
                disagreements.append({"label": "judge_disagreement", "case_id": case_id,
                                      "repetition": result["repetition"], "item": item["id"],
                                      "judge_status": item["status"], "expected": "supported"})
    boundaries = {}
    for row in per_case.values():
        agg = boundaries.setdefault(row["boundary"], {"cases": 0, "repetitions": 0, "passes": 0, "fails": 0,
                                                      "invalid": 0, "not_judged": 0, "misses": 0,
                                                      "false_rejections": 0, "abstentions": 0,
                                                      "not_judged_items": 0})
        agg["cases"] += 1
        for key in agg:
            if key != "cases":
                agg[key] += row[key]
    clusters = {}
    task_dir = Path(dispatcher.plan.task_dir)
    environment = json.loads((task_dir / "environment" / "manifest.json").read_bytes())
    for entry in environment["cases"]:
        case = json.loads((task_dir / entry["path"]).read_bytes())
        key = sha256(canonical_bytes(case["source"]["originals"])).hexdigest()
        clusters.setdefault(key, []).append(entry["case_id"])
    invalid = []
    for result in results:
        if result["verdict"] == "invalid":
            trial = by_trial.get(result["trial_id"])
            invalid.append({"case_id": result.get("case_id"), "repetition": result.get("repetition"),
                            "trial_id": result.get("trial_id"), "cause": result.get("cause"),
                            **_usage((trial.calls if trial else []) + verification.get(result["trial_id"], {})
                                     .get("calls", [])),
                            "wall_seconds": trial.wall_seconds if trial else None})
    provider = []
    base = Path(identity["trial_base_dir"]["path"])
    for entry in journal.dispatches:
        path = base / entry["trial_id"] / "trial-record.json"
        calls = []
        if path.is_file():
            trial_record = json.loads(path.read_bytes())
            calls = [{"purpose": call["manifest"]["purpose"], "served_model": call["manifest"].get("served_model"),
                      "provider_request_id": call["manifest"].get("provider_request_id"),
                      "provider_message_id": call["manifest"].get("provider_message_id")}
                     for call in trial_record.get("calls", [])]
        lines = read_judge_log(judge_log_path_for(identity, entry["trial_id"])) or []
        answers = [{"item_id": line.get("item_id"), "served_model": line.get("served_model"),
                    "provider_request_id": line.get("provider_request_id"),
                    "provider_message_id": line.get("provider_message_id"),
                    "raw_response": line.get("raw_response")}
                   for line in lines if line.get("kind") == "answer"]
        provider.append({"trial_id": entry["trial_id"], "case_id": entry["case_id"],
                         "repetition": entry["repetition"], "critic_calls": calls, "judge_answers": answers,
                         "judge_log_lines_sha256": next((item["lines_sha256"] for item in suite["judge_logs"]
                                                         if item["trial_id"] == entry["trial_id"]), None)})
    journal_lines = [json.loads(line) for line in Path(identity["dispatch_journal"]["path"]).read_bytes().splitlines()]
    spend = _usage(dispatcher.plan.meter.entries)
    spend["hard_stop_usd"] = identity["usd_hard_stop"]
    spend["by_role"] = {role: _usage([c for c in dispatcher.plan.meter.entries if c.get("role") == role])
                        for role in sorted({c.get("role") for c in dispatcher.plan.meter.entries})}
    return {
        "schema": REPORT_SCHEMA, "dispatcher_version": DISPATCHER_VERSION, "labels": dict(dispatcher.plan.labels),
        "manifest_sha256": dispatcher.manifest_sha256, "commit_ref": deepcopy(dispatcher.plan.commit_ref),
        "suite_outcome": suite["suite_outcome"], "suite_reasons": suite["reasons"],
        "suite_record": record, "gate": gate,
        "per_case": per_case, "per_boundary": boundaries,
        "judge_disagreements": disagreements,
        "same_item_misses_and_false_rejections": same_item,
        "v3_joint_error_metrics": "not computed: release-v7 has no generation path",
        "clusters": {"count": len(clusters), "cases_per_cluster": sorted(len(v) for v in clusters.values())},
        "invalid_trials": invalid, "missing_trials": missing,
        "attempt": {"attempt": manifest["attempt"],
                    "prior_verdicts": [item["suite_outcome"] for item in manifest["prior_attempts"]]},
        "dispatch_journal": {"entries": journal_lines, "head": journal.head},
        "provider_ids": provider,
        "provider_reconciliation": ("not performed by code: the two-way reconciliation with the provider's "
                                    "records (post_verdict_audit) is a manual audit step"),
        "stop_entry": journal.stop,
        "spend": spend,
        "trials": [{"slot": t.slot, "trial_id": t.trial_id, "status": t.status, "cause": t.cause,
                    "wall_seconds": t.wall_seconds, **_usage(t.calls)} for t in dispatcher.trials],
    }


def judge_log_path_for(identity: dict, trial_id: str) -> Path:
    return Path(identity["trial_base_dir"]["path"]) / trial_id / "judge-responses.jsonl"


__all__ = [
    "DISPATCHER_VERSION",
    "AttemptLedger",
    "DispatchPlan",
    "DispatchRefused",
    "Dispatcher",
    "Pricing",
    "Reservation",
    "SpendMeter",
    "UsdHardStopReached",
    "build_report",
    "git_commit_contains",
    "judge_log_path_for",
]
