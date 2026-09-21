"""Closed immutable input values for one exact staged-to-verified transition."""
from dataclasses import dataclass
from hashlib import sha256

from app.domain.refs import EntityRef,canonical_json,parse_canonical,uuid_string

ERRORS = {'invalid_input':(400,'Invalid installation input'),'unauthenticated':(401,'Authentication required'),
    'access_denied':(403,'Installation access denied'),'not_found':(404,'Installation command not found'),
    'conflict':(409,'Installation evidence conflicts'),'too_large':(413,'Installation evidence exceeds limits'),
    'capacity':(429,'Installation capacity unavailable'),'unavailable':(503,'Installation evidence unavailable')}
FIRST_ROLES = ('release_review','provenance','image_sbom','component_license_review','image_scan',
    'component_scan','source_report','dependency_report','filesystem_report','cohort_manifest')
ROLES = FIRST_ROLES + ('invocation','license_text','origin_evidence')
CAPS = {'release_review':262144,'provenance':262144,'image_sbom':8388608,
    'component_license_review':4194304,'image_scan':8388608,'component_scan':8388608,
    'source_report':262144,'dependency_report':262144,'filesystem_report':1048576,
    'cohort_manifest':1048576,'invocation':1048576,'license_text':8388608,'origin_evidence':1048576}
MAX_RAW = 50331648
MAX_HEADER = 32768
MAX_WIRE = 50364428
MEDIA_TYPE = 'application/vnd.deeptwin.provider-installation-v1'
PREFIX = b'DTPIV1\0\0'


class InstallationError(ValueError):
    def __init__(self,code='invalid_input'):
        if code not in ERRORS: raise ValueError('Unknown installation error')
        self.code = code
        super().__init__(code)


def require(condition,code='invalid_input'):
    if not condition: raise InstallationError(code)


def exact(value,keys):
    require(type(value) is dict and set(value) == set(keys))
    return value


def integer(value,low=0,high=253402300799999):
    require(type(value) is int and low <= value <= high)
    return value


def digest(value):
    import re
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None)
    return value


@dataclass(frozen=True,slots=True,init=False)
class InstallationCommand:
    content_bytes: bytes

    def __new__(cls,*args,**kwargs):
        raise TypeError('installation command requires parser')

    def as_dict(self): return parse_canonical(self.content_bytes)

    @property
    def command_id(self): return self.as_dict()['command_id']

    @property
    def stage_ref(self): return EntityRef.from_dict(self.as_dict()['staged_installation_ref'])

    @property
    def input_digest(self): return sha256(self.content_bytes).hexdigest()


def parse_installation_header(raw):
    try:
        require(type(raw) is bytes and 0 < len(raw) <= MAX_HEADER,'too_large')
        value = parse_canonical(raw)
        exact(value,('schema_version','command_id','staged_installation_ref','objects'))
        require(value['schema_version'] == 'provider-installation-command-v1')
        uuid_string(value['command_id'])
        ref = EntityRef.from_dict(value['staged_installation_ref'])
        require(ref.kind == 'extension_installation' and ref.version == 1)
        objects = value['objects']
        require(type(objects) is list and 12 <= len(objects) <= 128)
        for obj in objects:
            exact(obj,('role','sha256','size_bytes'))
            require(type(obj['role']) is str and obj['role'] in CAPS)
            digest(obj['sha256'])
            integer(obj['size_bytes'],1,CAPS[obj['role']])
        require(tuple(obj['role'] for obj in objects[:10]) == FIRST_ROLES)
        require(all(obj['role'] in ROLES[10:] for obj in objects[10:]))
        require(sum(obj['role'] == 'invocation' for obj in objects) == 2)
        require(len({obj['sha256'] for obj in objects}) == len(objects))
        require(objects[10:] == sorted(objects[10:],key=lambda obj:(obj['role'],obj['sha256'])))
        require(sum(obj['size_bytes'] for obj in objects) <= MAX_RAW,'too_large')
        require(sum(obj['size_bytes'] for obj in objects if obj['role'] == 'license_text') <= 8388608,'too_large')
        nonmetadata = {'image_sbom','image_scan','component_scan','component_license_review','license_text'}
        require(sum(obj['size_bytes'] for obj in objects if obj['role'] not in nonmetadata) <= 4194304,'too_large')
        result = object.__new__(InstallationCommand)
        object.__setattr__(result,'content_bytes',raw)
        return result
    except InstallationError: raise
    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):
        raise InstallationError() from None


@dataclass(frozen=True,slots=True)
class ReleasePacket:
    header: InstallationCommand
    objects: tuple[bytes,...]

    def __post_init__(self):
        require(type(self.header) is InstallationCommand and type(self.objects) is tuple)
        header = parse_installation_header(self.header.content_bytes)
        expected = header.as_dict()['objects']
        require(len(self.objects) == len(expected))
        for raw,obj in zip(self.objects,expected,strict=True):
            require(type(raw) is bytes and len(raw) == obj['size_bytes'] and sha256(raw).hexdigest() == obj['sha256'])


@dataclass(frozen=True,slots=True,init=False)
class VerifiedStageView:
    stage_ref: EntityRef
    stage_record_bytes: bytes
    candidate_bytes: bytes
    lineage_bytes: bytes
    current_head_bytes: bytes
    provider_files: tuple[tuple[str,bytes],...]

    def __new__(cls,*args,**kwargs): raise TypeError('stage view requires actual writer journal')

    @property
    def current_head(self): return parse_canonical(self.current_head_bytes)

    @property
    def stage_record(self): return parse_canonical(self.stage_record_bytes)


@dataclass(frozen=True,slots=True,init=False)
class ReleaseAssessment:
    review_sha256: str
    evidence: tuple[tuple[str,bytes],...]
    source_files: tuple[tuple[str,bytes],...]
    facts_bytes: bytes

    def __new__(cls,*args,**kwargs): raise TypeError('assessment requires actual evidence evaluation')


@dataclass(frozen=True,slots=True,init=False)
class ReviewEnvelope:
    content_bytes: bytes

    def __new__(cls,*args,**kwargs): raise TypeError('review requires parser')

    def as_dict(self): return parse_canonical(self.content_bytes)


def parse_review_envelope(raw):
    from base64 import b64decode,urlsafe_b64encode
    from jsonschema import Draft202012Validator
    from .provider_installation_schema_exports import review_envelope_schema
    from .lineage_contracts import _valid_version
    try:
        require(type(raw) is bytes and 0 < len(raw) <= CAPS['release_review'])
        value = parse_canonical(raw)
        require(Draft202012Validator(review_envelope_schema()).is_valid(value))
        uuid_string(value['key_id'])
        signature = b64decode(value['signature']+'==',altchars=b'-_',validate=True)
        require(len(signature) == 64 and urlsafe_b64encode(signature).rstrip(b'=').decode() == value['signature'])
        payload = value['payload']
        require(_valid_version(payload['subject']['extension_version']))
        for text in (payload['reviewer']['name'],payload['origin_review']['rationale'],
                     payload['license_review']['rationale'],payload['finding_review']['rationale']):
            require(len(text.encode('utf-8')) <= 4096)
        accepted = payload['finding_review']['accepted']
        indices = [(0 if row['scan'] == 'image' else 1,row['match_index']) for row in accepted]
        require(indices == sorted(set(indices)))
        result = object.__new__(ReviewEnvelope)
        object.__setattr__(result,'content_bytes',raw)
        return result
    except InstallationError: raise
    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError): raise InstallationError() from None


def parse_installation_reply(raw):
    try:
        require(type(raw) is bytes and 0 < len(raw) <= 8192)
        value = parse_canonical(raw)
        exact(value,('schema_version','command_id','staged_installation_ref','verified_installation_ref',
            'state','revision','release_review_sha256','release_source_context_sha256','verified_at_ms','event_cursor','links'))
        require(value['schema_version'] == 'provider-installation-reply-v1' and value['state'] == 'verified')
        integer(value['revision'],2,2)
        uuid_string(value['command_id'])
        staged,verified = (EntityRef.from_dict(value[key]) for key in ('staged_installation_ref','verified_installation_ref'))
        require(staged.kind == verified.kind == 'extension_installation' and staged.id == verified.id
                and staged.version == 1 and verified.version == 2)
        for key in ('release_review_sha256','release_source_context_sha256'): digest(value[key])
        integer(value['verified_at_ms'])
        require(type(value['event_cursor']) is str and 1 <= len(value['event_cursor']) <= 1024)
        require(value['links'] == {'self':'/api/v1/extensions/provider-installation/'+value['command_id'],'events':'/api/v1/events'})
        return value
    except InstallationError: raise
    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError): raise InstallationError() from None
