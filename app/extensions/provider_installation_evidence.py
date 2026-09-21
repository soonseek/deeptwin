"""Bounded raw evidence parsing and fixed offline release interpretation."""
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal

from .provider_installation_contracts import InstallationError,require,CAPS


class _RawParser:
    """Check each token/container budget before adding it to the parsed observation."""
    def __init__(self,raw):
        require(type(raw) is bytes)
        self.text = raw.decode('utf-8','strict')
        self.index,self.members = 0,0

    def whitespace(self):
        while self.index < len(self.text) and self.text[self.index] in ' \r\n\t': self.index += 1

    def member(self):
        self.members += 1
        require(self.members <= 262144,'too_large')

    def string(self):
        require(self.text[self.index] == '"')
        cursor,size = self.index+1,0
        while True:
            require(cursor < len(self.text))
            char = self.text[cursor]
            if char == '"': break
            point = ord(char)
            require(point >= 32)
            cursor += 1
            if char == '\\':
                require(cursor < len(self.text))
                escaped = self.text[cursor]
                cursor += 1
                require(escaped in '"\\/bfnrtu')
                if escaped == 'u':
                    token = self.text[cursor:cursor+4]
                    require(re.fullmatch('[0-9a-fA-F]{4}',token) is not None)
                    point = int(token,16)
                    cursor += 4
                    if 0xd800 <= point <= 0xdbff:
                        require(self.text[cursor:cursor+2] == '\\u')
                        token = self.text[cursor+2:cursor+6]
                        require(re.fullmatch('[0-9a-fA-F]{4}',token) is not None)
                        low = int(token,16)
                        require(0xdc00 <= low <= 0xdfff)
                        point = 0x10000 + ((point-0xd800)<<10) + low-0xdc00
                        cursor += 6
                    else: require(not 0xdc00 <= point <= 0xdfff)
                else: point = 0x20  # every non-unicode escape decodes to one ASCII byte
            size += 1 if point < 0x80 else 2 if point < 0x800 else 3 if point < 0x10000 else 4
            require(size <= 1048576,'too_large')
        value,end = json.decoder.scanstring(self.text,self.index+1,True)
        require(end == cursor+1)
        self.index = end
        return value

    def value(self,depth=0):
        require(depth <= 64,'too_large')
        self.whitespace()
        require(self.index < len(self.text))
        char = self.text[self.index]
        if char == '"': return self.string()
        if char in '[{':
            self.index += 1
            closing = '}' if char == '{' else ']'
            result = {} if char == '{' else []
            self.whitespace()
            if self.index < len(self.text) and self.text[self.index] == closing:
                self.index += 1
                return result
            while True:
                self.member()
                self.whitespace()
                require(self.index < len(self.text))
                if char == '{':
                    key = self.string()
                    require(key not in result)
                    self.whitespace()
                    require(self.index < len(self.text) and self.text[self.index] == ':')
                    self.index += 1
                    result[key] = self.value(depth+1)
                else: result.append(self.value(depth+1))
                self.whitespace()
                require(self.index < len(self.text))
                token = self.text[self.index]
                self.index += 1
                if token == closing: return result
                require(token == ',')
        for token,value in (('true',True),('false',False),('null',None)):
            if self.text.startswith(token,self.index):
                self.index += len(token)
                return value
        match = re.match(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?',self.text[self.index:self.index+129])
        require(match is not None)
        token = match.group()
        require(len(token) <= 128,'too_large')
        mantissa,*exponent = re.split('[eE]',token)
        digits = mantissa.replace('-','').replace('.','').lstrip('0')
        require(len(digits) <= 64,'too_large')
        require(not exponent or -308 <= int(exponent[0]) <= 308)
        self.index += len(token)
        return Decimal(token) if '.' in token or exponent else int(token)

    def parse(self):
        value = self.value()
        self.whitespace()
        require(self.index == len(self.text))
        return value


@dataclass(frozen=True,slots=True,init=False)
class ExternalDocument:
    content_bytes: bytes
    _observation: object

    def __new__(cls,*args,**kwargs): raise TypeError('external document requires bounded parsing')

    def as_dict(self): return deepcopy(self._observation)


def parse_external_document(role,raw):
    try:
        require(role in ('image_sbom','component_license_review','image_scan','component_scan','provenance'))
        require(type(raw) is bytes and 0 < len(raw) <= CAPS[role],'too_large')
        value = _RawParser(raw).parse()
        require(type(value) is dict)
        result = object.__new__(ExternalDocument)
        object.__setattr__(result,'content_bytes',raw)
        object.__setattr__(result,'_observation',value)
        return result
    except InstallationError: raise
    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError,IndexError):
        raise InstallationError() from None


def _native_object(required,optional=None):
    return {'type':'object','properties':{**required,**(optional or {})},
        'required':list(required),'additionalProperties':False}


def _syft_schema():
    """Syft 1.42.3 schema 16.1.3 selected definitions, with project closed objects.

    Source: anchore/syft v1.42.3 schema/json/schema-latest.json. Descriptive
    strings are omitted; required fields/types and the selected reference
    closure are preserved. Source/configuration semantic checks are separate.
    """
    s,b,i = {'type':'string'},{'type':'boolean'},{'type':'integer'}
    def arr(item): return {'type':'array','items':item}
    def strings(names): return {name:s for name in names.split()}
    def obj(required,optional=None): return _native_object(required,optional)
    digest = obj(strings('algorithm value'))
    location = obj(strings('path accessPath'),{'layerID':s,'annotations':{'type':'object','additionalProperties':s}})
    coordinates = obj({'path':s},{'layerID':s})
    license_ = obj({**strings('value spdxExpression type'),'urls':arr(s),'locations':arr(location)},{'contents':s})
    file_license = obj(strings('value spdxExpression type'),{'evidence':obj({name:i for name in ('confidence','offset','extent')})})
    security = obj({'symbolTableStripped':b,'nx':b,'relRO':s,'pie':b,'dso':b},
        {name:b for name in ('stackCanary','safeStack','cfi','fortify')})
    executable = obj({'format':s,'hasExports':b,'hasEntrypoint':b,'importedLibraries':arr(s)},
        {'elfSecurityFeatures':security})
    metadata = obj({'mode':i,'type':s,'userID':i,'groupID':i,'mimeType':s,'size':i},{'linkDestination':s})
    file_ = obj({'id':s,'location':coordinates},{'metadata':metadata,'contents':s,'digests':arr(digest),
        'licenses':arr(file_license),'executable':executable,'unknowns':arr(s)})
    dpkg = obj({**strings('package source version sourceVersion architecture maintainer'),'installedSize':i,
        'files':arr(obj({'path':s,'isConfigFile':b},{'digest':digest}))},
        {name:arr(s) for name in ('provides','depends','preDepends')})
    python = obj(strings('name version author authorEmail platform sitePackagesRootPath'),{
        'files':arr(obj({'path':s},{'digest':digest,'size':s})),'topLevelPackages':arr(s),
        'directUrlOrigin':obj({'url':s},strings('commitId vcs')),'requiresPython':s,
        'requiresDist':arr(s),'providesExtra':arr(s)})
    binary = obj({'matches':arr(obj({'classifier':s,'location':location}))})
    package = obj({**strings('id name version type foundBy language purl'),
        'locations':arr(location),'licenses':arr(license_),'cpes':arr(obj({'cpe':s},{'source':s})),
        'metadataType':{'enum':['dpkg-db-entry','python-package','binary-signature']},'metadata':{} })
    package['allOf'] = [{'if':{'properties':{'metadataType':{'const':name}}},
        'then':{'properties':{'metadata':shape}}} for name,shape in
        (('dpkg-db-entry',dpkg),('python-package',python),('binary-signature',binary))]
    distro = obj({}, {**strings('prettyName name id version versionID versionCodename buildID imageID imageVersion '
        'variant variantID homeURL supportURL bugReportURL privacyPolicyURL cpeName supportEnd'),
        'idLike':arr(s),'extendedSupport':b})
    return obj({'artifacts':{**arr(package),'minItems':1},'artifactRelationships':arr(obj(strings('parent child type'),{'metadata':{}})),
        'files':{**arr(file_),'minItems':1},'source':obj({**strings('id name version type'),'metadata':{}},{'supplier':s}),
        'distro':distro,'descriptor':obj({'name':{'const':'syft'},'version':{'const':'1.42.3'},'configuration':{}}),
        'schema':obj({'version':{'const':'16.1.3'},'url':s})})


def _validate_syft_structure(value):
    from jsonschema import Draft202012Validator
    require(Draft202012Validator(_syft_schema()).is_valid(value))


def _grype_configuration(*,input_file=False):
    """Finite v0.110.0 native JSON values; input spellings follow mapstructure."""
    value = {key:'' for key in ('file','distro','output-template-file','ignore-wontfix','platform',
        'fail-on-severity','name','default-image-pull-source')}
    value.update({key:False for key in ('pretty','add-cpes-if-none','check-for-app-update','only-fixed',
        'only-notfixed','show-suppressed','by-cve')})
    value.update({key:[] for key in ('ignore','exclude','vex-documents','vex-add')})
    value.update({'output':['json'],'from':None,'match-upstream-kernel-headers':True,'timestamp':True,
        'search':{'scope':'squashed','unindexed-archives':False,'indexed-archives':True},
        'externalSources':{'enable':False,'maven':{'searchUpstreamBySha1':False,
            'baseUrl':'https://search.maven.org/solrsearch/select','rateLimit':300000000}},
        'registry':{'insecure-skip-tls-verify':False,'insecure-use-http':False,'ca-cert':''},
        'SortBy':{'sort-by':'risk'},'fix-channel':{'redhat-eus':{'apply':'never','versions':'>= 8.0'}},
        'alerts':{'enable-eol-distro-warnings':True},'exp':{},'dev':{'db':{'debug':False}},
        'match':{name:{'using-cpes':name in ('jvm','stock')} for name in
            ('java','dotnet','javascript','python','ruby','rust','hex','jvm','stock','golang','dpkg','rpm')},
        'db':{'cache-dir':'/inputs/db','update-url':'https://grype.anchore.io/databases','ca-cert':'',
            'auto-update':False,'validate-by-hash-on-start':True,'validate-age':True,
            'max-allowed-built-age':432000000000000,'require-update-check':False,
            'update-available-timeout':30000000000,'update-download-timeout':300000000000,'max-update-check-frequency':7200000000000}})
    value['match']['golang'].update({'always-use-cpe-for-stdlib':True,'allow-main-module-pseudo-version-comparison':False})
    for name,strategy in (('dpkg','zero'),('rpm','auto')):
        value['match'][name].update({'missing-epoch-strategy':strategy,'use-cpes-for-eol':False})
    if input_file:
        value['external-sources'] = {'enable':False,'maven':{'search-maven-upstream':False,
            'base-url':'https://search.maven.org/solrsearch/select','rate-limit':'300ms'}}
        del value['externalSources'],value['SortBy'],value['ignore-wontfix']
        value['sort-by'],value['from'] = 'risk',[]
        value['db'].update({'max-allowed-built-age':'120h','update-available-timeout':'30s',
            'update-download-timeout':'300s','max-update-check-frequency':'2h'})
    return value


def _same_typed(value,expected):
    if type(value) is not type(expected): return False
    if type(expected) is dict:
        return value.keys() == expected.keys() and all(_same_typed(value[key],item) for key,item in expected.items())
    if type(expected) is list:
        return len(value) == len(expected) and all(_same_typed(a,b) for a,b in zip(value,expected,strict=True))
    return value == expected


def _validate_grype_configuration(value,*,input_file=False):
    require(type(value) is dict)
    compared = deepcopy(value)
    if not input_file:
        for key in ('ignore','exclude','vex-documents','vex-add'):
            if key in compared and compared[key] is None: compared[key] = []
    require(_same_typed(compared,_grype_configuration(input_file=input_file)))
    return compared


_LICENSE_IDS = frozenset(('MIT','Apache-2.0','BSD-2-Clause','BSD-3-Clause','ISC','Python-2.0','MPL-2.0',
    'Zlib','Unicode-3.0','GPL-2.0-only','GPL-2.0-or-later','GPL-3.0-only','GPL-3.0-or-later',
    'LGPL-2.1-only','LGPL-2.1-or-later','LGPL-3.0-only','LGPL-3.0-or-later'))
_EXCEPTIONS = frozenset(('Classpath-exception-2.0','GCC-exception-3.1','LLVM-exception'))


def _license_tree(value,local_licenses):
    require(type(value) is str and 0 < len(value.encode('utf-8')) <= 4096)
    def expression(start,depth):
        require(depth <= 16 and start < len(value))
        if value[start] == '(':
            left,end = expression(start+1,depth+1)
            match = re.match(r' (AND|OR) ',value[end:])
            require(match is not None)
            right,end = expression(end+len(match.group()),depth+1)
            require(end < len(value) and value[end] == ')')
            return (match.group(1),left,right),end+1
        match = re.match(r'[A-Za-z0-9.-]+',value[start:])
        require(match is not None)
        identifier = match.group()
        local = re.fullmatch(r'LicenseRef-[A-Za-z0-9.-]{1,120}',identifier) is not None
        require(identifier in _LICENSE_IDS or local and identifier in local_licenses)
        end = start+len(identifier)
        if value[end:end+6] == ' WITH ':
            require(not local)
            match = re.match(r'[A-Za-z0-9.-]+',value[end+6:])
            require(match is not None and match.group() in _EXCEPTIONS)
            return ('WITH',identifier,match.group()),end+6+len(match.group())
        return ('ID',identifier),end
    tree,end = expression(0,0)
    require(end == len(value))
    return tree


def _validate_license_selection(declared,concluded,local_licenses):
    declared_tree,selected = (_license_tree(value,local_licenses) for value in (declared,concluded))
    def permitted(original,result):
        if result[0] == 'OR': return False
        if original[0] == 'OR': return permitted(original[1],result) or permitted(original[2],result)
        if original[0] == 'AND':
            return result[0] == 'AND' and permitted(original[1],result[1]) and permitted(original[2],result[2])
        return original == result
    require(permitted(declared_tree,selected))


def _grype_schema():
    s,n = {'type':'string'},{'type':'number'}
    def arr(item): return {'type':'array','items':item}
    def strings(names): return {key:s for key in names.split()}
    obj = _native_object
    cvss = obj({'version':s,'vector':s,'metrics':obj({'baseScore':n},{'exploitabilityScore':n,'impactScore':n}),
        'vendorMetadata':{}},strings('source type'))
    ke = obj(strings('cve knownRansomwareCampaignUse'),{**strings('vendorProject product dateAdded requiredAction dueDate notes'),
        'urls':arr(s),'cwes':arr(s)})
    epss = obj({'cve':s,'epss':n,'percentile':n,'date':s})
    cwe = obj({'cve':s},strings('cwe source type'))
    required = {'id':{'type':'string','minLength':1},'dataSource':s,
        'severity':{'enum':['Negligible','Low','Medium','High','Critical','Unknown']},'urls':arr(s),'cvss':arr(cvss)}
    optional = {**strings('namespace description'),'knownExploited':arr(ke),'epss':arr(epss),'cwes':arr(cwe)}
    metadata = obj(required,optional)
    vulnerability = obj({**required,'fix':obj({'versions':arr(s),'state':s},
        {'available':arr(obj(strings('version date'),{'kind':s}))}),
        'advisories':arr(obj(strings('id link'))),'risk':n},optional)
    location = obj(strings('path accessPath'),{'layerID':s,'annotations':{'type':'object','additionalProperties':s}})
    artifact = obj({**strings('id name version type language purl'),'locations':{'anyOf':[{'type':'null'},arr(location)]},
        'licenses':arr(s),'cpes':arr(s),'upstreams':arr(obj({'name':s},{'version':s}))})
    detail = obj({'type':{'enum':['exact-direct-match','exact-indirect-match','cpe-match']},
        'matcher':{'enum':['dpkg-matcher','python-matcher','rust-matcher','stock-matcher']},
        'searchedBy':{},'found':{}},{'fix':obj({'suggestedVersion':s})})
    match = obj({'vulnerability':vulnerability,'relatedVulnerabilities':arr(metadata),
        'matchDetails':{**arr(detail),'minItems':1},'artifact':artifact})
    return obj({'matches':{**arr(match),'maxItems':8192},'source':{},'distro':{},
        'descriptor':obj({'name':{'const':'grype'},'version':{'const':'0.110.0'},'timestamp':s,'configuration':{},'db':{}})},
        {'ignoredMatches':{'type':'array','maxItems':0},'alertsByPackage':{'type':'array','maxItems':0}})


def _native_location_key(location):
    """Hashable exact selected native Location, after external schema admission.

    Values are strings except the optional string-to-string annotations object.
    No domain JSON serialization or smaller canonical-string budget applies.
    """
    return tuple((key,tuple(sorted(value.items())) if type(value) is dict else value)
        for key,value in sorted(location.items()))


def _scan_findings(document,projections,classes,*,scan):
    from jsonschema import Draft202012Validator
    require(scan in ('image','component') and Draft202012Validator(_grype_schema()).is_valid(document))
    _validate_grype_configuration(document['descriptor']['configuration'])
    accepted = []
    for index,match in enumerate(document['matches']):
        artifact = match['artifact']
        identifier = artifact['id']
        require(identifier in projections and identifier in classes)
        projected = projections[identifier]
        actual = {key:deepcopy(value) for key,value in artifact.items() if key != 'licenses'}
        actual['upstreams'] = [{'name':row['name'],'version':row.get('version','')} for row in actual['upstreams']]
        if scan == 'component': require(actual['locations'] is None)
        else:
            require(type(actual['locations']) is list and type(projected['locations']) is list)
            locations = [_native_location_key(value) for value in actual['locations']]
            require(len(locations) == len(set(locations)) and set(locations) == {_native_location_key(value) for value in projected['locations']})
            actual['locations'] = deepcopy(projected['locations'])
        require(_same_typed(actual,projected))
        class_ = classes[identifier]
        matcher = {'debian':'dpkg-matcher','python-wheel':'python-matcher','rust-crate':'rust-matcher',
            'cpython':'stock-matcher'}.get(class_)
        require(matcher is not None)
        for detail in match['matchDetails']:
            require(detail['matcher'] == matcher)
            require(detail['type'] != 'cpe-match' or matcher == 'stock-matcher')
        for vulnerability in (match['vulnerability'],*match['relatedVulnerabilities']):
            require(vulnerability['severity'] in ('Negligible','Low','Medium'))
            require(re.fullmatch(r'[\x20-\x7e]{1,128}',vulnerability['id']) is not None)
        accepted.append({'scan':scan,'match_index':index,'vulnerability_id':match['vulnerability']['id'],
            'artifact_id':identifier,'severity':match['vulnerability']['severity']})
    return accepted


def _identity(raw):
    from hashlib import sha256
    return {'sha256':sha256(raw).hexdigest(),'size_bytes':len(raw)}


def _oci_identity(value):
    return {'sha256':value['digest'][7:],'size_bytes':value['size_bytes']}


def _authenticate_review(packet,source_files,stage,now_ms):
    """Authenticates exact bytes/current policy; never itself an assessment."""
    from base64 import b64decode
    from app.domain.refs import canonical_json,parse_canonical
    from app.operations.setup import OriginProfile,parse_base64url_32
    from app.deployment.receipt_crypto import verify_detached
    from app.deployment.installation_release_contracts import (
        validate_release_sources,parse_release_trust,parse_release_context,installation_evidence_policy_sha256)
    from .provider_installation_contracts import ReleasePacket,VerifiedStageView,integer,parse_review_envelope
    from .provider_lineage import parse_provider_lineage
    try:
        require(type(packet) is ReleasePacket and type(stage) is VerifiedStageView)
        ReleasePacket(packet.header,packet.objects)
        integer(now_ms)
        require(packet.header.stage_ref == stage.stage_ref)
        geometry = parse_canonical(dict(stage.provider_files)['geometry.json'])
        profile = OriginProfile.from_dict(geometry['origin_profile'])
        validate_release_sources(source_files,provider_files=stage.provider_files,profile=profile)
        trust = parse_release_trust(source_files[0][1]).as_dict()
        context = parse_release_context(source_files[1][1]).as_dict()
        envelope = parse_review_envelope(packet.objects[0]).as_dict()
        review = envelope['payload']
        subject = review['subject']
        review_identity = _identity(packet.objects[0])
        require(review['objects'] == packet.header.as_dict()['objects'][1:])
        require(context['evidence_policy_sha256'] == review['evidence_policy_sha256'] == installation_evidence_policy_sha256())
        require(trust['valid_from_ms'] <= now_ms < trust['valid_until_ms'])
        require(envelope['key_id'] not in trust['revoked_key_ids']
            and review_identity['sha256'] not in trust['revoked_review_sha256']
            and subject['selected_manifest']['sha256'] not in trust['revoked_manifest_sha256'])
        keys = [key for key in trust['keys'] if key['key_id'] == envelope['key_id']]
        require(len(keys) == 1)
        key = keys[0]
        require(key['algorithm'] == 'ed25519' and key['role'] == 'provider_artifact_review'
            and key['review_profile_id'] == review['review_profile_id']
            and key['issuance_not_before_ms'] <= review['issued_at_ms'] < key['issuance_not_after_ms'])
        expected_allow = {'extension_id':subject['extension_id'],'extension_version':subject['extension_version'],
            'platform':subject['platform'],'image_index_sha256':subject['image_index']['sha256'],
            'selected_manifest_sha256':subject['selected_manifest']['sha256'],
            'release_review':review_identity,'key_id':envelope['key_id']}
        require(trust['allowed_releases'] == [expected_allow])
        unsigned = {key:value for key,value in envelope.items() if key != 'signature'}
        verify_detached(parse_base64url_32(key['public_key']),
            b'deeptwin:provider-release-review:v1\n'+canonical_json(unsigned),
            b64decode(envelope['signature']+'==',altchars=b'-_',validate=True))
        lineage = parse_provider_lineage(stage.lineage_bytes).as_dict()
        content = stage.stage_record['content']
        require(subject['platform'] == content['platform'] == context['platform'])
        selected = [row for row in lineage['platforms'] if row['measured_platform_entry']['platform'] == subject['platform']]
        require(len(selected) == 1)
        entry,identity = selected[0]['measured_platform_entry'],selected[0]['build_identity']
        require(subject['extension_id'] == lineage['extension_id'] == content['extension_id']
            and subject['extension_version'] == lineage['extension_version']
            and subject['image_index'] == _oci_identity(lineage['index'])
            and subject['selected_manifest'] == _oci_identity(entry['manifest'])
            and subject['config'] == _oci_identity(entry['config'])
            and subject['layers'] == [_oci_identity(layer) for layer in entry['layers']]
            and subject['build_identity_sha256'] == _identity(canonical_json(identity))['sha256'])
        for field,index in (('source_closure',6),('dependency_closure',7),('filesystem_inspection',8)):
            require(subject[field] == _identity(packet.objects[index]))
        return review
    except InstallationError: raise
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,RecursionError): raise InstallationError() from None


def _timestamp_ms(value,*,utc_seconds=False):
    from datetime import datetime,timedelta,timezone
    from fractions import Fraction
    try:
        require(type(value) is str and len(value) <= 35)
        pattern = (r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})')
        match = re.fullmatch(pattern,value)
        require(match is not None)
        year,month,day,hour,minute,second = map(int,match.groups()[:6])
        fraction,zone = match.group(7),match.group(8)
        require(not utc_seconds or (fraction is None and zone == 'Z'))
        offset = 0
        if zone != 'Z':
            hours,minutes = int(zone[1:3]),int(zone[4:6])
            require(hours <= 23 and minutes <= 59)
            offset = (hours*60+minutes)*(1 if zone[0] == '+' else -1)
        dt = datetime(year,month,day,hour,minute,second,tzinfo=timezone(timedelta(minutes=offset)))
        delta = dt-datetime(1970,1,1,tzinfo=timezone.utc)
        result = Fraction((delta.days*86400+delta.seconds)*1000)
        if fraction is not None: result += Fraction(int(fraction)*1000,10**len(fraction))
        require(0 <= result <= 253402300799999)
        return result
    except InstallationError: raise
    except (ValueError,OverflowError,TypeError): raise InstallationError() from None


def _validate_database(status,providers,scan_databases,built_at_ms):
    from .provider_installation_contracts import exact,integer
    integer(built_at_ms,0,2**63-1)
    exact(status,('schemaVersion','valid','from','built','path'))
    require(status['schemaVersion'] == '6.1.4' and status['valid'] is True
        and status['from'] == 'manual import' and status['path'] == '/inputs/db/6/vulnerability.db')
    require(type(status['built']) is str and '.' not in status['built']
        and _timestamp_ms(status['built']) == built_at_ms)
    require(type(providers) is list and 1 <= len(providers) <= 128)
    by_name = {}
    for row in providers:
        exact(row,('name','version','processor','dateCaptured','inputDigest'))
        name = row['name']
        require(type(name) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',name) is not None
            and name not in by_name)
        for key in ('version','processor','inputDigest'):
            require(type(row[key]) is str and 0 < len(row[key].encode('utf-8')) <= 256)
        require(re.fullmatch(r'[\x21-\x7e]+:[\x21-\x7e]+',row['inputDigest']) is not None)
        _timestamp_ms(row['dateCaptured'])
        by_name[name] = row
    require(type(scan_databases) is list and len(scan_databases) == 2)
    for database in scan_databases:
        exact(database,('status','providers'))
        require(_same_typed(database['status'],status))
        observations = database['providers']
        require(type(observations) is dict and set(observations) == set(by_name))
        for name,observation in observations.items():
            exact(observation,('captured','input'))
            require(type(observation['captured']) is str and '.' not in observation['captured'])
            captured = _timestamp_ms(observation['captured'])
            native = _timestamp_ms(by_name[name]['dateCaptured'])
            require(captured == (native//1000)*1000 and observation['input'] == by_name[name]['inputDigest'])


def _embedded_oci(value,expected):
    from base64 import b64decode,b64encode
    try:
        require(type(value) is str and 0 < len(value) <= 349528)
        raw = b64decode(value,validate=True)
        require(0 < len(raw) <= 262144 and b64encode(raw).decode('ascii') == value)
        require(_identity(raw) == _oci_identity(expected))
        parsed = _RawParser(raw).parse()
        require(type(parsed) is dict)
        return parsed
    except InstallationError: raise
    except (ValueError,TypeError,UnicodeError): raise InstallationError() from None


def _validate_image_metadata(metadata,filesystem):
    from .provider_installation_contracts import exact,integer
    required = {'userInput','imageID','manifestDigest','mediaType','tags','imageSize','layers','manifest',
        'config','repoDigests','architecture','os'}
    require(type(metadata) is dict and required <= set(metadata)
        and set(metadata) <= required | {'architectureVariant','labels','annotations'})
    entry,observed = filesystem['entry'],filesystem['config']
    require(metadata['userInput'] == '/inputs/image' and metadata['imageID'] == entry['config']['digest']
        and metadata['manifestDigest'] == entry['manifest']['digest'] and metadata['mediaType'] == entry['manifest']['media_type']
        and metadata['architecture'] == filesystem['platform'].split('/')[1] and metadata['os'] == 'linux'
        and metadata.get('architectureVariant','') == '')
    for key in ('tags','repoDigests'):
        require(metadata[key] is None or type(metadata[key]) is list and all(type(item) is str for item in metadata[key]))
    for key in ('labels','annotations'):
        if key in metadata:
            require(type(metadata[key]) is dict and all(type(value) is str for value in metadata[key].values()))
    manifest = _embedded_oci(metadata['manifest'],entry['manifest'])
    config = _embedded_oci(metadata['config'],entry['config'])
    require(type(manifest.get('schemaVersion')) is int and manifest['schemaVersion'] == 2
        and manifest.get('mediaType') == entry['manifest']['media_type'])
    def descriptor(value,expected):
        require(type(value) is dict)
        integer(value.get('size'),1,2**40)
        require(value.get('digest') == expected['digest'] and value.get('size') == expected['size_bytes']
            and value.get('mediaType') == expected['media_type'])
        # OCI descriptors may carry inert annotations, but never a remote fetch URL.
        require(set(value) <= {'mediaType','digest','size','annotations'})
        if 'annotations' in value:
            require(type(value['annotations']) is dict and all(type(v) is str for v in value['annotations'].values()))
    descriptor(manifest.get('config'),entry['config'])
    require(type(manifest.get('layers')) is list and len(manifest['layers']) == len(entry['layers']))
    for value,expected in zip(manifest['layers'],entry['layers'],strict=True): descriptor(value,expected)
    require(set(manifest) <= {'schemaVersion','mediaType','config','layers','annotations'})
    if 'annotations' in manifest:
        require(type(manifest['annotations']) is dict and all(type(v) is str for v in manifest['annotations'].values()))
    exact(config,('architecture','os','created','config','rootfs','history'))
    require(config['architecture'] == observed['architecture'] and config['os'] == observed['os']
        and config['created'] == '1970-01-01T00:00:00Z')
    expected_runtime = {'Entrypoint':observed['entrypoint'],'Cmd':observed['cmd'],'Env':observed['env'],
        'WorkingDir':observed['working_dir'],'User':observed['user'],'StopSignal':observed['stop_signal']}
    require(_same_typed(config['config'],expected_runtime))
    exact(config['rootfs'],('type','diff_ids'))
    diff_ids = config['rootfs']['diff_ids']
    require(config['rootfs']['type'] == 'layers' and type(diff_ids) is list
        and 1 <= len(diff_ids) <= 128 and diff_ids == observed['diff_ids']
        and all(type(value) is str and re.fullmatch('sha256:[0-9a-f]{64}',value) for value in diff_ids)
        and len(set(diff_ids)) == len(diff_ids) and len(diff_ids) == len(entry['layers']))
    require(type(config['history']) is list and 1 <= len(config['history']) <= 8192)
    for row in config['history']:
        require(type(row) is dict and set(row) <= {'created','created_by','author','comment','empty_layer'})
        for key,value in row.items(): require(type(value) is (bool if key == 'empty_layer' else str))
    require(config['history'][-1] == {'created':'1970-01-01T00:00:00Z','created_by':'provider-oci-build-v1'}
        and sum(not row.get('empty_layer',False) for row in config['history']) == len(diff_ids))
    require(type(metadata['layers']) is list and len(metadata['layers']) == len(diff_ids))
    for layer,diff_id,compressed in zip(metadata['layers'],diff_ids,entry['layers'],strict=True):
        exact(layer,('mediaType','digest','size'))
        require(layer['digest'] == diff_id and layer['mediaType'] == compressed['media_type'])
        integer(layer['size'],0,2**63-1)
    integer(metadata['imageSize'],0,2**63-1)
    require(metadata['imageSize'] == sum(layer['size'] for layer in metadata['layers']))
    return manifest,config


_CATALOGERS = ('binary-classifier-cataloger','dpkg-db-cataloger','file-digest-cataloger',
    'file-metadata-cataloger','python-installed-package-cataloger')
_CLASSIFIERS = (
    'python-binary,python-binary-lib,pypy-binary-lib,go-binary,julia-binary,helm,redis-binary,'
    'valkey-binary,nodejs-binary,busybox-binary,util-linux-binary,haproxy-binary,perl-binary,'
    'php-composer-binary,httpd-binary,memcached-binary,traefik-binary,arangodb-binary,'
    'postgresql-binary,mysql-binary,mysql-binary,mysql-binary,xtrabackup-binary,mariadb-binary,'
    'rust-standard-library-linux,rust-standard-library-macos,ruby-binary,erlang-binary,'
    'erlang-alpine-binary,erlang-library,swipl-binary,dart-binary,haskell-ghc-binary,'
    'haskell-cabal-binary,haskell-stack-binary,consul-binary,hashicorp-vault-binary,nginx-binary,'
    'bash-binary,openssl-binary,qt-qtbase-lib,gcc-binary,fluent-bit-binary,wordpress-cli-binary,'
    'curl-binary,lighttpd-binary,proftpd-binary,zstd-binary,xz-binary,gzip-binary,sqlcipher-binary,'
    'jq-binary,chrome-binary,ffmpeg-binary,ffmpeg-library,ffmpeg-library,elixir-binary,'
    'elixir-library,istio-binary,istio-binary,grafana-binary,grafana-binary,envoy-binary,mongodb-binary,'
    'java-binary,java-jdb-binary').split(',')


def _validate_syft_configuration(input_,audit,platform):
    require(platform in ('linux/amd64','linux/arm64'))
    python = {'guess-unpinned-requirements':False,'search-remote-licenses':False,'pypi-base-url':'https://pypi.org/pypi'}
    expected_input = {'check-for-app-update':False,'scope':'squashed','from':['oci-dir'],'platform':platform,
        'exclude':[],'enrich':[],'default-catalogers':list(_CATALOGERS),'select-catalogers':[],
        'package':{'search-indexed-archives':False,'search-unindexed-archives':False,'exclude-binary-overlap-by-ownership':False},
        'relationships':{'package-file-ownership':True,'package-file-ownership-overlap':False},
        'file':{'metadata':{'selection':'all','digests':['sha256']}},'license':{'content':'all','coverage':75},
        'python':python,'compliance':{'missing-name':'keep','missing-version':'keep'},
        'unknowns':{'remove-when-packages-defined':False,'executables-without-packages':True,'unexpanded-archives':True}}
    expected_audit = {'search':{'scope':'squashed'},'relationships':{'package-file-ownership':True,
        'package-file-ownership-overlap':False,'exclude-binary-packages-with-file-ownership-overlap':False},
        'data-generation':{'generate-cpes':True},'files':{'selection':'all','hashers':['sha256'],
            'content':{'globs':None,'skip-files-above-size':0}},'licenses':{'include-content':'all','coverage':75},
        'catalogers':{'requested':{'default':list(_CATALOGERS)},'used':list(_CATALOGERS)},
        'packages':{'binary':list(_CLASSIFIERS),'python':python,
            **{name:{} for name in ('dotnet','golang','java-archive','javascript','linux-kernel','nix')}}}
    require(type(input_) is dict and type(audit) is dict)
    normalized_input,normalized_audit = deepcopy(input_),deepcopy(audit)
    for value,key in ((normalized_input,'license'),(normalized_audit,'licenses')):
        require(type(value.get(key)) is dict)
        coverage = value[key].get('coverage')
        require(type(coverage) in (int,Decimal) and coverage == 75)
        value[key]['coverage'] = 75
    require(type(normalized_audit.get('packages')) is dict)
    for name in ('dotnet','golang','java-archive','javascript','linux-kernel','nix'):
        require(type(normalized_audit['packages'].get(name)) is dict)
        normalized_audit['packages'][name] = {}
    require(_same_typed(normalized_input,expected_input) and _same_typed(normalized_audit,expected_audit))


def _reference(value,cap=2**63-1):
    from .provider_installation_contracts import exact,digest,integer
    exact(value,('sha256','size_bytes'))
    digest(value['sha256'])
    integer(value['size_bytes'],1,cap)
    return value


class _EvidenceGraph:
    """Finite carrier identities with typed use, never an uploaded trust store."""
    def __init__(self,packet):
        from .provider_installation_contracts import ReleasePacket
        require(type(packet) is ReleasePacket)
        ReleasePacket(packet.header,packet.objects)
        self._entries = {row['sha256']:(row,raw) for row,raw in
            zip(packet.header.as_dict()['objects'][1:],packet.objects[1:],strict=True)}
        self._used = {}

    def _read(self,reference,roles,parser):
        _reference(reference)
        require(reference['sha256'] in self._entries)
        descriptor,raw = self._entries[reference['sha256']]
        require(descriptor['role'] in roles and descriptor['size_bytes'] == reference['size_bytes'])
        prior = self._used.get(reference['sha256'])
        require(prior is None or prior == parser)
        self._used[reference['sha256']] = parser
        return raw

    def project(self,reference,role,schema_version):
        from app.domain.refs import parse_canonical
        raw = self._read(reference,(role,),schema_version)
        value = parse_canonical(raw)
        def arrays(item):
            if type(item) is list:
                require(len(item) <= 8192)
                for child in item: arrays(child)
            elif type(item) is dict:
                for child in item.values(): arrays(child)
        arrays(value)
        require(type(value) is dict and value.get('schema_version') == schema_version)
        return value

    def raw_json(self,reference,kind,role='origin_evidence'):
        raw = self._read(reference,(role,),kind)
        return _RawParser(raw).parse()

    def text(self,reference,*,license_only=False):
        roles = ('license_text',) if license_only else ('origin_evidence','license_text')
        raw = self._read(reference,roles,'plain-utf8')
        role = self._entries[reference['sha256']][0]['role']
        require(0 < len(raw) <= (8388608 if role == 'license_text' else 65536))
        try: value = raw.decode('utf-8','strict')
        except UnicodeError: raise InstallationError() from None
        require('\0' not in value)
        return value

    def toolset(self,reference):
        from app.domain.refs import parse_canonical
        raw = self._read(reference,('origin_evidence',),'r1-toolset')
        require(len(raw) <= 65536)
        return parse_canonical(raw)

    def finish(self):
        require(set(self._used) == set(self._entries))


_DPKG_REQUIRED = frozenset(('Package','Status','Version','Architecture'))
_DPKG_OPTIONAL = frozenset(('Source','Multi-Arch','Essential','Protected','Priority','Section','Installed-Size',
    'Maintainer','Original-Maintainer','Homepage','Description','Depends','Pre-Depends','Provides','Recommends',
    'Suggests','Enhances','Breaks','Conflicts','Replaces','Conffiles','Built-Using'))
_DPKG_NAME = r'[a-z0-9][a-z0-9+.-]+'
_DPKG_VERSION = r'(?:[0-9]+:)?[0-9][A-Za-z0-9.+~:-]*'


@dataclass(frozen=True,slots=True,init=False)
class DpkgStatus:
    content_bytes: bytes
    _records: tuple

    def __new__(cls,*args,**kwargs): raise TypeError('dpkg status requires bounded retained parsing')

    def as_dict(self): return [dict(row) for row in self._records]


def parse_dpkg_status(raw,platform):
    """Deliberately strict installed-only control grammar, not dpkg emulation."""
    try:
        require(type(raw) is bytes and 0 < len(raw) <= 1048576,'too_large')
        require(platform in ('linux/amd64','linux/arm64') and raw.endswith(b'\n')
            and not raw.startswith(b'\xef\xbb\xbf'))
        require(all(byte >= 32 and byte != 127 or byte == 10 for byte in raw))
        # Check physical budgets on raw byte offsets before building decoded lines/fields.
        start,line_count = 0,0
        while start < len(raw):
            end = raw.find(b'\n',start)
            require(end >= start and end-start <= 4096,'too_large')
            line_count += 1
            require(line_count <= 65536,'too_large')
            start = end+1
        text = raw.decode('utf-8','strict')
        lines = text[:-1].split('\n')
        if lines and lines[-1] == '': lines.pop()
        require(bool(lines) and lines[0] != '' and lines[-1] != '')
        records,fields,case_names = [],{},set()
        names = set()
        previous,paragraph_lines = None,0
        def finish():
            require(_DPKG_REQUIRED <= fields.keys() and len(fields) <= 26)
            for key in _DPKG_REQUIRED: require(bool(fields[key]))
            package,version,architecture = fields['Package'],fields['Version'],fields['Architecture']
            require(len(package) <= 128 and re.fullmatch(_DPKG_NAME,package) is not None)
            require(len(version) <= 128 and re.fullmatch(_DPKG_VERSION,version) is not None)
            require(architecture in (platform.split('/')[1],'all') and package not in names)
            require(fields['Status'] == 'install ok installed')
            if 'Multi-Arch' in fields: require(fields['Multi-Arch'] in ('no','same','foreign','allowed'))
            if 'Source' in fields:
                source = re.fullmatch('('+_DPKG_NAME+r')(?: \(('+_DPKG_VERSION+r')\))?',fields['Source'])
                require(source is not None and len(source.group(1)) <= 128
                    and (source.group(2) is None or len(source.group(2)) <= 128))
            names.add(package)
            require(len(records) < 8192,'too_large')
            records.append(tuple(fields.items()))
        for line in (*lines,''):
            if line == '':
                require(bool(fields))
                finish()
                fields,case_names = {},set()
                previous,paragraph_lines = None,0
                continue
            paragraph_lines += 1
            require(paragraph_lines <= 4096,'too_large')
            if line.startswith(' '):
                require(previous in ('Description','Conffiles'))
                fields[previous] += '\n'+line[1:]
                continue
            name,separator,value = line.partition(': ')
            require(bool(separator) and name in _DPKG_REQUIRED | _DPKG_OPTIONAL
                and name.casefold() not in case_names and value == value.strip(' '))
            require(len(fields) < 26,'too_large')
            fields[name],previous = value,name
            case_names.add(name.casefold())
        result = object.__new__(DpkgStatus)
        object.__setattr__(result,'content_bytes',raw)
        object.__setattr__(result,'_records',tuple(records))
        return result
    except InstallationError: raise
    except (ValueError,TypeError,UnicodeError,RecursionError): raise InstallationError() from None


def _cataloger_path(path):
    if path.endswith('/lib/dpkg/status'): return 'status'
    if re.search(r'/lib/dpkg/status\.d(?:/|$)',path): return 'status-directory'
    if path.endswith('/lib/opkg/status') or re.search(r'/lib/opkg/info/[^/]+\.control\Z',path): return 'opkg'
    return None


def _virtual_target(path,target,links=None,rows=None):
    from collections import deque
    require(type(target) is str and 0 < len(target.encode('utf-8')) <= 1024
        and '\\' not in target and '\0' not in target)
    parts = [] if target.startswith('/') else path.split('/')[1:-1]
    pending = deque(target.split('/'))
    seen,hops = set(),0
    while pending:
        part = pending.popleft()
        if part in ('','.'): continue
        if part == '..':
            require(bool(parts))
            parts.pop()
        else:
            parts.append(part)
            current = '/'+ '/'.join(parts)
            if rows is not None:
                require(current in rows)
                require(not pending or rows[current]['kind'] in ('directory','symlink'))
            if links is not None and current in links:
                state = (current,tuple(pending))
                # A nonterminating target supplies no resolved retained prefix.
                # Its lexical reverse edges below still expose relevant aliases
                # and enforce the same finite reachability budget.
                if state in seen: return None
                # A proven repeated state is a closed cycle. Budget exhaustion
                # is not that proof: never drop an unresolved edge as unrelated.
                require(hops < 40,'too_large')
                seen.add(state)
                hops += 1
                replacement = links[current]
                require(type(replacement) is str and 0 < len(replacement.encode('utf-8')) <= 1024
                    and '\\' not in replacement and '\0' not in replacement)
                parts = [] if replacement.startswith('/') else parts[:-1]
                pending.extendleft(reversed(replacement.split('/')))
                require(len(('/'+ '/'.join((*parts,*pending))).encode('utf-8')) <= 4096,'too_large')
    return '/'+ '/'.join(parts)


def _dpkg_alias_paths(rows):
    """Bounded lexical prefix substitution over retained rows only; no host I/O."""
    from collections import deque
    original = {row['path'] for row in rows}
    links = {row['path']:row['target'] for row in rows if row['kind'] == 'symlink'}
    targets = {}
    for row in rows:
        if row['kind'] == 'symlink':
            # Never collapse '..' before its preceding symlink has resolved.
            target = _virtual_target(row['path'],row['target'],links)
            if target is not None: targets.setdefault(target,[]).append(row['path'])
            # Keep intermediate spellings for reverse chains and source suffix
            # checks. Lexical normalization is safe only without a parent step.
            if '..' not in row['target'].split('/'):
                lexical = _virtual_target(row['path'],row['target'])
                if lexical != target: targets.setdefault(lexical,[]).append(row['path'])
    queue = deque((path,0) for path in original)
    known,derived = set(original),set()
    while queue:
        path,hops = queue.popleft()
        parts = path.split('/')[1:]
        prefixes = ['/'] + ['/'+ '/'.join(parts[:index]) for index in range(1,len(parts)+1)]
        for prefix in prefixes:
            for link in targets.get(prefix,()):
                suffix = path if prefix == '/' and path != '/' else path[len(prefix):]
                require(len(link.encode('utf-8'))+len(suffix.encode('utf-8')) <= 4096,'too_large')
                alias = link+suffix
                # A lexical alias to status is forbidden even if its spelling was
                # already present as a physical symlink row in the complete tree.
                require(path != '/var/lib/dpkg/status' and _cataloger_path(alias) is None)
                if alias not in derived:
                    require(len(derived) < 8192,'too_large')
                    derived.add(alias)
                if alias not in known:
                    require(hops < 40,'too_large')
                    known.add(alias)
                    queue.append((alias,hops+1))
    return frozenset(derived)


def _validate_dpkg_paths(rows,reference):
    _reference(reference,1048576)
    require(type(rows) is list and 1 <= len(rows) <= 8192)
    by_path = {row['path']:row for row in rows}
    require(len(by_path) == len(rows))
    status = by_path.get('/var/lib/dpkg/status')
    require(type(status) is dict and status['kind'] == 'file' and status.get('nlink') == 1
        and status.get('sha256') == reference['sha256'] and status.get('size_bytes') == reference['size_bytes'])
    for path in ('/','/var','/var/lib','/var/lib/dpkg'):
        require(path in by_path and by_path[path]['kind'] == 'directory')
    for row in rows:
        path = row['path']
        source = _cataloger_path(path)
        if source == 'status': require(path == '/var/lib/dpkg/status')
        elif source == 'status-directory':
            require(path.endswith('/lib/dpkg/status.d') and row['kind'] == 'directory')
        else: require(source is None)
    _dpkg_alias_paths(rows)


_R1_LAUNCHER = (b'#!/usr/local/bin/python3.12 -ISB\nimport sys\n'
    b'sys.path[:] = ["/opt/deeptwin-extension/lib", "/opt/deeptwin-extension/site", "/usr/local/lib/python3.12", "/usr/local/lib/python3.12/lib-dynload"]\n'
    b'from app.workers.provider_worker import main\nraise SystemExit(main())\n')
_WHEELS = (
    ('attrs','26.1.0','c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309',67548),
    ('idna','3.19','815e7be7a7806d54abb586dc943addc79e8b2ee16915059658cbeff4b1b43bf4',68550),
    ('jsonschema','4.26.0','d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce',90630),
    ('jsonschema-specifications','2025.9.1','98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe',18437),
    ('referencing','0.37.0','381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231',26766),
    ('rpds-py','2026.6.3','ecabd69db66de867690f9797f2f8fa27ba501bbc24540cbdbdc649cd15888ba6',366189),
    ('typing-extensions','4.16.0','481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8',45571))
_ARM_RPDS = ('55927d532399c2c646100ff7feb48eaa940ad70f42cd68e1328f3ded9f81ca24',368180)


def _r1_wheels(platform):
    values = []
    for name,version,digest,size in _WHEELS:
        tag = 'py3-none-any'
        if name == 'rpds-py':
            arch = 'x86_64' if platform == 'linux/amd64' else 'aarch64'
            tag = 'cp312-cp312-manylinux_2_17_'+arch+'.manylinux2014_'+arch
            if platform == 'linux/arm64': digest,size = _ARM_RPDS
        values.append({'name':name,'version':version,'filename':name.replace('-','_')+'-'+version+'-'+tag+'.whl',
            'wheel':{'sha256':digest,'size_bytes':size}})
    return values


def _r1_sources():
    groups = {'app':['__init__'],'app/adapters':['__init__','claude_protocol'],
        'app/deployment':['__init__','contracts','files','mounts'],'app/domain':['__init__','events','refs','wire'],
        'app/extensions':['__init__','candidate_contracts','candidate_schema_exports','contracts','lineage_contracts',
            'lineage_schema_exports','port_contracts','port_schema_generator','provider_identity','provider_identity_schema_exports','registry','schema_exports'],
        'app/operations':['__init__','setup'],'app/workers':['__init__','_fixed_image_metadata','artifact_stream',
            'artifact_stream_transport','broker','extension_channel','extension_metadata','ipc_root','listener',
            'provider_messages','provider_metadata','provider_service','provider_transform','provider_worker']}
    paths = [directory+'/'+name+'.py' for directory,names in groups.items() for name in names]
    paths += ['deploy/provider_release/worker']+['schemas/v1/extensions/ports/provider-port-v1/'+role+'.schema.json'
        for role in ('config','request','result','error')]
    return tuple(sorted(paths))


def _path(value,*,absolute=True,cap=1024):
    require(type(value) is str and 0 < len(value.encode('utf-8')) <= cap
        and not any(ord(char) < 32 or ord(char) == 127 or char == '\\' for char in value))
    if absolute:
        require(value.startswith('/'))
        if value == '/': return value
        parts = value[1:].split('/')
    else:
        require(not value.startswith('/'))
        parts = value.split('/')
    require(all(part not in ('','.','..') for part in parts))
    return value


def _ordered(rows,key,minimum=0,maximum=8192):
    require(type(rows) is list and minimum <= len(rows) <= maximum)
    keys = [key(row) for row in rows]
    require(keys == sorted(set(keys)))


def _toolset(graph,reference):
    from .provider_installation_contracts import exact,integer,digest
    rows = graph.toolset(reference)
    _ordered(rows,lambda row:row['path'],1,128)
    required = {'deploy/provider_release/'+name+'.py' for name in ('__init__','contracts','inputs','oci','build','inspect','capsule','service')}
    require(required <= {row['path'] for row in rows})
    for row in rows:
        exact(row,('path','sha256','size_bytes'))
        _path(row['path'],absolute=False,cap=255)
        require(row['path'].endswith('.py'))
        digest(row['sha256'])
        integer(row['size_bytes'],0,33554432)
        require(row['size_bytes'] > 0 or row['path'].endswith('/__init__.py'))
    require(sum(row['size_bytes'] for row in rows) <= 33554432)
    return rows


def _r1_base(platform):
    """Frozen upstream declarations, not acquired or locally replayed base objects."""
    tables = {
        'linux/amd64':('9c47360a2a0355e2da18516d0b1c2126ec22c195d2185e97347c9d98398c5bef',1752,
            '59bf1d95c965f12dfc14afaf5af778fc1dbe5b372bd5c281645fc34d4c75d4e7',5684,
            (('a8ac7f6c67abc236e4c745052c404112b8fab6fe8ac3a329d1ef3b867ad67c71',28232655),
             ('268fd66f673d556a271a784d33c4541102f05dde43657861a8e793eb30ef38dd',3533349),
             ('ec613f6df89286159c101a9b15264bc627366aaf788a9ea9c3a456ad9b9b2b3e',13672032),
             ('35ef2f664a5c3b1e1408a24bd668ef33b82a89a534709e1c03aac6d50012d51a',249))),
        'linux/arm64':('d04f49f5882f49a3b91f874e75e19f0c265f7222da8659741a9d7eab148f22a9',1754,
            'a74ddf067736251b63204a4d7a26411cffa3da75600b4e67ad54c9c79f3f81cb',5693,
            (('75782e20ea1f4a9d9259bc20a5ecbbea8d5943bf5370bf0f5727900728f1cc9a',28117289),
             ('8662a60b808caf0f481c858e870db63699ac351820bd1577fb560dc553e72c38',3368479),
             ('4e1d2fc0dabb6394acabd86d1fd491fb5ed1dbec8818a32cd064357348bb1323',13602803),
             ('2df4c82f5bdbf667d202cadaffe51eeee7b81febb397af587551022611d12740',249)))}
    manifest,manifest_size,config,config_size,layers = tables[platform]
    def descriptor(media,digest,size): return {'media_type':'application/vnd.oci.image.'+media,
        'digest':'sha256:'+digest,'size_bytes':size}
    return {'index':descriptor('index.v1+json','782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254',6546),
        'entry':{'platform':platform,'manifest':descriptor('manifest.v1+json',manifest,manifest_size),
            'config':descriptor('config.v1+json',config,config_size),'layers':[
                {'position':index,**descriptor('layer.v1.tar+gzip',digest,size)}
                for index,(digest,size) in enumerate(layers,1)]}}


def _r1_limits(value):
    count = 0
    def visit(item,depth=0):
        nonlocal count
        count += 1
        require(count <= 65536 and depth <= 16,'too_large')
        if type(item) is dict:
            require(len(item) <= 32,'too_large')
            for key,value in item.items(): visit(key,depth+1); visit(value,depth+1)
        elif type(item) is list:
            for value in item: visit(value,depth+1)
        elif type(item) is str: require(len(item.encode('utf-8')) <= 1024,'too_large')
        elif type(item) is int: require(abs(item) <= 2**40)
        else: require(item is None or type(item) is bool)
    visit(value)


def _validate_r1(graph,review,stage):
    from app.domain.refs import canonical_json
    from .provider_lineage import parse_provider_lineage
    from .provider_installation_contracts import exact,integer,digest
    subject = review['subject']
    source = graph.project(subject['source_closure'],'source_report','provider-source-closure-v1')
    dependency = graph.project(subject['dependency_closure'],'dependency_report','provider-dependency-closure-v1')
    filesystem = graph.project(subject['filesystem_inspection'],'filesystem_report','provider-filesystem-inspection-v1')
    for value in (source,dependency,filesystem): _r1_limits(value)
    exact(source,('schema_version','producer_id','toolset','source_bundle','recipe','platform_inputs','files'))
    exact(dependency,('schema_version','producer_id','toolset','platforms'))
    exact(filesystem,('schema_version','inspector_id','toolset','platform','index','entry','build_identity',
        'source_closure','dependency_closure','launch_policy','config','filesystem'))
    require(source['producer_id'] == dependency['producer_id'] == 'provider-oci-build-v1'
        and filesystem['inspector_id'] == 'provider-oci-inspect-v1'
        and source['toolset'] == dependency['toolset'] == filesystem['toolset'])
    toolset = _toolset(graph,source['toolset'])
    _reference(source['source_bundle'],16777216)
    recipe = source['recipe']
    exact(recipe,('schema_version','builder_id','inspector_id','source_layout','launch_policy','base_lock',
        'toolset','dependency_sets','overlay_format','created'))
    require(recipe['schema_version'] == 'provider-private-build-recipe-v1'
        and recipe['builder_id'] == 'provider-oci-build-v1' and recipe['inspector_id'] == 'provider-oci-inspect-v1'
        and recipe['source_layout'] == 'provider-private-source44-v1'
        and recipe['launch_policy'] == 'provider-cpython-isolated-v1'
        and recipe['base_lock'] == {'sha256':'16a216e20696a8e63962c62366fa84edfb295abd1eb09ead950eb760f1a1317d','size_bytes':17917}
        and recipe['toolset'] == source['toolset'] and recipe['overlay_format'] == 'ustar-uncompressed-v1'
        and recipe['created'] == '1970-01-01T00:00:00Z')
    require(len(canonical_json(recipe)) <= 16384)
    source_rows = source['files']
    require(type(source_rows) is list and [r['source_path'] for r in source_rows] == list(_r1_sources()))
    for row in source_rows:
        exact(row,('source_path','image_path','sha256','size_bytes','mode'))
        path = _path(row['source_path'],absolute=False,cap=255)
        expected_path = '/opt/deeptwin-extension/'+('bin/worker' if path == 'deploy/provider_release/worker'
            else 'lib/'+path if path.startswith('app/') else 'ports/provider-port-v1/'+path.rsplit('/',1)[1])
        require(row['image_path'] == expected_path)
        digest(row['sha256'])
        cap = 16777216 if path == 'app/workers/provider_worker.py' else 262144 if path.startswith('schemas/') else 1048576
        integer(row['size_bytes'],0,cap)
        require(row['size_bytes'] > 0 or path.endswith('/__init__.py'))
        integer(row['mode'],0,4095)
        require(row['mode'] == (365 if path == 'deploy/provider_release/worker' else 292))
        if path == 'deploy/provider_release/worker': require(_identity(_R1_LAUNCHER) == {k:row[k] for k in ('sha256','size_bytes')})
    platforms = ('linux/amd64','linux/arm64')
    for rows in (source['platform_inputs'],recipe['dependency_sets'],dependency['platforms']):
        require(type(rows) is list and [row['platform'] for row in rows] == list(platforms))
    lock = ''.join(name+'=='+version+''.join(' --hash=sha256:'+h for h in sorted(
        {row['wheel']['sha256'] for platform in platforms for row in _r1_wheels(platform) if row['name'] == name}))+'\n'
        for name,version,*_ in _WHEELS).encode()
    all_installed = {}
    for index,platform in enumerate(platforms):
        row = dependency['platforms'][index]
        exact(row,('platform','input','distributions'))
        input_ = row['input']
        exact(input_,('schema_version','platform','python','roots','base','lock','artifacts'))
        require(input_ == {'schema_version':'provider-private-dependency-input-set-v1','platform':platform,
            'python':{'implementation':'CPython','version':'3.12.14','abi':'cp312','glibc_floor':'2.28'},
            'roots':['idna==3.19','jsonschema==4.26.0'],'base':_r1_base(platform),
            'lock':_identity(lock),'artifacts':_r1_wheels(platform)})
        input_raw = canonical_json(input_)
        require(len(input_raw) <= 32768)
        exact(recipe['dependency_sets'][index],('platform','input'))
        require(recipe['dependency_sets'][index]['input'] == _identity(input_raw))
        triple = {'schema_version':'extension-build-inputs-v1','source_bundle':source['source_bundle'],
            'build_recipe':_identity(canonical_json(recipe)),'dependency_input_set':_identity(input_raw)}
        require(source['platform_inputs'][index] == {'platform':platform,'inputs':triple})
        dists = row['distributions']
        require(type(dists) is list and [r['name'] for r in dists] == [r[0] for r in _WHEELS])
        installed = {}
        for dist,artifact in zip(dists,input_['artifacts'],strict=True):
            exact(dist,('name','version','wheel','files'))
            require(dist['name'] == artifact['name'] and dist['version'] == artifact['version'] and dist['wheel'] == artifact['wheel'])
            _ordered(dist['files'],lambda r:r['path'],1,4096)
            for file in dist['files']:
                exact(file,('path','sha256','size_bytes','mode'))
                path = _path(file['path'])
                require(path.startswith('/opt/deeptwin-extension/site/') and path not in installed)
                relative = path[len('/opt/deeptwin-extension/site/'):]
                require(not path.endswith(('.pth','.pyc')) and relative.split('/')[0] not in ('sitecustomize.py','usercustomize.py'))
                digest(file['sha256']); integer(file['size_bytes'],0,67108864); integer(file['mode'],292,292)
                installed[path] = file
        require(len(installed) <= 4096 and sum(r['size_bytes'] for r in installed.values()) <= 268435456)
        all_installed[platform] = installed
    platform = subject['platform']
    lineage = parse_provider_lineage(stage.lineage_bytes).as_dict()
    selected = next(row for row in lineage['platforms'] if row['measured_platform_entry']['platform'] == platform)
    require(filesystem['platform'] == platform and filesystem['index'] == lineage['index']
        and filesystem['entry'] == selected['measured_platform_entry'] and filesystem['build_identity'] == selected['build_identity']
        and subject['filesystem_inspection']['sha256'] == selected['extraction_evidence_sha256']
        and filesystem['source_closure'] == subject['source_closure'] and filesystem['dependency_closure'] == subject['dependency_closure']
        and filesystem['launch_policy'] == 'provider-cpython-isolated-v1')
    identity = filesystem['build_identity']
    require(identity['inputs'] == source['platform_inputs'][platforms.index(platform)]['inputs'])
    config = filesystem['config']
    exact(config,('architecture','os','entrypoint','cmd','env','working_dir','user','stop_signal','diff_ids'))
    require(config == {'architecture':platform.split('/')[1],'os':'linux',
        'entrypoint':['/opt/deeptwin-extension/bin/worker'],'cmd':[],
        'env':['LANG=C.UTF-8','LC_ALL=C.UTF-8','PATH=/usr/local/bin:/usr/bin:/bin'],
        'working_dir':'/','user':'65532:65532','stop_signal':'SIGTERM','diff_ids':config['diff_ids']})
    diffs = config['diff_ids']
    require(type(diffs) is list and 1 <= len(diffs) <= 128 and len(diffs) == len(set(diffs))
        and all(type(v) is str and re.fullmatch('sha256:[0-9a-f]{64}',v) for v in diffs))
    require(filesystem['entry']['layers'][:-1] == _r1_base(platform)['entry']['layers']
        and filesystem['entry']['layers'][-1]['media_type'] == 'application/vnd.oci.image.layer.v1.tar'
        and len(diffs) == len(filesystem['entry']['layers']) and diffs[-1] == filesystem['entry']['layers'][-1]['digest'])
    rows = filesystem['filesystem']
    _ordered(rows,lambda row:row['path'],1,8192)
    by_path = {}
    for row in rows:
        kind = row['kind']
        fields = {'directory':(),'file':('size_bytes','sha256','nlink'),'symlink':('target',)}
        require(kind in fields)
        exact(row,('path','kind','uid','gid','mode',*fields[kind]))
        path = _path(row['path'])
        integer(row['uid'],0,2**32-1); integer(row['gid'],0,2**32-1); integer(row['mode'],0,4095)
        if kind == 'file':
            digest(row['sha256']); integer(row['size_bytes'],0,2**33); integer(row['nlink'],1,8192)
        elif kind == 'symlink':
            require(type(row['target']) is str and 0 < len(row['target'].encode()) <= 1024
                and not any(ord(c) < 32 or ord(c) == 127 or c == '\\' for c in row['target']))
            _virtual_target(path,row['target'])
        by_path[path] = row
    require('/' in by_path and by_path['/']['kind'] == 'directory')
    for path in by_path:
        if path != '/': require(by_path.get(path.rsplit('/',1)[0] or '/',{}).get('kind') == 'directory')
    expected = {row['image_path']:{k:row[k] for k in ('sha256','size_bytes','mode')} for row in source_rows}
    expected.update({path:{k:row[k] for k in ('sha256','size_bytes','mode')} for path,row in all_installed[platform].items()})
    expected['/opt/deeptwin-extension/identity/build-identity-v2.json'] = {**_identity(canonical_json(identity)),'mode':292}
    parents = set()
    for path in expected:
        parent = path.rsplit('/',1)[0]
        while parent:
            parents.add(parent); parent = parent.rsplit('/',1)[0]
    protected = {path for path in by_path if path == '/opt/deeptwin-extension' or path.startswith('/opt/deeptwin-extension/')}
    require(protected == set(expected) | {path for path in parents if path.startswith('/opt/deeptwin-extension')})
    for path,facts in expected.items():
        row = by_path[path]
        require(row == {'path':path,'kind':'file','uid':0,'gid':0,'nlink':1,**facts})
    for path in parents:
        require(by_path[path] == {'path':path,'kind':'directory','uid':0,'gid':0,'mode':493})
    for row in rows:
        if row['kind'] == 'symlink':
            links = {path:value['target'] for path,value in by_path.items() if value['kind'] == 'symlink'}
            target = _virtual_target(row['path'],row['target'],links)
            protected_root = '/opt/deeptwin-extension'
            require(target is None or not (target == protected_root or target.startswith(protected_root+'/')
                or target == '/' or protected_root.startswith(target+'/')))
    require(identity['entrypoint'] == _identity(_R1_LAUNCHER))
    # All four accepted port identities must agree with these source rows as well.
    schema_rows = {row['source_path'].rsplit('/',1)[1]:row for row in source_rows if row['source_path'].startswith('schemas/')}
    for row in identity['port_schemas']:
        actual = schema_rows[row['role']+'.schema.json']
        require(row['sha256'] == actual['sha256'] and row['size_bytes'] == actual['size_bytes'])
    return source,dependency,filesystem,toolset


def _text(value,cap=4096,minimum=1):
    require(type(value) is str and minimum <= len(value.encode('utf-8')) <= cap and '\0' not in value)
    return value


def _support(graph,references,*,license_only=False):
    _ordered(references,lambda r:r['sha256'],1,128)
    return [graph.text(ref,license_only=license_only) for ref in references]


def _validate_cohort(graph,review,syft,scans,map_):
    from .provider_installation_contracts import exact,integer
    cohort = graph.project(review['cohort'],'cohort_manifest','provider-scanner-cohort-v1')
    exact(cohort,('schema_version','host_platform','syft','grype','adapter_source','producer_recipe','schema_sources','db','syft_run'))
    require(cohort['host_platform'] == review['subject']['platform'])
    graph.text(cohort['adapter_source']); graph.text(cohort['producer_recipe'])
    _ordered(cohort['schema_sources'],lambda r:r['uri'],1,64)
    for row in cohort['schema_sources']:
        exact(row,('uri','content')); _text(row['uri'],2048)
        require(type(graph.raw_json(row['content'],'schema-source')) is dict)
    configs = {}
    for name,version in (('syft','1.42.3'),('grype','0.110.0')):
        tool = cohort[name]
        exact(tool,('name','version','archive_identity','executable_identity','acquisition','version_output','config_input','resolved_config'))
        require(tool['name'] == name and tool['version'] == version)
        _reference(tool['archive_identity']); _reference(tool['executable_identity'])
        _support(graph,tool['acquisition']); graph.text(tool['version_output'])
        input_ = graph.raw_json(tool['config_input'],name+'-input-config')
        resolved = graph.raw_json(tool['resolved_config'],name+'-resolved-config')
        configs[name] = (input_,resolved)
    _validate_syft_configuration(*configs['syft'],cohort['host_platform'])
    require(_same_typed(syft['descriptor']['configuration'],configs['syft'][1]))
    _validate_grype_configuration(configs['grype'][0],input_file=True)
    _validate_grype_configuration(configs['grype'][1])
    for scan in scans.values():
        _validate_grype_configuration(scan['descriptor']['configuration'])
        # Only the four explicitly selected nil/empty configuration positions normalize.
        normalized = deepcopy(scan['descriptor']['configuration'])
        retained = deepcopy(configs['grype'][1])
        for item in (normalized,retained):
            for key in ('ignore','exclude','vex-documents','vex-add'):
                if item.get(key) == []: item[key] = None
        require(_same_typed(normalized,retained))
    database = cohort['db']
    exact(database,('schema_version','archive_identity','content_identity','built_at_ms','acquisition','distribution_metadata','status','providers'))
    integer(database['schema_version'],6,6); integer(database['built_at_ms'])
    _reference(database['archive_identity']); _reference(database['content_identity'])
    _support(graph,database['acquisition'])
    require(type(graph.raw_json(database['distribution_metadata'],'db-distribution')) is dict)
    status = graph.raw_json(database['status'],'db-status')
    providers = graph.raw_json(database['providers'],'db-providers')
    _validate_database(status,providers,[scan['descriptor']['db'] for scan in scans.values()],database['built_at_ms'])
    runs = []
    def validate_run(run,tool_name,argv,inputs,output):
        exact(run,('invocation_id','tool','started_at_ms','finished_at_ms','argv','environment','cwd','inputs','output','stderr_utf8','exit_code','diagnostics'))
        _text(run['invocation_id'],128)
        integer(run['started_at_ms']); integer(run['finished_at_ms']); integer(run['exit_code'],0,0)
        require(run['tool'] == tool_name and run['argv'] == argv and run['cwd'] == '/work'
            and run['environment'] == [{'name':'LANG','value':'C.UTF-8'},{'name':'LC_ALL','value':'C.UTF-8'}]
            and run['inputs'] == [{'name':name,'identity':identity} for name,identity in inputs]
            and run['output'] == output and run['diagnostics'] == [])
        _text(run['stderr_utf8'],65536,0)
        require(not run['stderr_utf8'].strip())
        require(run['started_at_ms'] <= run['finished_at_ms'] <= review['issued_at_ms']+300000
            and review['issued_at_ms']-run['finished_at_ms'] <= 86400000)
        runs.append(run)
    subject = review['subject']
    syft_tool,grype_tool = cohort['syft'],cohort['grype']
    validate_run(cohort['syft_run'],'syft',['/tools/syft','scan','/inputs/image','--config','/config/syft.json','--output','syft-json'],
        [('image_index',subject['image_index']),('selected_manifest',subject['selected_manifest']),
            ('config',syft_tool['config_input']),('executable',syft_tool['executable_identity'])],map_['image_sbom'])
    for kind,path,input_ in (('image','/inputs/image.syft.json',map_['image_sbom']),('component','/inputs/components.spdx.json',map_['component_spdx'])):
        invocation = graph.project(review[kind+'_invocation'],'invocation','provider-scanner-invocation-v1')
        exact(invocation,('schema_version','cohort','scan','run'))
        require(invocation['cohort'] == review['cohort'] and invocation['scan'] == kind)
        validate_run(invocation['run'],'grype',['/tools/grype','sbom:'+path,'--config','/config/grype.json','--output','json'],
            [('sbom',input_),('db',database['content_identity']),('config',grype_tool['config_input']),
                ('executable',grype_tool['executable_identity'])],review['finding_review'][kind+'_scan'])
        run = invocation['run']
        require(cohort['syft_run']['finished_at_ms'] <= run['started_at_ms']+300000)
        require(max(0,run['started_at_ms']-database['built_at_ms']) <= 432000000
            and max(0,review['issued_at_ms']-database['built_at_ms']) <= 432000000
            and database['built_at_ms'] <= run['started_at_ms']+300000)
        timestamp = _timestamp_ms(scans[kind]['descriptor']['timestamp'])
        require(run['started_at_ms']-300000 <= timestamp <= run['finished_at_ms']+300000)
    require(len({run['invocation_id'] for run in runs}) == 3)
    return cohort,runs


def _validate_provenance(graph,review,source,dependency,toolset,runs):
    from urllib.parse import quote
    from app.domain.refs import canonical_json,uuid_string
    from .provider_installation_contracts import exact
    value = graph.raw_json(review['provenance'],'provenance','provenance')
    exact(value,('_type','subject','predicateType','predicate'))
    require(value['_type'] == 'https://in-toto.io/Statement/v1' and value['predicateType'] == 'https://slsa.dev/provenance/v1')
    subject = review['subject']
    require(value['subject'] == [{'name':name,'digest':{'sha256':subject[field]['sha256']}}
        for name,field in (('image-index','image_index'),('selected-manifest','selected_manifest'),('image-config','config'))])
    exact(value['predicate'],('buildDefinition','runDetails'))
    build,run = value['predicate']['buildDefinition'],value['predicate']['runDetails']
    exact(build,('buildType','externalParameters','internalParameters','resolvedDependencies'))
    require(build['buildType'] == 'urn:deeptwin:build-type:provider-r1-offline-assembly:v1'
        and build['internalParameters'] == {} and build['externalParameters'] == {
            'extension_id':subject['extension_id'],'extension_version':subject['extension_version'],'platform':subject['platform'],
            'recipe':_identity(canonical_json(source['recipe'])),'source_closure':subject['source_closure'],
            'dependency_closure':subject['dependency_closure'],'toolset':source['toolset']})
    selected = next(row['input'] for row in dependency['platforms'] if row['platform'] == subject['platform'])
    observer = next(row['sha256'] for row in toolset if row['path'] == 'deploy/provider_release/inspect.py')
    def entry(suffix,digest): return {'uri':'urn:deeptwin:r1:'+suffix,'digest':{'sha256':digest}}
    dependencies = [entry(suffix,digest) for suffix,digest in (
        ('recipe',_identity(canonical_json(source['recipe']))['sha256']),('source-bundle',source['source_bundle']['sha256']),
        ('dependency-input-set',_identity(canonical_json(selected))['sha256']),('base-lock',source['recipe']['base_lock']['sha256']),
        ('dependency-lock',selected['lock']['sha256']),('base',selected['base']['index']['digest'][7:]),
        ('toolset',source['toolset']['sha256']),('observer',observer))]
    dependencies.extend(entry('source/'+quote(row['source_path'],safe='/.-_~'),row['sha256']) for row in source['files'])
    dependencies.extend(entry('wheel/'+quote(row['filename'],safe='/.-_~'),row['wheel']['sha256']) for row in selected['artifacts'])
    require(build['resolvedDependencies'] == sorted(dependencies,key=lambda row:row['uri']))
    exact(run,('builder','metadata','byproducts'))
    builder_deps = [entry('toolset',source['toolset']['sha256']),
        *[entry('tool/'+quote(row['path'],safe='/.-_~'),row['sha256']) for row in toolset]]
    require(run['builder'] == {'id':'urn:deeptwin:builder:provider-r1-observer:v1','version':{'observer':observer},
        'builderDependencies':sorted(builder_deps,key=lambda row:row['uri'])})
    exact(run['metadata'],('invocationId','startedOn','finishedOn'))
    uuid_string(run['metadata']['invocationId'])
    start = _timestamp_ms(run['metadata']['startedOn'],utc_seconds=True)
    finish = _timestamp_ms(run['metadata']['finishedOn'],utc_seconds=True)
    require(start <= finish <= review['issued_at_ms'] and all(finish <= invocation['started_at_ms'] for invocation in runs))
    require(run['byproducts'] == [{'name':name,'digest':{'sha256':subject[field]['sha256']}} for name,field in (
        ('source-report','source_closure'),('dependency-report','dependency_closure'),('filesystem-report','filesystem_inspection'))])


def _identifier(value,prefix=''):
    _text(value,128)
    require(re.fullmatch(re.escape(prefix)+r'[A-Za-z0-9.-]{1,120}',value) is not None if prefix
        else re.fullmatch(r'[\x20-\x7e]{1,128}',value) is not None)
    return value


def _strings(values,*,minimum=0,maximum=8192,cap=128):
    _ordered(values,lambda value:value,minimum,maximum)
    for value in values: _text(value,cap)


def _resolve_image_path(path,rows):
    """Resolve only the complete retained logical image; never open a host path."""
    _path(path)
    links = {name:row['target'] for name,row in rows.items() if row['kind'] == 'symlink'}
    resolved = _virtual_target('/',path,links,rows)
    require(resolved is not None and resolved in rows)
    _path(resolved)
    return resolved


def _purl(value,class_,name,version,*,arch=None,distro=None):
    from urllib.parse import quote,unquote_to_bytes
    _text(value,2048)
    require('#' not in value and value.count('?') <= 1)
    main,separator,query = value.partition('?')
    require(main.count('@') == 1)
    path,encoded_version = main.split('@')
    namespace = {'debian':'pkg:deb/debian/','python-wheel':'pkg:pypi/',
        'rust-crate':'pkg:cargo/','cpython':'pkg:generic/'}[class_]
    require(path.startswith(namespace))
    def decode(token):
        decoded = unquote_to_bytes(token).decode('utf-8','strict')
        require(quote(decoded,safe='.-_~') == token)
        return decoded
    require(decode(path[len(namespace):]) == name and decode(encoded_version) == version)
    qualifiers = {}
    if separator:
        require(class_ == 'debian' and query != '')
        for pair in query.split('&'):
            require(pair.count('=') == 1)
            key,token = pair.split('=')
            require(key in ('arch','distro','upstream') and key not in qualifiers)
            qualifiers[key] = decode(token)
        require(list(qualifiers) == sorted(qualifiers))
    if class_ == 'debian': require(qualifiers.get('arch') == arch and qualifiers.get('distro') == distro)
    else: require(not qualifiers)
    return qualifiers


def _reconcile_inventory(graph,review,source,dependency,filesystem):
    from app.domain.refs import canonical_json
    from .provider_installation_contracts import exact,integer
    map_ = graph.project(review['component_map'],'origin_evidence','provider-component-map-v2')
    exact(map_,('schema_version','image_sbom','component_spdx','filesystem_report','dependency_report','source_report',
        'dpkg_status','components','file_links','image_projection','component_projection'))
    subject = review['subject']
    require(map_['filesystem_report'] == subject['filesystem_inspection'] and map_['dependency_report'] == subject['dependency_closure']
        and map_['source_report'] == subject['source_closure'])
    syft = graph.raw_json(map_['image_sbom'],'image-sbom','image_sbom')
    spdx = graph.raw_json(map_['component_spdx'],'component-spdx','component_license_review')
    _validate_syft_structure(syft)
    require(syft['source']['type'] == 'image')
    _validate_image_metadata(syft['source']['metadata'],filesystem)
    # Schema URL is descriptive; the selected, code-owned schema version above is authoritative.
    _text(syft['schema']['url'],2048)
    rows = {row['path']:row for row in filesystem['filesystem']}
    regulars = {path:row for path,row in rows.items() if row['kind'] == 'file'}
    native_files,native_paths = {},{}
    for file in syft['files']:
        _identifier(file['id'])
        require(file['id'] not in native_files)
        coordinate = file['location']
        path = _resolve_image_path(coordinate['path'],rows)
        require(path in regulars and coordinate.get('layerID') in filesystem['config']['diff_ids'])
        actual = regulars[path]
        metadata = file.get('metadata')
        require(type(metadata) is dict and metadata['type'] == 'RegularFile'
            and metadata['size'] == actual['size_bytes'] and metadata['mode'] == actual['mode']
            and metadata['userID'] == actual['uid'] and metadata['groupID'] == actual['gid']
            and file.get('digests') == [{'algorithm':'sha256','value':actual['sha256']}]
            and 'linkDestination' not in metadata)
        native_files[file['id']] = file
        native_paths.setdefault(path,[]).append(file['id'])
    require(set(native_paths) == set(regulars))
    _validate_dpkg_paths(filesystem['filesystem'],map_['dpkg_status'])
    status_raw = graph._read(map_['dpkg_status'],('origin_evidence',),'dpkg-status')
    status = parse_dpkg_status(status_raw,subject['platform']).as_dict()
    status_by_name = {row['Package']:row for row in status}
    require(len(native_paths['/var/lib/dpkg/status']) == 1)
    status_id = native_paths['/var/lib/dpkg/status'][0]
    status_layer = native_files[status_id]['location']['layerID']
    artifacts = {}
    for artifact in syft['artifacts']:
        _identifier(artifact['id']); _identifier(artifact['name']); _identifier(artifact['version'])
        require(artifact['id'] not in artifacts and artifact['id'] not in native_files
            and type(artifact['locations']) is list and 1 <= len(artifact['locations']) <= 8192)
        encoded = [_native_location_key(location) for location in artifact['locations']]
        require(len(encoded) == len(set(encoded)))
        for location in artifact['locations']:
            require(_resolve_image_path(location['path'],rows) == _resolve_image_path(location['accessPath'],rows)
                and location.get('layerID') in filesystem['config']['diff_ids'])
        for license_ in artifact['licenses']:
            for location in license_['locations']:
                require(_resolve_image_path(location['path'],rows) == _resolve_image_path(location['accessPath'],rows)
                    and location.get('layerID') in filesystem['config']['diff_ids'])
        artifacts[artifact['id']] = artifact
    exact(spdx,('spdxVersion','dataLicense','SPDXID','name','documentNamespace','creationInfo','packages','files','relationships','hasExtractedLicensingInfos'))
    require(spdx['spdxVersion'] == 'SPDX-2.3' and spdx['dataLicense'] == 'CC0-1.0' and spdx['SPDXID'] == 'SPDXRef-DOCUMENT')
    _text(spdx['name']); _text(spdx['documentNamespace'],2048)
    exact(spdx['creationInfo'],('creators','created'))
    creators = spdx['creationInfo']['creators']
    require(type(creators) is list and 1 <= len(creators) <= 8
        and any(value.startswith(('Person: ','Organization: ')) for value in creators))
    for creator in creators:
        _text(creator); require(re.fullmatch(r'(?:Person|Organization|Tool): .+',creator) is not None)
    _timestamp_ms(spdx['creationInfo']['created'],utc_seconds=True)
    local_licenses = {}
    require(type(spdx['hasExtractedLicensingInfos']) is list and len(spdx['hasExtractedLicensingInfos']) <= 8192)
    for license_ in spdx['hasExtractedLicensingInfos']:
        require(type(license_) is dict and {'licenseId','extractedText'} <= set(license_) <= {'licenseId','extractedText','name'})
        id_ = _identifier(license_['licenseId'],'LicenseRef-')
        require(id_ not in local_licenses)
        text = _text(license_['extractedText'],1048576)
        ref = _identity(text.encode('utf-8'))
        require(graph.text(ref,license_only=True) == text)
        if 'name' in license_: _text(license_['name'])
        local_licenses[id_] = ref
    def checksum(value,digest): require(value == [{'algorithm':'SHA256','checksumValue':digest}])
    packages = {}
    require(type(spdx['packages']) is list and 2 <= len(spdx['packages']) <= 8192)
    for package in spdx['packages']:
        required = {'SPDXID','name','versionInfo','downloadLocation','filesAnalyzed','licenseConcluded',
            'licenseDeclared','copyrightText','primaryPackagePurpose','externalRefs'}
        require(type(package) is dict and required <= set(package) <= required|{'checksums','supplier','originator'})
        id_ = _identifier(package['SPDXID'],'SPDXRef-')
        require(id_ not in packages and id_ != 'SPDXRef-DOCUMENT' and package['filesAnalyzed'] is False)
        for key in ('name','versionInfo','downloadLocation','copyrightText','supplier','originator'):
            if key in package: _text(package[key])
        _validate_license_selection(package['licenseDeclared'],package['licenseConcluded'],local_licenses)
        require(package['primaryPackagePurpose'] in ('CONTAINER','LIBRARY','APPLICATION'))
        refs = package['externalRefs']
        require(type(refs) is list and len(refs) <= 9)
        ref_tuples = []
        for ref in refs:
            exact(ref,('referenceCategory','referenceType','referenceLocator'))
            _text(ref['referenceLocator'],2048)
            pair = (ref['referenceCategory'],ref['referenceType'])
            require(pair in (('PACKAGE-MANAGER','purl'),('SECURITY','cpe23Type')))
            ref_tuples.append((*pair,ref['referenceLocator']))
        require(len(ref_tuples) == len(set(ref_tuples)))
        packages[id_] = package
    roots = [row for row in packages.values() if row['primaryPackagePurpose'] == 'CONTAINER']
    require(len(roots) == 1)
    root = roots[0]
    root_id = root['SPDXID']
    require(root['name'] == subject['extension_id'] and root['versionInfo'] == subject['extension_version'] and root['externalRefs'] == [])
    checksum(root.get('checksums'),subject['selected_manifest']['sha256'])
    spdx_files,spdx_paths = {},{}
    require(type(spdx['files']) is list and len(spdx['files']) == len(regulars))
    for file in spdx['files']:
        exact(file,('SPDXID','fileName','checksums','licenseConcluded','licenseInfoInFiles','copyrightText'))
        id_ = _identifier(file['SPDXID'],'SPDXRef-'); path = _path(file['fileName'])
        require(id_ not in spdx_files and id_ not in packages and id_ != 'SPDXRef-DOCUMENT'
            and path in regulars and path not in spdx_paths)
        checksum(file['checksums'],regulars[path]['sha256'])
        _text(file['copyrightText'])
        _validate_license_selection(file['licenseConcluded'],file['licenseConcluded'],local_licenses)
        require(type(file['licenseInfoInFiles']) is list and 1 <= len(file['licenseInfoInFiles']) <= 32)
        for expression in file['licenseInfoInFiles']: _license_tree(expression,local_licenses)
        spdx_files[id_],spdx_paths[path] = file,id_
    require(set(spdx_paths) == set(regulars))
    _ordered(map_['components'],lambda row:row['spdx_id'],1,8192)
    components = {row['spdx_id']:row for row in map_['components']}
    require(set(components) == set(packages)-{root_id})
    selected = next(row for row in dependency['platforms'] if row['platform'] == subject['platform'])
    distributions = {row['name']:row for row in selected['distributions']}
    base_ref = _oci_identity(selected['input']['base']['index'])
    first_files = {row['image_path'] for row in source['files']}|{'/opt/deeptwin-extension/identity/build-identity-v2.json'}
    native_owners,expected_edges,projections,scan_projections,classes = {},set(),{'image':[],'component':[]},{'image':{},'component':{}},{'image':{},'component':{}}
    seen_debian,seen_python = set(),set()
    for id_,component in components.items():
        exact(component,('spdx_id','class','name','version','purl','cpes','syft_ids','parent_spdx_ids','files','inputs','license','scanner_scope'))
        _identifier(id_,'SPDXRef-'); _identifier(component['name']); _identifier(component['version'])
        class_ = component['class']
        require(class_ in ('debian','python-wheel','cpython','rust-crate','first-party'))
        _strings(component['cpes'],maximum=8,cap=2048)
        require(all(value.isascii() for value in component['cpes']))
        _strings(component['syft_ids']); _strings(component['parent_spdx_ids'],maximum=32)
        _strings(component['files'],minimum=1,cap=1024)
        require(set(component['files']) <= set(regulars)-{'/var/lib/dpkg/status'}
            and set(component['parent_spdx_ids']) <= set(components)-{id_})
        require(component['scanner_scope'] == ('first-party-not-covered' if class_ == 'first-party' else 'third-party'))
        package = packages[id_]
        require(package['name'] == component['name'] and package['versionInfo'] == component['version']
            and 'checksums' not in package)
        purls = [ref['referenceLocator'] for ref in package['externalRefs'] if ref['referenceType'] == 'purl']
        cpes = [ref['referenceLocator'] for ref in package['externalRefs'] if ref['referenceType'] == 'cpe23Type']
        require(purls == ([] if class_ == 'first-party' else [component['purl']]) and sorted(cpes) == component['cpes'])
        require(type(component['inputs']) is list and 1 <= len(component['inputs']) <= 128)
        input_kinds = []
        for input_ in component['inputs']:
            exact(input_,('kind','identity','evidence'))
            require(input_['kind'] in ('base','wheel','source','supplier'))
            _reference(input_['identity']); _support(graph,input_['evidence'])
            input_kinds.append(input_['kind'])
            if input_['kind'] == 'base': require(input_['identity'] == base_ref)
            elif input_['kind'] == 'source': require(input_['identity'] == source['source_bundle'])
            elif input_['kind'] == 'wheel': require(input_['identity'] in [row['wheel'] for row in distributions.values()])
            else: graph.text(input_['identity'])
        license_ = component['license']
        exact(license_,('concluded','texts','rationale','obligations'))
        require(license_['concluded'] == package['licenseConcluded'])
        _text(license_['rationale']); _support(graph,license_['texts'],license_only=True)
        # Every selected local term has its exact full text among the component's retained texts.
        def local_terms(tree):
            if tree[0] == 'ID': return {tree[1]} if tree[1].startswith('LicenseRef-') else set()
            if tree[0] == 'WITH': return set()
            return local_terms(tree[1])|local_terms(tree[2])
        for local in local_terms(_license_tree(license_['concluded'],local_licenses)):
            require(local_licenses[local] in license_['texts'])
        require(type(license_['obligations']) is list and [r['kind'] for r in license_['obligations']] ==
            ['notice','source-offer','redistribution','local-use'])
        for obligation in license_['obligations']:
            exact(obligation,('kind','disposition','rationale','evidence'))
            require(obligation['disposition'] in ('fulfilled','not-applicable'))
            _text(obligation['rationale']); _support(graph,obligation['evidence'])
        native = []
        for native_id in component['syft_ids']:
            require(native_id in artifacts and native_id not in native_owners)
            native_owners[native_id] = id_; native.append(artifacts[native_id])
        require(bool(native) or class_ in ('rust-crate','first-party'))
        require(not native or class_ not in ('rust-crate','first-party'))
        upstreams = []
        if class_ == 'debian':
            require(len(native) == 1 and input_kinds == ['base'])
            artifact = native[0]; metadata = artifact['metadata']
            name = component['name']
            require(name in status_by_name and name not in seen_debian)
            seen_debian.add(name)
            record = status_by_name[name]
            require(artifact['type'] == 'deb' and artifact['foundBy'] == 'dpkg-db-cataloger' and artifact['metadataType'] == 'dpkg-db-entry'
                and metadata['package'] == name and metadata['version'] == component['version'] == record['Version']
                and metadata['architecture'] == record['Architecture'])
            require(artifact['locations'] == [{'path':'/var/lib/dpkg/status','accessPath':'/var/lib/dpkg/status','layerID':status_layer}])
            require(syft['distro'].get('id') == 'debian' and type(syft['distro'].get('versionID')) is str)
            qualifiers = _purl(component['purl'],class_,name,component['version'],arch=record['Architecture'],
                distro='debian-'+syft['distro']['versionID'])
            if 'Source' in record:
                match = re.fullmatch('('+_DPKG_NAME+r')(?: \(('+_DPKG_VERSION+r')\))?',record['Source'])
                require(metadata['source'] == match.group(1) and metadata['sourceVersion'] == (match.group(2) or record['Version']))
            if metadata['source']:
                upstreams = [{'name':metadata['source'],'version':metadata['sourceVersion']}]
                if 'upstream' in qualifiers:
                    require(qualifiers['upstream'] in (metadata['source'],metadata['source']+'@'+metadata['sourceVersion']))
            elif 'upstream' in qualifiers:
                name,separator,version = qualifiers['upstream'].partition('@')
                _identifier(name); require(not separator or version != '')
                upstreams = [{'name':name,'version':version}]
            paths = [row['path'] for row in metadata['files']]
            require(len(paths) == len(set(paths)) and set(paths) == set(component['files']))
            for file in metadata['files']:
                _path(file['path'])
                if 'digest' in file and file['digest']['algorithm'] == 'sha256':
                    require(file['digest']['value'] == regulars[file['path']]['sha256'])
        elif class_ == 'python-wheel':
            normalized = re.sub(r'[-_.]+','-',component['name'].lower())
            require(normalized in distributions and normalized not in seen_python and len(native) == 1)
            seen_python.add(normalized)
            distribution = distributions[normalized]
            require(component['version'] == distribution['version'] and input_kinds == ['wheel']
                and component['inputs'][0]['identity'] == distribution['wheel']
                and set(component['files']) == {row['path'] for row in distribution['files']})
            _purl(component['purl'],class_,normalized,component['version'])
            artifact = native[0]; metadata = artifact['metadata']
            require(artifact['type'] == 'python' and artifact['foundBy'] == 'python-installed-package-cataloger'
                and artifact['metadataType'] == 'python-package' and re.sub(r'[-_.]+','-',metadata['name'].lower()) == normalized
                and metadata['version'] == component['version'] and metadata['sitePackagesRootPath'] == '/opt/deeptwin-extension/site')
            files = metadata.get('files')
            require(type(files) is list and len(files) == len(distribution['files']))
            paths = set()
            for file in files:
                path = '/opt/deeptwin-extension/site/'+_path(file['path'],absolute=False,cap=1024)
                require(path in component['files'] and path not in paths); paths.add(path)
                actual = regulars[path]
                is_record = path.endswith('.dist-info/RECORD')
                if file.get('size','') == '': require(is_record)
                else: require(re.fullmatch(r'0|[1-9][0-9]*',file['size']) is not None and int(file['size']) == actual['size_bytes'])
                if file.get('digest') is None: require(is_record)
                else: require(file['digest'] == {'algorithm':'sha256','value':actual['sha256']})
        elif class_ == 'cpython':
            require(component['name'] == 'python' and component['version'] == '3.12.14' and input_kinds == ['base']
                and package['primaryPackagePurpose'] == 'APPLICATION' and all(not path.startswith('/opt/deeptwin-extension/') for path in component['files']))
            _purl(component['purl'],class_,'python','3.12.14')
            require(component['cpes'] == ['cpe:2.3:a:'+vendor+':python:3.12.14:*:*:*:*:*:*:*' for vendor in ('python','python_software_foundation')])
            interpreter = _resolve_image_path('/usr/local/bin/python3.12',rows)
            require(interpreter in component['files'])
            for artifact in native:
                require(artifact['type'] == 'binary' and artifact['foundBy'] == 'binary-classifier-cataloger' and artifact['metadataType'] == 'binary-signature'
                    and type(artifact['metadata']['matches']) is list and len(artifact['metadata']['matches']) > 0)
                for match in artifact['metadata']['matches']:
                    require(match['classifier'] in ('python-binary','python-binary-lib')
                        and match['location'] in artifact['locations']
                        and _resolve_image_path(match['location']['path'],rows) in component['files'])
        elif class_ == 'rust-crate':
            _purl(component['purl'],class_,component['name'],component['version'])
            require('wheel' in input_kinds and 'supplier' in input_kinds and set(input_kinds) == {'wheel','supplier'}
                and len(component['parent_spdx_ids']) > 0)
            for parent in component['parent_spdx_ids']:
                parent_ = components[parent]
                require(parent_['class'] == 'python-wheel' and set(component['files']) <= set(parent_['files'])
                    and any(input_['kind'] == 'wheel' and input_['identity'] in [i['identity'] for i in parent_['inputs'] if i['kind'] == 'wheel']
                        for input_ in component['inputs']))
            require(any(path.endswith('.so') for path in component['files']))
        else:
            require(component['purl'] == '' and component['cpes'] == [] and input_kinds == ['source']
                and set(component['files']) <= first_files and not component['parent_spdx_ids'])
        for artifact in native:
            require(artifact['name'] == component['name'] and artifact['version'] == component['version']
                and artifact['purl'] == component['purl'] and sorted(row['cpe'] for row in artifact['cpes']) == component['cpes'])
            projection = {'input_id':artifact['id'],'grype_id':artifact['id'],'type':artifact['type'],
                'name':artifact['name'],'version':artifact['version'],'purl':artifact['purl'],'cpes':component['cpes'],'upstreams':upstreams}
            projections['image'].append(projection)
            scan_projections['image'][artifact['id']] = {'id':artifact['id'],**{k:projection[k] for k in ('name','version','type','purl','cpes','upstreams')},
                'locations':artifact['locations'],'language':artifact['language']}
            classes['image'][artifact['id']] = class_
        type_ = {'debian':'deb','python-wheel':'python','rust-crate':'rust-crate','cpython':'UnknownPackage','first-party':'UnknownPackage'}[class_]
        grype_id = id_[len('SPDXRef-'):]
        projection = {'input_id':id_,'grype_id':grype_id,'type':type_,'name':component['name'],'version':component['version'],
            'purl':component['purl'],'cpes':component['cpes'],'upstreams':upstreams}
        projections['component'].append(projection)
        scan_projections['component'][grype_id] = {'id':grype_id,**{k:projection[k] for k in ('name','version','type','purl','cpes','upstreams')},
            'locations':None,'language':{'python-wheel':'python','rust-crate':'rust'}.get(class_,'')}
        classes['component'][grype_id] = class_
        for parent in component['parent_spdx_ids'] or [root_id]: expected_edges.add((parent,'CONTAINS',id_))
        for path in component['files']: expected_edges.add((id_,'CONTAINS',spdx_paths[path]))
    require(set(native_owners) == set(artifacts) and seen_debian == set(status_by_name) and seen_python == set(distributions))
    require(any(row['class'] == 'cpython' for row in components.values()) and any(row['class'] == 'first-party' for row in components.values()))
    # Explicit parent DAG and reachability; neither a cycle nor a hidden nested package can cover a file.
    visited,visiting = set(),set()
    def parent_walk(id_):
        require(id_ not in visiting)
        if id_ in visited: return
        visiting.add(id_)
        for parent in components[id_]['parent_spdx_ids']: parent_walk(parent)
        visiting.remove(id_); visited.add(id_)
    for id_ in components: parent_walk(id_)
    _ordered(map_['file_links'],lambda row:row['path'],1,8192)
    require([row['path'] for row in map_['file_links']] == sorted(regulars))
    for link in map_['file_links']:
        exact(link,('path','syft_file_ids','spdx_file_id','components'))
        path = link['path']
        require(link['syft_file_ids'] == sorted(native_paths[path]) and link['spdx_file_id'] == spdx_paths[path]
            and link['components'] == sorted(id_ for id_,row in components.items() if path in row['files']))
        require(bool(link['components']) or path == '/var/lib/dpkg/status')
    expected_edges.add(('SPDXRef-DOCUMENT','DESCRIBES',root_id))
    expected_edges.add((root_id,'CONTAINS',spdx_paths['/var/lib/dpkg/status']))
    actual_edges = []
    require(type(spdx['relationships']) is list and len(spdx['relationships']) <= 65536)
    for row in spdx['relationships']:
        exact(row,('spdxElementId','relationshipType','relatedSpdxElement'))
        actual_edges.append((row['spdxElementId'],row['relationshipType'],row['relatedSpdxElement']))
    require(len(actual_edges) == len(set(actual_edges)) and set(actual_edges) == expected_edges)
    ownership = set()
    for row in syft['artifactRelationships']:
        require(row['parent'] in artifacts or row['parent'] in native_files)
        require(row['child'] in artifacts or row['child'] in native_files)
        if row['type'] == 'contains':
            require(row['parent'] in artifacts and row['child'] in native_files and row['child'] != status_id)
            edge = (row['parent'],row['child'])
            require(edge not in ownership); ownership.add(edge)
        else:
            # Only source-defined non-ownership relationships can remain descriptive.
            require(row['type'] in ('evident-by','dependency-of','overlap-by-ownership'))
            require(row['type'] != 'overlap-by-ownership')
    expected_ownership = {(native_id,file_id) for native_id,owner in native_owners.items()
        for path in components[owner]['files'] for file_id in native_paths[path]}
    require(ownership == expected_ownership)
    for kind in ('image','component'):
        require(map_[kind+'_projection'] == sorted(projections[kind],key=lambda row:row['input_id']))
    return map_,syft,scan_projections,classes


def _validated_release_facts(packet,source_files,stage,at_ms):
    """Pure complete retained-byte interpretation; no assessment or store authority."""
    try:
        review = _authenticate_review(packet,source_files,stage,at_ms)
        graph = _EvidenceGraph(packet)
        source,dependency,filesystem,toolset = _validate_r1(graph,review,stage)
        map_,syft,projections,classes = _reconcile_inventory(graph,review,source,dependency,filesystem)
        scans = {kind:graph.raw_json(review['finding_review'][kind+'_scan'],kind+'-scan',kind+'_scan')
            for kind in ('image','component')}
        findings = []
        for kind in ('image','component'):
            findings.extend(_scan_findings(scans[kind],projections[kind],classes[kind],scan=kind))
        require(review['finding_review']['accepted'] == findings)
        cohort,runs = _validate_cohort(graph,review,syft,scans,map_)
        _validate_provenance(graph,review,source,dependency,toolset,runs)
        _support(graph,review['reviewer']['authority_basis'])
        _support(graph,review['origin_review']['evidence'])
        _support(graph,review['license_review']['evidence'])
        graph.finish()
        return review
    except InstallationError: raise
    except (ValueError,TypeError,KeyError,AttributeError,IndexError,StopIteration,UnicodeError,RecursionError):
        raise InstallationError() from None


def validate_retained_release(packet,*,source_files,stage,verified_ms):
    """Historical integrity only, using journal-retained policy and recorded time.

    Caller is the mandatory composed journal. This never reads live sources or
    clocks, calls fresh admission, or allocates a ReleaseAssessment.
    """
    _validated_release_facts(packet,source_files,stage,verified_ms)


def evaluate_release(packet,*,source_files,stage,now_ms):
    """Fresh interpretation of signed evidence, not acquisition or native inspection."""
    from app.domain.refs import canonical_json
    from .provider_installation_contracts import ReleaseAssessment
    try:
        review = _validated_release_facts(packet,source_files,stage,now_ms)
        result = object.__new__(ReleaseAssessment)
        object.__setattr__(result,'review_sha256',_identity(packet.objects[0])['sha256'])
        object.__setattr__(result,'evidence',tuple((descriptor['role'],raw) for descriptor,raw in
            zip(packet.header.as_dict()['objects'],packet.objects,strict=True)))
        object.__setattr__(result,'source_files',source_files)
        object.__setattr__(result,'facts_bytes',canonical_json({'review_profile_id':review['review_profile_id'],
            'evidence_policy_sha256':review['evidence_policy_sha256'],'issued_at_ms':review['issued_at_ms'],
            'subject':review['subject'],'installation_release_context_sha256':_identity(source_files[1][1])['sha256']}))
        return result
    except InstallationError: raise
    except (ValueError,TypeError,KeyError,AttributeError,IndexError,StopIteration,UnicodeError,RecursionError):
        raise InstallationError() from None
