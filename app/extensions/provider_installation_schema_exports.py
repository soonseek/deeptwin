"""Structural exports for the finite installation command and verified record."""
from app.deployment.provider_source_schema_exports import (
    _object,_constant,_hash,_uuid,_reference,_integer,_array,_string,
)
from app.domain.deployment_receipt import _blob,_entity
from .provider_installation_contracts import ROLES


def _ref(version):
    value = _entity('extension_installation')
    value['properties']['version'] = _constant(version)
    return value


def installation_input_schema():
    return _object(schema_version=_constant('provider-installation-command-v1'),command_id=_uuid(),
        staged_installation_ref=_ref(1),objects=_array(_object(role={'enum':list(ROLES)},
            sha256=_hash(),size_bytes=_integer(1,8388608)),12,128))


def installation_content_schema():
    return _object(schema_version=_constant('provider-installation-verified-v1'),state=_constant('verified'),
        revision=_constant(2),stage_ref=_ref(1),previous_record_digest=_hash(),
        extension_id=_string(128,r'[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?'),
        extension_version=_string(32,r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'),
        platform={'enum':['linux/amd64','linux/arm64']},image_index_sha256=_hash(),
        selected_manifest_sha256=_hash(),service_descriptor_sha256=_hash(),command_id=_uuid(),
        verified_at_ms=_integer(0,253402300799999),release_context_blob_ref=_blob(8192),
        release_trust_blob_ref=_blob(16384),release_source_context_sha256=_hash(),
        release_review_sha256=_hash(),evidence_policy_sha256=_hash(),
        evidence=_array(_object(role={'enum':list(ROLES)},blob_ref=_blob(8388608)),12,128))


def installation_reply_schema():
    return _object(schema_version=_constant('provider-installation-reply-v1'),command_id=_uuid(),
        staged_installation_ref=_ref(1),verified_installation_ref=_ref(2),state=_constant('verified'),
        revision=_constant(2),release_review_sha256=_hash(),release_source_context_sha256=_hash(),
        verified_at_ms=_integer(0,253402300799999),event_cursor=_string(1024),
        links=_object(self=_string(128),events=_constant('/api/v1/events')))


def review_envelope_schema():
    def s(): return _reference(2**63-1)
    def refs(): return _array(s(),1,128)
    def u(): return _string(128,r'[\x20-\x7e]+')
    def text(): return _string(4096,r'[^\x00]+')
    def decision(): return _object(rationale=text(),evidence=refs())
    subject = _object(extension_id=_string(128,r'[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?'),
        extension_version=_string(32,r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'),
        platform={'enum':['linux/amd64','linux/arm64']},image_index=s(),selected_manifest=s(),config=s(),
        layers=_array(s(),1,128),build_identity_sha256=_hash(),source_closure=s(),dependency_closure=s(),filesystem_inspection=s())
    finding = _object(scan={'enum':['image','component']},match_index=_integer(0,8191),
        vulnerability_id=u(),artifact_id=u(),severity={'enum':['Negligible','Low','Medium']})
    payload = _object(schema_version=_constant('provider-release-review-v1'),
        review_profile_id=_constant('provider-artifact-review-v1'),evidence_policy_sha256=_hash(),
        issued_at_ms=_integer(0,2**63-1),reviewer=_object(id=u(),name=text(),authority_basis=refs()),subject=subject,
        objects=_array(_object(role={'enum':list(ROLES[1:])},sha256=_hash(),size_bytes=_integer(1,8388608)),1,127),
        provenance=s(),component_map=s(),cohort=s(),image_invocation=s(),component_invocation=s(),
        scope=_constant('local-artifact-use-only'),origin_review=decision(),license_review=decision(),
        finding_review=_object(image_scan=s(),component_scan=s(),rationale=text(),accepted=_array(finding,0,8192)))
    return _object(schema_version=_constant('provider-release-review-envelope-v1'),key_id=_uuid(),
        algorithm=_constant('ed25519'),payload=payload,signature=_string(86,r'[A-Za-z0-9_-]{86}'))


def record_body_condition():
    from app.domain.schema_exports import _timestamp
    return _object(schema_version=_constant('domain-v1'),kind=_constant('extension_installation'),id=_uuid(),
        version=_constant(2),created_at_utc=_timestamp(),actor_ref=_entity('actor'),
        parent_refs={'type':'array','minItems':1,'maxItems':1,'prefixItems':[_ref(1)],'items':False},
        purpose=_constant('operational'),access_policy_ref=_entity('access_policy'),
        retention_policy_ref=_entity('retention_policy'),content=installation_content_schema())


def record_schema():
    return _object(ref=_ref(2),body=record_body_condition())


def exported_schemas():
    from copy import deepcopy
    return {name+'.schema.json':{'$schema':'https://json-schema.org/draft/2020-12/schema',
        '$id':'urn:deeptwin:schemas:v2:extensions:'+name,**deepcopy(schema)} for name,schema in (
            ('provider-installation-input-v1',installation_input_schema()),
            ('provider-installation-reply-v1',installation_reply_schema()),
            ('provider-installation-record-v2',record_schema()),
            ('provider-release-review-v1',review_envelope_schema()))}
