"""Closed public release-source schemas; authority still requires actual byte joins."""
from .provider_source_schema_exports import (
    _object, _constant, _hash, _identity, _uuid, _profile_id,
    _reference, _integer, _array, _string, _document,
)


def release_trust_schema():
    timestamp = _integer(0, 253402300799999)
    key = _object(key_id=_uuid(), algorithm=_constant('ed25519'),
        public_key=_string(43, r'[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]'),
        role=_constant('provider_artifact_review'), review_profile_id=_constant('provider-artifact-review-v1'),
        issuance_not_before_ms=timestamp, issuance_not_after_ms=timestamp)
    allow = _object(extension_id=_string(128, r'[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?'),
        extension_version=_string(32, r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'),
        platform={'enum':['linux/amd64','linux/arm64']}, image_index_sha256=_hash(),
        selected_manifest_sha256=_hash(), release_review=_reference(262144), key_id=_uuid())
    return _document('installation-release-trust-v1',
        schema_version=_constant('installation-release-trust-v1'), instance_id=_identity(),
        origin_profile_digest=_hash(), deployment_profile_id=_profile_id(),
        policy_generation=_integer(1,2147483647), valid_from_ms=timestamp, valid_until_ms=timestamp,
        keys=_array(key,0,4), allowed_releases=_array(allow,0,1),
        revoked_key_ids=_array(_uuid(),0,16), revoked_review_sha256=_array(_hash(),0,16),
        revoked_manifest_sha256=_array(_hash(),0,16))


def release_context_schema():
    return _document('installation-release-context-v1',
        schema_version=_constant('installation-release-context-v1'),
        recipe_id=_constant('installation-release-source-recipe-v1'),
        layout_id=_constant('installation-release-source-layout-v1'),
        instance_id=_identity(), origin_profile_digest=_hash(), deployment_profile_id=_profile_id(),
        topology_id=_uuid(), topology_revision=_constant(1), platform={'enum':['linux/amd64','linux/arm64']},
        provider_source_context=_reference(16384), provider_geometry=_reference(65536),
        release_trust=_reference(16384), review_profile_id=_constant('provider-artifact-review-v1'),
        evidence_policy_sha256=_hash())


def release_expansion_schema():
    return _document('installation-release-expansion-v1',
        schema_version=_constant('installation-release-expansion-v1'),
        recipe_id=_constant('installation-release-source-recipe-v1'),
        original_expansion=_reference(1048576), release_context=_reference(8192),
        release_trust=_reference(16384), expanded_compose=_reference(1048576))
