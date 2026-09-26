"""T087: each distribution installs from its wheel and from its sdist into a fresh venv.

pip installs with `--no-index --no-deps` (the sdist path runs the root's in-tree PEP 517
backend under pip's build isolation). The installed code then runs with `python -I` from
a directory outside the repository, where `import app` fails and the module resolves
from that venv's site-packages; neither environment can import the other distribution.
"""

import base64
import json
from pathlib import Path

import pytest

from app.domain.refs import canonical_json
from app.extensions.contracts import ExtensionManifest
from app.tests.support.sdk_packages import (
    IMPORT_NAMES,
    PACKAGE_ROOTS,
    REPOSITORY,
    build,
    fresh_environment,
    pip_install,
    project_table,
    run_isolated,
)

CASES = tuple((distribution, kind) for distribution in PACKAGE_ROOTS for kind in ("wheel", "sdist"))

_PROBE = r"""
import importlib, importlib.metadata as metadata, json, sys
from pathlib import Path
distribution, module_name, repository = sys.argv[1], sys.argv[2], Path(sys.argv[3])
report = {}
for name in ("app", "deeptwin_ext" if module_name == "deeptwin_client" else "deeptwin_client"):
    try:
        importlib.import_module(name)
    except ModuleNotFoundError:
        report["absent:" + name] = True
    else:
        report["absent:" + name] = False
module = importlib.import_module(module_name)
report["file"] = module.__file__
report["path_in_repository"] = [entry for entry in sys.path if entry and Path(entry).resolve().is_relative_to(repository)]
report["version"] = metadata.version(distribution)
meta = metadata.metadata(distribution)
report["license"] = meta["License-Expression"]
report["requires"] = metadata.requires(distribution)
report["installer"] = (metadata.distribution(distribution).read_text("INSTALLER") or "").strip()
print(json.dumps(report))
"""


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    work = tmp_path_factory.mktemp("sdk-install")
    environments = {}
    for distribution, kind in CASES:
        artifact = build(distribution, kind, work / "dist")
        python = fresh_environment(work / f"{distribution}-{kind}")
        pip_install(python, artifact, cwd=work)
        environments[distribution, kind] = python
    outside = work / "outside-repository"
    outside.mkdir()
    assert REPOSITORY not in outside.parents
    return environments, outside


@pytest.mark.parametrize(("distribution", "kind"), CASES)
def test_installed_distribution_resolves_from_its_own_environment(installed, distribution, kind):
    environments, outside = installed
    python = environments[distribution, kind]
    code, stdout, stderr = run_isolated(
        python, _PROBE, cwd=outside, args=(distribution, IMPORT_NAMES[distribution], str(REPOSITORY)))
    assert code == 0, stderr[-4000:]
    report = json.loads(stdout)
    assert report["absent:app"] is True
    assert all(value is True for key, value in report.items() if key.startswith("absent:"))
    environment_root = python.parent.parent
    assert "site-packages" in report["file"]
    assert Path(report["file"]).is_relative_to(environment_root)
    assert report["path_in_repository"] == []
    assert report["version"] == project_table(distribution)["project"]["version"]
    assert report["license"] == "Apache-2.0"
    assert report["requires"] is None
    assert report["installer"] == "pip"


_EXT_SCRIPT = r"""
import json, sys
from deeptwin_ext import WorkerRequest, build_manifest, canonical_manifest_bytes
value = build_manifest(**json.loads(sys.argv[1]))
print(json.dumps({"manifest": value, "canonical": canonical_manifest_bytes(value).decode("utf-8")}))
"""

MANIFEST_ARGUMENTS = {
    "extension_id": "org.example.installed-tool",
    "extension_version": "1.0.0",
    "extension_kind": "tool",
    "artifact_type": "package",
    "artifact_sha256": "a" * 64,
    "source_kind": "third_party",
    "source_locator": "https://example.invalid/installed-tool",
    "provenance_sha256": "b" * 64,
    "license_expression": "MIT",
    "entrypoint_protocol": "worker-json-v1",
    "entrypoint_name": "main",
    "isolation_profile": "runtime-worker-v1",
}


@pytest.mark.parametrize("kind", ("wheel", "sdist"))
def test_installed_extension_kit_manifest_is_accepted_by_the_core_parser(installed, kind):
    environments, outside = installed
    code, stdout, stderr = run_isolated(environments["deeptwin-ext", kind], _EXT_SCRIPT, cwd=outside,
                                        args=(json.dumps(MANIFEST_ARGUMENTS),))
    assert code == 0, stderr[-4000:]
    report = json.loads(stdout)
    parsed = ExtensionManifest.from_mapping(report["manifest"])
    assert parsed.extension_id == "org.example.installed-tool"
    assert report["canonical"].encode("utf-8") == canonical_json(report["manifest"])


_CLIENT_OFFLINE = r"""
import base64, json, pickle
from deeptwin_client import ClientConfigurationError, DeepTwinClient
bearer = "dt_sc_" + base64.urlsafe_b64encode(b"offline-probe-never-issued-32byt").rstrip(b"=").decode()
report = {}
for label, url, kwargs in (
    ("plaintext", "http://deeptwin.test", {}),
    ("userinfo", "https://user@deeptwin.test", {}),
    ("query", "https://deeptwin.test/?a=1", {}),
    ("path", "https://deeptwin.test/base", {}),
    ("short-bearer", "https://deeptwin.test", {"bearer": "dt_sc_short"}),
    ("wrong-prefix", "https://deeptwin.test", {"bearer": "xx" + bearer[2:]}),
    ("address", "https://deeptwin.test", {"connect_address": "localhost"}),
):
    try:
        DeepTwinClient(url, **({"bearer": bearer} | kwargs))
    except ClientConfigurationError as error:
        report[label] = str(error)
client = DeepTwinClient("https://deeptwin.test:8443", bearer=bearer)
report["repr"] = repr(client)
try:
    pickle.dumps(client)
except TypeError:
    report["pickle"] = "refused"
for label, path in (("dotdot", "/api/v1/../session"), ("encoded", "/api/v1/a%2Fb"), ("prefix", "/session")):
    try:
        client.request("GET", path)
    except ClientConfigurationError as error:
        report[label] = str(error)
try:
    client.read_extension_binding("..")
except ClientConfigurationError as error:
    report["segment"] = str(error)
print(json.dumps(report))
"""


@pytest.mark.parametrize("kind", ("wheel", "sdist"))
def test_installed_client_refuses_before_any_io(installed, kind):
    environments, outside = installed
    code, stdout, stderr = run_isolated(environments["deeptwin-client", kind], _CLIENT_OFFLINE, cwd=outside)
    assert code == 0, stderr[-4000:]
    report = json.loads(stdout)
    for label in ("plaintext", "userinfo", "query", "path"):
        assert report[label] == "base URL must be an https origin"
    assert report["short-bearer"] == report["wrong-prefix"] == "bearer credential has the wrong form"
    assert report["address"] == "connect address must be an IP literal"
    assert report["repr"] == "DeepTwinClient(https://deeptwin.test:8443)"
    assert report["pickle"] == "refused"
    for label in ("dotdot", "encoded", "prefix"):
        assert report[label] == "path must be a plain /api/v1 path"
    assert report["segment"] == "path segment is invalid"
    bearer = "dt_sc_" + base64.urlsafe_b64encode(b"offline-probe-never-issued-32byt").rstrip(b"=").decode()
    assert bearer not in stdout and bearer[6:] not in stdout
