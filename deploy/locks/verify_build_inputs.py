#!/usr/bin/env python3
"""Offline structural verifier for DeepTwin T089 build-input lock artifacts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any

MAX_BODY_BYTES = 1_048_576
MAX_DEPTH = 32
MAX_ITEMS = 10_000
MAX_STRING_BYTES = 65_536
MAX_INTEGER = (1 << 63) - 1
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PLATFORMS = {("linux", "amd64"), ("linux", "arm64")}
LOCK_REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)==([^ ]+) (.+)$")
LOCK_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})")
PYTHON_PROFILES = {
    "control-plane": "control-plane",
    "runtime": "runtime-and-evaluation-workers",
    "provider": "credentialed-provider-gateway",
    "document": "document-worker",
    "speech": "speech-worker-downstream-inputs",
}

CODEX_SCHEMA = "deeptwin-managed-runner-build-input-v3"
CODEX_PLATFORMS = ("linux/amd64", "linux/arm64")
CODEX_COMPONENTS = ("codex", "codex-code-mode-host", "bubblewrap")
CODEX_OMITTED_COMPONENTS = (
    "codex-package.json",
    "full-package-tar",
    "ripgrep",
    "zsh",
)
CODEX_RELEASE_BASE = (
    "https://github.com/openai/codex/releases/download/rust-v0.153.4/"
)


def _codex_component(
    name: str,
    asset_name: str,
    archive_bytes: int,
    archive_sha256: str,
    member_path: str,
    installed_path: str,
    executable_bytes: int,
    executable_sha256: str,
    bundle_bytes: int,
    bundle_sha256: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "archive": {
            "url": f"{CODEX_RELEASE_BASE}{asset_name}.tar.gz",
            "filename": f"{asset_name}.tar.gz",
            "bytes": archive_bytes,
            "sha256": archive_sha256,
            "member_path": member_path,
        },
        "executable": {
            "installed_path": installed_path,
            "bytes": executable_bytes,
            "sha256": executable_sha256,
            "mode": "0755",
        },
        "sigstore_bundle": {
            "url": f"{CODEX_RELEASE_BASE}{asset_name}.sigstore",
            "filename": f"{asset_name}.sigstore",
            "bytes": bundle_bytes,
            "sha256": bundle_sha256,
            "verified": True,
        },
        "signature_scope": "extracted executable only",
    }


CODEX_PLATFORM_INPUTS = {
    "linux/amd64": {
        "target": "x86_64-unknown-linux-musl",
        "components": [
            _codex_component(
                "codex",
                "codex-x86_64-unknown-linux-musl",
                98582872,
                "f479424eca092484dc40d87ae28c44f4cc40234a60045d6131e493800d814a30",
                "codex-x86_64-unknown-linux-musl",
                "/opt/deeptwin/codex/bin/codex",
                258659424,
                "56ef98ab4032d317ab26e9b5e5a175650717351edb16ed9cde0cb6d1734d62da",
                8585,
                "0dc1cab06eade46e05659b84289751a9425f7bb7886c5a10ddc3d6f5735cfaa2",
            ),
            _codex_component(
                "codex-code-mode-host",
                "codex-code-mode-host-x86_64-unknown-linux-musl",
                25733165,
                "f95830a869590957664bbfc67bccb08773806b693670baf15908176f89b4cd31",
                "codex-code-mode-host-x86_64-unknown-linux-musl",
                "/opt/deeptwin/codex/bin/codex-code-mode-host",
                69460032,
                "3e85d67471825f73d02ff5f7e047ca1f6ca8caa3f59e4c6e8d9ca6ca7302cb45",
                8585,
                "a31c6bc2aa530b98986207d67e61061096ba384f623b49ed9992bb628145900f",
            ),
            _codex_component(
                "bubblewrap",
                "bwrap-x86_64-unknown-linux-musl",
                261563,
                "e7d65c75e05637e42b93f6abf9222fa0d26b537648a7a34c122b75021d41756d",
                "bwrap-x86_64-unknown-linux-musl",
                "/opt/deeptwin/codex/bin/bwrap",
                529776,
                "77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c",
                8565,
                "4e0e55799310ed3655041bc06246b3ab4b7917a04fc821b8b010d73c23fd53f0",
            ),
        ],
    },
    "linux/arm64": {
        "target": "aarch64-unknown-linux-musl",
        "components": [
            _codex_component(
                "codex",
                "codex-aarch64-unknown-linux-musl",
                90899740,
                "5cda6182bd94c3a30f2eb63a495489ebf7f691fddb14d70f48c6c1a5071b6cde",
                "codex-aarch64-unknown-linux-musl",
                "/opt/deeptwin/codex/bin/codex",
                222567456,
                "4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6",
                8565,
                "847b47e73068f86635c23ab5501647a93fab9ad0c450d6661a88481dfcd6d759",
            ),
            _codex_component(
                "codex-code-mode-host",
                "codex-code-mode-host-aarch64-unknown-linux-musl",
                24358441,
                "d8047b8d33370d6090e729d27eb76de60a2686baa1c143c138c9b05dc70d813b",
                "codex-code-mode-host-aarch64-unknown-linux-musl",
                "/opt/deeptwin/codex/bin/codex-code-mode-host",
                63381656,
                "d677dedf8179ca28ceb869a2e0b60d3ffad3d26f6e7738f7617d34500128a369",
                8585,
                "def3aaaf54077d58f2aa41667d374c4b9c0695ef4d6fb0b7645fdbf0badbe408",
            ),
            _codex_component(
                "bubblewrap",
                "bwrap-aarch64-unknown-linux-musl",
                254882,
                "2c6ea97dfb0a936b695ece6df058b89d4dfd53774a9ad852b3e4c98e6bbdfd20",
                "bwrap-aarch64-unknown-linux-musl",
                "/opt/deeptwin/codex/bin/bwrap",
                529168,
                "c547cbdc762a70ed216789ffaa4c6c0e7d2beabe32245a498f8e365a9fc8dab4",
                8585,
                "de750905a97468d3fca09304dddf26fefe4427692a316a1486b7eb6f74273f6e",
            ),
        ],
    },
}
CODEX_SIGNATURE_IDENTITY = (
    "https://github.com/openai/codex/.github/workflows/"
    "rust-release.yml@refs/tags/rust-v0.153.4"
)
CODEX_SIGNATURE_ISSUER = "https://token.actions.githubusercontent.com"
CODEX_RUNTIME_LAYOUT = {
    "install_root": "/opt/deeptwin/codex",
    "codex_path": "/opt/deeptwin/codex/bin/codex",
    "code_mode_host_path": "/opt/deeptwin/codex/bin/codex-code-mode-host",
    "bubblewrap_path": "/opt/deeptwin/codex/bin/bwrap",
    "bash_path": "/bin/bash",
    "path_env": "/opt/deeptwin/codex/bin:/usr/bin:/bin",
    "required_internal_sandbox_profiles": ["read-only", "workspace-write"],
    "codex_home_policy": "isolated_per_run",
}
CODEX_BOOKWORM_INDEX = {
    "media_type": "application/vnd.oci.image.index.v1+json",
    "digest": "sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171",
    "bytes": 5651,
}
CODEX_BASH_SOURCE_INPUTS = [
    {
        "filename": "bash_5.2.15-2.dsc",
        "url": "https://snapshot.debian.org/file/1c8463de9b96f5e72d178a50c49f80242e48d8c7",
        "bytes": 2317,
        "sha256": "f51753e946af43eb58549c81e03b35a47af9fe6c6364179ccd4ef862b7c3b2d3",
    },
    {
        "filename": "bash_5.2.15.orig.tar.gz",
        "url": "https://snapshot.debian.org/file/87f4eb879578479049306f3b721ff38aa17cfa1d",
        "bytes": 9997221,
        "sha256": "7a315bc0e9d90713159e4390ec1096a41e4f33cd8cc3d1a749a8e5ad56600f51",
    },
    {
        "filename": "bash_5.2.15-2.debian.tar.xz",
        "url": "https://snapshot.debian.org/file/d922d9f78e120a6068105ebfe7c15cbadddc31a0",
        "bytes": 97380,
        "sha256": "998f8ea5b754a734ae7d8306e149c43d713ddfcf49623a036004b729237dbcca",
    },
]


def _codex_runtime_image(
    *,
    source_revision: str,
    manifest_digest: str,
    manifest_bytes: int,
    config_digest: str,
    config_bytes: int,
    layer_digest: str,
    layer_bytes: int,
    architecture: str,
    package_bytes: int,
    package_sha256: str,
    package_snapshot_sha1: str,
    member_bytes: int,
    member_sha256: str,
) -> dict[str, Any]:
    return {
        "distribution": "debian",
        "suite": "bookworm",
        "repository": "docker.io/library/debian",
        "tag": "bookworm-20260824-slim",
        "created_at": "2026-08-24T00:00:00Z",
        "snapshot": "20260824T000000Z",
        "source_repository": "https://github.com/debuerreotype/docker-debian-artifacts.git",
        "source_revision": source_revision,
        "index": CODEX_BOOKWORM_INDEX,
        "manifest": {
            "media_type": "application/vnd.oci.image.manifest.v1+json",
            "digest": manifest_digest,
            "bytes": manifest_bytes,
        },
        "config": {
            "media_type": "application/vnd.oci.image.config.v1+json",
            "digest": config_digest,
            "bytes": config_bytes,
        },
        "layers": [{
            "position": 1,
            "media_type": "application/vnd.oci.image.layer.v1.tar+gzip",
            "digest": layer_digest,
            "bytes": layer_bytes,
        }],
        "bash": {
            "package": "bash",
            "package_version": "5.2.15-2+b13",
            "source_package": "bash",
            "source_version": "5.2.15-2",
            "installed_path": "/bin/bash",
            "mode": "0755",
            "binary_package": {
                "filename": f"bash_5.2.15-2+b13_{architecture}.deb",
                "url": f"https://snapshot.debian.org/file/{package_snapshot_sha1}",
                "bytes": package_bytes,
                "sha256": package_sha256,
            },
            "package_member": {
                "path": "bin/bash",
                "installed_path": "/bin/bash",
                "bytes": member_bytes,
                "sha256": member_sha256,
                "mode": "0755",
            },
            "license_member": {
                "path": "usr/share/doc/bash/copyright",
                "bytes": 9764,
                "sha256": "06319d84c3e5ed096036f6a9310a030c7e84e50dff2b8a6792285c83ec0ada73",
            },
            "source_inputs": CODEX_BASH_SOURCE_INPUTS,
        },
    }


CODEX_RUNTIME_INPUTS = {
    "linux/amd64": _codex_runtime_image(
        source_revision="bae6d64d90b4068b09ff9d8b564c2773ef5d8d83",
        manifest_digest="sha256:5ae3c39ebd15e229dcedd5cee596b2497182493d41ff162e824ba13fc1b2b867",
        manifest_bytes=1021,
        config_digest="sha256:160466e67bb85a4099d9d9c2356b4a6a64747b281a22c142efbd4539db1b8525",
        config_bytes=453,
        layer_digest="sha256:a8ac7f6c67abc236e4c745052c404112b8fab6fe8ac3a329d1ef3b867ad67c71",
        layer_bytes=28232655,
        architecture="amd64",
        package_bytes=1490652,
        package_sha256="82130bb6a560cd2a7234d8018baf73f188f5dd56413d5aa0accc987b2197a6a1",
        package_snapshot_sha1="c3d560d63523ba240e565376b57724de72e89e6b",
        member_bytes=1265648,
        member_sha256="55b89ab22bee4792a210f493a53fb066accd5d30b69837c28d98be5ff863efcf",
    ),
    "linux/arm64": _codex_runtime_image(
        source_revision="f73bd086e8d0e5e1c8b838ccc442bf24eb3ea205",
        manifest_digest="sha256:6bd27d44e6c32a66bbd72d7cb2b76a8ae3497ec2e5274a81abd1b37f6013fa1f",
        manifest_bytes=1041,
        config_digest="sha256:32d322b19846336d25f755f73618a448e3621982d52c48064e95af8b3dcbc2d9",
        config_bytes=468,
        layer_digest="sha256:75782e20ea1f4a9d9259bc20a5ecbbea8d5943bf5370bf0f5727900728f1cc9a",
        layer_bytes=28117289,
        architecture="arm64",
        package_bytes=1444200,
        package_sha256="fdb470b5ec1773b90014138bfc1deda4505c1c23e7f5731e8b527c636ac03385",
        package_snapshot_sha1="2b5075a3983b5d1b4d6288bcccf0371ebc0fccd3",
        member_bytes=1346480,
        member_sha256="f5918390c5b15392ad8835e8368a79c1ee9937fbb19f2349cccf5d4524183299",
    ),
}
CODEX_RUNTIME_MUTATION_POLICY = {
    "browser_download_at_runtime": False,
    "model_download_at_runtime": False,
    "package_install_at_runtime": False,
    "package_resolution_at_runtime": False,
    "tool_download_at_runtime": False,
}
CODEX_RUST_DEPENDENCY_INVENTORY = {
    "path": "deploy/manifests/codex-0.153.4-rust-dependencies.json",
    "schema_version": "deeptwin-codex-rust-dependency-inventory-v1",
    "bytes": 857379,
    "sha256": "9d67a5dda134bcdaab8bc62cc2b0fdbb7d2adb3c94062b0a12ea14d09b71b644",
    "inventory_digest": "a09a94f6099c7f003555d4a1b43da996098c11d2c26a7cefb75062c2799b0d47",
    "status": "candidate_exact_input_inventory_not_release_qualified",
    "release_gate": "not_satisfied",
    "evidence": {
        "path": "specs/001-autonomous-release/evidence/codex-0.153.4-rust-dependency-inventory.md",
        "bytes": 11254,
        "sha256": "5aeb4354cacda1e6ced6187ece19cef9fe28f310e09c12a9d0aff6faefaef0ce",
    },
}
AGE_PLATFORM_ARCHIVES = {
    "linux/amd64": {
        "platform": "linux/amd64",
        "url": "https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-amd64.tar.gz",
        "bytes": 19405817,
        "sha256": "cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10",
        "sigsum_proof": {
            "url": "https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-amd64.tar.gz.proof",
            "bytes": 1921,
            "sha256": "98402fa59b4e433426156b4a7e74a32e44902e0434c61158f7de18ffc84f1f97",
            "verified": True,
            "exit_code": 0,
            "verifier": "sigsum-verify@v0.13.1",
            "named_policy": "sigsum-generic-2025-1",
        },
        "copied_members": [
            {
                "path": "age/age",
                "mode": "0755",
                "bytes": 6977014,
                "sha256": "eb7dd1b518f0a307c99cd97782623c5321da049154b04acd2d98d21aa7bc9b2c",
            },
            {
                "path": "age/age-keygen",
                "mode": "0755",
                "bytes": 4051278,
                "sha256": "0a0009db842259d6717f7eeb30acb6b90d2a2eb924c6acd0a0db0ca1f1537899",
            },
            {
                "path": "age/LICENSE",
                "mode": "0644",
                "bytes": 2975,
                "sha256": "afbdb4e07a359499db587ae632815809b1fc1670a92d5449af112ce9a67833a2",
            },
        ],
    },
    "linux/arm64": {
        "platform": "linux/arm64",
        "url": "https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-arm64.tar.gz",
        "bytes": 17771923,
        "sha256": "6b8dc4333c53a5a57c9e5834e3a48f92605d7154014cd07269ff3327db5d37f4",
        "sigsum_proof": {
            "url": "https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-arm64.tar.gz.proof",
            "bytes": 1921,
            "sha256": "a174de2bf22a72efedd1a779cbee8b7d5605b41a25fae085807003b4abf5688e",
            "verified": True,
            "exit_code": 0,
            "verifier": "sigsum-verify@v0.13.1",
            "named_policy": "sigsum-generic-2025-1",
        },
        "copied_members": [
            {
                "path": "age/age",
                "mode": "0755",
                "bytes": 6540637,
                "sha256": "41b072352f4561018949623c674d16ef704019b9108a9bbdbd21292efebfc94f",
            },
            {
                "path": "age/age-keygen",
                "mode": "0755",
                "bytes": 3854433,
                "sha256": "00b549cebf68302893fc489830f37e706712689ca877f84d85439d700d2997c7",
            },
            {
                "path": "age/LICENSE",
                "mode": "0644",
                "bytes": 2975,
                "sha256": "afbdb4e07a359499db587ae632815809b1fc1670a92d5449af112ce9a67833a2",
            },
        ],
    },
}

AGE_EMBEDDED_MODULES = [
    {
        "name": "filippo.io/age",
        "version": "v1.3.2",
        "license_sha256": "c5d65279d02955c0fc2294ae417c3add650d228f4f5c82bd6d531fc26c89cd96",
    },
    {
        "name": "filippo.io/edwards25519",
        "version": "v1.2.0",
        "license_sha256": "2d36597f7117c38b006835ae7f537487207d8ec407aa9d9980794b2030cbc067",
    },
    {"name": "filippo.io/hpke", "version": "v0.4.0", "license_sha256": "911f8f5782931320f5b8d1160a76365b83aea6447ee6c04fa6d5591467db9dad"},
    {"name": "filippo.io/nistec", "version": "v0.0.4", "license_sha256": "911f8f5782931320f5b8d1160a76365b83aea6447ee6c04fa6d5591467db9dad"},
    {"name": "golang.org/x/crypto", "version": "v0.55.0", "license_sha256": "911f8f5782931320f5b8d1160a76365b83aea6447ee6c04fa6d5591467db9dad"},
    {"name": "golang.org/x/sys", "version": "v0.47.0", "license_sha256": "911f8f5782931320f5b8d1160a76365b83aea6447ee6c04fa6d5591467db9dad"},
    {"name": "golang.org/x/term", "version": "v0.45.0", "license_sha256": "911f8f5782931320f5b8d1160a76365b83aea6447ee6c04fa6d5591467db9dad"},
]

AGE_LICENSE_FILES = [
    {
        "path": "deploy/locks/licenses/age-1.3.2/filippo.io-age-BSD-3-Clause.txt",
        "bytes": 1516,
        "sha256": "c5d65279d02955c0fc2294ae417c3add650d228f4f5c82bd6d531fc26c89cd96",
        "source_member": "age/LICENSE",
    },
    {
        "path": "deploy/locks/licenses/age-1.3.2/filippo.io-edwards25519-BSD-3-Clause.txt",
        "bytes": 1479,
        "sha256": "2d36597f7117c38b006835ae7f537487207d8ec407aa9d9980794b2030cbc067",
        "source_member": "age/vendor/filippo.io/edwards25519/LICENSE",
    },
    {
        "path": "deploy/locks/licenses/age-1.3.2/go-authors-BSD-3-Clause.txt",
        "bytes": 1453,
        "sha256": "911f8f5782931320f5b8d1160a76365b83aea6447ee6c04fa6d5591467db9dad",
        "source_member": "age/vendor/filippo.io/hpke/LICENSE",
    },
]

AGE_LICENSE_COMPONENTS = [
    {
        "module": "go-runtime-and-standard-library",
        "version": "go1.27.0",
        "module_sum": None,
        "license_spdx": "BSD-3-Clause",
        "license_file": "deploy/locks/licenses/age-1.3.2/go-authors-BSD-3-Clause.txt",
        "source_license_member": None,
    },
    {
        "module": "filippo.io/age",
        "version": "v1.3.2",
        "module_sum": None,
        "license_spdx": "BSD-3-Clause",
        "license_file": "deploy/locks/licenses/age-1.3.2/filippo.io-age-BSD-3-Clause.txt",
        "source_license_member": "age/LICENSE",
    },
    {
        "module": "filippo.io/edwards25519",
        "version": "v1.2.0",
        "module_sum": "h1:crnVqOiS4jqYleHd9vaKZ+HKtHfllngJIiOpNpoJsjo=",
        "license_spdx": "BSD-3-Clause",
        "license_file": "deploy/locks/licenses/age-1.3.2/filippo.io-edwards25519-BSD-3-Clause.txt",
        "source_license_member": "age/vendor/filippo.io/edwards25519/LICENSE",
    },
    {
        "module": "filippo.io/hpke",
        "version": "v0.4.0",
        "module_sum": "h1:p575VVQ6ted4pL+it6M00V/f2qTZITO0zgmdKCkd5+A=",
        "license_spdx": "BSD-3-Clause",
        "license_file": "deploy/locks/licenses/age-1.3.2/go-authors-BSD-3-Clause.txt",
        "source_license_member": "age/vendor/filippo.io/hpke/LICENSE",
    },
    {
        "module": "filippo.io/nistec",
        "version": "v0.0.4",
        "module_sum": "h1:F14ZHT5htWlMnQVPndX9ro9arf56cBhQxq4LnDI491s=",
        "license_spdx": "BSD-3-Clause",
        "license_file": "deploy/locks/licenses/age-1.3.2/go-authors-BSD-3-Clause.txt",
        "source_license_member": "age/vendor/filippo.io/nistec/LICENSE",
    },
    {
        "module": "golang.org/x/crypto",
        "version": "v0.55.0",
        "module_sum": "h1:+KWHjbgOaAQ66dh/YlkZKHlz9ZUlq61AFirAR9ntP8M=",
        "license_spdx": "BSD-3-Clause",
        "license_file": "deploy/locks/licenses/age-1.3.2/go-authors-BSD-3-Clause.txt",
        "source_license_member": "age/vendor/golang.org/x/crypto/LICENSE",
    },
    {
        "module": "golang.org/x/sys",
        "version": "v0.47.0",
        "module_sum": "h1:o7XGOvZQCADBQQ4Y7VNq2dRWQR7JmOUW8Kxx4ZsNgWs=",
        "license_spdx": "BSD-3-Clause",
        "license_file": "deploy/locks/licenses/age-1.3.2/go-authors-BSD-3-Clause.txt",
        "source_license_member": "age/vendor/golang.org/x/sys/LICENSE",
    },
    {
        "module": "golang.org/x/term",
        "version": "v0.45.0",
        "module_sum": "h1:NwWyBmoJCbfTHpxrWoZ9C6/VxOf7ic219I8xZZFdrf0=",
        "license_spdx": "BSD-3-Clause",
        "license_file": "deploy/locks/licenses/age-1.3.2/go-authors-BSD-3-Clause.txt",
        "source_license_member": "age/vendor/golang.org/x/term/LICENSE",
    },
]

AGE_EXECUTABLE_MODULE_SETS = {
    "age": ["filippo.io/edwards25519", "filippo.io/hpke", "filippo.io/nistec", "golang.org/x/crypto", "golang.org/x/sys", "golang.org/x/term"],
    "age-keygen": ["filippo.io/hpke", "golang.org/x/crypto", "golang.org/x/sys", "golang.org/x/term"],
}

CHROMIUM_ASSETS = {
    "linux/amd64": {
        "platform": "linux/amd64",
        "url": "https://cdn.playwright.dev/builds/cft/153.0.8010.12/linux64/chrome-headless-shell-linux64.zip",
        "bytes": 119809080,
        "sha256": "a9da028861a0cf789ff25c2fed45f5f1aaf969ed9247835b6a7821a4f7af9d1d",
        "executable_path": "chrome-headless-shell-linux64/chrome-headless-shell",
        "executable_bytes": 197422408,
        "executable_sha256": "ded93a9c9a53a1ae040f08124badcca95c938e9d5015ff340c3b5538c41bf39e",
    },
    "linux/arm64": {
        "platform": "linux/arm64",
        "url": "https://cdn.playwright.dev/builds/cft/153.0.8010.12/linux-arm64/chrome-headless-shell-linux-arm64.zip",
        "bytes": 120278638,
        "sha256": "d433c45172c7836e38124fe545f767b02210bfb43a6262f08a297473a8e91c99",
        "executable_path": "chrome-headless-shell-linux-arm64/chrome-headless-shell",
        "executable_bytes": 189402512,
        "executable_sha256": "f5d89353cc9ef8dc1541268bbee1f05ee40a31ce3d9799b3a274e5147f6a8cdb",
    },
}

SPEECH_LICENSE_INPUTS = [
    {
        "component": "OpenAI Whisper",
        "source_commit": "86098128c0b4f24f0e2aa2994de830614b474227",
        "source_url": "https://raw.githubusercontent.com/openai/whisper/86098128c0b4f24f0e2aa2994de830614b474227/LICENSE",
        "source_sha256": "b5d65a59060e68c4ff940e1eddfa6f94b2d68fdf58ed7f4dd57721c997e35e9d",
        "vendored_path": "deploy/locks/licenses/OpenAI-Whisper-MIT.txt",
    }
]

UPSTREAM_PROVENANCE = {
    "python-service-base": [
        {
            "platform": "linux/amd64",
            "subject_manifest_digest": "sha256:9c47360a2a0355e2da18516d0b1c2126ec22c195d2185e97347c9d98398c5bef",
            "manifest": {
                "media_type": "application/vnd.oci.image.manifest.v1+json",
                "digest": "sha256:53c4d2b5bc4738547933a1665005e5e86608b47008548432ef67a5363fcd73a9",
                "size_bytes": 841,
            },
            "config": {
                "media_type": "application/vnd.oci.image.config.v1+json",
                "digest": "sha256:341ee29c94bfec17d00d5d124f2bfa8a79a0065c082a67f3e73245fec6718b05",
                "size_bytes": 241,
            },
            "artifacts": [
                {
                    "artifact_type": "https://spdx.dev/Document",
                    "media_type": "application/vnd.in-toto+json",
                    "digest": "sha256:23b3283dd3bf812c45bc863c519fecc0363b9f2ab6ecbf9a0e1f154d147f2b1a",
                    "size_bytes": 2575043,
                },
                {
                    "artifact_type": "https://slsa.dev/provenance/v0.2",
                    "media_type": "application/vnd.in-toto+json",
                    "digest": "sha256:ef18699e0e3dc0f0b0f71baa3a5fa453b82f411d30efc7d08009549af5c2a528",
                    "size_bytes": 23677,
                },
            ],
        },
        {
            "platform": "linux/arm64",
            "subject_manifest_digest": "sha256:d04f49f5882f49a3b91f874e75e19f0c265f7222da8659741a9d7eab148f22a9",
            "manifest": {
                "media_type": "application/vnd.oci.image.manifest.v1+json",
                "digest": "sha256:e10f0ebebe5802bb60b6431b54604f0f4acf2fc6662c96c0f8ed08605a51e265",
                "size_bytes": 841,
            },
            "config": {
                "media_type": "application/vnd.oci.image.config.v1+json",
                "digest": "sha256:2ae4a7b08208b3573572244074409bbc076c1e8ddc075b003835756396ed181e",
                "size_bytes": 241,
            },
            "artifacts": [
                {
                    "artifact_type": "https://spdx.dev/Document",
                    "media_type": "application/vnd.in-toto+json",
                    "digest": "sha256:8a1f07dfe003ac637d681ba0653963e86ea59c8ee59c62ce8ee25ba2e8ee5616",
                    "size_bytes": 2575292,
                },
                {
                    "artifact_type": "https://slsa.dev/provenance/v0.2",
                    "media_type": "application/vnd.in-toto+json",
                    "digest": "sha256:138d0c29e252560597a2b027552bac53e0b44c068c8147390836338b80869bd8",
                    "size_bytes": 23787,
                },
            ],
        },
    ],
    "browser-node-base": [
        {
            "platform": "linux/amd64",
            "subject_manifest_digest": "sha256:6642ef280aebc09c4541bee0b15c9f89f0f3f3c247ddee79ae1d37eddfdcbbaa",
            "manifest": {
                "media_type": "application/vnd.oci.image.manifest.v1+json",
                "digest": "sha256:e4629ce16afadf66c8766cd164745221677379636f095b5b10f226bd69171943",
                "size_bytes": 841,
            },
            "config": {
                "media_type": "application/vnd.oci.image.config.v1+json",
                "digest": "sha256:9ba12d708d98032aa115a5857a344373151aca287bc959fbda2d278bd02cd5b7",
                "size_bytes": 241,
            },
            "artifacts": [
                {
                    "artifact_type": "https://spdx.dev/Document",
                    "media_type": "application/vnd.in-toto+json",
                    "digest": "sha256:77ee43dec873759bf69aa9db56a5bee395f1896dbb5ffae9cc6130371d5287ae",
                    "size_bytes": 2573668,
                },
                {
                    "artifact_type": "https://slsa.dev/provenance/v0.2",
                    "media_type": "application/vnd.in-toto+json",
                    "digest": "sha256:f71591d3af468a28f5b79cd269f8487ebbf8c9f19b7b1c12643b11982468fe6a",
                    "size_bytes": 27197,
                },
            ],
        },
        {
            "platform": "linux/arm64",
            "subject_manifest_digest": "sha256:e9b5516b06baeaea9a8e65a7aec6a85fbb960a30b52b66968f2c8092b3e2a3eb",
            "manifest": {
                "media_type": "application/vnd.oci.image.manifest.v1+json",
                "digest": "sha256:3e398475fe6c354a7c1f05936c3c15d339f8494493b12e419d5fe99cb301a75c",
                "size_bytes": 841,
            },
            "config": {
                "media_type": "application/vnd.oci.image.config.v1+json",
                "digest": "sha256:ebf0008dcc52b46073176ec69b6b96148c12fe367f093069a10d5b347544b66e",
                "size_bytes": 241,
            },
            "artifacts": [
                {
                    "artifact_type": "https://spdx.dev/Document",
                    "media_type": "application/vnd.in-toto+json",
                    "digest": "sha256:1fdbd758a6a4941e794dcc5a6c939e12fcc90141eac88046b8da6a43acccce93",
                    "size_bytes": 2573991,
                },
                {
                    "artifact_type": "https://slsa.dev/provenance/v0.2",
                    "media_type": "application/vnd.in-toto+json",
                    "digest": "sha256:cc46352174747b42fa364a7ad0307e105507ab24989a92d141e5a688fa68565d",
                    "size_bytes": 27403,
                },
            ],
        },
    ],
    "portable-edge-upstream": [
        {
            "platform": "linux/amd64",
            "subject_manifest_digest": "sha256:98eb57d882ccd5213d1688764db10c1ca2c58a1ca3a6717a3411ad798f7a423a",
            "manifest": {
                "media_type": "application/vnd.oci.image.manifest.v1+json",
                "digest": "sha256:ac93e0dc57158bf4e7bfeb068df1aaf7faeda5675bf6549c32cb20112e804db2",
                "size_bytes": 840,
            },
            "config": {
                "media_type": "application/vnd.oci.image.config.v1+json",
                "digest": "sha256:4e944dd2922a565c9021b63caf22ab470156069942351bf1cd5dabf2268b25f4",
                "size_bytes": 241,
            },
            "artifacts": [
                {
                    "artifact_type": "https://spdx.dev/Document",
                    "media_type": "application/vnd.in-toto+json",
                    "digest": "sha256:a39a20466be46fdee3ae825e32040ebd50155a64516772585a4a214a7fad4eb1",
                    "size_bytes": 314461,
                },
                {
                    "artifact_type": "https://slsa.dev/provenance/v0.2",
                    "media_type": "application/vnd.in-toto+json",
                    "digest": "sha256:7fccd04675d0f07dd45c595d13955410e7214c29cc8bc012c27714ce29f32a13",
                    "size_bytes": 18430,
                },
            ],
        },
        {
            "platform": "linux/arm64",
            "subject_manifest_digest": "sha256:1172d4213087d3fc30bafc7ff2c2896180eb0c41ff7f75f315568fb36cabdcba",
            "manifest": {
                "media_type": "application/vnd.oci.image.manifest.v1+json",
                "digest": "sha256:334d2f19856452896dcb5584a12badc9bde3a9a70c6ffe037958a269a5c332e8",
                "size_bytes": 840,
            },
            "config": {
                "media_type": "application/vnd.oci.image.config.v1+json",
                "digest": "sha256:b6e57a588096fc10aa6be02c455125829dec1c372cc06e10b693853e9640077c",
                "size_bytes": 241,
            },
            "artifacts": [
                {
                    "artifact_type": "https://spdx.dev/Document",
                    "media_type": "application/vnd.in-toto+json",
                    "digest": "sha256:19862c58d4d5f35d41dc92cc36e978545770d9ed6d572d3b5128e2f2c6f9e6ed",
                    "size_bytes": 313915,
                },
                {
                    "artifact_type": "https://slsa.dev/provenance/v0.2",
                    "media_type": "application/vnd.in-toto+json",
                    "digest": "sha256:20475686c5ba314a35167ae648d5b8449ddc85f81642ec71a87655bc5c081a5c",
                    "size_bytes": 18611,
                },
            ],
        },
    ],
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _reject_json_float(_: str) -> None:
    raise ValueError("floating-point JSON values are forbidden")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value is forbidden: {value}")


def _validate_json_tree(value: Any, *, depth: int = 0) -> int:
    """Validate the aggregate lock's bounded canonical-JSON scalar domain."""

    if depth > MAX_DEPTH:
        raise ValueError(f"JSON nesting exceeds depth {MAX_DEPTH}")
    if value is None or type(value) is bool:
        return 1
    if type(value) is int:
        if value < -MAX_INTEGER or value > MAX_INTEGER:
            raise ValueError("JSON integer exceeds signed 63-bit domain")
        return 1
    if type(value) is str:
        if len(value.encode("utf-8", "surrogatepass")) > MAX_STRING_BYTES:
            raise ValueError("JSON string exceeds 64 KiB")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError("unpaired Unicode surrogate is forbidden")
        return 1
    if type(value) is list:
        if len(value) > MAX_ITEMS:
            raise ValueError(f"JSON array exceeds {MAX_ITEMS} items")
        return 1 + sum(
            _validate_json_tree(item, depth=depth + 1) for item in value
        )
    if type(value) is dict:
        if len(value) > MAX_ITEMS:
            raise ValueError(f"JSON object exceeds {MAX_ITEMS} members")
        count = 1
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("JSON object keys must be strings")
            count += _validate_json_tree(key, depth=depth + 1)
            count += _validate_json_tree(item, depth=depth + 1)
        return count
    raise ValueError(f"unsupported JSON value: {type(value).__name__}")


def load_json(path: Path, *, max_total_items: int = MAX_ITEMS) -> dict[str, Any]:
    """Load a bounded, unambiguous JSON object from a regular non-symlink file."""

    if type(max_total_items) is not int or not 1 <= max_total_items <= 50_000:
        raise ValueError("max_total_items must be an integer in the range 1..50000")
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError(f"{path}: JSON input is unavailable: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{path}: JSON input must be a regular non-symlink file")
    if info.st_size > MAX_BODY_BYTES:
        raise ValueError(f"{path}: JSON body exceeds 1 MiB")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{path}: JSON input could not be read: {exc}") from exc
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError(f"{path}: JSON body exceeds 1 MiB")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{path}: UTF-8 BOM is forbidden")
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_float=_reject_json_float,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: invalid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    except RecursionError as exc:
        raise ValueError(f"{path}: JSON nesting exceeds parser limits") from exc
    if type(value) is not dict:
        raise ValueError(f"{path}: root must be an object")
    if _validate_json_tree(value) > max_total_items:
        raise ValueError(f"{path}: JSON tree exceeds {max_total_items} total items")
    return value


def require_digest(value: str, label: str, *, prefix: bool = False) -> None:
    candidate = value
    if prefix:
        if not candidate.startswith("sha256:"):
            raise ValueError(f"{label}: descriptor digest must start with sha256:")
        candidate = candidate.removeprefix("sha256:")
    if not HEX64.fullmatch(candidate):
        raise ValueError(f"{label}: invalid or abbreviated SHA-256")


def canonicalize_package_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def parse_lock(path: Path) -> dict[str, dict[str, Any]]:
    """Parse the deliberately small requirements subset used by release locks."""
    statements: list[str] = []
    current = ""
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        current = f"{current} {stripped}".strip()
        if current.endswith("\\"):
            current = current[:-1].rstrip()
            continue
        statements.append(current)
        current = ""
    if current:
        raise ValueError(f"{path}: unterminated continuation")

    result: dict[str, dict[str, Any]] = {}
    observed_order: list[str] = []
    for statement in statements:
        match = LOCK_REQUIREMENT.fullmatch(statement)
        if not match:
            raise ValueError(f"{path}: unsupported lock statement: {statement}")
        raw_name, version, hash_text = match.groups()
        name = canonicalize_package_name(raw_name)
        if raw_name != name or name in result or not version:
            raise ValueError(f"{path}: noncanonical, duplicate or unversioned pin: {statement}")
        hashes = set(LOCK_HASH.findall(hash_text))
        if not hashes or hash_text.count("--hash=sha256:") != len(hashes):
            raise ValueError(f"{path}: missing, duplicate or malformed hash: {statement}")
        residue = LOCK_HASH.sub("", hash_text).strip()
        if residue:
            raise ValueError(f"{path}: unexpected requirement option: {residue}")
        result[name] = {"version": version, "hashes": hashes}
        observed_order.append(name)
    if observed_order != sorted(observed_order):
        raise ValueError(f"{path}: package pins must be canonically sorted")
    if not result:
        raise ValueError(f"{path}: empty service lock")
    return result


def reject_abbreviated_digests(value: Any, label: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_label = f"{label}.{key}"
            if key == "sha256" and isinstance(child, str):
                require_digest(child, child_label)
            elif key == "digest" and isinstance(child, str):
                require_digest(child, child_label, prefix=True)
            reject_abbreviated_digests(child, child_label)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_abbreviated_digests(child, f"{label}[{index}]")
    elif isinstance(value, str) and "..." in value:
        raise ValueError(f"{label}: abbreviated value is not lockable")


def verify_descriptor(value: dict[str, Any], label: str, size_key: str) -> None:
    if set(value) < {"media_type", "digest", size_key}:
        raise ValueError(f"{label}: incomplete descriptor")
    if not isinstance(value["media_type"], str) or not value["media_type"]:
        raise ValueError(f"{label}: empty media type")
    require_digest(value["digest"], f"{label}.digest", prefix=True)
    if not isinstance(value[size_key], int) or value[size_key] <= 0:
        raise ValueError(f"{label}.{size_key}: positive integer required")


def verify_image(image: dict[str, Any], label: str) -> None:
    verify_descriptor(image["top_descriptor"], f"{label}.top_descriptor", "size_bytes")
    media = image["top_descriptor"]["media_type"]
    if media not in {
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    }:
        raise ValueError(f"{label}: unsupported top-level media type")
    observed: set[tuple[str, str]] = set()
    for index, platform in enumerate(image.get("platforms", [])):
        p_label = f"{label}.platforms[{index}]"
        key = (platform.get("os"), platform.get("architecture"))
        if key in observed:
            raise ValueError(f"{p_label}: duplicate platform")
        observed.add(key)
        verify_descriptor(platform["manifest"], f"{p_label}.manifest", "size_bytes")
        verify_descriptor(platform["config"], f"{p_label}.config", "size_bytes")
        positions: list[int] = []
        for layer_index, layer in enumerate(platform.get("layers", [])):
            verify_descriptor(layer, f"{p_label}.layers[{layer_index}]", "size_bytes")
            positions.append(layer.get("position"))
        if positions != list(range(1, len(positions) + 1)):
            raise ValueError(f"{p_label}: layer positions must be ordered from one")
    if observed != PLATFORMS:
        raise ValueError(f"{label}: expected exact linux/amd64+linux/arm64 coverage")
    provenance = image.get("provenance_descriptors")
    if not isinstance(provenance, list) or len(provenance) != 2:
        raise ValueError(f"{label}: exact dual-platform provenance records required")
    platform_manifests = {
        f"{item['os']}/{item['architecture']}": item["manifest"]["digest"]
        for item in image["platforms"]
    }
    provenance_platforms: set[str] = set()
    for index, record in enumerate(provenance):
        record_label = f"{label}.provenance_descriptors[{index}]"
        if not isinstance(record, dict) or set(record) != {
            "platform",
            "subject_manifest_digest",
            "manifest",
            "config",
            "artifacts",
        }:
            raise ValueError(f"{record_label}: exact provenance record shape required")
        platform = record["platform"]
        if (
            platform in provenance_platforms
            or platform not in platform_manifests
            or record["subject_manifest_digest"] != platform_manifests[platform]
        ):
            raise ValueError(f"{record_label}: provenance subject binding changed")
        provenance_platforms.add(platform)
        verify_descriptor(record["manifest"], f"{record_label}.manifest", "size_bytes")
        verify_descriptor(record["config"], f"{record_label}.config", "size_bytes")
        if (
            record["manifest"].get("media_type")
            != "application/vnd.oci.image.manifest.v1+json"
            or record["config"].get("media_type")
            != "application/vnd.oci.image.config.v1+json"
        ):
            raise ValueError(f"{record_label}: provenance OCI media types changed")
        artifacts = record["artifacts"]
        if not isinstance(artifacts, list) or len(artifacts) != 2:
            raise ValueError(f"{record_label}: exact SPDX and SLSA artifacts required")
        artifact_types: set[str] = set()
        for artifact_index, artifact in enumerate(artifacts):
            artifact_label = f"{record_label}.artifacts[{artifact_index}]"
            if not isinstance(artifact, dict) or set(artifact) != {
                "artifact_type",
                "media_type",
                "digest",
                "size_bytes",
            }:
                raise ValueError(f"{artifact_label}: exact artifact descriptor shape required")
            verify_descriptor(artifact, artifact_label, "size_bytes")
            if artifact.get("media_type") != "application/vnd.in-toto+json":
                raise ValueError(f"{artifact_label}: provenance artifact media type changed")
            artifact_type = artifact.get("artifact_type")
            if artifact_type in artifact_types:
                raise ValueError(f"{artifact_label}: duplicate provenance artifact type")
            artifact_types.add(artifact_type)
        if artifact_types != {
            "https://spdx.dev/Document",
            "https://slsa.dev/provenance/v0.2",
        }:
            raise ValueError(f"{record_label}: exact SPDX and SLSA artifacts required")
    if provenance_platforms != {"linux/amd64", "linux/arm64"}:
        raise ValueError(f"{label}: exact dual-platform provenance records required")


def verify_model(model: dict[str, Any]) -> None:
    files = model.get("files", [])
    paths = [item["path"] for item in files]
    if len(paths) != len(set(paths)) or not files:
        raise ValueError("speech model files must be nonempty and unique")
    total = 0
    for index, item in enumerate(files):
        require_digest(item["sha256"], f"speech.files[{index}].sha256")
        if not isinstance(item["size_bytes"], int) or item["size_bytes"] < 0:
            raise ValueError(f"speech.files[{index}]: invalid size")
        total += item["size_bytes"]
    if total != model["verification"]["total_size_bytes"]:
        raise ValueError("speech model total byte count mismatch")
    if model.get("download_at_runtime") is not False:
        raise ValueError("speech model runtime download must be false")


def verify_speech_license_inputs(root: Path, model: dict[str, Any]) -> None:
    license_inputs = model.get("license_inputs")
    if license_inputs != SPEECH_LICENSE_INPUTS:
        raise ValueError("speech model exact nonempty license input inventory changed")
    if model.get("license_declared_by_model_card") != "MIT":
        raise ValueError("speech model declared license changed")
    license_input = license_inputs[0]
    relative = license_input["vendored_path"]
    path = root / relative
    if (
        not path.is_file()
        or path.is_symlink()
        or path.stat().st_size != 1063
        or sha256_file(path) != license_input["source_sha256"]
    ):
        raise ValueError("speech model vendored license bytes changed")


def verify_chromium_input(browser: dict[str, Any]) -> None:
    chromium = browser.get("chromium_headless_shell")
    if not isinstance(chromium, dict):
        raise ValueError("Chromium headless-shell declaration is missing")
    if (
        chromium.get("version") != "153.0.8010.12"
        or chromium.get("playwright_revision") != "1243"
        or chromium.get("mode") != "headless-shell-only"
        or chromium.get("member_count_each") != 287
        or chromium.get("about_sha256")
        != "34d078ce3003087a8374e7c6156fda374769b8047d6ddaf419d66414aa48edfb"
        or chromium.get("license_headless_shell")
        != {
            "bytes": 2257005,
            "sha256": "b92247f7a44c14627ef5cbbe0aa6dcca4e4422b7c05e6f2c660054061a5e3da7",
        }
        or chromium.get("widevine_present") is not False
        or chromium.get("mirrored_by_deeptwin") is not False
    ):
        raise ValueError("Chromium headless-shell identity or license binding changed")
    assets = chromium.get("assets")
    if not isinstance(assets, list) or len(assets) != len(CHROMIUM_ASSETS):
        raise ValueError("Chromium exact dual-platform asset inventory changed")
    observed: set[str] = set()
    for item in assets:
        if not isinstance(item, dict):
            raise ValueError("Chromium exact dual-platform asset inventory changed")
        platform = item.get("platform")
        if platform in observed or item != CHROMIUM_ASSETS.get(platform):
            raise ValueError("Chromium exact dual-platform asset inventory changed")
        observed.add(platform)
    if observed != set(CHROMIUM_ASSETS):
        raise ValueError("Chromium exact dual-platform asset inventory changed")


def verify_age_build_input(age: dict[str, Any]) -> None:
    if (
        age.get("schema_version") != "deeptwin-tool-build-input-v1"
        or age.get("tool") != "age"
        or age.get("version") != "1.3.2"
        or age.get("tag") != "v1.3.2"
        or age.get("source_commit")
        != "b74dce4cdbe35b5e5f66c06d9612b72f89028758"
    ):
        raise ValueError("age exact release identity changed")
    archives = age.get("platform_archives")
    if not isinstance(archives, list) or len(archives) != len(AGE_PLATFORM_ARCHIVES):
        raise ValueError("age exact dual-platform archive inventory changed")
    observed: set[str] = set()
    for archive in archives:
        if not isinstance(archive, dict):
            raise ValueError("age exact dual-platform archive inventory changed")
        platform = archive.get("platform")
        if platform in observed or archive != AGE_PLATFORM_ARCHIVES.get(platform):
            raise ValueError("age exact dual-platform archive inventory changed")
        observed.add(platform)
    if observed != set(AGE_PLATFORM_ARCHIVES):
        raise ValueError("age exact dual-platform archive inventory changed")
    if age.get("embedded_modules") != AGE_EMBEDDED_MODULES:
        raise ValueError("age exact embedded-module inventory changed")
    if age.get("forbidden_archive_members_in_final_image") != [
        "age/age-inspect",
        "age/age-plugin-batchpass",
        "age/age-plugin-pq",
        "age/age-plugin-tag",
        "age/age-plugin-tagpq",
    ]:
        raise ValueError("age forbidden archive-member inventory changed")


def verify_age_license_bundle_structure(
    root: Path,
    age: dict[str, Any],
    age_license_manifest: dict[str, Any],
) -> None:
    if (
        age_license_manifest.get("schema_version")
        != "deeptwin-static-go-license-bundle-v1"
        or age_license_manifest.get("status")
        != "candidate_technical_inventory_not_legal_approval"
        or age_license_manifest.get("tool") != "age"
        or age_license_manifest.get("version") != age["version"]
        or age_license_manifest.get("go_version") != "go1.27.0"
        or age_license_manifest.get("source_archive_sha256")
        != "c160d6f907992561413a28818f7d7585b35977cdbc449f3e96c4f8c99d22d21e"
        or age_license_manifest.get("go_source")
        != {
            "url": "https://go.dev/dl/go1.27.0.src.tar.gz",
            "release_metadata_url": "https://go.dev/dl/?mode=json&include=all",
            "bytes": 35080395,
            "sha256": "7002403d7cc44529ef6d26f69a44818263395ead7c16c05a5808ae047ebeb0e5",
            "license_member": "go/LICENSE",
            "license_bytes": 1453,
            "license_sha256": "911f8f5782931320f5b8d1160a76365b83aea6447ee6c04fa6d5591467db9dad",
        }
        or age_license_manifest.get("release_archive_license")
        != {
            "member": "age/LICENSE",
            "bytes": 2975,
            "sha256": "afbdb4e07a359499db587ae632815809b1fc1670a92d5449af112ce9a67833a2",
        }
        or age_license_manifest.get("license_files") != AGE_LICENSE_FILES
        or age_license_manifest.get("components") != AGE_LICENSE_COMPONENTS
        or age_license_manifest.get("executable_module_sets")
        != AGE_EXECUTABLE_MODULE_SETS
    ):
        raise ValueError("age exact runtime license component/file inventory changed")
    runtime_ref = age.get("runtime_license_bundle", {})
    if (
        runtime_ref.get("component_count") != len(AGE_LICENSE_COMPONENTS)
        or runtime_ref.get("unique_license_file_count") != len(AGE_LICENSE_FILES)
        or runtime_ref.get("legal_approval") is not False
    ):
        raise ValueError("age runtime license bundle binding changed")
    for item in AGE_LICENSE_FILES:
        path = root / item["path"]
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != item["bytes"]
            or sha256_file(path) != item["sha256"]
        ):
            raise ValueError("age runtime license bytes changed")


def verify_upstream_provenance_evidence(root: Path, upstream: dict[str, Any]) -> None:
    reference = upstream.get("provenance_verification")
    if not isinstance(reference, dict) or set(reference) != {
        "path",
        "bytes",
        "sha256",
        "verified",
        "scope",
    }:
        raise ValueError("upstream provenance verification reference is incomplete")
    relative = reference["path"]
    path = root / relative
    if (
        relative
        != "specs/001-autonomous-release/evidence/upstream-image-provenance-results.json"
        or reference.get("verified") is not True
        or reference.get("scope")
        != "Published SPDX and SLSA descriptor inventory and exact statement-subject linkage for the selected linux/amd64 and linux/arm64 runnable manifests"
        or not path.is_file()
        or path.is_symlink()
        or path.stat().st_size != reference.get("bytes")
        or sha256_file(path) != reference.get("sha256")
    ):
        raise ValueError("upstream provenance verification reference changed")
    evidence = load_json(path)
    if (
        set(evidence)
        != {
            "schema_version",
            "verified_at",
            "network_used",
            "registry",
            "method",
            "images",
            "verified",
            "qualification_boundary",
        }
        or evidence.get("schema_version")
        != "deeptwin-upstream-image-provenance-results-v1"
        or evidence.get("network_used") is not True
        or evidence.get("registry") != "registry-1.docker.io/v2"
        or evidence.get("verified") is not True
        or not isinstance(evidence.get("verified_at"), str)
        or not evidence["verified_at"]
        or not isinstance(evidence.get("method"), str)
        or not evidence["method"]
        or not isinstance(evidence.get("qualification_boundary"), str)
        or not evidence["qualification_boundary"]
    ):
        raise ValueError("upstream provenance verification result is not valid")
    manifest_images = {item["image_id"]: item for item in upstream["images"]}
    evidence_images = evidence.get("images")
    if not isinstance(evidence_images, list) or len(evidence_images) != len(
        manifest_images
    ):
        raise ValueError("upstream provenance evidence image inventory changed")
    evidence_by_id = {
        item.get("image_id"): item
        for item in evidence_images
        if isinstance(item, dict)
    }
    if len(evidence_by_id) != len(evidence_images) or set(evidence_by_id) != set(
        manifest_images
    ):
        raise ValueError("upstream provenance evidence image inventory changed")
    for image_id, image in manifest_images.items():
        result = evidence_by_id[image_id]
        if (
            set(result) != {"image_id", "repository", "index_digest", "platforms"}
            or result.get("repository") != image["repository"]
            or result.get("index_digest") != image["top_descriptor"]["digest"]
        ):
            raise ValueError("upstream provenance evidence image binding changed")
        declarations = {
            item["platform"]: item for item in image["provenance_descriptors"]
        }
        platform_results = result.get("platforms")
        if not isinstance(platform_results, list) or len(platform_results) != len(
            declarations
        ):
            raise ValueError("upstream provenance evidence platform inventory changed")
        results_by_platform = {
            item.get("platform"): item
            for item in platform_results
            if isinstance(item, dict)
        }
        if len(results_by_platform) != len(platform_results) or set(
            results_by_platform
        ) != set(declarations):
            raise ValueError("upstream provenance evidence platform inventory changed")
        for platform, declaration in declarations.items():
            result_platform = results_by_platform[platform]
            if set(result_platform) != {
                "platform",
                "runnable_manifest_digest",
                "attestation_manifest",
                "config",
                "spdx",
                "slsa",
            }:
                raise ValueError("upstream provenance evidence platform shape changed")
            artifact_by_type = {
                item["artifact_type"]: item for item in declaration["artifacts"]
            }
            spdx = result_platform["spdx"]
            slsa = result_platform["slsa"]
            if (
                not isinstance(spdx, dict)
                or set(spdx)
                != {
                    "digest",
                    "bytes",
                    "statement_type",
                    "predicate_type",
                    "subject_digest",
                    "spdx_version",
                    "package_count",
                    "file_count",
                }
                or not isinstance(slsa, dict)
                or set(slsa)
                != {
                    "digest",
                    "bytes",
                    "statement_type",
                    "predicate_type",
                    "subject_digest",
                    "builder_id",
                    "config_source",
                    "entry_point",
                    "materials_count",
                }
                or result_platform["runnable_manifest_digest"]
                != declaration["subject_manifest_digest"]
                or result_platform["attestation_manifest"]
                != {
                    "digest": declaration["manifest"]["digest"],
                    "bytes": declaration["manifest"]["size_bytes"],
                }
                or result_platform["config"]
                != {
                    "digest": declaration["config"]["digest"],
                    "bytes": declaration["config"]["size_bytes"],
                }
                or spdx.get("digest")
                != artifact_by_type["https://spdx.dev/Document"]["digest"]
                or spdx.get("bytes")
                != artifact_by_type["https://spdx.dev/Document"]["size_bytes"]
                or spdx.get("statement_type")
                != "https://in-toto.io/Statement/v0.1"
                or spdx.get("predicate_type") != "https://spdx.dev/Document"
                or spdx.get("subject_digest")
                != declaration["subject_manifest_digest"]
                or spdx.get("spdx_version") != "SPDX-2.3"
                or type(spdx.get("package_count")) is not int
                or spdx["package_count"] <= 0
                or type(spdx.get("file_count")) is not int
                or spdx["file_count"] <= 0
                or slsa.get("digest")
                != artifact_by_type["https://slsa.dev/provenance/v0.2"]["digest"]
                or slsa.get("bytes")
                != artifact_by_type["https://slsa.dev/provenance/v0.2"]["size_bytes"]
                or slsa.get("statement_type")
                != "https://in-toto.io/Statement/v0.1"
                or slsa.get("predicate_type")
                != "https://slsa.dev/provenance/v0.2"
                or slsa.get("subject_digest")
                != declaration["subject_manifest_digest"]
                or slsa.get("builder_id") != "https://github.com/docker-library"
                or slsa.get("config_source")
                != (
                    f"{image['source_repository']}.git#{image['source_commit']}:"
                    f"{image['source_path'].rsplit('/', 1)[0]}"
                )
                or slsa.get("entry_point") != image["source_path"].rsplit("/", 1)[1]
                or type(slsa.get("materials_count")) is not int
                or slsa["materials_count"] <= 0
            ):
                raise ValueError("upstream provenance evidence statement binding changed")


def verify_upstream_provenance_policy(root: Path, upstream: dict[str, Any]) -> None:
    images = upstream.get("images")
    if not isinstance(images, list) or len(images) != len(UPSTREAM_PROVENANCE):
        raise ValueError("upstream exact image provenance inventory changed")
    observed_ids: set[str] = set()
    for image in images:
        image_id = image.get("image_id") if isinstance(image, dict) else None
        if (
            image_id in observed_ids
            or image_id not in UPSTREAM_PROVENANCE
            or image.get("provenance_descriptors") != UPSTREAM_PROVENANCE[image_id]
        ):
            raise ValueError("upstream exact image provenance inventory changed")
        observed_ids.add(image_id)
    if observed_ids != set(UPSTREAM_PROVENANCE):
        raise ValueError("upstream exact image provenance inventory changed")
    blockers = upstream.get("release_blockers")
    if not isinstance(blockers, list) or not blockers or any(
        not isinstance(item, str) or not item for item in blockers
    ):
        raise ValueError("upstream image release-blocker inventory is incomplete")
    verify_upstream_provenance_evidence(root, upstream)


def verify_python_wheels(
    root: Path, manifest: dict[str, Any], roots: dict[str, Any]
) -> None:
    label = "python-wheels"
    target_platforms = {
        (item.get("os"), item.get("architecture"))
        for item in manifest.get("target_platforms", [])
    }
    if target_platforms != PLATFORMS:
        raise ValueError(f"{label}: expected exact linux/amd64+linux/arm64 targets")
    runtime = manifest.get("runtime", {})
    if (
        runtime.get("implementation") != "CPython"
        or runtime.get("python_version") != roots["python"]["version"]
        or runtime.get("abi") != roots["python"]["abi"]
        or runtime.get("glibc_floor") != roots["python"]["glibc_floor"]
    ):
        raise ValueError(f"{label}: runtime and service root declarations disagree")

    lock_declarations = manifest.get("service_locks", [])
    if {item.get("service") for item in lock_declarations} != set(PYTHON_PROFILES):
        raise ValueError(f"{label}: exact service-profile declarations are required")
    declaration_by_service = {item["service"]: item for item in lock_declarations}
    locks: dict[str, dict[str, dict[str, Any]]] = {}
    for service, declaration in declaration_by_service.items():
        relative = declaration.get("path")
        if relative != f"deploy/locks/requirements-{service}-linux.lock":
            raise ValueError(f"{label}.{service}: unexpected lock path")
        locks[service] = parse_lock(root / relative)
        if declaration.get("package_count") != len(locks[service]):
            raise ValueError(f"{label}.{service}: package count mismatch")
        consumers = declaration.get("consumers")
        if not isinstance(consumers, list) or not consumers or len(consumers) != len(set(consumers)):
            raise ValueError(f"{label}.{service}: nonempty unique consumers required")

    artifact_keys: set[tuple[str, str, str, str]] = set()
    by_usage: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    artifacts = manifest.get("artifacts", [])
    if not artifacts:
        raise ValueError(f"{label}: artifact inventory is empty")
    for index, artifact in enumerate(artifacts):
        a_label = f"{label}.artifacts[{index}]"
        name = artifact.get("name")
        version = artifact.get("version")
        filename = artifact.get("filename")
        digest = artifact.get("sha256")
        if not isinstance(name, str) or name != canonicalize_package_name(name):
            raise ValueError(f"{a_label}: canonical package name required")
        if not isinstance(version, str) or not version:
            raise ValueError(f"{a_label}: version required")
        if not isinstance(filename, str) or not filename.endswith(".whl"):
            raise ValueError(f"{a_label}: wheel filename required")
        if not isinstance(digest, str):
            raise ValueError(f"{a_label}: sha256 required")
        require_digest(digest, f"{a_label}.sha256")
        if not isinstance(artifact.get("size_bytes"), int) or artifact["size_bytes"] <= 0:
            raise ValueError(f"{a_label}: positive byte size required")
        key = (name, version, filename, digest)
        if key in artifact_keys:
            raise ValueError(f"{a_label}: duplicate artifact identity")
        artifact_keys.add(key)

        source = artifact.get("source", {})
        if source.get("type") == "pypi":
            if canonicalize_package_name(source.get("project", "")) != name:
                raise ValueError(f"{a_label}: PyPI project/name mismatch")
            release_url = source.get("release_metadata_url", "")
            download_url = source.get("download_url", "")
            if release_url != f"https://pypi.org/pypi/{name}/{version}/json":
                raise ValueError(f"{a_label}: unexpected PyPI release URL")
            if not download_url.startswith("https://files.pythonhosted.org/packages/"):
                raise ValueError(f"{a_label}: unexpected wheel download authority")
            if download_url.rsplit("/", 1)[-1] != filename:
                raise ValueError(f"{a_label}: wheel URL filename mismatch")
        elif source.get("type") == "local-derived":
            if name != "deeptwin-faster-whisper":
                raise ValueError(f"{a_label}: unexpected locally derived package")
            if source.get("derivation_ref") != (
                "deploy/locks/service-roots.json#derived_build_inputs/speech-worker"
            ):
                raise ValueError(f"{a_label}: invalid derivation reference")
        else:
            raise ValueError(f"{a_label}: unsupported source type")

        wheel_platform = artifact.get("wheel", {}).get("platform", {})
        artifact_platform = (
            wheel_platform.get("os"),
            wheel_platform.get("architecture"),
        )
        if artifact_platform not in PLATFORMS | {("any", "any")}:
            raise ValueError(f"{a_label}: unsupported wheel platform")

        license_info = artifact.get("license", {})
        resources = license_info.get("embedded_resources")
        if not isinstance(resources, list):
            raise ValueError(f"{a_label}: embedded legal-resource list required")
        resource_paths: set[str] = set()
        for resource_index, resource in enumerate(resources):
            r_label = f"{a_label}.license.embedded_resources[{resource_index}]"
            path = resource.get("path")
            if not isinstance(path, str) or not path or path in resource_paths:
                raise ValueError(f"{r_label}: unique resource path required")
            resource_paths.add(path)
            require_digest(resource.get("sha256", ""), f"{r_label}.sha256")
            if not isinstance(resource.get("size_bytes"), int) or resource["size_bytes"] <= 0:
                raise ValueError(f"{r_label}: positive byte size required")
        if license_info.get("t084_embedded_license_follow_up_required") != (not resources):
            raise ValueError(f"{a_label}: legal follow-up flag mismatch")

        usages = artifact.get("usage")
        if not isinstance(usages, list) or not usages:
            raise ValueError(f"{a_label}: at least one service/platform usage required")
        usage_keys: set[tuple[str, str]] = set()
        for usage in usages:
            service = usage.get("service")
            platform = (usage.get("os"), usage.get("architecture"))
            if service not in PYTHON_PROFILES or platform not in PLATFORMS:
                raise ValueError(f"{a_label}: unknown service or target platform")
            if artifact_platform != ("any", "any") and artifact_platform != platform:
                raise ValueError(f"{a_label}: wheel/usage platform mismatch")
            usage_key = (service, platform[1])
            if usage_key in usage_keys:
                raise ValueError(f"{a_label}: duplicate usage")
            usage_keys.add(usage_key)
            by_usage.setdefault((service, platform[0], platform[1]), []).append(artifact)

    for service, lock in locks.items():
        combined_hashes: dict[str, set[str]] = {name: set() for name in lock}
        for os_name, architecture in sorted(PLATFORMS):
            selected = by_usage.get((service, os_name, architecture), [])
            selected_by_name: dict[str, dict[str, Any]] = {}
            for artifact in selected:
                name = artifact["name"]
                if name in selected_by_name:
                    raise ValueError(
                        f"{label}.{service}/{architecture}: duplicate package artifact {name}"
                    )
                selected_by_name[name] = artifact
            if set(selected_by_name) != set(lock):
                raise ValueError(f"{label}.{service}/{architecture}: closure name mismatch")
            for name, artifact in selected_by_name.items():
                if artifact["version"] != lock[name]["version"]:
                    raise ValueError(f"{label}.{service}/{name}: version mismatch")
                if artifact["sha256"] not in lock[name]["hashes"]:
                    raise ValueError(f"{label}.{service}/{name}: artifact absent from lock")
                combined_hashes[name].add(artifact["sha256"])
        for name, observed_hashes in combined_hashes.items():
            if observed_hashes != lock[name]["hashes"]:
                raise ValueError(f"{label}.{service}/{name}: lock contains unused hash")

        roots_key = PYTHON_PROFILES[service]
        for root_requirement in roots["services"].get(roots_key, []):
            match = re.fullmatch(r"([^=]+)==(.+)", root_requirement)
            if not match:
                raise ValueError(f"service-roots.{roots_key}: exact pin required")
            name = canonicalize_package_name(match.group(1))
            if name not in lock or lock[name]["version"] != match.group(2):
                raise ValueError(f"{label}.{service}: direct root missing from closure")

    expected_missing = {
        (artifact["name"], artifact["version"], artifact["filename"], artifact["sha256"])
        for artifact in artifacts
        if not artifact["license"]["embedded_resources"]
    }
    declared_missing = {
        (item.get("name"), item.get("version"), item.get("filename"), item.get("sha256"))
        for item in manifest.get("legal_gate", {}).get(
            "artifacts_without_embedded_license_resources", []
        )
    }
    if declared_missing != expected_missing:
        raise ValueError(f"{label}: legal-gate inventory mismatch")

    expected_external_packages = {
        (name, version) for name, version, _filename, _digest in expected_missing
    }
    external_entries = manifest.get("legal_gate", {}).get(
        "external_source_license_resources", []
    )
    declared_external_packages: set[tuple[str, str]] = set()
    external_paths: set[str] = set()
    for entry_index, entry in enumerate(external_entries):
        entry_label = f"{label}.legal_gate.external[{entry_index}]"
        package_key = (entry.get("name"), entry.get("version"))
        if package_key in declared_external_packages:
            raise ValueError(f"{entry_label}: duplicate package license entry")
        declared_external_packages.add(package_key)
        repository = entry.get("source_repository", "")
        commit = entry.get("source_commit", "")
        if (
            not repository.startswith("https://github.com/")
            or not re.fullmatch(r"[0-9a-f]{40}", commit)
            or not isinstance(entry.get("source_tag"), str)
        ):
            raise ValueError(f"{entry_label}: exact upstream source identity required")
        resources = entry.get("resources")
        if not isinstance(resources, list) or not resources:
            raise ValueError(f"{entry_label}: external license resource required")
        for resource_index, resource in enumerate(resources):
            resource_label = f"{entry_label}.resources[{resource_index}]"
            relative = resource.get("path", "")
            if (
                not relative.startswith("deploy/locks/licenses/")
                or relative in external_paths
            ):
                raise ValueError(f"{resource_label}: unique locked license path required")
            external_paths.add(relative)
            resource_path = root / relative
            if (
                resource_path.stat().st_size != resource.get("bytes")
                or sha256_file(resource_path) != resource.get("sha256")
                or f"/{commit}/" not in resource.get("source_url", "")
            ):
                raise ValueError(f"{resource_label}: external license bytes changed")
    if declared_external_packages != expected_external_packages:
        raise ValueError(f"{label}: external license package coverage mismatch")

    derived_digest = roots["derived_build_inputs"]["speech-worker"]["output_sha256"]
    derived = [
        artifact
        for artifact in artifacts
        if artifact["name"] == "deeptwin-faster-whisper"
    ]
    if len(derived) != 1 or derived[0]["sha256"] != derived_digest:
        raise ValueError(f"{label}: derived speech wheel digest mismatch")


def canonical_digest(value: dict[str, Any], excluded_key: str) -> str:
    projection = {key: item for key, item in value.items() if key != excluded_key}
    encoded = json.dumps(
        projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_exact_equal(actual: Any, expected: Any) -> bool:
    """Compare JSON values without Python's bool/int or int/float coercion."""

    return json.dumps(
        actual, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) == json.dumps(
        expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _verify_codex_rust_dependency_inputs(root: Path) -> None:
    """Validate Rust/license/SBOM closure independently of the runner schema."""

    for reference, label in (
        (CODEX_RUST_DEPENDENCY_INVENTORY, "Rust dependency inventory"),
        (CODEX_RUST_DEPENDENCY_INVENTORY["evidence"], "Rust inventory evidence"),
    ):
        relative = reference["path"]
        reference_path = root / relative
        if (
            reference_path.is_symlink()
            or not reference_path.is_file()
            or reference_path.stat().st_size != reference["bytes"]
            or sha256_file(reference_path) != reference["sha256"]
        ):
            raise ValueError(f"Codex {label} reference changed: {relative}")

    rust_verifier_path = root / "deploy/locks/verify_codex_rust_inventory.py"
    if rust_verifier_path.is_symlink() or not rust_verifier_path.is_file():
        raise ValueError("Codex Rust inventory verifier is absent or not regular")
    rust_spec = importlib.util.spec_from_file_location(
        "deeptwin_codex_rust_inventory_verifier", rust_verifier_path
    )
    if rust_spec is None or rust_spec.loader is None:
        raise ValueError("Codex Rust inventory verifier could not be loaded")
    rust_module = importlib.util.module_from_spec(rust_spec)
    sys.modules[rust_spec.name] = rust_module
    rust_spec.loader.exec_module(rust_module)
    rust_result = rust_module.verify_inventory(root)
    if not _json_exact_equal(
        {
            "inventory_digest": rust_result.get("inventory_digest"),
            "package_count": rust_result.get("package_count"),
            "release_gate": rust_result.get("release_gate"),
        },
        {
            "inventory_digest": CODEX_RUST_DEPENDENCY_INVENTORY["inventory_digest"],
            "package_count": 1047,
            "release_gate": "not_satisfied",
        },
    ):
        raise ValueError("Codex Rust inventory verified summary changed")


def _load_codex_v3_contract(
    root: Path,
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
    verifier_path = root / "deploy/locks/verify_codex_runner.py"
    spec = importlib.util.spec_from_file_location(
        "deeptwin_codex_runner_policy_for_component", verifier_path
    )
    if spec is None or spec.loader is None:
        raise ValueError("Codex managed-runner verifier could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    bootstrap = getattr(module, "COSIGN_BOOTSTRAP_POLICY", None)
    build_blockers = getattr(module, "EXPECTED_BUILD_INPUT_BLOCKERS", None)
    downstream_blockers = getattr(
        module, "EXPECTED_DOWNSTREAM_RELEASE_BLOCKERS", None
    )
    if (
        type(bootstrap) is not dict
        or type(build_blockers) is not tuple
        or type(downstream_blockers) is not tuple
    ):
        raise ValueError("Codex v3 gate or verifier-bootstrap contract is unavailable")
    signature_policy = {
        "offline": True,
        "subject_scope": "extracted executable only",
        "certificate_identity": CODEX_SIGNATURE_IDENTITY,
        "certificate_oidc_issuer": CODEX_SIGNATURE_ISSUER,
        "verifier_bootstrap": bootstrap,
    }
    return signature_policy, list(build_blockers), list(downstream_blockers)


def _verify_codex_blocker_records(
    value: Any,
    *,
    label: str,
    expected: list[dict[str, str]],
    build_input: bool,
) -> list[dict[str, str]]:
    if type(value) is not list or len(value) > 64:
        raise ValueError(f"Codex {label} must be a bounded structured list")
    blocker_ids: set[str] = set()
    gate_ids: set[str] = set()
    for record in value:
        if type(record) is not dict or set(record) != {
            "blocker_id", "owner_task", "gate_id", "summary"
        }:
            raise ValueError(
                f"Codex {label} must use exact structured blocker records"
            )
        if any(type(record[key]) is not str for key in record):
            raise ValueError(f"Codex {label} fields must be strings")
        if any(
            re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", record[key]) is None
            for key in ("blocker_id", "gate_id")
        ):
            raise ValueError(f"Codex {label} IDs must be stable kebab-case")
        if (
            not record["summary"]
            or len(record["summary"].encode("utf-8")) > 256
            or "\n" in record["summary"]
        ):
            raise ValueError(f"Codex {label} summary must be concise and bounded")
        if build_input and record["owner_task"] != "T089":
            raise ValueError("Codex build-input blocker ownership changed")
        if record["blocker_id"] in blocker_ids or record["gate_id"] in gate_ids:
            raise ValueError(f"Codex {label} has duplicate blocker or gate IDs")
        blocker_ids.add(record["blocker_id"])
        gate_ids.add(record["gate_id"])
    if not _json_exact_equal(value, expected):
        raise ValueError(
            f"Codex {label} inventory, ownership, or canonical order changed"
        )
    return value


def verify_codex_build_input(root: Path, codex: dict[str, Any]) -> None:
    """Verify the exact minimal Codex runner and its split gate ownership.

    The signed standalone executables, dated Debian Bookworm OCI descriptors,
    Bash binary package/member/license and matching source inputs are pinned.
    Runtime qualification and the remaining legal/source-to-binary gates stay
    open; exact inputs must not be confused with a releasable runner.
    """

    expected_root_keys = {
        "schema_version",
        "status",
        "version",
        "tag",
        "source_commit",
        "target_platforms",
        "signature_policy",
        "runtime_layout",
        "platform_inputs",
        "omitted_components",
        "runtime_mutation_policy",
        "build_input_gate",
        "build_input_blockers",
        "release_gate",
        "downstream_release_blockers",
    }
    if set(codex) != expected_root_keys:
        raise ValueError("Codex candidate root claim inventory changed")
    expected_identity = {
        "schema_version": CODEX_SCHEMA,
        "status": "candidate_not_release_qualified",
        "version": "0.153.4",
        "tag": "rust-v0.153.4",
        "source_commit": "3d2ee51ca2d5db578f328aa75e20aa22c0197c9a",
        "target_platforms": list(CODEX_PLATFORMS),
    }
    if any(
        not _json_exact_equal(codex.get(key), value)
        for key, value in expected_identity.items()
    ):
        raise ValueError("Codex minimal-runner identity or platform order changed")

    (
        expected_signature_policy,
        expected_build_blockers,
        expected_downstream_blockers,
    ) = _load_codex_v3_contract(root)
    if not _json_exact_equal(
        codex.get("signature_policy"), expected_signature_policy
    ):
        raise ValueError("Codex executable-scoped signature policy changed")
    if not _json_exact_equal(codex.get("runtime_layout"), CODEX_RUNTIME_LAYOUT):
        raise ValueError("Codex fixed runtime layout changed")
    if not _json_exact_equal(
        codex.get("omitted_components"), list(CODEX_OMITTED_COMPONENTS)
    ):
        raise ValueError("Codex omitted component boundary changed")
    if not _json_exact_equal(
        codex.get("runtime_mutation_policy"), CODEX_RUNTIME_MUTATION_POLICY
    ):
        raise ValueError("Codex runtime mutation policy changed")
    build_blockers = _verify_codex_blocker_records(
        codex.get("build_input_blockers"),
        label="build_input_blockers",
        expected=expected_build_blockers,
        build_input=True,
    )
    downstream_blockers = _verify_codex_blocker_records(
        codex.get("downstream_release_blockers"),
        label="downstream_release_blockers",
        expected=expected_downstream_blockers,
        build_input=False,
    )
    expected_build_gate = "not_satisfied" if build_blockers else "satisfied"
    if codex.get("build_input_gate") != expected_build_gate:
        raise ValueError(
            "Codex build_input_gate must depend only on T089 build blockers"
        )
    expected_release_gate = (
        "not_satisfied" if build_blockers or downstream_blockers else "satisfied"
    )
    if codex.get("release_gate") != expected_release_gate:
        raise ValueError(
            "Codex release_gate must include downstream release blockers"
        )

    platform_inputs = codex.get("platform_inputs")
    if type(platform_inputs) is not list or len(platform_inputs) != len(
        CODEX_PLATFORMS
    ):
        raise ValueError("Codex platform_inputs must contain the exact supported pair")
    for index, platform in enumerate(CODEX_PLATFORMS):
        platform_input = platform_inputs[index]
        if type(platform_input) is not dict or set(platform_input) != {
            "platform",
            "target",
            "components",
            "runtime_image",
        }:
            raise ValueError(f"Codex {platform} platform input shape changed")
        expected = CODEX_PLATFORM_INPUTS[platform]
        if (
            platform_input.get("platform") != platform
            or platform_input.get("target") != expected["target"]
        ):
            raise ValueError("Codex platform input ordering or target changed")

        components = platform_input.get("components")
        if type(components) is not list or [
            item.get("name") if type(item) is dict else None for item in components
        ] != list(CODEX_COMPONENTS):
            raise ValueError(f"Codex {platform} component ordering changed")
        if not _json_exact_equal(components, expected["components"]):
            raise ValueError(f"Codex {platform} signed standalone component input changed")

        runtime_image = platform_input.get("runtime_image")
        if not _json_exact_equal(runtime_image, CODEX_RUNTIME_INPUTS[platform]):
            raise ValueError(
                f"Codex {platform} Bookworm runtime closure changed"
            )

    _verify_codex_rust_dependency_inputs(root)


def verify_repository(
    root: Path,
    require_release_ready: bool,
    *,
    verify_aggregate_lock: bool = True,
) -> None:
    manifests = root / "deploy" / "manifests"
    locks = root / "deploy" / "locks"
    paths = {
        "upstream": manifests / "upstream-images.json",
        "browser": manifests / "browser-worker.json",
        "browser_debian": manifests / "browser-debian-bookworm.json",
        "browser_debian_sources": manifests / "browser-debian-bookworm.sources.json",
        "codex": manifests / "codex-0.153.4.json",
        "age": manifests / "age-1.3.2.json",
        "speech": manifests / "speech-model.json",
        "python_wheels": manifests / "python-wheel-artifacts.json",
        "roots": locks / "service-roots.json",
    }
    values = {name: load_json(path) for name, path in paths.items()}
    for name, value in values.items():
        reject_abbreviated_digests(value, name)
    verify_codex_build_input(root, values["codex"])

    for index, image in enumerate(values["upstream"].get("images", [])):
        verify_image(image, f"upstream.images[{index}]")
    if len(values["upstream"].get("images", [])) != 3:
        raise ValueError("exactly Python, Node and Caddy upstream images are required")
    verify_upstream_provenance_policy(root, values["upstream"])

    upstream_by_id = {
        image["image_id"]: image for image in values["upstream"]["images"]
    }
    browser_node = values["browser"]["node"]["base_image"]
    if (
        browser_node["top_descriptor"]["digest"]
        != upstream_by_id["browser-node-base"]["top_descriptor"]["digest"]
    ):
        raise ValueError("browser Node base digest disagrees with upstream image lock")
    node = values["browser"]["node"]
    node_provenance = node["official_release_provenance"]
    signed_checksums = node_provenance["signed_checksums"]
    keyring = node_provenance["verification_keyring"]
    node_license = node_provenance["license"]
    for resource, resource_label in (
        (signed_checksums, "signed checksums"),
        (keyring, "verification keyring"),
        (node_license, "license"),
    ):
        resource_path = root / resource["path"]
        if (
            resource_path.stat().st_size != resource["bytes"]
            or sha256_file(resource_path) != resource["sha256"]
        ):
            raise ValueError(f"Node {resource_label} reference changed")
    if (
        node.get("version") != "24.20.0"
        or node_provenance.get("source_tag") != "v24.20.0"
        or node_provenance.get("source_commit")
        != "71b8b174857e25106d39b61a9e6f30d927da8b01"
        or signed_checksums.get("openpgp_verified") is not True
        or signed_checksums.get("signer_fingerprint")
        != "5BE8A3F6C8A5C01D106C0AD820B1A390B168D356"
        or keyring.get("source_commit")
        != "5b7f55f4a7e35d1176d27a6b81b0c3c3b794216b"
        or node_license.get("identical_in_both_platform_archives") is not True
    ):
        raise ValueError("Node official release provenance binding changed")
    node_platforms = {
        (item.get("os"), item.get("architecture")): item
        for item in node_provenance.get("platforms", [])
    }
    if set(node_platforms) != PLATFORMS:
        raise ValueError("Node official release platform closure changed")
    for platform, item in node_platforms.items():
        expected_arch = "x64" if platform[1] == "amd64" else "arm64"
        if (
            item.get("archive_url")
            != f"https://nodejs.org/dist/v24.20.0/node-v24.20.0-linux-{expected_arch}.tar.xz"
            or not isinstance(item.get("archive_bytes"), int)
            or item["archive_bytes"] <= 0
            or not isinstance(item.get("executable_bytes"), int)
            or item["executable_bytes"] <= 0
            or item.get("base_image_executable_sha256_match") is not True
        ):
            raise ValueError("Node official release platform binding changed")
        require_digest(item["archive_sha256"], "Node archive sha256")
        require_digest(item["executable_sha256"], "Node executable sha256")
    node_verifier = node_provenance["offline_release_verifier"]
    for path_key, size_key, digest_key, label in (
        ("path", "bytes", "sha256", "verifier"),
        ("test_path", "test_bytes", "test_sha256", "verifier test"),
        ("result_path", "result_bytes", "result_sha256", "verification result"),
    ):
        relative = node_verifier[path_key]
        resource_path = root / relative
        if (
            not relative.startswith(("deploy/", "specs/001-autonomous-release/evidence/"))
            or resource_path.stat().st_size != node_verifier[size_key]
            or sha256_file(resource_path) != node_verifier[digest_key]
        ):
            raise ValueError(f"Node offline {label} reference changed")
    node_result = load_json(root / node_verifier["result_path"])
    result_platforms = {
        item.get("platform"): item for item in node_result.get("platforms", [])
    }
    if (
        node_verifier.get("offline_test_count") != 20
        or node_verifier.get("network_during_verification") is not False
        or node_verifier.get("verified") is not True
        or node_verifier.get("runtime_image")
        != "python@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254"
        or node_result.get("verified") is not True
        or node_result.get("network_used") is not False
        or set(result_platforms) != {"linux/amd64", "linux/arm64"}
        or any(
            result_platforms[f"linux/{architecture}"].get("node_sha256")
            != node_platforms[("linux", architecture)]["executable_sha256"]
            for architecture in ("amd64", "arm64")
        )
    ):
        raise ValueError("Node offline release verification binding changed")
    browser_debian = values["browser_debian"]
    browser_debian_ref = values["browser"]["debian_runtime_lock"]
    if (
        browser_debian_ref.get("path") != "deploy/manifests/browser-debian-bookworm.json"
        or sha256_file(root / browser_debian_ref["path"])
        != browser_debian_ref.get("sha256")
    ):
        raise ValueError("browser worker Debian lock reference changed")
    if (
        browser_debian["upstream_inputs"]["node_base_image"]["top_descriptor"]["digest"]
        != browser_node["top_descriptor"]["digest"]
    ):
        raise ValueError("browser Debian closure disagrees with the Node base lock")
    if (
        browser_debian["roots"]["playwright_debian12_chromium"]
        != values["browser"]["debian12_runtime_roots"]
        or browser_debian["roots"]["rendering_fonts"]
        != values["browser"]["rendering_font_roots"]
    ):
        raise ValueError("browser Debian roots disagree with browser worker manifest")
    browser_source_ref = browser_debian["source_license_evidence"]
    if sha256_file(root / browser_source_ref["path"]) != browser_source_ref["sha256"]:
        raise ValueError("browser Debian source/license sidecar hash mismatch")
    browser_verifier_ref = browser_debian["snapshot"]["openpgp_verification"][
        "verification_script"
    ]
    if sha256_file(root / browser_verifier_ref["path"]) != browser_verifier_ref["sha256"]:
        raise ValueError("browser Debian verifier hash mismatch")
    browser_runtime_verifier_ref = browser_debian["runtime_verifier"]
    if (
        sha256_file(root / browser_runtime_verifier_ref["path"])
        != browser_runtime_verifier_ref["sha256"]
    ):
        raise ValueError("browser runtime verifier hash mismatch")

    browser = values["browser"]
    verify_chromium_input(browser)
    security = browser["runtime_security"]
    if not all(
        security.get(key) is True
        for key in (
            "non_root",
            "chromium_sandbox",
            "reject_no_sandbox",
            "no_new_privileges",
            "read_only_root",
        )
    ):
        raise ValueError("browser worker security baseline was weakened")
    capabilities = security["linux_capabilities"]
    if (
        capabilities.get("drop") != "ALL"
        or capabilities.get("add") != []
        or capabilities.get("forbidden") != ["SYS_ADMIN", "SYS_PTRACE"]
    ):
        raise ValueError("browser worker capability boundary changed")

    seccomp_ref = security["seccomp_profile"]
    seccomp_path = root / seccomp_ref["path"]
    if (
        seccomp_path.stat().st_size != seccomp_ref["bytes"]
        or sha256_file(seccomp_path) != seccomp_ref["sha256"]
    ):
        raise ValueError("browser worker seccomp profile reference changed")
    seccomp_base_ref = seccomp_ref["base"]
    seccomp_base_path = root / seccomp_base_ref["path"]
    if (
        seccomp_base_path.stat().st_size != seccomp_base_ref["bytes"]
        or sha256_file(seccomp_base_path) != seccomp_base_ref["sha256"]
        or seccomp_base_ref.get("source_commit")
        != "61eaf32614c7c71b60bd8927d3e6a4ffc8ff1f31"
    ):
        raise ValueError("browser worker base seccomp profile reference changed")
    seccomp = load_json(seccomp_path)
    seccomp_base = load_json(seccomp_base_path)
    sandbox_rule = seccomp.get("syscalls", [None])[0]
    rule_digest = hashlib.sha256(
        json.dumps(
            sandbox_rule, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    non_syscall_projection = {
        key: value for key, value in seccomp.items() if key != "syscalls"
    }
    base_non_syscall_projection = {
        key: value for key, value in seccomp_base.items() if key != "syscalls"
    }
    clone3_rules = [
        rule
        for rule in seccomp.get("syscalls", [])
        if "clone3" in rule.get("names", []) and rule.get("action") == "SCMP_ACT_ERRNO"
    ]
    expected_syscalls = ["clone", "setns", "unshare", "chroot"]
    if (
        seccomp_ref.get("patch", {}).get("operation")
        != "prepend_exact_syscall_rule"
        or rule_digest
        != seccomp_ref.get("patch", {}).get("canonical_rule_sha256")
        or seccomp.get("syscalls", [])[1:] != seccomp_base.get("syscalls", [])
        or non_syscall_projection != base_non_syscall_projection
        or not clone3_rules
        or any(rule.get("errnoRet") != 38 for rule in clone3_rules)
    ):
        raise ValueError("browser seccomp derived-profile binding changed")
    if (
        seccomp.get("defaultAction") != "SCMP_ACT_ERRNO"
        or not isinstance(sandbox_rule, dict)
        or sandbox_rule.get("action") != "SCMP_ACT_ALLOW"
        or sandbox_rule.get("names") != expected_syscalls
        or seccomp_ref.get("sandbox_syscalls") != expected_syscalls
        or sandbox_rule.get("args") != []
        or sandbox_rule.get("includes") != {}
        or sandbox_rule.get("excludes") != {}
    ):
        raise ValueError("browser seccomp sandbox syscall rule changed")

    canary_ref = security["runtime_canary"]
    canary_path = root / canary_ref["path"]
    if (
        canary_path.stat().st_size != canary_ref["bytes"]
        or sha256_file(canary_path) != canary_ref["sha256"]
        or canary_ref.get("expected_playwright_version")
        != browser["playwright_core"]["version"]
        or canary_ref.get("expected_browser_version")
        != browser["chromium_headless_shell"]["version"]
    ):
        raise ValueError("browser runtime canary reference changed")

    playwright = browser["playwright_core"]
    attestations = playwright["npm_attestations"]
    postcheck = attestations["slsa_allowlist_postcheck"]
    postcheck_impl = postcheck["implementation"]
    for path_key, size_key, digest_key in (
        ("path", "bytes", "sha256"),
        ("test_path", "test_bytes", "test_sha256"),
    ):
        relative = postcheck_impl[path_key]
        implementation_path = root / relative
        if (
            not relative.startswith("deploy/")
            or implementation_path.stat().st_size != postcheck_impl[size_key]
            or sha256_file(implementation_path) != postcheck_impl[digest_key]
        ):
            raise ValueError("Playwright provenance postcheck reference changed")
    expected_provenance = postcheck["expected"]
    runtime_qualification = postcheck["runtime_qualification"]
    runtime_result_path = root / runtime_qualification["result_path"]
    if (
        runtime_result_path.stat().st_size != runtime_qualification["result_bytes"]
        or sha256_file(runtime_result_path) != runtime_qualification["result_sha256"]
    ):
        raise ValueError("Playwright provenance runtime result reference changed")
    runtime_result = load_json(runtime_result_path)
    runtime_platforms = {
        item.get("container_platform"): item
        for item in runtime_result.get("platforms", [])
    }
    if (
        postcheck.get("required") is not True
        or postcheck.get("release_enforcement_implemented") is not True
        or postcheck_impl.get("policy_pass_exit_code_before_runtime_qualification") != 3
        or postcheck_impl.get("release_success_exit_code") != 0
        or expected_provenance.get("subject_name")
        != f"pkg:npm/playwright-core@{playwright['version']}"
        or expected_provenance.get("subject_sha512")
        != attestations["subject"]["sha512"]
        or expected_provenance.get("source_commit") != playwright["source_commit"]
        or expected_provenance.get("source_ref") != attestations["source_ref"]
        or runtime_qualification.get("node_version") != node["version"]
        or runtime_qualification.get("node_release_provenance_ref")
        != "node.official_release_provenance"
        or runtime_qualification.get("runtime_image")
        != "node@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e"
        or runtime_qualification.get("platforms_passed")
        != ["linux/amd64", "linux/arm64"]
        or runtime_qualification.get("network_during_verification") is not False
        or runtime_qualification.get("read_only_root") is not True
        or runtime_qualification.get("no_new_privileges") is not True
        or runtime_qualification.get("capabilities_dropped") != "ALL"
        or runtime_qualification.get("exact_signed_node_executable_match") is not True
        or runtime_qualification.get("qualified") is not True
        or runtime_result.get("network_used") is not False
        or set(runtime_platforms) != {"linux/amd64", "linux/arm64"}
        or any(
            runtime_platforms[f"linux/{architecture}"].get("runtime_policy_ready")
            is not True
            or runtime_platforms[f"linux/{architecture}"].get(
                "observed_postcheck_node_executable_sha256"
            )
            != node_platforms[("linux", architecture)]["executable_sha256"]
            for architecture in ("amd64", "arm64")
        )
    ):
        raise ValueError("Playwright provenance postcheck binding changed")

    roots = values["roots"]
    if roots["python"]["glibc_floor"] != "2.28":
        raise ValueError("service Python glibc floor must be 2.28")
    derived = roots["derived_build_inputs"]["speech-worker"]
    for key, filename in (
        ("builder_sha256", "build_downstream_faster_whisper.py"),
        ("verifier_sha256", "verify_downstream_faster_whisper.py"),
    ):
        actual = sha256_file(locks / filename)
        if derived[key] != actual:
            raise ValueError(f"speech {filename} hash mismatch: {actual}")
    verify_model(values["speech"])
    verify_speech_license_inputs(root, values["speech"])
    verify_python_wheels(root, values["python_wheels"], roots)

    age = values["age"]
    verify_age_build_input(age)
    age_license_ref = age["runtime_license_bundle"]
    age_verifier_ref = age["offline_runtime_verifier"]
    age_canary_ref = age["native_runtime_canary"]
    for reference, path_key, size_key, digest_key, reference_label in (
        (age_license_ref, "path", "bytes", "sha256", "license bundle"),
        (age_verifier_ref, "path", "bytes", "sha256", "runtime verifier"),
        (age_verifier_ref, "test_path", "test_bytes", "test_sha256", "runtime verifier test"),
        (age_canary_ref, "path", "bytes", "sha256", "native canary"),
        (age_canary_ref, "result_path", "result_bytes", "result_sha256", "native result"),
        (age_canary_ref, "evidence_path", "evidence_bytes", "evidence_sha256", "runtime evidence"),
    ):
        relative = reference[path_key]
        reference_path = root / relative
        if (
            not relative.startswith(("deploy/", "specs/001-autonomous-release/evidence/"))
            or reference_path.stat().st_size != reference[size_key]
            or sha256_file(reference_path) != reference[digest_key]
        ):
            raise ValueError(f"age {reference_label} reference changed")
    age_license_manifest = load_json(root / age_license_ref["path"])
    verify_age_license_bundle_structure(root, age, age_license_manifest)
    if (
        age_license_manifest.get("schema_version")
        != "deeptwin-static-go-license-bundle-v1"
        or age_license_manifest.get("tool") != "age"
        or age_license_manifest.get("version") != age["version"]
        or len(age_license_manifest.get("components", []))
        != age_license_ref.get("component_count")
        or len(age_license_manifest.get("license_files", []))
        != age_license_ref.get("unique_license_file_count")
        or age_license_ref.get("legal_approval") is not False
    ):
        raise ValueError("age runtime license bundle binding changed")
    age_license_paths: set[str] = set()
    for item in age_license_manifest["license_files"]:
        relative = item["path"]
        if relative in age_license_paths or not relative.startswith(
            "deploy/locks/licenses/age-1.3.2/"
        ):
            raise ValueError("age runtime license path changed")
        age_license_paths.add(relative)
        license_path = root / relative
        if (
            license_path.stat().st_size != item["bytes"]
            or sha256_file(license_path) != item["sha256"]
        ):
            raise ValueError("age runtime license bytes changed")
    age_native_result = load_json(root / age_canary_ref["result_path"])
    native_platforms = {
        item.get("platform")
        for item in age_native_result.get("native_canaries", [])
        if item.get("status") == "pass" and item.get("container_exit_code") == 0
    }
    if (
        age.get("runtime_profile", {}).get("negative_tests_completed") is not True
        or set(age_canary_ref.get("platforms_passed", []))
        != {"linux/amd64", "linux/arm64"}
        or native_platforms != {"linux/amd64", "linux/arm64"}
        or age_verifier_ref.get("status") != "pass"
        or age_verifier_ref.get("offline_test_count") != 7
        or age_canary_ref.get("production_bridge_implemented") is not False
    ):
        raise ValueError("age runtime qualification binding changed")

    codex_release_blockers = [
        *values["codex"].get("build_input_blockers", []),
        *values["codex"].get("downstream_release_blockers", []),
    ]
    if require_release_ready and codex_release_blockers:
        raise ValueError(
            "codex: unresolved release blockers: "
            f"{len(codex_release_blockers)}"
        )
    for manifest_name in ("upstream", "browser", "age"):
        blockers = values[manifest_name].get("release_blockers", [])
        if require_release_ready and blockers:
            raise ValueError(f"{manifest_name}: unresolved release blockers: {len(blockers)}")
    if require_release_ready and values["python_wheels"].get("legal_gate", {}).get(
        "artifacts_without_embedded_license_resources"
    ):
        raise ValueError("python-wheels: unresolved embedded-license-resource follow-up")
    if require_release_ready and values["browser_debian"].get("required_release_gates"):
        raise ValueError("browser-debian: unresolved native or legal release gates")

    aggregate_path = manifests / "build-input-lock.json"
    if verify_aggregate_lock and aggregate_path.exists():
        verifier_path = locks / "verify_build_input_lock.py"
        spec = importlib.util.spec_from_file_location(
            "deeptwin_aggregate_build_input_verifier", verifier_path
        )
        if spec is None or spec.loader is None:
            raise ValueError("aggregate build-input verifier could not be loaded")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.verify_aggregate(root, require_locked=False)
    elif verify_aggregate_lock and require_release_ready:
        raise ValueError("aggregate build-input-lock.json is missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root",
    )
    parser.add_argument("--require-release-ready", action="store_true")
    args = parser.parse_args()
    verify_repository(args.root.resolve(), args.require_release_ready)
    print("build-input manifests: structural verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
