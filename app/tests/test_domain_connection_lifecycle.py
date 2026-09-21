"""Finite ownership tests for the shared DomainStore SQLite path."""

from contextlib import contextmanager
import os
import sqlite3

import pytest

from app.storage import Store
from app.tests.test_domain_storage import opened, record


class LifecycleBaseException(BaseException):
    pass


def _module():
    from app.domain import store

    return store


def _create_observation_table(domain):
    with domain._connection(write=True) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS connection_lifecycle "
            "(name TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )


def _observed_values(real_connect, path):
    with real_connect(path) as db:
        return [row[0] for row in db.execute(
            "SELECT value FROM connection_lifecycle ORDER BY name"
        )]


@contextmanager
def _verified_store(path):
    path.mkdir(mode=0o700)
    input_directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    store = None
    try:
        store = Store(path, _verified_directory_fd=input_directory)
        yield store, input_directory
    finally:
        if store is not None:
            store.close_verified_handles()
        os.close(input_directory)


def _install_connection_factory(monkeypatch, module, domain, *,
                                setup_failure=None, post_yield_failure=None,
                                rollback_failure=None, commit_mode=None,
                                close_mode=None):
    real_connect = sqlite3.connect
    events = []
    connections = []

    class InstrumentedConnection(sqlite3.Connection):
        database_list_calls = 0

        def execute(self, sql, parameters=(), /):
            if sql == "PRAGMA foreign_keys=ON" and setup_failure is not None:
                events.append((
                    "setup-fail", self in domain._active_write_connections,
                ))
                raise setup_failure
            if sql == "PRAGMA database_list":
                self.database_list_calls += 1
                if self.database_list_calls == 3 and post_yield_failure is not None:
                    events.append((
                        "post-yield-fail", self in domain._active_write_connections,
                    ))
                    raise post_yield_failure
            return super().execute(sql, parameters)

        def rollback(self):
            events.append("rollback")
            if rollback_failure is not None:
                raise rollback_failure
            return super().rollback()

        def commit(self):
            events.append("commit")
            if commit_mode == "before":
                raise sqlite3.OperationalError("commit before effect")
            result = super().commit()
            if commit_mode == "after":
                raise sqlite3.OperationalError("commit after effect")
            return result

        def close(self):
            events.append(
                "close-registered" if self in domain._active_write_connections else "close"
            )
            if close_mode == "refuse":
                raise OSError("connection close refused")
            if close_mode == "after":
                super().close()
                raise OSError("connection close after release")
            return super().close()

    def connect(*args, **kwargs):
        kwargs["factory"] = InstrumentedConnection
        connection = real_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(module.sqlite3, "connect", connect)
    return real_connect, events, connections


def _track_domain_directory_closes(monkeypatch, module, domain, events):
    real_close = os.close
    directory_identity = domain.data_dir.stat().st_ino

    def tracking_close(descriptor):
        try:
            is_domain_directory = os.fstat(descriptor).st_ino == directory_identity
        except OSError:
            is_domain_directory = False
        if is_domain_directory:
            events.append("directory-close")
        return real_close(descriptor)

    monkeypatch.setattr(module.os, "close", tracking_close)
    return real_close


def test_normal_record_commit_survives_reopen(tmp_path):
    module, legacy, domain, roots = opened(tmp_path)
    item = record(roots, content={"purpose": "lifecycle baseline"})
    ref = domain.put(item)
    reopened = module.DomainStore(legacy)
    assert reopened.get(ref).body_bytes == item.body_bytes


def test_real_sql_commit_rollback_membership_and_later_connection(tmp_path):
    _, legacy, domain, _ = opened(tmp_path)
    _create_observation_table(domain)

    with domain._connection(write=True) as db:
        assert db in domain._active_write_connections
        db.execute("INSERT INTO connection_lifecycle VALUES ('commit', 'kept')")
    assert not domain._active_write_connections

    primary = RuntimeError("body failure")
    with pytest.raises(RuntimeError) as caught:
        with domain._connection(write=True) as db:
            db.execute("INSERT INTO connection_lifecycle VALUES ('rollback', 'lost')")
            raise primary
    assert caught.value is primary
    assert not domain._active_write_connections
    with domain._connection() as db:
        assert [row[0] for row in db.execute(
            "SELECT value FROM connection_lifecycle ORDER BY name"
        )] == ["kept"]
    assert legacy.path.exists()


def test_plain_and_verified_borrow_preserve_source_handles_and_closed_capability_refuses(tmp_path):
    plain = Store(tmp_path / "plain")
    with plain._borrow_verified_handles() as borrowed:
        assert borrowed is None

    with _verified_store(tmp_path / "verified") as (verified, input_directory):
        originals = (verified._verified_directory_fd, verified._verified_database_fd)
        with verified._borrow_verified_handles() as pair:
            assert pair is not None
            assert pair != originals
            os.fstat(pair[0])
            os.fstat(pair[1])
        os.fstat(input_directory)
        os.fstat(originals[0])
        os.fstat(originals[1])
        verified.close_verified_handles()
        with pytest.raises(ValueError, match="identity is closed"):
            with verified._borrow_verified_handles():
                pass


def test_connection_subclass_supports_sql_but_is_rejected_as_record_writer(tmp_path, monkeypatch):
    module, _, domain, roots = opened(tmp_path)
    _create_observation_table(domain)
    _, _, connections = _install_connection_factory(monkeypatch, module, domain)
    item = record(roots, content={"purpose": "exact connection type"})

    with pytest.raises(module.StorageError, match="Exact active"):
        with domain._connection(write=True) as db:
            db.execute("INSERT INTO connection_lifecycle VALUES ('direct', 'works')")
            domain._put_in_transaction(db, item)
    assert connections


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit, LifecycleBaseException])
def test_body_primary_survives_rollback_and_close_failures(
        tmp_path, monkeypatch, exception_type):
    module, _, domain, _ = opened(tmp_path)
    rollback_failure = OSError("rollback secondary")
    primary = exception_type("body primary")
    real_connect, events, connections = _install_connection_factory(
        monkeypatch, module, domain,
        rollback_failure=rollback_failure, close_mode="refuse",
    )
    real_close = _track_domain_directory_closes(monkeypatch, module, domain, events)

    try:
        with pytest.raises(exception_type) as caught:
            with domain._connection(write=True):
                raise primary
        assert caught.value is primary
        assert events[-3:] == ["rollback", "close", "directory-close"]
        assert not domain._active_write_connections
    finally:
        monkeypatch.setattr(module.sqlite3, "connect", real_connect)
        monkeypatch.setattr(module.os, "close", real_close)
        for connection in connections:
            sqlite3.Connection.close(connection)


@pytest.mark.parametrize("checkpoint", ["setup", "post-yield"])
def test_execute_checkpoint_primary_rolls_back_and_fully_unwinds(
        tmp_path, monkeypatch, checkpoint):
    module, _, domain, _ = opened(tmp_path)
    primary = sqlite3.OperationalError(f"{checkpoint} primary")
    options = ({"setup_failure": primary} if checkpoint == "setup"
               else {"post_yield_failure": primary})
    _, events, _ = _install_connection_factory(monkeypatch, module, domain, **options)
    _track_domain_directory_closes(monkeypatch, module, domain, events)

    with pytest.raises(sqlite3.OperationalError) as caught:
        with domain._connection(write=True) as db:
            if checkpoint == "post-yield":
                db.execute("SELECT 1")
    assert caught.value is primary
    assert (f"{checkpoint}-fail", checkpoint == "post-yield") in events
    assert "rollback" in events
    assert events[-3:] == ["rollback", "close", "directory-close"]
    assert not domain._active_write_connections


@pytest.mark.parametrize("commit_mode, expected", [("before", []), ("after", ["value"])])
def test_commit_failure_distinguishes_before_effect_from_commit_then_raise(
        tmp_path, monkeypatch, commit_mode, expected):
    module, legacy, domain, _ = opened(tmp_path)
    _create_observation_table(domain)
    real_connect, events, _ = _install_connection_factory(
        monkeypatch, module, domain, commit_mode=commit_mode,
    )

    with pytest.raises(sqlite3.OperationalError, match=f"commit {commit_mode} effect"):
        with domain._connection(write=True) as db:
            db.execute("INSERT INTO connection_lifecycle VALUES ('row', 'value')")
    monkeypatch.setattr(module.sqlite3, "connect", real_connect)
    assert _observed_values(real_connect, legacy.path) == expected
    assert events[-3:] == ["commit", "rollback", "close"]


@pytest.mark.parametrize("close_mode", ["refuse", "after"])
def test_successful_commit_close_failure_keeps_row_without_rollback(
        tmp_path, monkeypatch, close_mode):
    module, legacy, domain, _ = opened(tmp_path)
    _create_observation_table(domain)
    real_connect, events, connections = _install_connection_factory(
        monkeypatch, module, domain, close_mode=close_mode,
    )
    real_close = _track_domain_directory_closes(monkeypatch, module, domain, events)

    try:
        with pytest.raises(OSError, match="connection close"):
            with domain._connection(write=True) as db:
                db.execute("INSERT INTO connection_lifecycle VALUES ('row', 'committed')")
        assert "rollback" not in events
        assert events[-3:] == ["commit", "close", "directory-close"]
        monkeypatch.setattr(module.sqlite3, "connect", real_connect)
        assert _observed_values(real_connect, legacy.path) == ["committed"]
        if close_mode == "refuse":
            assert connections[-1].execute("SELECT 1").fetchone()[0] == 1
        else:
            with pytest.raises(sqlite3.ProgrammingError):
                connections[-1].execute("SELECT 1")
    finally:
        monkeypatch.setattr(module.sqlite3, "connect", real_connect)
        monkeypatch.setattr(module.os, "close", real_close)
        if close_mode == "refuse":
            for connection in connections:
                sqlite3.Connection.close(connection)


def test_directory_child_open_failure_releases_reached_parent(tmp_path, monkeypatch):
    module = _module()
    real_open, real_close = os.open, os.close
    opened_fds = []
    closed_fds = []

    def tracking_open(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        opened_fds.append(descriptor)
        return descriptor

    def tracking_close(descriptor):
        closed_fds.append(descriptor)
        return real_close(descriptor)

    monkeypatch.setattr(module.os, "open", tracking_open)
    monkeypatch.setattr(module.os, "close", tracking_close)
    with pytest.raises(FileNotFoundError):
        with module._directory(tmp_path / "missing"):
            pass
    assert len(closed_fds) == len(opened_fds)


def test_directory_parent_close_failure_after_child_acquisition_attempts_child(
        tmp_path, monkeypatch):
    module = _module()
    target = tmp_path / "target"
    target.mkdir()
    real_open, real_close = os.open, os.close
    opened_fds = []
    close_attempts = []
    refused = []
    primary = OSError("parent close refused")

    def tracking_open(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        opened_fds.append(descriptor)
        return descriptor

    def failing_close(descriptor):
        close_attempts.append(descriptor)
        if len(close_attempts) == 1:
            refused.append(descriptor)
            raise primary
        return real_close(descriptor)

    monkeypatch.setattr(module.os, "open", tracking_open)
    monkeypatch.setattr(module.os, "close", failing_close)
    try:
        with pytest.raises(OSError) as caught:
            with module._directory(target):
                pass
        assert caught.value is primary
        assert close_attempts == opened_fds
    finally:
        monkeypatch.setattr(module.os, "open", real_open)
        monkeypatch.setattr(module.os, "close", real_close)
        for descriptor in refused:
            try:
                os.fstat(descriptor)
            except OSError:
                pass
            else:
                real_close(descriptor)


def test_directory_body_primary_survives_final_close_failure(tmp_path, monkeypatch):
    module = _module()
    target = tmp_path / "target"
    target.mkdir()
    real_close = os.close
    primary = LifecycleBaseException("directory body")
    close_failure = OSError("directory close refused")
    refused = []

    def failing_close(descriptor):
        try:
            is_target = os.fstat(descriptor).st_ino == target.stat().st_ino
        except OSError:
            is_target = False
        if is_target:
            refused.append(descriptor)
            raise close_failure
        return real_close(descriptor)

    monkeypatch.setattr(module.os, "close", failing_close)
    try:
        with pytest.raises(LifecycleBaseException) as caught:
            with module._directory(target):
                raise primary
        assert caught.value is primary
        assert len(refused) == 1
    finally:
        monkeypatch.setattr(module.os, "close", real_close)
        for descriptor in refused:
            real_close(descriptor)


def test_directory_tracks_acquisitions_when_numeric_fd_is_reused(tmp_path, monkeypatch):
    module = _module()
    target = tmp_path / "one" / "two"
    target.mkdir(parents=True)
    real_open, real_close = os.open, os.close
    acquisitions = []
    closes = []

    def tracking_open(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        acquisitions.append(descriptor)
        return descriptor

    def tracking_close(descriptor):
        closes.append(descriptor)
        return real_close(descriptor)

    monkeypatch.setattr(module.os, "open", tracking_open)
    monkeypatch.setattr(module.os, "close", tracking_close)
    with module._directory(target):
        pass
    assert len(acquisitions) == len(closes)
    assert len(set(acquisitions)) < len(acquisitions)


def test_nested_visible_directory_close_error_keeps_unsafe_path_mapping(
        tmp_path, monkeypatch):
    module, _, domain, _ = opened(tmp_path)
    real_open, real_close = os.open, os.close
    target_name = domain.data_dir.name
    target_open_count = 0
    fault_descriptor = None
    close_failure = OSError("visible directory close refused")
    refused = []

    def tracking_open(path, *args, **kwargs):
        nonlocal target_open_count, fault_descriptor
        descriptor = real_open(path, *args, **kwargs)
        if path == target_name:
            target_open_count += 1
            if target_open_count == 2:
                fault_descriptor = descriptor
        return descriptor

    def failing_close(descriptor):
        if descriptor == fault_descriptor:
            refused.append(descriptor)
            raise close_failure
        return real_close(descriptor)

    monkeypatch.setattr(module.os, "open", tracking_open)
    monkeypatch.setattr(module.os, "close", failing_close)
    try:
        with pytest.raises(module.UnsafePath) as caught:
            with domain._connection():
                pass
        assert caught.value.__cause__ is close_failure
        assert len(refused) == 1
    finally:
        monkeypatch.setattr(module.os, "open", real_open)
        monkeypatch.setattr(module.os, "close", real_close)
        for descriptor in refused:
            real_close(descriptor)


def test_verified_borrow_second_dup_primary_survives_first_cleanup_failure(
        tmp_path, monkeypatch):
    with _verified_store(tmp_path / "verified") as (store, _):
        real_dup, real_close = os.dup, os.close
        duplicate = []
        close_attempts = []
        primary = OSError("second dup failed")
        secondary = OSError("first duplicate close failed")

        def failing_dup(descriptor):
            if not duplicate:
                duplicate.append(real_dup(descriptor))
                return duplicate[0]
            raise primary

        def failing_close(descriptor):
            if descriptor == duplicate[0]:
                close_attempts.append(descriptor)
                raise secondary
            return real_close(descriptor)

        monkeypatch.setattr(os, "dup", failing_dup)
        monkeypatch.setattr(os, "close", failing_close)
        try:
            with pytest.raises(OSError) as caught:
                with store._borrow_verified_handles():
                    pass
            assert caught.value is primary
            assert close_attempts == duplicate
        finally:
            monkeypatch.setattr(os, "dup", real_dup)
            monkeypatch.setattr(os, "close", real_close)
            for descriptor in duplicate:
                real_close(descriptor)
        os.fstat(store._verified_directory_fd)
        os.fstat(store._verified_database_fd)
        with store._borrow_verified_handles() as pair:
            assert pair is not None


def test_verified_borrow_body_primary_survives_both_close_failures(
        tmp_path, monkeypatch):
    with _verified_store(tmp_path / "verified") as (store, _):
        real_dup, real_close = os.dup, os.close
        duplicates = []
        close_attempts = []
        primary = LifecycleBaseException("borrow body")

        def tracking_dup(descriptor):
            duplicate = real_dup(descriptor)
            duplicates.append(duplicate)
            return duplicate

        def failing_close(descriptor):
            if descriptor in duplicates:
                close_attempts.append(descriptor)
                raise OSError(f"duplicate close {descriptor}")
            return real_close(descriptor)

        monkeypatch.setattr(os, "dup", tracking_dup)
        monkeypatch.setattr(os, "close", failing_close)
        try:
            with pytest.raises(LifecycleBaseException) as caught:
                with store._borrow_verified_handles():
                    raise primary
            assert caught.value is primary
            assert close_attempts == list(reversed(duplicates))
        finally:
            monkeypatch.setattr(os, "dup", real_dup)
            monkeypatch.setattr(os, "close", real_close)
            for descriptor in duplicates:
                real_close(descriptor)


@pytest.mark.parametrize("failure_position", ["database", "directory"])
def test_verified_borrow_no_primary_preserves_first_close_error_and_attempts_both(
        tmp_path, monkeypatch, failure_position):
    with _verified_store(tmp_path / "verified") as (store, _):
        real_dup, real_close = os.dup, os.close
        duplicates = []
        attempts = []
        refused = []
        failure = OSError(f"{failure_position} duplicate close")

        def tracking_dup(descriptor):
            duplicate = real_dup(descriptor)
            duplicates.append(duplicate)
            return duplicate

        def failing_close(descriptor):
            if descriptor in duplicates:
                attempts.append(descriptor)
                position = "database" if descriptor == duplicates[1] else "directory"
                if position == failure_position:
                    refused.append(descriptor)
                    raise failure
            return real_close(descriptor)

        monkeypatch.setattr(os, "dup", tracking_dup)
        monkeypatch.setattr(os, "close", failing_close)
        try:
            with pytest.raises(OSError) as caught:
                with store._borrow_verified_handles():
                    pass
            assert caught.value is failure
            assert attempts == list(reversed(duplicates))
        finally:
            monkeypatch.setattr(os, "dup", real_dup)
            monkeypatch.setattr(os, "close", real_close)
            for descriptor in refused:
                real_close(descriptor)
        os.fstat(store._verified_directory_fd)
        os.fstat(store._verified_database_fd)


def test_integrated_verified_connection_preserves_db_primary_through_all_cleanup(
        tmp_path, monkeypatch):
    module = _module()
    with _verified_store(tmp_path / "verified") as (legacy, _):
        domain = module.DomainStore(legacy)
        real_connect = sqlite3.connect
        real_dup, real_open, real_close = os.dup, os.open, os.close
        connections = []
        duplicates = []
        refused_fds = []
        attempts = []
        outer_descriptor = None
        target_name = legacy.data_dir.name
        primary = sqlite3.OperationalError("database primary")

        class FailingConnection(sqlite3.Connection):
            def rollback(self):
                attempts.append("rollback")
                raise OSError("rollback secondary")

            def close(self):
                attempts.append("connection")
                raise OSError("connection secondary")

        def connect(*args, **kwargs):
            kwargs["factory"] = FailingConnection
            connection = real_connect(*args, **kwargs)
            connections.append(connection)
            return connection

        def tracking_dup(descriptor):
            duplicate = real_dup(descriptor)
            duplicates.append(duplicate)
            return duplicate

        def tracking_open(path, *args, **kwargs):
            nonlocal outer_descriptor
            descriptor = real_open(path, *args, **kwargs)
            if path == target_name and outer_descriptor is None:
                outer_descriptor = descriptor
            return descriptor

        def failing_close(descriptor):
            if descriptor == outer_descriptor:
                attempts.append("outer-directory")
                refused_fds.append(descriptor)
                raise OSError("outer directory secondary")
            if descriptor in duplicates:
                position = "duplicate-database" if descriptor == duplicates[1] \
                    else "duplicate-directory"
                attempts.append(position)
                refused_fds.append(descriptor)
                raise OSError(f"{position} secondary")
            return real_close(descriptor)

        monkeypatch.setattr(module.sqlite3, "connect", connect)
        monkeypatch.setattr(os, "dup", tracking_dup)
        monkeypatch.setattr(os, "open", tracking_open)
        monkeypatch.setattr(os, "close", failing_close)
        try:
            with pytest.raises(sqlite3.OperationalError) as caught:
                with domain._connection(write=True):
                    raise primary
            assert caught.value is primary
            assert not domain._active_write_connections
            assert attempts == [
                "rollback", "connection", "outer-directory",
                "duplicate-database", "duplicate-directory",
            ]
        finally:
            monkeypatch.setattr(module.sqlite3, "connect", real_connect)
            monkeypatch.setattr(os, "dup", real_dup)
            monkeypatch.setattr(os, "open", real_open)
            monkeypatch.setattr(os, "close", real_close)
            for connection in connections:
                sqlite3.Connection.close(connection)
            for descriptor in dict.fromkeys(refused_fds):
                real_close(descriptor)
        os.fstat(legacy._verified_directory_fd)
        os.fstat(legacy._verified_database_fd)
