import importlib.util
import json
import threading
import time
from uuid import uuid4

import pytest

from app.storage import ConflictError, Store
from app.understanding import Understanding


def module():
    assert importlib.util.find_spec('app.model_selection'), 'Versioned model selection is missing'
    return importlib.import_module('app.model_selection')


def choice(model='model-a', effort='low', catalog_id='catalog-1'):
    return {
        'provider': 'codex', 'mode': 'subscription', 'model': model,
        'effort': effort, 'catalog_id': catalog_id,
    }


class Catalog:
    def __init__(self):
        self.valid = True

    def validate_choice(self, value):
        if not self.valid or value not in [choice(), choice('model-b')]:
            raise ValueError('Not in current catalog')
        return {**value, 'display_name': value['model'], 'fetched_at': '2026-09-07T00:00:00+00:00'}


def test_selection_versions_are_durable_and_do_not_change_work_input(tmp_path):
    store, catalog = Store(tmp_path), Catalog()
    work = store.create_work('  내 원 설명\n')
    settings = module().ModelSelection(store, catalog)
    assert settings.get(work['id']) == {'version': 0, 'selection': None}
    first = settings.save(work['id'], 0, choice())
    assert first['version'] == 1 and first['selection']['model'] == 'model-a'
    assert store.get_work(work['id']) == work
    second = settings.save(work['id'], 1, choice('model-b'))
    assert second['version'] == 2
    reopened = module().ModelSelection(store, catalog)
    assert reopened.get(work['id']) == second
    assert reopened.get(work['id'], 1) == first
    assert [e['kind'] for e in store.events(work['id'])][-2:] == ['model_selection_saved'] * 2


def test_stale_writer_and_other_work_cannot_overwrite_selection(tmp_path):
    store = Store(tmp_path)
    work, other = store.create_work('a'), store.create_work('b')
    settings = module().ModelSelection(store, Catalog())
    first = settings.save(work['id'], 0, choice())
    with pytest.raises(ConflictError):
        settings.save(work['id'], 0, choice('model-b'))
    assert settings.get(work['id']) == first
    assert settings.get(other['id'])['selection'] is None
    with pytest.raises(KeyError):
        settings.save('not-a-work', 0, choice())


def test_request_records_latest_catalog_validation_without_mutating_saved_choice(tmp_path):
    class RefreshableCatalog(Catalog):
        validation_id = 'catalog-1'

        def validate_choice(self, value):
            return {**super().validate_choice(value),
                    'validated_catalog_id': self.validation_id}

    store, catalog = Store(tmp_path), RefreshableCatalog()
    work = store.create_work('원 업무')
    settings = module().ModelSelection(store, catalog)
    original = settings.save(work['id'], 0, choice())
    catalog.validation_id = 'catalog-2'
    with store._connection() as db:
        frozen = settings.for_request(db, work['id'], 1)
    assert frozen['version'] == 1
    assert frozen['selection']['validated_catalog_id'] == 'catalog-2'
    assert settings.get(work['id']) == original


@pytest.mark.parametrize('value', [choice('not-advertised'), choice(effort='ultra'),
                                 {**choice(), 'mode': 'api'}, {**choice(), 'extra': 'x'}, None])
def test_invalid_selection_cannot_enter_history(tmp_path, value):
    store = Store(tmp_path)
    work = store.create_work('a')
    settings = module().ModelSelection(store, Catalog())
    before = store.events(work['id'])
    with pytest.raises(ValueError):
        settings.save(work['id'], 0, value)
    assert settings.get(work['id']) == {'version': 0, 'selection': None}
    assert store.events(work['id']) == before


class Model:
    def __init__(self):
        self.selections = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def generate(self, prompt, schema, cancel, *, selection):
        self.selections.append(selection)
        self.entered.set()
        assert self.release.wait(2)
        return {'model': selection['model'], 'text': json.dumps({
            'summary': {'text': '원 업무', 'evidence': [{'source_id': 'work-description', 'quote': '원 업무'}]},
            'deliverables': [], 'constraints': [], 'open_questions': [], 'assumptions': []})}


def settled(service, work_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        records = service.list_for(work_id)
        if records and records[-1]['status'] not in {'queued', 'running'}:
            return records[-1]
        time.sleep(.01)
    pytest.fail('Request failed to finish')


def test_understanding_freezes_selection_and_idempotency_includes_settings(tmp_path):
    store = Store(tmp_path)
    work = store.create_work('원 업무')
    settings = module().ModelSelection(store, Catalog())
    settings.save(work['id'], 0, choice())
    model, key = Model(), str(uuid4())
    with Understanding(store, lambda: model, selection_store=settings) as service:
        record = service.create(work['id'], 1, key, True, model_selection_version=1)
        assert model.entered.wait(2)
        assert record['model_selection_version'] == 1
        assert record['model_selection']['model'] == 'model-a'
        settings.save(work['id'], 1, choice('model-b'))
        with pytest.raises(ValueError):
            service.create(work['id'], 1, key, True, model_selection_version=2)
        assert service.create(work['id'], 1, key, True, model_selection_version=1)['id'] == record['id']
        model.release.set()
        result = settled(service, work['id'])
        assert result['model'] == 'model-a'
        assert model.selections[0]['model'] == 'model-a'
        with store._connection() as db:
            audit = json.loads(db.execute('SELECT input_json FROM understanding_requests').fetchone()[0])
        assert audit['model_selection']['model'] == 'model-a'
        assert audit['model_selection_version'] == 1


def test_missing_stale_or_unavailable_selection_never_starts_model(tmp_path):
    store, catalog = Store(tmp_path), Catalog()
    work = store.create_work('원 업무')
    settings = module().ModelSelection(store, catalog)
    constructed = []
    with Understanding(store, lambda: constructed.append(True), selection_store=settings) as service:
        for version in [None, 0, True, -1]:
            with pytest.raises(ValueError):
                service.create(work['id'], 1, str(uuid4()), True, model_selection_version=version)
        settings.save(work['id'], 0, choice())
        settings.save(work['id'], 1, choice('model-b'))
        with pytest.raises(ConflictError):
            service.create(work['id'], 1, str(uuid4()), True, model_selection_version=1)
        catalog.valid = False
        with pytest.raises(ValueError):
            service.create(work['id'], 1, str(uuid4()), True, model_selection_version=2)
        assert constructed == []
        assert service.list_for(work['id']) == []


def test_actual_model_mismatch_is_not_a_successful_selected_execution(tmp_path):
    class WrongModel(Model):
        def generate(self, *args, **kwargs):
            return {**super().generate(*args, **kwargs), 'model': 'silently-substituted-model'}
    store = Store(tmp_path)
    work = store.create_work('원 업무')
    settings = module().ModelSelection(store, Catalog())
    settings.save(work['id'], 0, choice())
    model = WrongModel()
    model.release.set()
    with Understanding(store, lambda: model, selection_store=settings) as service:
        service.create(work['id'], 1, str(uuid4()), True, model_selection_version=1)
        record = settled(service, work['id'])
        assert record['status'] == 'failed' and record['reason'] == 'model_mismatch'
        assert record['result'] is None and record['model'] == 'silently-substituted-model'
        assert record['model_selection']['model'] == 'model-a'
