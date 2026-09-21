"""Source syntax does not grant release admission."""
import importlib
import json
from hashlib import sha256

import pytest

from app.domain.refs import canonical_json
from app.deployment.contracts import DeploymentSourceError
from app.tests.installation_release_fixture import release_source_case, source_inputs


def contracts():
    try:
        return importlib.import_module('app.deployment.installation_release_contracts')
    except ModuleNotFoundError as error:
        assert error.name == 'app.deployment.installation_release_contracts'
        pytest.fail('Actual installation release source codecs are missing')


@pytest.mark.parametrize('release_source_case', ['valid','deny_empty','foreign_policy', *['P'+str(i) for i in range(1,11)]], indirect=True)
def test_PA_source_policy_syntax_without_admission(release_source_case):
    c = contracts()
    raw = release_source_case.files['release_trust']
    context = release_source_case.files['release_context']
    assert release_source_case.source_pin == sha256(context).hexdigest()
    if release_source_case.variant in ('P5','foreign_policy'):
        assert release_source_case.source is None
    else:
        assert release_source_case.source.read_current() == (('release-trust.json',raw),('installation-release-context.json',context))
    if release_source_case.variant == 'P5':
        with pytest.raises(DeploymentSourceError): c.parse_release_trust(raw)
    else:
        parsed = c.parse_release_trust(raw)
        assert parsed.content_bytes == raw
        assert parsed.as_dict() == json.loads(raw)
        detached = parsed.as_dict()
        detached['keys'].clear()
        assert parsed.as_dict() == json.loads(raw)


@pytest.mark.parametrize('change', ['extra','bool','duplicate_key','reversed_interval','bad_key','duplicate_public'])
def test_source_rejects_malformed_authority_declarations(change):
    c = contracts()
    kwargs, _, _ = source_inputs()
    value = json.loads(kwargs['release_trust_bytes'])
    if change == 'extra': value['approved'] = True
    if change == 'bool': value['policy_generation'] = True
    if change == 'duplicate_key': value['keys'] *= 2
    if change == 'reversed_interval': value['valid_until_ms'] = value['valid_from_ms']
    if change == 'bad_key': value['keys'][0]['public_key'] += '='
    if change == 'duplicate_public':
        value['keys'].append({**value['keys'][0], 'key_id':'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'})
    with pytest.raises(DeploymentSourceError): c.parse_release_trust(canonical_json(value))


def test_policy_bytes_are_canonical_detached_and_shared_digest():
    c = contracts()
    raw = c.installation_evidence_policy_bytes()
    value = json.loads(raw)
    expected = {
        'schema_version':'provider-installation-evidence-policy-v1','policy_revision':2,
        'review_profile_id':'provider-artifact-review-v1','interpretation_id':'provider-release-adapter-preflight-r2-dpkg-status-v1',
        'review':{'envelope':'provider-release-review-envelope-v1','payload':'provider-release-review-v1',
            'algorithm':'ed25519','signature_prefix':'deeptwin:provider-release-review:v1\n',
            'scope':'local-artifact-use-only','trust':'independent-current-exact-allow-deny-wins-v1','role':'provider_artifact_review'},
        'codecs':{'canonical':'domain-canonical-v1','canonical_max_bytes':1048576,'canonical_max_depth':32,
            'canonical_max_recursive_items':10000,'canonical_max_string_bytes':65536,'raw':'provider-external-json-v1',
            'raw_max_depth':64,'raw_max_members_elements':262144,'raw_max_string_bytes':1048576,
            'raw_max_numeric_token_bytes':128,'raw_max_significant_digits':64,'raw_min_exponent':-308,
            'raw_max_exponent':308,'embedded_oci_max_bytes':262144},
        'carrier':{'codec':'provider-installation-binary-v1','max_raw_bytes':50331648,'max_header_bytes':32768,
            'max_objects':128,'receive_deadline_ms':60000,'max_scan_bytes':8388608,'max_image_sbom_bytes':8388608,
            'max_spdx_bytes':4194304,'max_review_bytes':262144,'max_provenance_bytes':262144,'max_map_bytes':1048576,
            'max_metadata_total_bytes':4194304,'max_license_total_bytes':8388608,'max_source_report_bytes':262144,
            'max_dependency_report_bytes':262144,'max_filesystem_report_bytes':1048576},
        'native':{'syft_version':'1.42.3','syft_schema_version':'16.1.3','syft_projection':'syft-five-cataloger-audit-v1',
            'catalogers':['binary-classifier-cataloger','dpkg-db-cataloger','file-digest-cataloger','file-metadata-cataloger','python-installed-package-cataloger'],
            'grype_version':'0.110.0','grype_projection':'grype-mapstructure-json-db-v1','db_schema_version':'6.1.4',
            'layer_coordinates':'config-diff-id-v1','warnings':'refuse','nonwhitespace_stderr':'refuse',
            'ignored_matches':'refuse','filter_overrides':'refuse','unknown_decision_fields':'refuse'},
        'coverage':{'component_map':'provider-component-map-v2','spdx':'spdx-2.3-closed-components-v1',
            'classes':['debian','python-wheel','cpython','rust-crate','first-party'],'python_distributions_per_platform':7,
            'first_party':'reviewed-not-cve-covered','non_python_binary':'refuse','license_grammar':'provider-spdx-license-subset-v1',
            'file_coverage':'exact-r1-regular-file-inverse-dpkg-status-root-v2',
            'debian_status':'retained-dpkg-control-installed-bijection-v1','allowed_severities':['Negligible','Low','Medium'],
            'finding_acceptance':'every-match-index-exact-v1','feed_coverage':'attributable-origin-review-not-inferred-v1'},
        'issuance':{'scan_max_age_ms':86400000,'db_max_age_ms':432000000,'clock_skew_ms':300000,
            'later_admission':'current-trust-allow-deny-not-daily-review-v1'},
        'provenance':{'statement':'https://in-toto.io/Statement/v1','predicate':'https://slsa.dev/provenance/v1',
            'build_type':'urn:deeptwin:build-type:provider-r1-offline-assembly:v1','projection':'r1-toolset-exact-dependencies-v1',
            'run_metadata':'signed-assertion-utc-seconds-ordered-v1','r1_report_mutation':'forbidden',
            'runtime_execution_proof':'not-derived-from-source-toolset'},
    }
    assert value == expected
    assert canonical_json(value) == raw
    assert value['interpretation_id'] == 'provider-release-adapter-preflight-r2-dpkg-status-v1'
    assert value['carrier']['max_raw_bytes'] == 50331648
    assert value['native']['layer_coordinates'] == 'config-diff-id-v1'
    assert value['provenance']['run_metadata'] == 'signed-assertion-utc-seconds-ordered-v1'
    value['native']['catalogers'].clear()
    assert c.installation_evidence_policy_bytes() == raw
    assert c.installation_evidence_policy_sha256() == sha256(raw).hexdigest()


def test_foreign_policy_cannot_be_source_context():
    from app.deployment.installation_release_render import render_installation_release_sources
    c = contracts()
    kwargs,provider,_ = source_inputs()
    result = render_installation_release_sources(**kwargs)
    value = json.loads(result.bundle_files[1][1])
    value['evidence_policy_sha256'] = 'f'*64
    with pytest.raises(DeploymentSourceError): c.parse_release_context(canonical_json(value))


def test_source_schema_exports_are_exact_closed_generated_artifacts():
    from pathlib import Path
    from app.deployment import installation_release_schema_exports as schemas
    root = Path(__file__).resolve().parents[2]
    for name, factory in (('trust',schemas.release_trust_schema),('context',schemas.release_context_schema),
                          ('expansion',schemas.release_expansion_schema)):
        path = root / 'schemas/v2/deployment' / ('installation-release-'+name+'-v1.schema.json')
        assert json.loads(path.read_bytes()) == factory()
        assert factory()['additionalProperties'] is False


def test_new_service_api_are_not_source_dependencies():
    # the import guard runs in a fresh interpreter: reloading the source modules in this
    # process would mint new class objects and break every later `type(x) is Class`
    # identity check across the suite (the provider installation service's constructor)
    import subprocess
    import sys
    from pathlib import Path

    probe = '''
import builtins, importlib
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if 'provider_installation' in name:
        raise AssertionError('source module imported installation service/API')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
for name in ('contracts', 'schema_exports', 'render', 'sources'):
    importlib.import_module('app.deployment.installation_release_' + name)
print('clean')
'''
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run([sys.executable, '-B', '-c', probe], cwd=root, capture_output=True,
                               text=True, timeout=120, env={'PYTHONPATH': str(root), 'PATH': ''}, check=False)
    assert completed.returncode == 0 and completed.stdout.strip() == 'clean', completed.stderr[-2000:]
    kwargs,_,_ = source_inputs()
    from app.deployment.installation_release_render import render_installation_release_sources
    assert render_installation_release_sources(**kwargs).bundle_files[0][1] == kwargs['release_trust_bytes']
