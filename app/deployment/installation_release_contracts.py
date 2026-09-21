"""Closed independent release-source declarations and fixed evidence interpretation."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator

from app.domain.refs import canonical_json, uuid_string
from app.domain.wire import WireLimits, parse_json_object
from app.operations.setup import OriginProfile, parse_base64url_32
from app.extensions.lineage_contracts import _valid_version
from app.extensions.contracts import _text, _IDENTIFIER

from . import contracts as c
from .provider_source_contracts import validate_provider_source_bundle, parse_provider_context

ROOT = Path('/run/deeptwin/installation-release-sources')
INPUT_ROOT = Path('/run/deeptwin/installation-release-init-input')
STARTUP_KEY = 'DEEPTWIN_INSTALLATION_RELEASE_CONTEXT_SHA256'
LAYOUT = (('release-trust.json', 16384), ('installation-release-context.json', 8192))
RECIPE = {'schema_version': 'installation-release-source-recipe-v1',
          'renderer_id': 'installation-release-render-v1',
          'initializer_id': 'installation-release-init-v1',
          'layout_id': 'installation-release-source-layout-v1',
          'file_count': 2, 'aggregate_bytes_max': 24576}


def installation_evidence_policy_bytes() -> bytes:
    return canonical_json({
        'schema_version': 'provider-installation-evidence-policy-v1', 'policy_revision': 2,
        'review_profile_id': 'provider-artifact-review-v1',
        'interpretation_id': 'provider-release-adapter-preflight-r2-dpkg-status-v1',
        'review': {'envelope': 'provider-release-review-envelope-v1',
            'payload': 'provider-release-review-v1', 'algorithm': 'ed25519',
            'signature_prefix': 'deeptwin:provider-release-review:v1\n',
            'scope': 'local-artifact-use-only', 'trust': 'independent-current-exact-allow-deny-wins-v1',
            'role': 'provider_artifact_review'},
        'codecs': {'canonical': 'domain-canonical-v1', 'canonical_max_bytes': 1048576,
            'canonical_max_depth': 32, 'canonical_max_recursive_items': 10000,
            'canonical_max_string_bytes': 65536, 'raw': 'provider-external-json-v1',
            'raw_max_depth': 64, 'raw_max_members_elements': 262144,
            'raw_max_string_bytes': 1048576, 'raw_max_numeric_token_bytes': 128,
            'raw_max_significant_digits': 64, 'raw_min_exponent': -308,
            'raw_max_exponent': 308, 'embedded_oci_max_bytes': 262144},
        'carrier': {'codec': 'provider-installation-binary-v1', 'max_raw_bytes': 50331648,
            'max_header_bytes': 32768, 'max_objects': 128, 'receive_deadline_ms': 60000,
            'max_scan_bytes': 8388608, 'max_image_sbom_bytes': 8388608,
            'max_spdx_bytes': 4194304, 'max_review_bytes': 262144,
            'max_provenance_bytes': 262144, 'max_map_bytes': 1048576,
            'max_metadata_total_bytes': 4194304, 'max_license_total_bytes': 8388608,
            'max_source_report_bytes': 262144, 'max_dependency_report_bytes': 262144,
            'max_filesystem_report_bytes': 1048576},
        'native': {'syft_version': '1.42.3', 'syft_schema_version': '16.1.3',
            'syft_projection': 'syft-five-cataloger-audit-v1',
            'catalogers': ['binary-classifier-cataloger', 'dpkg-db-cataloger',
                'file-digest-cataloger', 'file-metadata-cataloger', 'python-installed-package-cataloger'],
            'grype_version': '0.110.0', 'grype_projection': 'grype-mapstructure-json-db-v1',
            'db_schema_version': '6.1.4', 'layer_coordinates': 'config-diff-id-v1',
            'warnings': 'refuse', 'nonwhitespace_stderr': 'refuse', 'ignored_matches': 'refuse',
            'filter_overrides': 'refuse', 'unknown_decision_fields': 'refuse'},
        'coverage': {'component_map': 'provider-component-map-v2',
            'spdx': 'spdx-2.3-closed-components-v1',
            'classes': ['debian', 'python-wheel', 'cpython', 'rust-crate', 'first-party'],
            'python_distributions_per_platform': 7, 'first_party': 'reviewed-not-cve-covered',
            'non_python_binary': 'refuse', 'license_grammar': 'provider-spdx-license-subset-v1',
            'file_coverage': 'exact-r1-regular-file-inverse-dpkg-status-root-v2',
            'debian_status': 'retained-dpkg-control-installed-bijection-v1',
            'allowed_severities': ['Negligible', 'Low', 'Medium'],
            'finding_acceptance': 'every-match-index-exact-v1',
            'feed_coverage': 'attributable-origin-review-not-inferred-v1'},
        'issuance': {'scan_max_age_ms': 86400000, 'db_max_age_ms': 432000000,
            'clock_skew_ms': 300000, 'later_admission': 'current-trust-allow-deny-not-daily-review-v1'},
        'provenance': {'statement': 'https://in-toto.io/Statement/v1',
            'predicate': 'https://slsa.dev/provenance/v1',
            'build_type': 'urn:deeptwin:build-type:provider-r1-offline-assembly:v1',
            'projection': 'r1-toolset-exact-dependencies-v1',
            'run_metadata': 'signed-assertion-utc-seconds-ordered-v1',
            'r1_report_mutation': 'forbidden',
            'runtime_execution_proof': 'not-derived-from-source-toolset'},
    })


def installation_evidence_policy_sha256() -> str:
    return sha256(installation_evidence_policy_bytes()).hexdigest()


def _require(condition):
    if not condition:
        raise c.DeploymentSourceError()


@dataclass(frozen=True, slots=True, init=False)
class ReleaseTrust:
    content_bytes: bytes

    def __init__(self):
        raise TypeError('release trust requires parsed source bytes')

    def as_dict(self):
        from app.domain.refs import parse_canonical
        return parse_canonical(self.content_bytes)


@dataclass(frozen=True, slots=True, init=False)
class ReleaseContext(ReleaseTrust):
    pass


def _parse(raw, kind, cap, cls):
    from . import installation_release_schema_exports as s
    try:
        schema = getattr(s, 'release_' + kind + '_schema')()
        value = parse_json_object(raw, required=schema['required'], limits=WireLimits(
            max_bytes=cap, max_depth=8, max_items=4096, max_members=32,
            max_string_bytes=1024, max_integer=253402300799999))
        _require(canonical_json(value) == raw and Draft202012Validator(schema).is_valid(value))
        if kind == 'trust':
            _require(value['valid_from_ms'] < value['valid_until_ms'])
            keys = value['keys']
            ids = [item['key_id'] for item in keys]
            _require(ids == sorted(set(ids)))
            _require(len({item['public_key'] for item in keys}) == len(keys))
            for item in keys:
                uuid_string(item['key_id'])
                parse_base64url_32(item['public_key'])
                _require(item['issuance_not_before_ms'] < item['issuance_not_after_ms'])
            for field in ('revoked_key_ids','revoked_review_sha256','revoked_manifest_sha256'):
                _require(value[field] == sorted(set(value[field])))
            for identifier in value['revoked_key_ids']: uuid_string(identifier)
            for item in value['allowed_releases']:
                _require(item['key_id'] in ids)
                _text(item['extension_id'], 'extension_id', 128, pattern=_IDENTIFIER)
                _require(_valid_version(item['extension_version']))
        else:
            uuid_string(value['topology_id'])
            _require(value['evidence_policy_sha256'] == installation_evidence_policy_sha256())
        result = object.__new__(cls)
        object.__setattr__(result, 'content_bytes', raw)
        return result
    except c.DeploymentSourceError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        raise c.DeploymentSourceError() from None


def parse_release_trust(raw: bytes) -> ReleaseTrust:
    return _parse(raw, 'trust', 16384, ReleaseTrust)


def parse_release_context(raw: bytes) -> ReleaseContext:
    return _parse(raw, 'context', 8192, ReleaseContext)


def _reference(raw):
    return {'sha256': sha256(raw).hexdigest(), 'size_bytes': len(raw)}


def _context_bytes(provider_files, trust_bytes, profile):
    validate_provider_source_bundle(provider_files)
    docs = dict(provider_files)
    old = parse_provider_context(docs['source-context.json'])
    geometry = c.parse(docs['geometry.json'], cap=65536, depth=12, items=4096)
    trust = parse_release_trust(trust_bytes).as_dict()
    _require(type(profile) is OriginProfile)
    for obj in (trust, old):
        _require(obj['instance_id'] == profile.instance_id and obj['origin_profile_digest'] == profile.digest)
    _require(trust['deployment_profile_id'] == profile.deployment_profile_id)
    _require(geometry['origin_profile'] == profile.as_dict())
    for allow in trust['allowed_releases']:
        _require(allow['platform'] == geometry['platform'])
    raw = canonical_json({'schema_version': 'installation-release-context-v1',
        'recipe_id': 'installation-release-source-recipe-v1',
        'layout_id': 'installation-release-source-layout-v1',
        'instance_id': profile.instance_id, 'origin_profile_digest': profile.digest,
        'deployment_profile_id': profile.deployment_profile_id, 'topology_id': old['topology_id'],
        'topology_revision': 1, 'platform': geometry['platform'],
        'provider_source_context': _reference(docs['source-context.json']),
        'provider_geometry': _reference(docs['geometry.json']), 'release_trust': _reference(trust_bytes),
        'review_profile_id': 'provider-artifact-review-v1',
        'evidence_policy_sha256': installation_evidence_policy_sha256()})
    parse_release_context(raw)
    return raw


def validate_release_sources(files, *, provider_files, profile):
    _require(type(files) is tuple and len(files) == 2)
    _require(all(type(pair) is tuple and len(pair) == 2 for pair in files))
    _require(tuple(name for name, _ in files) == tuple(name for name, _ in LAYOUT))
    _require(all(type(raw) is bytes and 1 <= len(raw) <= cap
        for (_, raw), (_, cap) in zip(files, LAYOUT, strict=True)))
    _require(sum(len(raw) for _, raw in files) <= 24576)
    _require(files[1][1] == _context_bytes(provider_files, files[0][1], profile))
