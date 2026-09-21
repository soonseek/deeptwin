import importlib
import json
import pytest
from app.tests.installation_release_fixture import source_inputs, descriptor
from app.deployment.provider_source_render import render_provider_sources


def test_outer_renderer_preserves_all_eighteen_old_bytes_and_policy_join():
    try:
        module = importlib.import_module('app.deployment.installation_release_render')
    except ModuleNotFoundError:
        pytest.fail('Actual installation release renderer is missing')
    kwargs, bundle, _ = source_inputs()
    result = module.render_installation_release_sources(**kwargs)
    assert result.provider_artifacts.bundle_files == bundle
    files = dict(result.bundle_files)
    assert tuple(files) == ('release-trust.json','installation-release-context.json')
    context = json.loads(files['installation-release-context.json'])
    assert context['provider_source_context'] == descriptor(dict(bundle)['source-context.json'])
    assert context['provider_geometry'] == descriptor(dict(bundle)['geometry.json'])
    assert context['release_trust'] == descriptor(kwargs['release_trust_bytes'])


def test_full_compose_projection_preserves_independent_provider_renderer():
    from app.deployment.installation_release_render import render_installation_release_sources
    kwargs,_,_ = source_inputs()
    baseline = render_provider_sources(**{key:value for key,value in kwargs.items()
        if key not in ('release_trust_bytes','initializer_image')})
    result = render_installation_release_sources(**kwargs)
    before,after = json.loads(baseline.expanded_compose_bytes),json.loads(result.expanded_compose_bytes)
    initializer = after['services'].pop('installation-release-root-init')
    assert initializer['network_mode'] == 'none' and initializer['read_only'] is True
    control = after['services']['control']
    added = [mount for mount in control['volumes'] if mount['target'] == '/run/deeptwin/installation-release-sources']
    assert len(added) == 1 and added[0]['read_only'] is True
    control['volumes'].remove(added[0])
    assert control['environment'].pop('DEEPTWIN_INSTALLATION_RELEASE_CONTEXT_SHA256') == result.context_sha256
    assert control['depends_on'].pop('installation-release-root-init') == {'condition':'service_completed_successfully'}
    volume = after['volumes'].pop('installation-release-sources')
    assert volume['name'].endswith('-installation-release-sources')
    assert len(initializer['configs']) == 2
    for config in initializer['configs']:
        removed = after['configs'].pop(config['source'])
        assert removed == {'name':config['source'],'external':True}
    assert after == before
    assert result.provider_artifacts.bundle_files == baseline.bundle_files
    assert result.provider_artifacts.expansion_record_bytes == baseline.expansion_record_bytes
