from __future__ import annotations

import json
import socket
import sys
from collections.abc import Callable
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from shutil import copy2
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from deploy.locks.verify_receipt_dependency_candidate import (
    ADDENDUM_PATH,
    BASE_INPUTS,
    ERROR_TEXT,
    LOCK_PATH,
    ReceiptDependencyError,
    main,
    verify_candidate,
)

FIXTURE_PATHS = (*BASE_INPUTS, ADDENDUM_PATH, LOCK_PATH)
EXPECTED_BASE_REFS = [
    {"path": path, "sha256": digest, "size_bytes": size}
    for path, (size, digest) in BASE_INPUTS.items()
]
PYNACL_HASHES = {
    "46065496ab748469cdd999246d17e301b2c24ae2fdf739132e580a0e94c94a87",
    "8a66d6fb6ae7661c58995f9c6435bda2b1e68b54b598a6a10247bfcdadac996c",
}


def _fixture(tmp_path: Path) -> Path:
    for relative in FIXTURE_PATHS:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(REPO_ROOT / relative, destination)
    return tmp_path


def _load_addendum(root: Path) -> dict[str, Any]:
    return json.loads((root / ADDENDUM_PATH).read_text(encoding="utf-8"))


def _write_addendum(root: Path, value: object) -> None:
    (root / ADDENDUM_PATH).write_text(
        json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )


def _rewrite_lock(root: Path, text: str) -> None:
    path = root / LOCK_PATH
    path.write_text(text, encoding="utf-8")
    raw = path.read_bytes()
    addendum = _load_addendum(root)
    addendum["service_lock"]["sha256"] = sha256(raw).hexdigest()
    addendum["service_lock"]["size_bytes"] = len(raw)
    _write_addendum(root, addendum)


def _assert_invalid(root: object, canary: str = "") -> None:
    with pytest.raises(ReceiptDependencyError) as raised:
        verify_candidate(root)  # type: ignore[arg-type]
    assert str(raised.value) == ERROR_TEXT
    assert raised.value.code == ERROR_TEXT
    if canary:
        assert canary not in str(raised.value)
        assert canary not in repr(raised.value)


def test_repository_receipt_dependency_candidate_is_inert_and_complete() -> None:
    result = verify_candidate(REPO_ROOT)

    assert result == {
        "schema_version": "deeptwin-control-receipt-dependency-candidate-v1",
        "status": "candidate_not_release_qualified",
        "service": "control-plane",
        "package_count": 18,
        "target_platforms": ["linux/amd64", "linux/arm64"],
        "lock_sha256": sha256((REPO_ROOT / LOCK_PATH).read_bytes()).hexdigest(),
        "addendum_sha256": sha256(
            (REPO_ROOT / ADDENDUM_PATH).read_bytes()
        ).hexdigest(),
    }


def test_main_prints_only_the_exact_inert_summary(capsys: pytest.CaptureFixture[str]) -> None:
    expected = verify_candidate(REPO_ROOT)

    assert main() == 0
    assert capsys.readouterr() == (
        json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n",
        "",
    )


@pytest.mark.parametrize("relative", tuple(BASE_INPUTS))
def test_changed_base_input_is_rejected_even_when_claim_is_recomputed(
    tmp_path: Path, relative: str
) -> None:
    root = _fixture(tmp_path)
    path = root / relative
    raw = bytearray(path.read_bytes())
    raw[0] ^= 1
    path.write_bytes(raw)
    addendum = _load_addendum(root)
    claimed = next(item for item in addendum["base_inputs"] if item["path"] == relative)
    claimed["sha256"] = sha256(raw).hexdigest()
    claimed["size_bytes"] = len(raw)
    _write_addendum(root, addendum)

    _assert_invalid(root)


@pytest.mark.parametrize("relative", FIXTURE_PATHS)
def test_missing_fixed_input_is_rejected(tmp_path: Path, relative: str) -> None:
    root = _fixture(tmp_path)
    (root / relative).unlink()

    _assert_invalid(root)


def test_symlink_is_rejected_before_its_external_canary_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture(tmp_path / "fixture")
    canary = tmp_path / "external-CANARY-NOT-OPENED"
    canary.write_text("external-CANARY-NOT-OPENED", encoding="utf-8")
    link = root / ADDENDUM_PATH
    link.unlink()
    link.symlink_to(canary)
    original_open = Path.open
    attempted = False

    def guarded_open(path: Path, *args: object, **kwargs: object) -> Any:
        nonlocal attempted
        if path == link:
            attempted = True
            raise AssertionError("symlink target open was attempted")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    _assert_invalid(root, "external-CANARY-NOT-OPENED")
    assert attempted is False


@pytest.mark.parametrize("ancestor", ["locks", "manifests"])
def test_symlinked_input_ancestor_is_rejected_before_external_files_are_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ancestor: str
) -> None:
    root = _fixture(tmp_path / "fixture")
    link = root / "deploy" / ancestor
    canary = tmp_path / f"CANARY-EXTERNAL-{ancestor}"
    link.rename(canary)
    link.symlink_to(canary, target_is_directory=True)
    original_open = Path.open
    opened: list[Path] = []

    def monitored_open(path: Path, *args: object, **kwargs: object) -> Any:
        if path.parent == link:
            opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", monitored_open)

    _assert_invalid(root, canary.name)
    assert opened == []


def test_explicit_root_symlink_resolves_to_its_real_directory(tmp_path: Path) -> None:
    real_root = _fixture(tmp_path / "real-root")
    root_link = tmp_path / "fixture-root"
    root_link.symlink_to(real_root, target_is_directory=True)

    assert verify_candidate(root_link) == verify_candidate(real_root)


def test_nonregular_input_is_rejected(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    path = root / LOCK_PATH
    path.unlink()
    path.mkdir()

    _assert_invalid(root)


def test_oversized_candidate_inputs_are_rejected(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    (root / ADDENDUM_PATH).write_bytes(b" " * 65_537)

    _assert_invalid(root)


@pytest.mark.parametrize(
    "raw_mutator",
    [
        lambda raw: b"\xef\xbb\xbf" + raw,
        lambda raw: raw.replace(
            b'{\n  "schema_version":',
            b'{\n  "status": "duplicate",\n  "schema_version":',
            1,
        ),
        lambda raw: raw + b"TRAILING-CANARY",
        lambda raw: b"\xff" + raw[1:],
        lambda raw: b"[]\n",
    ],
    ids=["bom", "duplicate-key", "trailing-data", "invalid-utf8", "non-object"],
)
def test_strict_json_encoding_is_enforced(
    tmp_path: Path, raw_mutator: Callable[[bytes], bytes]
) -> None:
    root = _fixture(tmp_path)
    path = root / ADDENDUM_PATH
    path.write_bytes(raw_mutator(path.read_bytes()))

    _assert_invalid(root, "TRAILING-CANARY")


def test_json_object_order_is_irrelevant_and_trailing_whitespace_is_allowed(
    tmp_path: Path,
) -> None:
    root = _fixture(tmp_path)
    addendum = _load_addendum(root)
    addendum["runtime"] = dict(reversed(list(addendum["runtime"].items())))
    addendum["base_inputs"] = [
        dict(reversed(list(item.items()))) for item in addendum["base_inputs"]
    ]
    addendum["service_lock"] = dict(
        reversed(list(addendum["service_lock"].items()))
    )
    addendum["artifacts"] = [
        dict(reversed(list(item.items()))) for item in addendum["artifacts"]
    ]
    path = root / ADDENDUM_PATH
    path.write_text(
        json.dumps(addendum, ensure_ascii=True) + "\n \t\n", encoding="utf-8"
    )

    result = verify_candidate(root)

    assert result["addendum_sha256"] == sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "release_qualified"),
        ("service", "provider"),
        ("consumers", ["provider"]),
        ("runtime", {"implementation": "PyPy"}),
        ("target_platforms", [{"os": "linux", "architecture": "amd64"}]),
        ("added_direct_roots", ["pynacl==1.6.1"]),
    ],
)
def test_fixed_addendum_fields_are_closed(
    tmp_path: Path, field: str, value: object
) -> None:
    root = _fixture(tmp_path)
    addendum = _load_addendum(root)
    addendum[field] = value
    _write_addendum(root, addendum)

    _assert_invalid(root)


@pytest.mark.parametrize("field", ["status", "artifacts"])
def test_exact_ten_field_shape_rejects_missing_fields(tmp_path: Path, field: str) -> None:
    root = _fixture(tmp_path)
    addendum = _load_addendum(root)
    del addendum[field]
    _write_addendum(root, addendum)

    _assert_invalid(root)


def test_exact_ten_field_shape_rejects_unknown_fields(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    addendum = _load_addendum(root)
    addendum["unknown"] = "CANARY-UNKNOWN-FIELD"
    _write_addendum(root, addendum)

    _assert_invalid(root, "CANARY-UNKNOWN-FIELD")


@pytest.mark.parametrize("value", [-1, 1 << 63, True, 1.5])
def test_json_integer_domain_and_float_exclusion(tmp_path: Path, value: object) -> None:
    root = _fixture(tmp_path)
    addendum = _load_addendum(root)
    addendum["service_lock"]["size_bytes"] = value
    _write_addendum(root, addendum)

    _assert_invalid(root)


@pytest.mark.parametrize("kind", ["depth", "string", "items", "surrogate"])
def test_addendum_tree_limits_are_enforced(tmp_path: Path, kind: str) -> None:
    root = _fixture(tmp_path)
    addendum = _load_addendum(root)
    if kind == "depth":
        nested: object = "control-plane"
        for _ in range(17):
            nested = [nested]
        addendum["consumers"] = nested
    elif kind == "string":
        addendum["status"] = "x" * 4097
    elif kind == "items":
        addendum["consumers"] = [0] * 4001
    else:
        addendum["status"] = "\ud800"
    _write_addendum(root, addendum)

    _assert_invalid(root)


@pytest.mark.parametrize("mutation", ["order", "count", "path", "digest", "size"])
def test_base_reference_list_is_exact_and_ordered(tmp_path: Path, mutation: str) -> None:
    root = _fixture(tmp_path)
    addendum = _load_addendum(root)
    if mutation == "order":
        addendum["base_inputs"][0], addendum["base_inputs"][1] = (
            addendum["base_inputs"][1], addendum["base_inputs"][0]
        )
    elif mutation == "count":
        addendum["base_inputs"].pop()
    elif mutation == "path":
        addendum["base_inputs"][0]["path"] = "CANARY-UNKNOWN-PATH"
    elif mutation == "digest":
        addendum["base_inputs"][0]["sha256"] = "0" * 64
    else:
        addendum["base_inputs"][0]["size_bytes"] += 1
    _write_addendum(root, addendum)

    _assert_invalid(root, "CANARY-UNKNOWN-PATH")


@pytest.mark.parametrize("mutation", ["path", "digest", "size", "count"])
def test_service_lock_reference_is_exact(tmp_path: Path, mutation: str) -> None:
    root = _fixture(tmp_path)
    addendum = _load_addendum(root)
    if mutation == "path":
        addendum["service_lock"]["path"] = "../../CANARY-EXTERNAL-LOCK"
    elif mutation == "digest":
        addendum["service_lock"]["sha256"] = "0" * 64
    elif mutation == "size":
        addendum["service_lock"]["size_bytes"] += 1
    else:
        addendum["service_lock"]["package_count"] = 17
    _write_addendum(root, addendum)

    _assert_invalid(root, "CANARY-EXTERNAL-LOCK")


def test_unknown_manifest_path_is_never_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture(tmp_path / "fixture")
    canary = tmp_path / "CANARY-UNKNOWN-MANIFEST-PATH"
    canary.write_text("must remain unread", encoding="utf-8")
    addendum = _load_addendum(root)
    addendum["service_lock"]["path"] = str(canary)
    _write_addendum(root, addendum)
    original_open = Path.open
    attempted = False

    def guarded_open(path: Path, *args: object, **kwargs: object) -> Any:
        nonlocal attempted
        if path == canary:
            attempted = True
            raise AssertionError("unknown manifest path was opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    _assert_invalid(root, "CANARY-UNKNOWN-MANIFEST-PATH")
    assert attempted is False


@pytest.mark.parametrize(
    "mutation",
    [
        "provider-substitution",
        "missing-platform",
        "duplicate-platform",
        "swapped-wheel-platform",
        "wrong-version",
        "changed-source",
        "changed-license",
        "changed-size",
        "changed-tag",
        "extra-wheel",
    ],
)
def test_artifacts_are_exact_pinned_copies_with_control_usage_only(
    tmp_path: Path, mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    network_attempted = False

    def reject_network(*args: object, **kwargs: object) -> None:
        del args, kwargs
        nonlocal network_attempted
        network_attempted = True
        raise AssertionError("artifact metadata triggered a network request")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    root = _fixture(tmp_path)
    addendum = _load_addendum(root)
    artifacts = addendum["artifacts"]
    if mutation == "provider-substitution":
        artifacts[0]["usage"][0]["service"] = "provider"
    elif mutation == "missing-platform":
        artifacts.pop()
    elif mutation == "duplicate-platform":
        artifacts.append(deepcopy(artifacts[0]))
    elif mutation == "swapped-wheel-platform":
        artifacts[0]["wheel"]["platform"]["architecture"] = "arm64"
    elif mutation == "wrong-version":
        artifacts[0]["version"] = "1.6.1"
    elif mutation == "changed-source":
        artifacts[0]["source"]["download_url"] = "https://example.invalid/CANARY"
    elif mutation == "changed-license":
        artifacts[0]["license"]["embedded_resources"][0]["size_bytes"] += 1
    elif mutation == "changed-size":
        artifacts[0]["size_bytes"] += 1
    elif mutation == "changed-tag":
        artifacts[0]["wheel"]["tags"][0] = "cp312-none-any"
    else:
        artifacts.append(deepcopy(artifacts[1]))
        artifacts[-1]["sha256"] = "f" * 64
    _write_addendum(root, addendum)

    _assert_invalid(root, "CANARY")
    assert network_attempted is False


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-base-package",
        "changed-base-version",
        "changed-base-hash",
        "second-added-package",
        "missing-pynacl-hash",
        "extra-pynacl-hash",
        "duplicate-pynacl-hash",
        "malformed",
        "unsorted-name",
        "duplicate-package",
        "unpinned",
    ],
)
def test_candidate_lock_is_an_exact_base_plus_pynacl_delta(
    tmp_path: Path, mutation: str
) -> None:
    root = _fixture(tmp_path)
    text = (root / LOCK_PATH).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if mutation == "missing-base-package":
        text = "".join(line for line in lines if not line.startswith("click=="))
    elif mutation == "changed-base-version":
        text = text.replace("click==8.5.0", "click==8.5.1", 1)
    elif mutation == "changed-base-hash":
        text = text.replace(
            "255bc9599cf7748b4b1a446ccc735421bd08a2ae529a8b88597d3de5664ee360",
            "0" * 64,
            1,
        )
    elif mutation == "second-added-package":
        text = text.replace(
            "starlette==1.6.0",
            "requests==2.0.0 --hash=sha256:" + "1" * 64 + "\nstarlette==1.6.0",
            1,
        )
    elif mutation == "missing-pynacl-hash":
        text = text.replace(
            " \\\n    --hash=sha256:8a66d6fb6ae7661c58995f9c6435bda2b1e68b54b598a6a10247bfcdadac996c",
            "",
            1,
        )
    elif mutation == "extra-pynacl-hash":
        text = text.replace(
            " --hash=sha256:8a66d6fb6ae7661c58995f9c6435bda2b1e68b54b598a6a10247bfcdadac996c",
            " --hash=sha256:8a66d6fb6ae7661c58995f9c6435bda2b1e68b54b598a6a10247bfcdadac996c"
            " --hash=sha256:" + "2" * 64,
            1,
        )
    elif mutation == "duplicate-pynacl-hash":
        text = text.replace(
            " --hash=sha256:8a66d6fb6ae7661c58995f9c6435bda2b1e68b54b598a6a10247bfcdadac996c",
            " --hash=sha256:8a66d6fb6ae7661c58995f9c6435bda2b1e68b54b598a6a10247bfcdadac996c"
            " --hash=sha256:8a66d6fb6ae7661c58995f9c6435bda2b1e68b54b598a6a10247bfcdadac996c",
            1,
        )
    elif mutation == "malformed":
        text = text.replace("click==8.5.0", "click~=8.5.0-CANARY", 1)
    elif mutation == "unsorted-name":
        text = text.replace("click==8.5.0", "Click==8.5.0", 1)
    elif mutation == "duplicate-package":
        click_line = next(line for line in lines if line.startswith("click=="))
        text = text.replace(click_line, click_line + click_line, 1)
    else:
        text = text.replace("click==8.5.0 --hash=sha256:", "click --hash=sha256:", 1)
    _rewrite_lock(root, text)

    _assert_invalid(root, "CANARY")


def test_candidate_lock_length_overflow_is_rejected(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    (root / LOCK_PATH).write_bytes(b"#" + b"x" * 16_384)

    _assert_invalid(root)


def test_fixed_error_normalizes_type_and_parser_canaries(tmp_path: Path) -> None:
    _assert_invalid("CANARY-WRONG-ROOT", "CANARY-WRONG-ROOT")
    root = _fixture(tmp_path)
    text = (root / LOCK_PATH).read_text(encoding="utf-8")
    _rewrite_lock(root, text.replace("click==8.5.0", "CANARY-MALFORMED", 1))

    _assert_invalid(root, "CANARY-MALFORMED")


def test_historical_inputs_remain_byte_for_byte_frozen() -> None:
    actual = [
        {
            "path": path,
            "sha256": sha256((REPO_ROOT / path).read_bytes()).hexdigest(),
            "size_bytes": (REPO_ROOT / path).stat().st_size,
        }
        for path in BASE_INPUTS
    ]

    assert actual == EXPECTED_BASE_REFS
    assert PYNACL_HASHES == {
        artifact["sha256"] for artifact in _load_addendum(REPO_ROOT)["artifacts"]
    }
