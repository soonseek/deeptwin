"""Pure additive release-source expansion, preserving the provider bundle verbatim."""
import json
from copy import deepcopy
from dataclasses import dataclass

from app.domain.refs import canonical_json
from app.operations.setup import OriginProfile
from . import contracts as c
from . import installation_release_contracts as r
from .provider_source_contracts import _image
from .provider_source_render import render_provider_sources, _insert, _mount, _overlap


@dataclass(frozen=True, slots=True)
class InstallationReleaseArtifacts:
    provider_artifacts: object
    bundle_files: tuple[tuple[str, bytes], ...]
    context_sha256: str
    expanded_compose_bytes: bytes
    expansion_record_bytes: bytes


def render_installation_release_sources(*, base_compose_bytes, base_service_ids_bytes,
        original_prepare_recipe_bytes, original_prepare_instance_bytes,
        original_receipt_recipe_bytes, original_receipt_instance_bytes, original_trust_bytes,
        provider_recipe_bytes, provider_instance_bytes, provider_trust_bytes,
        release_trust_bytes: bytes, initializer_image: str) -> InstallationReleaseArtifacts:
    try:
        _image(initializer_image)
        provider = render_provider_sources(base_compose_bytes=base_compose_bytes,
            base_service_ids_bytes=base_service_ids_bytes,
            original_prepare_recipe_bytes=original_prepare_recipe_bytes,
            original_prepare_instance_bytes=original_prepare_instance_bytes,
            original_receipt_recipe_bytes=original_receipt_recipe_bytes,
            original_receipt_instance_bytes=original_receipt_instance_bytes,
            original_trust_bytes=original_trust_bytes, provider_recipe_bytes=provider_recipe_bytes,
            provider_instance_bytes=provider_instance_bytes, provider_trust_bytes=provider_trust_bytes)
        profile = OriginProfile.from_dict(c.parse_instance(original_prepare_instance_bytes)['origin_profile'])
        context = r._context_bytes(provider.bundle_files, release_trust_bytes, profile)
        bundle = (('release-trust.json', release_trust_bytes), ('installation-release-context.json', context))
        r.validate_release_sources(bundle, provider_files=provider.bundle_files, profile=profile)
        before = c.parse(provider.expanded_compose_bytes, cap=1048576, depth=32, items=10000, canonical=False)
        expanded = deepcopy(before)
        services, volumes, configs = (expanded[key] for key in ('services','volumes','configs'))
        for service in services.values():
            for mount in (*service.get('volumes',()), *service.get('configs',())):
                r._require(not any(_overlap(mount['target'], str(path)) for path in (r.ROOT,r.INPUT_ROOT)))
        volume = 'installation-release-sources'
        actual = f'dt-{profile.instance_id}-{volume}'
        r._require(not any(value.get('name') == actual for value in volumes.values()))
        _insert(volumes, volume, {'name':actual})
        control = services['control']
        control['volumes'].append(_mount(volume,str(r.ROOT),True))
        _insert(control['environment'], r.STARTUP_KEY, c.digest(context))
        condition = {'condition':'service_completed_successfully'}
        _insert(control['depends_on'],'installation-release-root-init',dict(condition))
        mounts = []
        names = []
        for suffix, filename in (('trust','release-trust.json'), ('context','installation-release-context.json')):
            name = f'dt-{profile.instance_id}-installation-release-{suffix}'
            r._require(not any(value.get('name') == name for value in configs.values()))
            _insert(configs,name,{'external':True,'name':name})
            names.append(name)
            mounts.append({'source':name,'target':str(r.INPUT_ROOT / filename),'uid':'0','gid':'0','mode':0o440})
        _insert(services,'installation-release-root-init',{
            'image':initializer_image,'entrypoint':['python','-m','app.operations.installation_release_init'],
            'command':[],'user':'0:0','group_add':['21201'],'restart':'no','init':True,
            'privileged':False,'read_only':True,'network_mode':'none','cap_drop':['ALL'],
            'cap_add':['CHOWN','FOWNER','FSETID'],'security_opt':['no-new-privileges:true'],
            'tty':False,'stdin_open':False,'pids_limit':32,'mem_limit':'64m','cpus':0.25,
            'ulimits':{'nofile':{'soft':256,'hard':256}},
            'volumes':[_mount(volume,str(r.ROOT),False),
                       _mount('provider-stage-sources','/run/deeptwin/provider-stage-sources',True)],
            'configs':mounts,'depends_on':{'provider-source-root-init':dict(condition)}})
        stripped = deepcopy(expanded)
        del stripped['services']['installation-release-root-init']
        stripped['services']['control']['volumes'].pop()
        del stripped['services']['control']['environment'][r.STARTUP_KEY]
        del stripped['services']['control']['depends_on']['installation-release-root-init']
        del stripped['volumes'][volume]
        for name in names: del stripped['configs'][name]
        r._require(stripped == before)
        raw = json.dumps(expanded,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
        c.parse(raw,cap=1048576,depth=32,items=10000,canonical=False)
        record = canonical_json({'schema_version':'installation-release-expansion-v1',
            'recipe_id':'installation-release-source-recipe-v1',
            'original_expansion':r._reference(provider.expansion_record_bytes),
            'release_context':r._reference(context),'release_trust':r._reference(release_trust_bytes),
            'expanded_compose':r._reference(raw)})
        return InstallationReleaseArtifacts(provider,bundle,c.digest(context),raw,record)
    except c.DeploymentSourceError:
        raise
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,RecursionError):
        raise c.DeploymentSourceError() from None
