import json
import sqlite3
from dataclasses import dataclass, replace

import pytest

from app.model_catalog import ModelCatalog
from app.model_selection import (
    ModelSelection,
    ModelSelectionConflict,
    ModelSelectionError,
)
from app.storage import Store
from app.tests.test_model_catalog import CodexFixture


@dataclass(frozen=True)
class ClaudeModel:
    id: str
    display_name: str
    created_at: str
    max_input_tokens: int | None
    max_tokens: int | None
    _capabilities: dict | None

    @property
    def capabilities(self):
        return self._capabilities


@dataclass(frozen=True)
class ClaudeSnapshot:
    binding_id: str
    catalog_id: str
    fetched_at_ms: int
    max_age_ms: int
    credential_generation: int
    binding_generation: int
    request_epoch: int
    models: tuple


@dataclass(frozen=True)
class CodexAPIModel:
    model_id: str
    owned_by: str
    created: int
    shutdown_date: str | None = None
    capabilities: tuple = ()
    execution_eligible: bool = False


@dataclass(frozen=True)
class CodexAPISnapshot:
    provider: str
    mode: str
    binding_id: str
    catalog_id: str
    fetched_at_ms: int
    max_age_ms: int
    credential_generation: int
    binding_generation: int
    models: tuple


@dataclass(frozen=True)
class Binding:
    binding_id: str
    workspace_id: str | None = None
    project_id: str | None = None
    organization_id: str | None = None


class APISource:
    def __init__(self, snapshot):
        self.value = snapshot
        self.calls = []
        self.state = 'not_checked'

    def fetch_catalog(self, binding, *, explicit_action):
        self.calls.append((binding, explicit_action))
        self.state = 'catalog_current'
        return self.value

    def connection_state(self, binding):
        assert binding.binding_id
        return self.state


@dataclass
class MutableBinding:
    binding_id: str
    workspace_id: str | None = None


class WorkspaceChangingSource(APISource):
    def fetch_catalog(self, binding, *, explicit_action):
        result = super().fetch_catalog(binding, explicit_action=explicit_action)
        binding.workspace_id = 'workspace-changed-during-refresh'
        return result


def choice(catalog, provider, mode, model, effort=None):
    return {
        'provider': provider,
        'mode': mode,
        'catalog_id': catalog['catalog_id'],
        'model': model,
        'effort': effort,
    }


def configured_catalog(tmp_path, *, clock_ms=lambda: 1_789_000_000_100):
    store = Store(tmp_path)
    codex = CodexFixture(store)
    claude_binding = Binding('claude-binding-1', workspace_id='workspace-private')
    codex_api_binding = Binding(
        'codex-api-binding-1', project_id='project-private', organization_id='org-private'
    )
    claude = APISource(ClaudeSnapshot(
        binding_id=claude_binding.binding_id,
        catalog_id='adapter-claude-catalog',
        fetched_at_ms=1_789_000_000_000,
        max_age_ms=900_000,
        credential_generation=3,
        binding_generation=4,
        request_epoch=7,
        models=(ClaudeModel(
            'claude-dynamic', 'Claude Dynamic', '2026-09-08T00:00:00Z', 200_000, 8_000,
            {
                'text_input': {'supported': True},
                'image_input': {'supported': True},
                'effort': {
                    'supported': True,
                    'low': {'supported': True},
                    'high': {'supported': False},
                },
                'thinking': {
                    'supported': True,
                    'types': {
                        'adaptive': {'supported': True},
                        'enabled': {'supported': False},
                    },
                },
            },
        ),),
    ))
    codex_api = APISource(CodexAPISnapshot(
        provider='codex', mode='api', binding_id=codex_api_binding.binding_id,
        catalog_id='adapter-codex-api-catalog', fetched_at_ms=1_789_000_000_100,
        max_age_ms=900_000, credential_generation=5, binding_generation=6,
        models=(CodexAPIModel('codex-api-dynamic', 'openai', 1_789_000_000),),
    ))
    subject = ModelCatalog(store, codex, api_sources={
        ('claude', 'api'): (claude, claude_binding),
        ('codex', 'api'): (codex_api, codex_api_binding),
    }, clock_ms=clock_ms)
    return subject, claude, codex_api, store


def test_all_modes_are_lazy_then_use_only_dynamic_source_rows(tmp_path):
    subject, claude, codex_api, _ = configured_catalog(tmp_path)

    assert subject.snapshot('claude', 'api')['status'] == 'unqueried'
    assert subject.snapshot('codex', 'api')['status'] == 'unqueried'
    assert claude.calls == codex_api.calls == []

    claude_value = subject.refresh('claude', 'api')
    api_value = subject.refresh('codex', 'api')

    assert claude.calls[0][1] is True and codex_api.calls[0][1] is True
    assert [model['model'] for model in claude_value['models']] == ['claude-dynamic']
    assert [model['model'] for model in api_value['models']] == ['codex-api-dynamic']
    assert claude_value['provider'] == 'claude' and claude_value['mode'] == 'api'
    assert api_value['provider'] == 'codex' and api_value['mode'] == 'api'
    assert claude_value['auth_mode'] == api_value['auth_mode'] == 'api_key'
    assert claude_value['billing'] == api_value['billing'] == 'api'


def test_snapshot_binds_opaque_authority_epoch_raw_claims_and_digest(tmp_path):
    subject, _, _, _ = configured_catalog(tmp_path)

    value = subject.refresh('claude', 'api')

    assert value['binding_id'] == 'claude-binding-1'
    assert value['workspace_binding'].startswith('workspace-')
    assert 'workspace-private' not in repr(value)
    assert value['request_epoch'] == 1
    assert value['source_request_epoch'] == 7
    assert value['source_catalog_id'] == 'adapter-claude-catalog'
    assert value['credential_generation'] == 3
    assert value['binding_generation'] == 4
    assert value['capability_claims_digest'].startswith('sha256:')
    model = value['models'][0]
    assert model['raw_capability_claims']['image_input']['supported'] is True
    assert model['capability_claims_digest'].startswith('sha256:')
    assert subject.snapshot('claude', 'api') == value


def test_api_connection_rebind_invalidates_visible_catalog_and_old_choice(tmp_path):
    subject, claude, _, _ = configured_catalog(tmp_path)
    current = subject.refresh('claude', 'api')
    old_choice = choice(current, 'claude', 'api', 'claude-dynamic', 'low')
    assert subject.validate_choice(old_choice)['model'] == 'claude-dynamic'

    replacement_binding = Binding(
        'claude-binding-rotated', workspace_id='workspace-private'
    )
    replacement = APISource(replace(
        claude.value,
        binding_id=replacement_binding.binding_id,
        catalog_id='adapter-claude-catalog-rotated',
        request_epoch=1,
    ))
    subject.replace_api_source(
        'claude', 'api', (replacement, replacement_binding)
    )

    assert subject.snapshot('claude', 'api')['status'] == 'unqueried'
    with pytest.raises(ValueError, match='stale|binding'):
        subject.validate_choice(old_choice)
    refreshed = subject.refresh('claude', 'api')
    assert refreshed['binding_id'] == replacement_binding.binding_id

    subject.replace_api_source('claude', 'api', None)
    assert subject.snapshot('claude', 'api')['status'] == 'unavailable'
    with pytest.raises(ValueError):
        subject.replace_api_source('claude', 'subscription', None)


def test_capability_and_effort_unknown_fail_closed(tmp_path):
    subject, _, _, _ = configured_catalog(tmp_path)
    claude = subject.refresh('claude', 'api')
    codex_api = subject.refresh('codex', 'api')

    selected = subject.validate_choice(
        choice(claude, 'claude', 'api', 'claude-dynamic', 'low'),
        required_capabilities=('image_input',),
    )
    assert selected['capability_claims_digest'] == claude['models'][0]['capability_claims_digest']
    with pytest.raises(ValueError, match='unknown|unsupported'):
        subject.validate_choice(
            choice(claude, 'claude', 'api', 'claude-dynamic', 'high'),
        )
    with pytest.raises(ValueError, match='unknown|unsupported'):
        subject.validate_choice(
            choice(codex_api, 'codex', 'api', 'codex-api-dynamic'),
            required_capabilities=('text_input',),
        )
    with pytest.raises(ValueError, match='unknown|unsupported'):
        subject.validate_choice(
            choice(codex_api, 'codex', 'api', 'codex-api-dynamic', 'medium')
        )
    adaptive = {
        **choice(claude, 'claude', 'api', 'claude-dynamic', 'low'),
        'thinking': 'adaptive',
    }
    assert subject.validate_choice(adaptive)['thinking'] == 'adaptive'
    with pytest.raises(ValueError, match='unknown|unsupported'):
        subject.validate_choice({**adaptive, 'thinking': 'enabled'})


def test_persisted_capability_claim_or_projection_tampering_is_rejected(tmp_path):
    subject, _, _, store = configured_catalog(tmp_path)
    catalog = subject.refresh('codex', 'api')
    selected = choice(catalog, 'codex', 'api', 'codex-api-dynamic')
    with sqlite3.connect(store.path) as db:
        row = db.execute(
            'SELECT payload FROM model_catalogs_v2 WHERE id = ?', (catalog['catalog_id'],)
        ).fetchone()
        payload = json.loads(row[0])
        payload['models'][0]['capabilities']['text_input'] = True
        db.execute(
            'UPDATE model_catalogs_v2 SET payload = ? WHERE id = ?',
            (json.dumps(payload), catalog['catalog_id']),
        )
    with pytest.raises(ValueError, match='integrity'):
        subject.validate_choice(selected, required_capabilities=('text_input',))


def test_catalog_modes_and_bindings_cannot_be_crossed(tmp_path):
    subject, claude_source, _, _ = configured_catalog(tmp_path)
    claude = subject.refresh('claude', 'api')
    codex_subscription = subject.refresh('codex', 'subscription')

    with pytest.raises(ValueError):
        subject.validate_choice({
            **choice(claude, 'claude', 'api', 'claude-dynamic', 'low'),
            'mode': 'subscription',
        })
    with pytest.raises(ValueError):
        subject.validate_choice({
            **choice(codex_subscription, 'codex', 'subscription', 'gpt-fixture', 'low'),
            'catalog_id': claude['catalog_id'],
        })

    claude_source.value = ClaudeSnapshot(
        **{**claude_source.value.__dict__, 'binding_id': 'claude-binding-other'}
    )
    assert subject.refresh('claude', 'api')['status'] == 'error'
    assert subject.snapshot('claude', 'api') == claude

    claude_source.value = ClaudeSnapshot(
        **{**claude_source.value.__dict__, 'binding_id': 'claude-binding-1'}
    )
    claude_source.state = 'invalidated'
    with pytest.raises(ValueError, match='stale|binding'):
        subject.validate_choice(choice(claude, 'claude', 'api', 'claude-dynamic', 'low'))


def test_policy_precedence_and_frozen_run_choice_are_deterministic(tmp_path):
    subject, _, _, store = configured_catalog(tmp_path)
    claude = subject.refresh('claude', 'api')
    codex = subject.refresh('codex', 'subscription')
    work = store.create_work('모델 정책 업무')
    selections = ModelSelection(store, subject)
    default = choice(codex, 'codex', 'subscription', 'gpt-fixture', 'low')
    purpose = choice(codex, 'codex', 'subscription', 'gpt-second', 'high')
    agent = {
        **choice(claude, 'claude', 'api', 'claude-dynamic', 'low'),
        'thinking': 'adaptive',
    }

    policy = selections.save_policy(
        work['id'], 0, default=default,
        purpose_overrides={'draft': purpose},
        agent_overrides={'writer-agent': agent},
    )
    assert policy['version'] == 1
    assert selections.resolve(work['id'], 1, purpose='review', agent_id='other')['source'] == 'default'
    assert selections.resolve(work['id'], 1, purpose='draft', agent_id='other')['source'] == 'purpose'
    resolved = selections.resolve(
        work['id'], 1, purpose='draft', agent_id='writer-agent',
        required_capabilities=('image_input',),
    )
    assert resolved['source'] == 'agent' and resolved['selection']['provider'] == 'claude'
    assert resolved['selection']['thinking'] == 'adaptive'

    frozen = selections.freeze_for_run(
        'run-1', work['id'], 1, purpose='draft', agent_id='writer-agent',
        required_capabilities=('image_input',),
    )
    selections.save_policy(work['id'], 1, default=agent, purpose_overrides={}, agent_overrides={})
    assert selections.get_run_choice('run-1', purpose='draft', agent_id='writer-agent') == frozen
    assert frozen['required_capabilities'] == ['image_input']
    assert selections.freeze_for_run(
        'run-1', work['id'], 1, purpose='draft', agent_id='writer-agent',
        required_capabilities=('image_input',),
    ) == frozen
    with pytest.raises(ModelSelectionConflict):
        selections.freeze_for_run(
            'run-1', work['id'], 2, purpose='draft', agent_id='writer-agent'
        )
    with pytest.raises(ModelSelectionConflict):
        selections.freeze_for_run(
            'run-1', work['id'], 1, purpose='draft', agent_id='writer-agent',
            required_capabilities=('text_input',),
        )


@pytest.mark.parametrize('bad', [
    {'purpose_overrides': {'': {}}},
    {'purpose_overrides': {'draft/unsafe': {}}},
    {'agent_overrides': {'*': {}}},
    {'agent_overrides': {'agent': None}},
])
def test_invalid_policy_scope_or_choice_never_enters_history(tmp_path, bad):
    subject, _, _, store = configured_catalog(tmp_path)
    catalog = subject.refresh('codex', 'subscription')
    work = store.create_work('잘못된 정책')
    selections = ModelSelection(store, subject)
    arguments = {
        'default': choice(catalog, 'codex', 'subscription', 'gpt-fixture', 'low'),
        'purpose_overrides': {}, 'agent_overrides': {},
    }
    arguments.update(bad)
    with pytest.raises(ModelSelectionError):
        selections.save_policy(work['id'], 0, **arguments)
    assert selections.get_policy(work['id']) == {
        'version': 0, 'default': None, 'purpose_overrides': {}, 'agent_overrides': {}
    }


def test_catalog_does_not_contain_hard_coded_account_model_names():
    from pathlib import Path
    source = Path(ModelCatalog.__module__.replace('.', '/')).with_suffix('.py')
    text = source.read_text(encoding='utf-8')
    assert 'claude-dynamic' not in text
    assert 'gpt-fixture' not in text
    assert 'astra' not in text.casefold()
    assert 'fable' not in text.casefold()


def test_old_catalog_id_cannot_be_combined_with_model_added_only_later(tmp_path):
    subject, _, _, _ = configured_catalog(tmp_path)
    first = subject.refresh('codex', 'subscription')
    subject.codex.pages = [{
        'data': [{
            'id': 'new-only', 'model': 'new-only', 'displayName': 'New Only',
            'hidden': False, 'isDefault': True, 'defaultReasoningEffort': 'low',
            'supportedReasoningEfforts': [
                {'reasoningEffort': 'low', 'description': 'Low'},
            ],
            'inputModalities': ['text'],
        }],
        'nextCursor': None,
    }]
    subject.refresh('codex', 'subscription')

    with pytest.raises(ValueError, match='selected catalog'):
        subject.validate_choice(
            choice(first, 'codex', 'subscription', 'new-only', 'low')
        )


def test_api_catalog_validity_window_is_enforced_by_persisted_selection_layer(tmp_path):
    clock = {'now': 1_789_000_000_100}
    subject, claude, _, _ = configured_catalog(
        tmp_path, clock_ms=lambda: clock['now'],
    )
    claude.value = ClaudeSnapshot(
        **{**claude.value.__dict__, 'fetched_at_ms': clock['now'], 'max_age_ms': 10}
    )
    catalog = subject.refresh('claude', 'api')
    selected = choice(catalog, 'claude', 'api', 'claude-dynamic', 'low')
    assert subject.validate_choice(selected)['model'] == 'claude-dynamic'

    clock['now'] += 11
    with pytest.raises(ValueError, match='stale|validity'):
        subject.validate_choice(selected)

    claude.value = ClaudeSnapshot(**{
        **claude.value.__dict__,
        'catalog_id': 'adapter-claude-catalog-new',
        'fetched_at_ms': clock['now'],
        'request_epoch': 8,
    })
    current = subject.refresh('claude', 'api')
    revalidated = subject.validate_choice(selected)
    assert revalidated['catalog_id'] == catalog['catalog_id']
    assert revalidated['validated_catalog_id'] == current['catalog_id']


def test_catalog_refresh_between_resolve_and_insert_cannot_freeze_removed_model(
        tmp_path, monkeypatch):
    subject, _, _, store = configured_catalog(tmp_path)
    first = subject.refresh('codex', 'subscription')
    work = store.create_work('동결 경쟁')
    selections = ModelSelection(store, subject)
    policy = selections.save_policy(
        work['id'], 0,
        default=choice(first, 'codex', 'subscription', 'gpt-fixture', 'low'),
        purpose_overrides={}, agent_overrides={},
    )
    original_resolve = selections.resolve

    def resolve_then_replace(*args, **kwargs):
        resolved = original_resolve(*args, **kwargs)
        subject.codex.pages = [{
            'data': [{
                'id': 'replacement', 'model': 'replacement',
                'displayName': 'Replacement', 'hidden': False, 'isDefault': True,
                'defaultReasoningEffort': 'low',
                'supportedReasoningEfforts': [
                    {'reasoningEffort': 'low', 'description': 'Low'},
                ],
                'inputModalities': ['text'],
            }],
            'nextCursor': None,
        }]
        subject.refresh('codex', 'subscription')
        return resolved

    monkeypatch.setattr(selections, 'resolve', resolve_then_replace)
    with pytest.raises(ModelSelectionConflict, match='목록|연결'):
        selections.freeze_for_run(
            'run-race', work['id'], policy['version'],
            purpose='draft', agent_id='writer',
        )
    with sqlite3.connect(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM run_model_choices').fetchone()[0] == 0


def test_api_source_identity_and_duplicate_rows_fail_at_aggregation_boundary(tmp_path):
    subject, claude, codex_api, _ = configured_catalog(tmp_path)
    codex_api.value = replace(codex_api.value, provider='claude')
    assert subject.refresh('codex', 'api')['status'] == 'error'

    codex_api.value = replace(
        codex_api.value, provider='codex', mode='subscription',
    )
    assert subject.refresh('codex', 'api')['status'] == 'error'

    codex_api.value = replace(
        codex_api.value, mode='api',
        models=(codex_api.value.models[0], codex_api.value.models[0]),
    )
    assert subject.refresh('codex', 'api')['status'] == 'error'

    claude.value = replace(
        claude.value, models=(claude.value.models[0], claude.value.models[0]),
    )
    assert subject.refresh('claude', 'api')['status'] == 'error'


def test_duplicate_subscription_default_and_malformed_capability_claim_fail_closed(tmp_path):
    subject, claude, _, _ = configured_catalog(tmp_path)
    subject.codex.pages[1]['data'][0]['isDefault'] = True
    assert subject.refresh('codex', 'subscription')['status'] == 'error'

    bad_model = replace(
        claude.value.models[0],
        _capabilities={
            **claude.value.models[0].capabilities,
            'image_input': {'supported': 'yes'},
        },
    )
    claude.value = replace(claude.value, models=(bad_model,))
    assert subject.refresh('claude', 'api')['status'] == 'error'


def test_workspace_binding_change_during_api_refresh_is_rejected(tmp_path):
    store = Store(tmp_path)
    binding = MutableBinding('binding-1', 'workspace-before')
    snapshot = ClaudeSnapshot(
        binding_id='binding-1', catalog_id='source-catalog',
        fetched_at_ms=1_789_000_000_000, max_age_ms=900_000,
        credential_generation=1, binding_generation=1, request_epoch=1,
        models=(ClaudeModel(
            'dynamic', 'Dynamic', '2026-09-08T00:00:00Z', None, None,
            {'text_input': {'supported': True}},
        ),),
    )
    source = WorkspaceChangingSource(snapshot)
    subject = ModelCatalog(
        store, CodexFixture(store),
        api_sources={('claude', 'api'): (source, binding)},
        clock_ms=lambda: 1_789_000_000_100,
    )

    assert subject.refresh('claude', 'api')['status'] == 'error'
    assert subject.snapshot('claude', 'api')['status'] == 'unqueried'


def test_saved_choice_rejects_same_connection_id_in_a_different_workspace(tmp_path):
    subject, claude, _, _ = configured_catalog(tmp_path)
    catalog = subject.refresh('claude', 'api')
    claude.state = 'catalog_current'
    subject._api_sources[('claude', 'api')] = (
        claude, Binding('claude-binding-1', workspace_id='workspace-other')
    )

    with pytest.raises(ValueError, match='stale|binding|workspace'):
        subject.validate_choice(choice(catalog, 'claude', 'api', 'claude-dynamic', 'low'))


def test_local_and_source_request_epochs_remain_distinct_across_source_restart(tmp_path):
    subject, claude, codex_api, _ = configured_catalog(tmp_path)
    first = subject.refresh('claude', 'api')
    assert (first['request_epoch'], first['source_request_epoch']) == (1, 7)

    claude.value = replace(
        claude.value, catalog_id='adapter-claude-catalog-2', request_epoch=8,
    )
    second = subject.refresh('claude', 'api')
    assert (second['request_epoch'], second['source_request_epoch']) == (2, 8)
    # A provider adapter process may restart its in-memory epoch. The persisted
    # local epoch remains monotonic while preserving the exact source claim.
    claude.value = replace(
        claude.value, catalog_id='adapter-after-restart', request_epoch=1,
    )
    after_restart = subject.refresh('claude', 'api')
    assert (after_restart['request_epoch'], after_restart['source_request_epoch']) == (3, 1)

    first_api = subject.refresh('codex', 'api')
    codex_api.value = replace(codex_api.value, catalog_id='adapter-codex-api-catalog-2')
    second_api = subject.refresh('codex', 'api')
    assert first_api['source_request_epoch'] is second_api['source_request_epoch'] is None
    assert second_api['request_epoch'] == first_api['request_epoch'] + 1


def test_choice_cannot_claim_effort_or_thinking_absent_from_its_original_catalog(tmp_path):
    subject, claude, _, _ = configured_catalog(tmp_path)
    original = subject.refresh('claude', 'api')
    richer_claims = {
        **claude.value.models[0].capabilities,
        'effort': {
            'supported': True,
            'low': {'supported': True},
            'high': {'supported': True},
        },
        'thinking': {
            'supported': True,
            'types': {
                'adaptive': {'supported': True},
                'enabled': {'supported': True},
            },
        },
    }
    claude.value = replace(
        claude.value,
        catalog_id='adapter-claude-richer', request_epoch=8,
        models=(replace(claude.value.models[0], _capabilities=richer_claims),),
    )
    subject.refresh('claude', 'api')

    with pytest.raises(ValueError, match='selected catalog|unknown|unsupported'):
        subject.validate_choice(choice(original, 'claude', 'api', 'claude-dynamic', 'high'))
    with pytest.raises(ValueError, match='selected catalog|unknown|unsupported'):
        subject.validate_choice({
            **choice(original, 'claude', 'api', 'claude-dynamic', 'low'),
            'thinking': 'enabled',
        })


@pytest.mark.parametrize('corruption', ['state', 'payload', 'binding', 'workspace'])
def test_freeze_fence_rejects_changed_local_or_api_authority_without_fetch(
        tmp_path, monkeypatch, corruption):
    subject, claude, _, store = configured_catalog(tmp_path)
    catalog = subject.refresh('claude', 'api')
    initial_fetches = len(claude.calls)
    work = store.create_work('API 동결 경계')
    selections = ModelSelection(store, subject)
    policy = selections.save_policy(
        work['id'], 0,
        default=choice(catalog, 'claude', 'api', 'claude-dynamic', 'low'),
        purpose_overrides={}, agent_overrides={},
    )
    original_resolve = selections.resolve

    def resolve_then_change(*args, **kwargs):
        resolved = original_resolve(*args, **kwargs)
        if corruption == 'binding':
            claude.state = 'invalidated'
        elif corruption == 'workspace':
            subject._api_sources[('claude', 'api')] = (
                claude, Binding('claude-binding-1', workspace_id='workspace-other')
            )
        else:
            with store._connection() as db:
                if corruption == 'state':
                    db.execute('''UPDATE model_catalog_state_v2 SET status = 'error'
                        WHERE provider = 'claude' AND mode = 'api' ''')
                else:
                    db.execute('UPDATE model_catalogs_v2 SET payload = ? WHERE id = ?',
                               ('not-json', catalog['catalog_id']))
        return resolved

    monkeypatch.setattr(selections, 'resolve', resolve_then_change)
    with pytest.raises(ModelSelectionConflict, match='목록|연결'):
        selections.freeze_for_run(
            f'run-{corruption}', work['id'], policy['version'],
            purpose='draft', agent_id='writer',
        )
    assert len(claude.calls) == initial_fetches
    with sqlite3.connect(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM run_model_choices').fetchone()[0] == 0


def test_freeze_fence_rechecks_original_catalog_when_current_catalog_is_newer(
        tmp_path, monkeypatch):
    subject, claude, _, store = configured_catalog(tmp_path)
    original = subject.refresh('claude', 'api')
    claude.value = replace(
        claude.value, catalog_id='adapter-current', request_epoch=8,
    )
    subject.refresh('claude', 'api')
    work = store.create_work('원본 카탈로그 무결성')
    selections = ModelSelection(store, subject)
    policy = selections.save_policy(
        work['id'], 0,
        default=choice(original, 'claude', 'api', 'claude-dynamic', 'low'),
        purpose_overrides={}, agent_overrides={},
    )
    original_resolve = selections.resolve

    def resolve_then_corrupt_original(*args, **kwargs):
        resolved = original_resolve(*args, **kwargs)
        with store._connection() as db:
            db.execute('UPDATE model_catalogs_v2 SET payload = ? WHERE id = ?',
                       ('not-json', original['catalog_id']))
        return resolved

    monkeypatch.setattr(selections, 'resolve', resolve_then_corrupt_original)
    with pytest.raises(ModelSelectionConflict, match='목록|연결'):
        selections.freeze_for_run(
            'run-original-corrupt', work['id'], policy['version'],
            purpose='draft', agent_id='writer',
        )


@pytest.mark.parametrize('surface', ['snapshot', 'validate', 'freeze'])
def test_valid_old_payload_cannot_be_pasted_into_the_current_catalog_row(
        tmp_path, surface):
    subject, claude, _, store = configured_catalog(tmp_path)
    original = subject.refresh('claude', 'api')
    work = store.create_work('카탈로그 행 바꿔치기')
    selections = ModelSelection(store, subject)
    policy = selections.save_policy(
        work['id'], 0,
        default=choice(original, 'claude', 'api', 'claude-dynamic', 'low'),
        purpose_overrides={}, agent_overrides={},
    )
    replacement = replace(
        claude.value.models[0], id='new-only', display_name='New Only',
    )
    claude.value = replace(
        claude.value, catalog_id='adapter-current-new-only', request_epoch=8,
        models=(replacement,),
    )
    current = subject.refresh('claude', 'api')
    with store._connection() as db:
        old_payload = db.execute(
            'SELECT payload FROM model_catalogs_v2 WHERE id=?',
            (original['catalog_id'],),
        ).fetchone()['payload']
        db.execute(
            'UPDATE model_catalogs_v2 SET payload=? WHERE id=?',
            (old_payload, current['catalog_id']),
        )

    selected = choice(original, 'claude', 'api', 'claude-dynamic', 'low')
    if surface == 'snapshot':
        assert subject.snapshot('claude', 'api')['status'] == 'error'
    elif surface == 'validate':
        with pytest.raises(ValueError, match='integrity|stale|changed|match|payload'):
            subject.validate_choice(selected)
    else:
        with pytest.raises((ModelSelectionError, ModelSelectionConflict)):
            selections.freeze_for_run(
                'run-cut-and-paste', work['id'], policy['version'],
                purpose='draft', agent_id='writer',
            )


@pytest.mark.parametrize('surface', ['snapshot', 'validate', 'freeze'])
def test_current_catalog_pointer_cannot_be_rolled_back_to_an_old_valid_row(
        tmp_path, surface):
    subject, claude, _, store = configured_catalog(tmp_path)
    original = subject.refresh('claude', 'api')
    work = store.create_work('카탈로그 포인터 롤백')
    selections = ModelSelection(store, subject)
    policy = selections.save_policy(
        work['id'], 0,
        default=choice(original, 'claude', 'api', 'claude-dynamic', 'low'),
        purpose_overrides={}, agent_overrides={},
    )
    claude.value = replace(
        claude.value, catalog_id='adapter-new-head', request_epoch=8,
    )
    subject.refresh('claude', 'api')
    with store._connection() as db:
        db.execute(
            "UPDATE model_catalog_state_v2 SET status='ready',catalog_id=? "
            "WHERE provider='claude' AND mode='api'",
            (original['catalog_id'],),
        )

    selected = choice(original, 'claude', 'api', 'claude-dynamic', 'low')
    if surface == 'snapshot':
        assert subject.snapshot('claude', 'api')['status'] == 'error'
    elif surface == 'validate':
        with pytest.raises(ValueError, match='stale|changed|missing'):
            subject.validate_choice(selected)
    else:
        with pytest.raises((ModelSelectionError, ModelSelectionConflict)):
            selections.freeze_for_run(
                'run-pointer-rollback', work['id'], policy['version'],
                purpose='draft', agent_id='writer',
            )
