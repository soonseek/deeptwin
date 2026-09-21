"""Mandatory same-store historical/current installation composition."""
from dataclasses import dataclass
from hashlib import sha256

from ..deployment import prepare_records as old
from ..deployment import prepare_storage as storage
from ..deployment.prepare_contracts import DeploymentPrepareError,require
from ..deployment.prepare_lifecycle import instant
from ..domain.public_events import EventEnvelope,_decode_cursor,_event_cursor_in_transaction
from ..domain.refs import EntityRef,ObjectRef,canonical_json,parse_canonical
from ..domain.store import BlobRef
from .provider_installation_contracts import (CAPS,ReleasePacket,VerifiedStageView,
    parse_installation_header,parse_installation_reply)

EVENT_TYPES = ('extension.verified',)


@dataclass(frozen=True,slots=True,init=False)
class VerifiedInstallationView:
    ref: EntityRef
    stage_ref: EntityRef
    record_bytes: bytes
    head_bytes: bytes
    def __new__(cls,*args,**kwargs): raise TypeError('verified installation requires composed journal')
    @property
    def content(self): return parse_canonical(self.record_bytes)['content']
    @property
    def head(self): return parse_canonical(self.head_bytes)


def stage_view(domain,db,item):
    """Project the already verified private journal; never recurse into prepare."""
    domain._assert_write_transaction(db)
    require(item.get('provider_row') is not None and item.get('installation') is not None,'unavailable')
    bundle,candidate_ref = old.candidate(domain,db,item['anchor']['candidate_ref']['id'])
    require(candidate_ref.as_dict() == item['anchor']['candidate_ref'],'unavailable')
    lineage = [raw for kind,raw in bundle.documents if kind == 'provenance']
    require(len(lineage) == 1,'unavailable')
    stage = item['installation']
    view = object.__new__(VerifiedStageView)
    for name,value in {'stage_ref':stage['ref'],'stage_record_bytes':stage['record'].body_bytes,
        'candidate_bytes':bundle.content_bytes,'lineage_bytes':lineage[0],
        'current_head_bytes':canonical_json(item.get('installation_current',stage)['head']),
        'provider_files':item['context']['files']}.items(): object.__setattr__(view,name,value)
    return view


def content_for(stage,command,review,sources,evidence,verified_ms):
    subject = review['subject']
    return {'schema_version':'provider-installation-verified-v1','state':'verified','revision':2,
        'stage_ref':stage.stage_ref.as_dict(),'previous_record_digest':stage.stage_ref.sha256,
        'extension_id':subject['extension_id'],'extension_version':subject['extension_version'],
        'platform':subject['platform'],'image_index_sha256':subject['image_index']['sha256'],
        'selected_manifest_sha256':subject['selected_manifest']['sha256'],
        'service_descriptor_sha256':stage.stage_record['content']['service_descriptor_digest'],
        'command_id':command.command_id,'verified_at_ms':verified_ms,
        'release_context_blob_ref':sources[1].as_dict(),'release_trust_blob_ref':sources[0].as_dict(),
        'release_source_context_sha256':sources[1].sha256,'release_review_sha256':evidence[0].sha256,
        'evidence_policy_sha256':review['evidence_policy_sha256'],
        'evidence':[{'role':obj['role'],'blob_ref':blob.as_dict()} for obj,blob in
            zip(command.as_dict()['objects'],evidence,strict=True)]}


def event_fields(roots,ref,actor,command_id,verified_ms,item):
    from .port_contracts import PORT_CONTRACTS
    # Actual provider staging already checked its port tuple and candidate tier.
    tier = PORT_CONTRACTS['provider-port-v1'].trust_tier
    return {'vault_id':roots.genesis.id,'recorded_at_utc':instant(verified_ms),
        'observed_at_utc':instant(verified_ms),'actor_kind':'human','actor_ref':actor,
        'event_type':'extension.verified','object_refs':(ObjectRef(ref.kind,ref.id,ref.version,ref.sha256),),
        'correlation_id':command_id,'causation_id':item['installation']['row']['event_id'],
        'status':'succeeded','error_code':None,'public_metadata':{'extension_kind':'provider','trust_tier':tier,'revision':2},
        'private_evidence_refs':(ref,),'retention_class':'core','policy_ref':roots.access_policy}


def reply_for(command,ref,content,cursor):
    return {'schema_version':'provider-installation-reply-v1','command_id':command.command_id,
        'staged_installation_ref':command.stage_ref.as_dict(),'verified_installation_ref':ref.as_dict(),
        'state':'verified','revision':2,'release_review_sha256':content['release_review_sha256'],
        'release_source_context_sha256':content['release_source_context_sha256'],
        'verified_at_ms':content['verified_at_ms'],'event_cursor':cursor,
        'links':{'self':'/api/v1/extensions/provider-installation/'+command.command_id,'events':'/api/v1/events'}}


def _verify_one(domain,db,roots,profile,journal,item,row,head):
    from .provider_installation_evidence import validate_retained_release
    from .provider_installation_contracts import parse_review_envelope
    stage = item['installation']
    require(item.get('provider_row') is not None,'unavailable')
    ref = EntityRef('extension_installation',row['installation_id'],2,row['anchor_digest'])
    old.bound_associations(db,roots.genesis.id,ref.kind,ref.id,2,edges=4,blobs=130)
    record = old.bounded_body(db,roots.genesis.id,ref,65536)
    domain._check_graph(db,[ref],roots)
    content,body = record.body['content'],record.body
    command = parse_installation_header(row['command_json'].encode())
    evidence = tuple(BlobRef.from_dict(value['blob_ref']) for value in content['evidence'])
    sources = tuple(BlobRef.from_dict(content[key]) for key in ('release_trust_blob_ref','release_context_blob_ref'))
    source_files = tuple((name,old._bounded_blob(domain,db,roots,blob,cap)) for (name,cap),blob in
        zip((('release-trust.json',16384),('installation-release-context.json',8192)),sources,strict=True))
    objects = tuple(old._bounded_blob(domain,db,roots,blob,CAPS[obj['role']]) for obj,blob in
        zip(command.as_dict()['objects'],evidence,strict=True))
    packet = ReleasePacket(command,objects)
    view = stage_view(domain,db,item)
    validate_retained_release(packet,source_files=source_files,stage=view,verified_ms=row['verified_ms'])
    review = parse_review_envelope(packet.objects[0]).as_dict()['payload']
    actor = EntityRef.from_dict(parse_canonical(row['actor_ref'].encode()))
    accounts = db.execute('SELECT actor_ref FROM owner_auth_accounts LIMIT 2').fetchall()
    require(len(accounts) == 1 and accounts[0][0] == row['actor_ref'],'unavailable')
    require(content == content_for(view,command,review,sources,evidence,row['verified_ms'])
        and row['request_id'] == item['ref'].id and row['extension_id'] == stage['row']['extension_id']
        and row['vault_id'] == roots.genesis.id and ref.id == stage['ref'].id
        and command.command_id == row['command_id'] and command.stage_ref == stage['ref']
        and command.input_digest == row['input_digest'] and row['http_status'] == 200
        and row['previous_head_hash'] == stage['head']['hash']
        and stage['row']['installed_ms'] <= row['verified_ms'] <= journal['control']['clock_floor_ms']
        and body['actor_ref'] == actor.as_dict() and body['access_policy_ref'] == roots.access_policy.as_dict()
        and body['retention_policy_ref'] == roots.retention_policy.as_dict()
        and body['parent_refs'] == [stage['ref'].as_dict()] and body['created_at_utc'] == instant(row['verified_ms'])
        and head == {**stage['head'],'revision':2,'installation_anchor_digest':ref.sha256,
            'hash':storage.digest('installation_heads',{**stage['head'],'revision':2,'installation_anchor_digest':ref.sha256})},'unavailable')
    args = (roots.genesis.id,ref.kind,ref.id,ref.version)
    actual_edges = {tuple(value) for value in db.execute('SELECT target_kind,target_id,target_version,target_sha256 FROM domain_edges WHERE vault_id=? AND source_kind=? AND source_id=? AND source_version=?',args)}
    expected_edges = {(value.kind,value.id,value.version,value.sha256) for value in (actor,roots.access_policy,roots.retention_policy,stage['ref'])}
    actual_blobs = {tuple(value) for value in db.execute('SELECT purpose,sha256,size FROM domain_record_blobs WHERE vault_id=? AND source_kind=? AND source_id=? AND source_version=?',args)}
    require(actual_edges == expected_edges and len(actual_edges) == 4
        and actual_blobs == {(b.purpose,b.sha256,b.size) for b in (*sources,*evidence)},'unavailable')
    event_row = db.execute('SELECT * FROM api_event_envelopes WHERE event_id=? LIMIT 2',(row['event_id'],)).fetchone()
    require(event_row is not None and type(event_row['envelope']) is bytes and len(event_row['envelope']) <= 8192,'unavailable')
    event = EventEnvelope.from_bytes(event_row['envelope'])
    expected = EventEnvelope.create(event_id=row['event_id'],sequence=event_row['sequence'],
        **event_fields(roots,ref,actor,command.command_id,row['verified_ms'],item))
    stage_event = db.execute('SELECT sequence FROM api_event_envelopes WHERE event_id=?',(stage['row']['event_id'],)).fetchone()
    require(event.body_bytes == expected.body_bytes and event_row['event_type'] == 'extension.verified'
        and event_row['vault_id'] == roots.genesis.id and stage_event is not None and stage_event[0] < event.sequence,'unavailable')
    reply = parse_installation_reply(row['reply_json'].encode())
    current_cursor = _decode_cursor(_event_cursor_in_transaction(db,vault_id=roots.genesis.id,
        sequence=event.sequence,event_types=EVENT_TYPES))
    frozen = _decode_cursor(reply['event_cursor'])
    require(frozen['generation'] <= current_cursor['generation']
        and {**frozen,'generation':current_cursor['generation']} == current_cursor
        and reply == reply_for(command,ref,content,reply['event_cursor']),'unavailable')
    return {'ref':ref,'record':record,'anchor':content,'head':head,'verification':row,'reply':reply}


def verify_installation_extensions(domain,db,roots,profile,journal):
    """Always run after historical loaders, including empty/pre-v6 stores."""
    # Legacy inspection issues no stage view; retained verification does.
    if journal['rows'].get('installation_verifications'):
        domain._assert_write_transaction(db)
    try:
        rows = journal['rows']
        verifications = rows.get('installation_verifications',())
        require(len(verifications) <= 1,'unavailable')
        events = db.execute("SELECT event_id FROM api_event_envelopes WHERE event_type='extension.verified' LIMIT 2").fetchall()
        require(len(events) == len(verifications) and {r[0] for r in events} == {r['event_id'] for r in verifications},'unavailable')
        seen = set()
        for item in journal['requests'].values():
            stage = item.get('installation')
            if stage is None:
                item['installation_current'] = None
                continue
            heads = [h for h in rows['installation_heads'] if h['request_id'] == item['ref'].id]
            require(len(heads) == 1,'unavailable')
            matches = [v for v in verifications if v['request_id'] == item['ref'].id]
            if matches:
                item['installation_current'] = _verify_one(domain,db,roots,profile,journal,item,matches[0],heads[0])
                seen.add(matches[0]['request_id'])
            else:
                require(heads[0] == stage['head'],'unavailable')
                item['installation_current'] = {**stage,'verification':None}
        require(seen == {row['request_id'] for row in verifications},'unavailable')
    except DeploymentPrepareError: raise
    except (ValueError,TypeError,KeyError,IndexError,AttributeError):
        raise DeploymentPrepareError('unavailable') from None
