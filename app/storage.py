"""SQLite owns intake bytes, metadata, revisions and metadata-only events."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
from threading import RLock
import unicodedata
from urllib.parse import quote
from uuid import uuid4

from .ingestion import MAX_FILE_BYTES, extract


class ConflictError(ValueError):
    """The caller edited a revision that is no longer current."""


class StorageIntegrityError(ValueError):
    """A registered immutable storage projection cannot be verified."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _text(value):
    if not isinstance(value, str) or len(value) > 20_000:
        raise ValueError('Text must be a string of at most 20,000 characters')


class Store:
    def __init__(self, data_dir: Path, *, _verified_directory_fd=None):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / 'intake.sqlite3'
        self._verified_handle_lock = RLock()
        self._verified_directory_fd = None
        self._verified_database_fd = None
        self._verified_identity_required = _verified_directory_fd is not None
        self._verified_expected_identity = None
        if _verified_directory_fd is None:
            if self.data_dir.is_symlink():
                raise ValueError('Storage directory cannot be a symlink')
            self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.data_dir.chmod(0o700)
            if self.path.is_symlink():
                raise ValueError('Database cannot be a symlink')
            descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(descriptor)
            self.path.chmod(0o600)
            with self._connection() as db:
                self._initialize(db)
            return

        if type(_verified_directory_fd) is not int or _verified_directory_fd < 0:
            raise TypeError('Verified storage directory descriptor is invalid')
        if not hasattr(os, 'O_NOFOLLOW'):
            raise RuntimeError('This platform cannot retain a no-follow storage identity')
        directory_fd = os.dup(_verified_directory_fd)
        database_fd = None
        try:
            directory = os.fstat(directory_fd)
            if (not stat.S_ISDIR(directory.st_mode)
                    or directory.st_uid != os.getuid()):
                raise ValueError('Storage directory identity is unsafe')
            self._assert_verified_identity(directory_fd)
            os.fchmod(directory_fd, 0o700)
            self._assert_verified_identity(directory_fd)

            flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
            if hasattr(os, 'O_CLOEXEC'):
                flags |= os.O_CLOEXEC
            try:
                database_fd = os.open(
                    'intake.sqlite3', flags, 0o600, dir_fd=directory_fd,
                )
            except OSError as exc:
                raise ValueError('Database identity is unsafe') from exc
            database = os.fstat(database_fd)
            if (not stat.S_ISREG(database.st_mode) or database.st_nlink != 1
                    or database.st_uid != os.getuid()):
                raise ValueError('Database identity is unsafe')
            os.fchmod(database_fd, 0o600)
            self._assert_verified_identity(directory_fd, database_fd)
            self._verified_expected_identity = (
                directory.st_dev, directory.st_ino,
                database.st_dev, database.st_ino,
            )

            # Transfer the capabilities to this Store.  Every later connection made by
            # a server-created Store borrows duplicates, so the exact directory/database
            # identity survives all follow-up startup constructors and the app lifetime.
            with self._verified_handle_lock:
                self._verified_directory_fd = directory_fd
                self._verified_database_fd = database_fd
            directory_fd = database_fd = None

            # The file has already been created through the retained dirfd. SQLite is
            # forbidden from creating by pathname and the connected identity is checked
            # before any mutable PRAGMA, schema statement or startup event.
            with self._connection() as db:
                self._initialize(db)
        except BaseException:
            self.close_verified_handles()
            raise
        finally:
            if database_fd is not None:
                os.close(database_fd)
            if directory_fd is not None:
                os.close(directory_fd)

    @staticmethod
    def _initialize(db):
        db.executescript('''
            CREATE TABLE IF NOT EXISTS works (
                id TEXT PRIMARY KEY, text TEXT NOT NULL, revision INTEGER NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
                metadata TEXT NOT NULL, data BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS revisions (
                work_id TEXT NOT NULL REFERENCES works(id), revision INTEGER NOT NULL,
                snapshot TEXT NOT NULL, PRIMARY KEY(work_id, revision));
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL, work_id TEXT,
                created_at TEXT NOT NULL, metadata TEXT NOT NULL);
        ''')
        Store._event(db, 'session_started', None, {})

    def _assert_verified_identity(self, directory_fd, database_fd=None,
                                  connected_path=None):
        try:
            expected_directory = os.fstat(directory_fd)
            visible_directory = os.stat(self.data_dir, follow_symlinks=False)
        except OSError as exc:
            raise ValueError('Storage directory identity changed') from exc
        if (not stat.S_ISDIR(visible_directory.st_mode)
                or (expected_directory.st_dev, expected_directory.st_ino)
                != (visible_directory.st_dev, visible_directory.st_ino)):
            raise ValueError('Storage directory identity changed')
        if database_fd is None:
            return
        try:
            expected_database = os.fstat(database_fd)
            held_database = os.stat(
                'intake.sqlite3', dir_fd=directory_fd, follow_symlinks=False,
            )
            visible_database = os.stat(self.path, follow_symlinks=False)
            connected_database = (
                visible_database if connected_path is None
                else os.stat(connected_path, follow_symlinks=False)
            )
        except OSError as exc:
            raise ValueError('Database identity changed') from exc
        identity = (expected_database.st_dev, expected_database.st_ino)
        if (not all(stat.S_ISREG(item.st_mode) for item in (
                expected_database, held_database, visible_database,
                connected_database))
                or any((item.st_dev, item.st_ino) != identity for item in (
                    held_database, visible_database, connected_database))):
            raise ValueError('Database identity changed')

    @contextmanager
    def _borrow_verified_handles(self):
        """Borrow stable descriptor duplicates, or ``None`` for a legacy Store.

        Closing the retained handles cannot invalidate a connection already in flight;
        conversely, a verified Store whose capability was closed never falls back to an
        unverified pathname connection.
        """
        pair = None
        with self._verified_handle_lock:
            directory_fd = self._verified_directory_fd
            database_fd = self._verified_database_fd
            if (directory_fd is None) != (database_fd is None):
                raise ValueError('Verified storage identity is incomplete')
            if directory_fd is None:
                if self._verified_identity_required:
                    raise ValueError('Verified storage identity is closed')
            else:
                duplicate_directory = os.dup(directory_fd)
                try:
                    duplicate_database = os.dup(database_fd)
                except BaseException:
                    owned_directory = duplicate_directory
                    duplicate_directory = None
                    try:
                        os.close(owned_directory)
                    except BaseException:
                        pass
                    raise
                pair = (duplicate_directory, duplicate_database)
        primary = None
        try:
            yield pair
        except BaseException as exc:
            primary = exc
            raise
        finally:
            if pair is not None:
                owned_pair = pair
                pair = None
                cleanup_error = None
                for descriptor in reversed(owned_pair):
                    try:
                        os.close(descriptor)
                    except BaseException as exc:
                        if primary is None and cleanup_error is None:
                            cleanup_error = exc
                if primary is None and cleanup_error is not None:
                    raise cleanup_error

    def close_verified_handles(self):
        """Idempotently revoke the server-retained filesystem capabilities."""
        with self._verified_handle_lock:
            pair = (self._verified_directory_fd, self._verified_database_fd)
            self._verified_directory_fd = None
            self._verified_database_fd = None
        for descriptor in reversed(pair):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def reopen_verified_handles(self):
        """Reacquire the same inode capabilities for a repeated app lifespan.

        Re-entry is read-only at the filesystem boundary: missing/replaced components
        are rejected, never created or chmodded. The stored inode tuple comes only from
        the initial retained descriptors.
        """
        if not self._verified_identity_required:
            return
        with self._verified_handle_lock:
            if (self._verified_directory_fd is None
                    and self._verified_database_fd is None):
                pass
            elif (type(self._verified_directory_fd) is int
                    and type(self._verified_database_fd) is int):
                return
            else:
                raise ValueError('Verified storage identity is incomplete')

            expected = self._verified_expected_identity
            if (type(expected) is not tuple or len(expected) != 4
                    or any(type(value) is not int for value in expected)):
                raise ValueError('Verified storage identity is unavailable')
            if not hasattr(os, 'O_NOFOLLOW'):
                raise RuntimeError(
                    'This platform cannot retain a no-follow storage identity'
                )
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            if hasattr(os, 'O_CLOEXEC'):
                flags |= os.O_CLOEXEC
            directory_fd = os.open('/', flags)
            database_fd = None
            try:
                for name in self.data_dir.parts[1:]:
                    child = os.open(name, flags, dir_fd=directory_fd)
                    os.close(directory_fd)
                    directory_fd = child
                database_flags = os.O_RDWR | os.O_NOFOLLOW
                if hasattr(os, 'O_CLOEXEC'):
                    database_flags |= os.O_CLOEXEC
                database_fd = os.open(
                    'intake.sqlite3', database_flags, dir_fd=directory_fd,
                )
                directory = os.fstat(directory_fd)
                database = os.fstat(database_fd)
                observed = (
                    directory.st_dev, directory.st_ino,
                    database.st_dev, database.st_ino,
                )
                if (observed != expected or not stat.S_ISDIR(directory.st_mode)
                        or directory.st_uid != os.getuid()
                        or stat.S_IMODE(directory.st_mode) != 0o700
                        or not stat.S_ISREG(database.st_mode)
                        or database.st_nlink != 1
                        or database.st_uid != os.getuid()
                        or stat.S_IMODE(database.st_mode) != 0o600):
                    raise ValueError('Verified storage identity changed')
                self._assert_verified_identity(directory_fd, database_fd)
                self._verified_directory_fd = directory_fd
                self._verified_database_fd = database_fd
                directory_fd = database_fd = None
            except OSError as exc:
                raise ValueError('Verified storage identity changed') from exc
            finally:
                if database_fd is not None:
                    os.close(database_fd)
                if directory_fd is not None:
                    os.close(directory_fd)

    @contextmanager
    def _connection_handles(self, directory_fd, database_fd):
        supplied = directory_fd is not None or database_fd is not None
        if supplied:
            if type(directory_fd) is not int or type(database_fd) is not int:
                raise TypeError('Verified storage descriptors must be supplied together')
            yield (directory_fd, database_fd)
            return
        with self._borrow_verified_handles() as pair:
            yield pair

    @contextmanager
    def _connection(self, *, _verified_directory_fd=None,
                    _verified_database_fd=None):
        with self._connection_handles(
                _verified_directory_fd, _verified_database_fd) as handles:
            verified = handles is not None
            if verified:
                directory_fd, database_fd = handles
                self._assert_verified_identity(
                    directory_fd, database_fd,
                )
                uri = 'file:' + quote(os.fspath(self.path), safe='/') + '?mode=rw'
                db = sqlite3.connect(uri, timeout=10, uri=True)
                rows = db.execute('PRAGMA database_list').fetchall()
                if len(rows) != 1 or rows[0][1] != 'main' or not rows[0][2]:
                    db.close()
                    raise ValueError('SQLite database identity is unavailable')
                connected_path = Path(os.path.abspath(rows[0][2]))
                try:
                    self._assert_verified_identity(
                        directory_fd, database_fd,
                        connected_path,
                    )
                except BaseException:
                    db.close()
                    raise
            else:
                db = sqlite3.connect(self.path, timeout=10)
                connected_path = None
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys = ON')
            try:
                with db:
                    yield db
                    if verified:
                        self._assert_verified_identity(
                            directory_fd, database_fd, connected_path,
                        )
                if verified:
                    self._assert_verified_identity(
                        directory_fd, database_fd, connected_path,
                    )
            finally:
                db.close()

    @staticmethod
    def _event(db, kind, work_id, metadata):
        db.execute('INSERT INTO events(kind, work_id, created_at, metadata) VALUES (?, ?, ?, ?)',
                   (kind, work_id, _now(), json.dumps(metadata)))

    @staticmethod
    def _work(db, work_id):
        row = db.execute('SELECT * FROM works WHERE id = ?', (work_id,)).fetchone()
        if row is None:
            raise KeyError(work_id)
        work = dict(row)
        work['files'] = [json.loads(row['metadata']) for row in db.execute(
            'SELECT metadata FROM files WHERE work_id = ? ORDER BY rowid', (work_id,))]
        return work

    def _snapshot(self, db, work_id):
        work = self._work(db, work_id)
        db.execute('INSERT INTO revisions VALUES (?, ?, ?)',
                   (work_id, work['revision'], json.dumps(work, ensure_ascii=False)))
        return work

    def create_work(self, text=''):
        _text(text)
        work_id, timestamp = str(uuid4()), _now()
        with self._connection() as db:
            db.execute('INSERT INTO works VALUES (?, ?, 1, ?, ?)', (work_id, text, timestamp, timestamp))
            work = self._snapshot(db, work_id)
            self._event(db, 'work_created', work_id, {'revision': 1})
        return work

    def list_work(self):
        with self._connection() as db:
            db.execute('BEGIN')
            return [self._work(db, row['id']) for row in db.execute('SELECT id FROM works ORDER BY rowid')]

    def get_work(self, work_id):
        with self._connection() as db:
            db.execute('BEGIN')
            return self._work(db, work_id)

    def get_revision(self, work_id, revision):
        with self._connection() as db:
            row = db.execute('SELECT snapshot FROM revisions WHERE work_id = ? AND revision = ?',
                             (work_id, revision)).fetchone()
            if row is None:
                raise KeyError((work_id, revision))
            return json.loads(row['snapshot'])

    def update_work(self, work_id, text, expected_revision):
        _text(text)
        if type(expected_revision) is not int:
            raise ValueError('Expected revision must be an integer')
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            work = self._work(db, work_id)
            if work['revision'] != expected_revision:
                raise ConflictError('Work revision changed; reload before editing')
            db.execute('UPDATE works SET text = ?, revision = revision + 1, updated_at = ? WHERE id = ?',
                       (text, _now(), work_id))
            work = self._snapshot(db, work_id)
            self._event(db, 'work_updated', work_id, {'revision': work['revision']})
        return work

    def add_file(self, work_id, name, data, media_type, expected_revision=None):
        if expected_revision is not None and type(expected_revision) is not int:
            raise ValueError('Expected revision must be an integer')
        if (not isinstance(name, str) or not name or len(name) > 255 or name in {'.', '..'}
                or '/' in name or '\\' in name
                or any(unicodedata.category(char).startswith('C') for char in name)):
            raise ValueError('Filename must be a safe basename')
        if not isinstance(data, bytes) or len(data) > MAX_FILE_BYTES:
            raise ValueError('File must contain at most 10 MiB')
        if not isinstance(media_type, str) or len(media_type) > 255:
            raise ValueError('Invalid media type')
        reading = extract(name, data)
        # The client-supplied MIME is not trusted for serving or extraction.
        metadata = dict(id=str(uuid4()), name=name, size=len(data),
                        sha256=hashlib.sha256(data).hexdigest(), **reading)
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            work = self._work(db, work_id)
            if expected_revision is not None and work['revision'] != expected_revision:
                raise ConflictError('Work revision changed; reload before uploading')
            if len(work['files']) >= 20:
                raise ValueError('At most 20 files per work')
            db.execute('INSERT INTO files VALUES (?, ?, ?, ?)',
                       (metadata['id'], work_id, json.dumps(metadata, ensure_ascii=False), data))
            db.execute('UPDATE works SET revision = revision + 1, updated_at = ? WHERE id = ?', (_now(), work_id))
            updated = self._snapshot(db, work_id)
            self._event(db, 'file_added', work_id,
                        {'file_id': metadata['id'], 'revision': updated['revision'], 'size': len(data),
                         'sha256': metadata['sha256'], 'read_status': metadata['read_status']})
        return metadata

    def read_file(self, work_id, file_id):
        try:
            with self._connection() as db:
                db.execute('BEGIN')
                row = db.execute('SELECT metadata,typeof(data) AS data_type,'
                                 'length(data) AS data_size FROM files '
                                 'WHERE work_id = ? AND id = ?',
                                 (work_id, file_id)).fetchone()
                if row is None:
                    raise KeyError((work_id, file_id))
                metadata_text = row['metadata']
                mapped_table = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='domain_legacy_files'"
                ).fetchone() is not None
                migration_table = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='domain_migrations'"
                ).fetchone() is not None
                version_two = False
                if migration_table:
                    version_two = db.execute(
                        'SELECT 1 FROM domain_migrations WHERE version=2').fetchone() is not None
                mappings = []
                if mapped_table:
                    mappings = list(db.execute(
                        'SELECT vault_id,work_id,file_id,metadata_sha256,legacy_sha256,legacy_size,'
                        'purpose,blob_sha256,blob_size,read_source,migrated_at_utc '
                        'FROM domain_legacy_files '
                        'WHERE file_id=? LIMIT 2', (file_id,)))
                if len(mappings) > 1:
                    raise StorageIntegrityError('Multiple migrated file bindings exist')
                mapping = mappings[0] if mappings else None
                legacy_data = None
                if mapping is None:
                    if (row['data_type'] != 'blob' or type(row['data_size']) is not int
                            or not 0 <= row['data_size'] <= MAX_FILE_BYTES):
                        raise StorageIntegrityError(
                            'File storage metadata is unavailable or corrupt')
                    data = db.execute('SELECT data FROM files WHERE work_id=? AND id=?',
                                      (work_id, file_id)).fetchone()
                    legacy_data = data['data']
                    if (type(legacy_data) is not bytes
                            or len(legacy_data) != row['data_size']):
                        raise StorageIntegrityError(
                            'File storage metadata is unavailable or corrupt')
        except (sqlite3.DatabaseError, TypeError, UnicodeError) as exc:
            raise StorageIntegrityError('File storage metadata is unavailable or corrupt') from exc

        domain = None
        if mapped_table or version_two:
            # A v2 read validates the complete additive schema before either CAS or
            # still-unmigrated legacy bytes are accepted. A v1-only store is not
            # silently upgraded by this read path.
            from .domain.store import DomainStore, StorageError as DomainStorageError
            try:
                domain = DomainStore(self)
            except (DomainStorageError, sqlite3.DatabaseError, OSError,
                    TypeError, UnicodeError) as exc:
                raise StorageIntegrityError(
                    'Migrated file content is unavailable or corrupt') from exc
        if mapping is None:
            try:
                metadata = json.loads(metadata_text)
                if (not isinstance(metadata, dict) or metadata.get('id') != file_id
                        or type(metadata.get('size')) is not int
                        or metadata['size'] != len(legacy_data)
                        or metadata.get('sha256') != hashlib.sha256(legacy_data).hexdigest()):
                    raise StorageIntegrityError(
                        'File storage metadata is unavailable or corrupt')
                return metadata, legacy_data
            except (TypeError, UnicodeError, json.JSONDecodeError) as exc:
                raise StorageIntegrityError(
                    'File storage metadata is unavailable or corrupt') from exc

        try:
            metadata = json.loads(metadata_text)
            metadata_bytes = metadata_text.encode('utf-8')
            migrated_at = mapping['migrated_at_utc']
            try:
                parsed_migration_time = datetime.strptime(
                    migrated_at, '%Y-%m-%dT%H:%M:%S.%fZ')
            except (TypeError, ValueError) as exc:
                raise StorageIntegrityError(
                    'Migrated file binding is inconsistent') from exc
            if parsed_migration_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ') != migrated_at:
                raise StorageIntegrityError('Migrated file binding is inconsistent')
            if (not isinstance(metadata, dict) or metadata.get('id') != file_id
                    or mapping['work_id'] != work_id or mapping['file_id'] != file_id
                    or mapping['read_source'] != 'cas'
                    or mapping['purpose'] != 'operational'
                    or hashlib.sha256(metadata_bytes).hexdigest() != mapping['metadata_sha256']
                    or metadata.get('sha256') != mapping['legacy_sha256']
                    or metadata.get('sha256') != mapping['blob_sha256']
                    or type(metadata.get('size')) is not int
                    or metadata['size'] != mapping['legacy_size']
                    or metadata['size'] != mapping['blob_size']):
                raise StorageIntegrityError('Migrated file binding is inconsistent')
            # Lazy import avoids making the legacy Store depend on domain initialization.
            # The domain repository revalidates its migration schema, vault and CAS path.
            from .domain.refs import DomainContractError
            from .domain.store import BlobRef
            blob = BlobRef(mapping['vault_id'], mapping['purpose'],
                           mapping['blob_sha256'], mapping['blob_size'])
            data = domain.read_blob(blob, purpose=mapping['purpose'])
            return metadata, data
        except StorageIntegrityError:
            raise
        except (DomainContractError, DomainStorageError, sqlite3.DatabaseError,
                OSError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise StorageIntegrityError(
                'Migrated file content is unavailable or corrupt') from exc

    def events(self, work_id=None):
        with self._connection() as db:
            rows = db.execute('SELECT * FROM events ORDER BY id') if work_id is None else db.execute(
                'SELECT * FROM events WHERE work_id = ? ORDER BY id', (work_id,))
            return [{**dict(row), 'metadata': json.loads(row['metadata'])} for row in rows]
