"""One authenticated, offline staged-to-verified installation transition."""
import sqlite3
import time

from ..deployment import prepare_records as old
from ..deployment import prepare_storage as storage
from ..deployment.installation_release_sources import InstallationReleaseSource
from ..deployment.prepare_contracts import DeploymentPrepareError
from ..deployment.prepare_lifecycle import instant
from ..deployment.prepare_service import PersistentDeploymentPrepare
from ..domain.public_events import _append_event_in_transaction,_event_cursor_in_transaction
from ..domain.refs import EntityRef,canonical_json,parse_canonical,uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore,StorageError,_writer
from ..services.owner_auth import OwnerAuthError,PersistentOwnerAuthority
from . import provider_installation_records as records
from .provider_installation_contracts import InstallationError,ReleasePacket,require,parse_installation_reply
from .provider_installation_evidence import evaluate_release,_authenticate_review


def _mapped(error):
    code = getattr(error,'code','unavailable')
    return InstallationError(code if code in ('invalid_input','unauthenticated','access_denied','not_found',
        'conflict','too_large','capacity','unavailable') else 'unavailable')


class PersistentProviderInstallation:
    def __init__(self,domain_store,owner_authority,*,prepare_service,release_source):
        require(type(domain_store) is DomainStore and type(owner_authority) is PersistentOwnerAuthority
            and type(prepare_service) is PersistentDeploymentPrepare
            and prepare_service._domain is domain_store and prepare_service._owner is owner_authority
            and owner_authority._domain is domain_store
            and (release_source is None or type(release_source) is InstallationReleaseSource
                and release_source._provider_context is prepare_service._provider_context),'unavailable')
        self._domain,self._owner,self._prepare,self._source = domain_store,owner_authority,prepare_service,release_source
        try:
            with _writer(),self._domain._connection(write=True) as db:
                self._prepare._journal(db)
                require(storage._layout(db) is storage._V6,'unavailable')
        except InstallationError: raise
        except (ValueError,sqlite3.Error,StorageError,OSError): raise InstallationError('unavailable') from None

    def _authenticate(self,request,db,*,read=False):
        require(getattr(request,'method',None) in (('GET','HEAD') if read else ('POST',)),'access_denied')
        try:
            actor = self._prepare._authenticate(request,db,read=read)
            return self._prepare._actor_ref(db,actor)
        except (OwnerAuthError,DeploymentPrepareError) as error: raise _mapped(error) from None

    @staticmethod
    def _select(journal,stage_ref):
        matches = [item for item in journal['requests'].values() if item.get('installation') is not None
            and item['installation']['ref'] == stage_ref and item.get('provider_row') is not None]
        require(len(matches) == 1,'conflict')
        return matches[0]

    @staticmethod
    def _replay(journal,actor,command):
        matches = [row for row in journal['rows']['installation_verifications'] if row['command_id'] == command.command_id]
        if not matches: return None
        row = matches[0]
        require(row['actor_ref'] == canonical_json(actor.as_dict()).decode()
            and row['command_json'] == command.content_bytes.decode() and row['input_digest'] == command.input_digest,'conflict')
        return parse_installation_reply(row['reply_json'].encode())

    @staticmethod
    def _now(journal,item):
        now = time.time_ns()//1000000
        require(type(now) is int and 0 <= now <= 253402300799999
            and now >= journal['control']['clock_floor_ms']
            and now >= item['installation']['row']['installed_ms'],'unavailable')
        return now

    def execute(self,authenticated_request,packet):
        try:
            require(type(packet) is ReleasePacket)
            ReleasePacket(packet.header,packet.objects)
            command = packet.header
            with _writer(),self._domain._connection(write=True) as db:
                actor = self._authenticate(authenticated_request,db)
                journal = self._prepare._journal(db)
                replay = self._replay(journal,actor,command)
                if replay is not None: return replay
                item = self._select(journal,command.stage_ref)
                require(item['installation_current']['ref'] == command.stage_ref,'conflict')
                require(not journal['rows']['installation_verifications'],'capacity')
                require(self._source is not None,'unavailable')
                source_files = self._source.read_current()
                stage = records.stage_view(self._domain,db,item)
                now = self._now(journal,item)
            # No writes precede complete exact signed closure admission.
            assessment = evaluate_release(packet,source_files=source_files,stage=stage,now_ms=now)
            sources = tuple(self._domain.put_blob(raw,purpose='operational') for _,raw in assessment.source_files)
            evidence = tuple(self._domain.put_blob(raw,purpose='operational') for _,raw in assessment.evidence)
            with _writer(),self._domain._connection(write=True) as db:
                final_actor = self._authenticate(authenticated_request,db)
                require(final_actor == actor,'conflict')
                journal = self._prepare._journal(db)
                replay = self._replay(journal,actor,command)
                if replay is not None: return replay
                item = self._select(journal,command.stage_ref)
                require(item['installation_current']['ref'] == command.stage_ref
                    and item['installation_current']['head'] == stage.current_head,'conflict')
                require(not journal['rows']['installation_verifications'],'capacity')
                require(self._source.read_current() == assessment.source_files,'unavailable')
                final_stage = records.stage_view(self._domain,db,item)
                require(final_stage == stage,'conflict')
                final_now = self._now(journal,item)
                review = _authenticate_review(packet,assessment.source_files,final_stage,final_now)
                facts = parse_canonical(assessment.facts_bytes)
                require(review['subject'] == facts['subject'] and review['issued_at_ms'] == facts['issued_at_ms']
                    and review['evidence_policy_sha256'] == facts['evidence_policy_sha256'],'conflict')
                roots = self._domain._read_roots(db)
                for blob,raw in zip((*sources,*evidence),
                    (*[raw for _,raw in assessment.source_files],*[raw for _,raw in assessment.evidence]),strict=True):
                    require(old._bounded_blob(self._domain,db,roots,blob,len(raw)) == raw,'unavailable')
                self._prepare._floor(db,journal['control'],final_now)
                content = records.content_for(final_stage,command,review,sources,evidence,final_now)
                record = ImmutableRecord.create(kind='extension_installation',id=command.stage_ref.id,version=2,
                    created_at_utc=instant(final_now),actor_ref=actor,parent_refs=(command.stage_ref,),purpose='operational',
                    access_policy_ref=roots.access_policy,retention_policy_ref=roots.retention_policy,content=content)
                self._domain._put_in_transaction(db,record)
                event = _append_event_in_transaction(db,**records.event_fields(roots,record.ref,actor,command.command_id,final_now,item))
                cursor = _event_cursor_in_transaction(db,vault_id=roots.genesis.id,sequence=event.sequence,event_types=records.EVENT_TYPES)
                reply = records.reply_for(command,record.ref,content,cursor)
                raw_reply = canonical_json(reply)
                parse_installation_reply(raw_reply)
                storage.insert(db,'installation_verifications',{'request_id':item['ref'].id,
                    'extension_id':content['extension_id'],'vault_id':roots.genesis.id,'kind':record.ref.kind,
                    'installation_id':record.ref.id,'version':2,'anchor_digest':record.ref.sha256,
                    'command_id':command.command_id,'actor_ref':canonical_json(actor.as_dict()).decode(),
                    'command_json':command.content_bytes.decode(),'input_digest':command.input_digest,
                    'reply_json':raw_reply.decode(),'http_status':200,'event_id':event.event_id,
                    'verified_ms':final_now,'previous_head_hash':item['installation']['head']['hash']})
                storage._advance_installation_head(db,item['installation']['head'],record.ref.sha256)
                self._prepare._journal(db)
                return reply
        except InstallationError: raise
        except (OwnerAuthError,DeploymentPrepareError) as error: raise _mapped(error) from None
        except (sqlite3.Error,StorageError,ValueError,TypeError,KeyError,OSError):
            raise InstallationError('unavailable') from None

    def read(self,authenticated_request,command_id):
        try: uuid_string(command_id)
        except ValueError: raise InstallationError('invalid_input') from None
        try:
            with _writer(),self._domain._connection(write=True) as db:
                actor = self._authenticate(authenticated_request,db,read=True)
                journal = self._prepare._journal(db)
                rows = [row for row in journal['rows']['installation_verifications'] if row['command_id'] == command_id]
                require(len(rows) == 1,'not_found')
                require(rows[0]['actor_ref'] == canonical_json(actor.as_dict()).decode(),'access_denied')
                return parse_installation_reply(rows[0]['reply_json'].encode())
        except InstallationError: raise
        except (OwnerAuthError,DeploymentPrepareError) as error: raise _mapped(error) from None
        except (sqlite3.Error,StorageError,ValueError,TypeError,KeyError,OSError): raise InstallationError('unavailable') from None

    def rehydrate(self,db,installation_ref):
        self._domain._assert_write_transaction(db)
        require(type(installation_ref) is EntityRef and installation_ref.kind == 'extension_installation'
            and installation_ref.version == 2,'invalid_input')
        journal = self._prepare._journal(db)
        matches = [item['installation_current'] for item in journal['requests'].values()
            if item.get('installation_current') is not None and item['installation_current']['ref'] == installation_ref]
        require(len(matches) == 1 and matches[0].get('verification') is not None,'not_found')
        item = matches[0]
        result = object.__new__(records.VerifiedInstallationView)
        for name,value in {'ref':installation_ref,'stage_ref':EntityRef.from_dict(item['anchor']['stage_ref']),
            'record_bytes':item['record'].body_bytes,'head_bytes':canonical_json(item['head'])}.items(): object.__setattr__(result,name,value)
        return result
