from types import SimpleNamespace
from threading import Event

import pytest

from app import codex_understanding
from app.generation_profiles import GenerationPurpose, profile_for
from app.tests.test_codex_environmentless import RecordingRPC, _selection


@pytest.fixture
def isolated_rpc(tmp_path, monkeypatch):
    created = []

    def factory(*args, **kwargs):
        rpc = RecordingRPC(*args, **kwargs)
        created.append(rpc)
        return rpc

    monkeypatch.setattr(codex_understanding, 'find_codex', lambda: '/test/codex')
    monkeypatch.setattr(
        codex_understanding,
        '_generation_environment',
        lambda: {'CODEX_EXEC_SERVER_URL': 'none'},
    )
    return SimpleNamespace(
        store=SimpleNamespace(data_dir=tmp_path / 'data'),
        factory=factory,
        created=created,
    )


def test_understanding_wrapper_keeps_its_profile_and_return_contract(isolated_rpc):
    subject = codex_understanding.CodexUnderstandingModel(
        isolated_rpc.store,
        rpc_factory=isolated_rpc.factory,
        version_reader=lambda _path: True,
    )
    profile = profile_for(GenerationPurpose.WORK_UNDERSTANDING)
    assert subject.instruction_profile == profile
    schema = {'type': 'object', 'properties': {'summary': {'type': 'string'}}}

    result = subject.generate(
        'synthetic intake', schema, Event(), selection=_selection(),
    )

    assert result == {'text': '{"summary":"ok"}', 'model': _selection()['model']}
    rpc = isolated_rpc.created[0]
    thread = dict(rpc.calls)['thread/start']
    turn = dict(rpc.calls)['turn/start']
    assert thread['baseInstructions'] == profile.base_instructions
    assert thread['developerInstructions'] == profile.developer_instructions
    assert turn['outputSchema'] == schema
    assert turn['input'] == [{'type': 'text', 'text': 'synthetic intake'}]
    assert rpc.closed
