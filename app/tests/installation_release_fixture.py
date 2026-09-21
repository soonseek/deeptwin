"""Independent synthetic public source inputs; no installation service imports."""

import json
from base64 import urlsafe_b64encode
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.refs import canonical_json
from app.tests.provider_source_fixture import case as provider_case
from app.tests.provider_source_reader_fixture import ReaderTree

ROOT = Path('/run/deeptwin/installation-release-sources')
KEY = '99999999-9999-4999-8999-999999999999'
IMAGE = 'registry.example.invalid/synthetic/release-init@sha256:' + 'b' * 64


def descriptor(raw):
    return {'sha256': sha256(raw).hexdigest(), 'size_bytes': len(raw)}


def trust_document(bundle, variant='valid'):
    profile = json.loads(bundle[1][1])['origin_profile']
    value = {
        'schema_version': 'installation-release-trust-v1',
        'instance_id': profile['instance_id'], 'origin_profile_digest': profile['digest'],
        'deployment_profile_id': profile['deployment_profile_id'], 'policy_generation': 1,
        'valid_from_ms': 0, 'valid_until_ms': 253402300799999,
        'keys': [{'key_id': KEY, 'algorithm': 'ed25519',
                  'public_key': urlsafe_b64encode(b'T' * 32).rstrip(b'=').decode(),
                  'role': 'provider_artifact_review', 'review_profile_id': 'provider-artifact-review-v1',
                  'issuance_not_before_ms': 0, 'issuance_not_after_ms': 253402300799999}],
        'allowed_releases': [{'extension_id': 'synthetic-provider', 'extension_version': '1.0.0',
            'platform': json.loads(bundle[9][1])['platform'], 'image_index_sha256': '1' * 64,
            'selected_manifest_sha256': '2' * 64,
            'release_review': descriptor(b'SYNTHETIC TEST ONLY review bytes'), 'key_id': KEY}],
        'revoked_key_ids': [], 'revoked_review_sha256': [], 'revoked_manifest_sha256': [],
    }
    if variant in ('deny_empty', 'P1', 'P9'):
        value['allowed_releases'] = []
    if variant == 'P2': value['revoked_key_ids'] = [KEY]
    if variant == 'P3': value['revoked_review_sha256'] = [value['allowed_releases'][0]['release_review']['sha256']]
    if variant == 'P4': value['revoked_manifest_sha256'] = ['2' * 64]
    if variant == 'P5': value['keys'] = []
    if variant == 'P6': value['valid_until_ms'] = 1
    if variant == 'P7': value['valid_from_ms'] = 253402300799998
    if variant in ('P8', 'P10'):
        value['keys'][0]['issuance_not_after_ms'] = 100000
    return value


@pytest.fixture
def release_source_case(request, tmp_path, monkeypatch):
    from types import MappingProxyType
    from app.deployment.installation_release_contracts import _context_bytes
    from app.deployment.installation_release_sources import open_installation_release_sources
    from app.deployment.contracts import DeploymentSourceError
    variant = getattr(request, 'param', 'valid')
    assert variant in ('valid','deny_empty','foreign_policy',*[f'P{i}' for i in range(1,11)])
    tree = ReaderTree(tmp_path, monkeypatch)
    trust = canonical_json(trust_document(tree.bundle, variant))
    context = json.loads(_context_bytes(tree.bundle,canonical_json(trust_document(tree.bundle)),tree.profile))
    context['release_trust'] = descriptor(trust)
    if variant == 'foreign_policy': context['evidence_policy_sha256'] = 'f'*64
    context = canonical_json(context)
    tree.directory(ROOT,0,21201); tree.directory(ROOT/'documents',0,21201); tree.mount(ROOT,True)
    for name,raw in (('release-trust.json',trust),('installation-release-context.json',context)):
        tree.write(ROOT/'documents'/name,raw,0,21201)
    provider = tree.open()
    source = None
    pin = sha256(context).hexdigest()
    try:
        try:
            source = open_installation_release_sources(profile=tree.profile,context_sha256=pin,
                provider_source_context=provider,protected_roots=())
        except DeploymentSourceError:
            if variant not in ('P5','foreign_policy'): raise
        yield SimpleNamespace(files=MappingProxyType({'release_trust':trust,'release_context':context}),
            tree=tree,source_root=ROOT,source_pin=pin,variant=variant,source=source)
    finally:
        if source is not None: source.close()
        provider.close()
        assert not tree.live


def source_inputs(**options):
    kwargs, bundle, old = provider_case(**options)
    return {**kwargs, 'release_trust_bytes': canonical_json(trust_document(bundle)),
            'initializer_image': IMAGE}, bundle, old
