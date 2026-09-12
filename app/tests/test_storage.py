import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.storage import ConflictError, Store


def test_blank_literal_revision_and_restart(tmp_path):
    store = Store(tmp_path / 'data')
    assert store.list_work() == []
    work = store.create_work('\n한국어 </textarea><script>literal</script>')
    assert work['revision'] == 1 and work['files'] == []
    changed = store.update_work(work['id'], '다른 업무', 1)
    assert changed['revision'] == 2
    assert store.get_revision(work['id'], 1) == work
    assert Store(tmp_path / 'data').get_work(work['id']) == changed
    assert store.list_work() == [changed]
    with pytest.raises(ConflictError):
        store.update_work(work['id'], 'lost update', 1)
    assert store.get_work(work['id']) == changed


def test_files_are_distinct_atomic_persistent_blobs(tmp_path):
    store = Store(tmp_path)
    work = store.create_work()
    content = '\n업무 원문'.encode()
    first = store.add_file(work['id'], '자료.txt', content, 'text/plain')
    second = store.add_file(work['id'], '자료.txt', b'other', 'text/plain')
    assert first['id'] != second['id']
    assert first['sha256'] == hashlib.sha256(content).hexdigest()
    assert first['text'] == content.decode() and first['read_status'] == 'read'
    restored = Store(tmp_path)
    assert restored.read_file(work['id'], first['id']) == (first, content)
    assert restored.get_revision(work['id'], 1)['files'] == []
    assert restored.get_revision(work['id'], 2)['files'] == [first]
    assert len(restored.get_work(work['id'])['files']) == 2
    other = store.create_work()
    with pytest.raises(KeyError):
        store.read_file(other['id'], first['id'])


@pytest.mark.parametrize('name', ['../a.txt', 'a/b.txt', 'a\\b.txt', '.', '..', '', 'a\n.txt', 'a\x00.txt'])
def test_unsafe_names_do_not_change_work(tmp_path, name):
    store = Store(tmp_path)
    work = store.create_work()
    before = store.events()
    with pytest.raises(ValueError):
        store.add_file(work['id'], name, b'abc', 'text/plain')
    assert store.get_work(work['id']) == work
    assert store.events() == before


def test_limits_and_unknown_formats_preserve_snapshot(tmp_path):
    store = Store(tmp_path)
    work = store.create_work('x' * 20_000)
    with pytest.raises(ValueError):
        store.update_work(work['id'], 'x' * 20_001, 1)
    with pytest.raises(ValueError):
        store.add_file(work['id'], 'big.txt', b'x' * (10 * 1024 * 1024 + 1), 'text/plain')
    with pytest.raises(ValueError):
        store.add_file(work['id'], 'app.exe', b'bad', 'application/octet-stream')
    for index in range(20):
        store.add_file(work['id'], f'{index}.txt', b'x', 'text/plain')
    with pytest.raises(ValueError):
        store.add_file(work['id'], '21.txt', b'x', 'text/plain')
    assert store.get_work(work['id'])['revision'] == 21


def test_metadata_events_and_private_files(tmp_path):
    folder = tmp_path / 'private'
    store = Store(folder)
    work = store.create_work('secret content auth-token')
    store.add_file(work['id'], 'input.txt', b'private bytes', 'text/plain')
    assert store.events()[0]['kind'] == 'session_started'
    assert all(event['work_id'] == work['id'] for event in store.events(work['id']))
    assert 'secret content' not in repr(store.events())
    assert 'private bytes' not in repr(store.events())
    assert folder.stat().st_mode & 0o077 == 0
    assert (folder / 'intake.sqlite3').stat().st_mode & 0o077 == 0


def test_corrupt_database_is_not_replaced(tmp_path):
    db = tmp_path / 'intake.sqlite3'
    db.write_bytes(b'not a database')
    with pytest.raises(sqlite3.DatabaseError):
        Store(tmp_path)
    assert db.read_bytes() == b'not a database'


def test_missing_references_and_failed_transaction_are_honest(tmp_path):
    store = Store(tmp_path)
    work = store.create_work('original')
    for operation in [lambda: store.get_work('missing'), lambda: store.get_revision(work['id'], 99),
                      lambda: store.update_work('missing', 'new', 1)]:
        with pytest.raises(KeyError):
            operation()
    with sqlite3.connect(tmp_path / 'intake.sqlite3') as db:
        db.execute("CREATE TRIGGER prevent_events BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(sqlite3.DatabaseError):
        store.add_file(work['id'], 'a.txt', b'atomic', 'text/plain')
    assert store.get_work(work['id']) == work


def test_concurrent_edits_never_overwrite_the_same_revision(tmp_path):
    store = Store(tmp_path)
    work = store.create_work()

    def edit(text):
        try:
            return store.update_work(work['id'], text, 1)
        except ConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(edit, ['one', 'two']))
    assert sum(result is not None for result in results) == 1
    assert store.get_work(work['id'])['revision'] == 2


def test_mime_is_not_trusted_and_database_symlink_is_rejected(tmp_path):
    store = Store(tmp_path / 'safe')
    work = store.create_work()
    file = store.add_file(work['id'], 'text.txt', b'literal', 'text/html')
    assert file['media_type'] == 'text/plain'
    linked = tmp_path / 'linked'
    linked.mkdir()
    (linked / 'intake.sqlite3').symlink_to(tmp_path / 'safe/intake.sqlite3')
    with pytest.raises(ValueError):
        Store(linked)


def test_stale_upload_does_not_change_files_revision_or_events(tmp_path):
    store = Store(tmp_path)
    first = store.create_work('first')
    latest = store.update_work(first['id'], 'other editor', first['revision'])
    before_events = store.events()
    with pytest.raises(ConflictError):
        store.add_file(first['id'], 'stale.txt', b'content', 'text/plain', expected_revision=first['revision'])
    assert store.get_work(first['id']) == latest
    assert store.events() == before_events
    file = store.add_file(first['id'], 'current.txt', b'current', 'text/plain', expected_revision=latest['revision'])
    assert store.get_work(first['id'])['files'] == [file]
    assert store.get_work(first['id'])['revision'] == latest['revision'] + 1


@pytest.mark.parametrize('revision', [True, False, '1', 1.0])
def test_upload_expected_revision_requires_integer_without_mutation(tmp_path, revision):
    store = Store(tmp_path)
    work = store.create_work()
    before_events = store.events()
    with pytest.raises(ValueError):
        store.add_file(work['id'], 'file.txt', b'text', 'text/plain', expected_revision=revision)
    assert store.get_work(work['id']) == work
    assert store.events() == before_events
