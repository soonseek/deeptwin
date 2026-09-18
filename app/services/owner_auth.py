"""Durable owner/session authority consumed by the actual web command boundary."""
import hmac
import json
import secrets
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from importlib.metadata import version
from threading import RLock
from uuid import uuid4

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError

from ..domain.public_events import _append_event_in_transaction, _install_event_schema
from ..domain.refs import EntityRef, canonical_json, uuid_string
from ..domain.request_identity import (
    AuthenticatedRequest,
    AuthenticatedSession,
    RequestDenied,
)
from ..domain.schemas import Actor, ImmutableRecord
from ..domain.store import DomainStore, _writer
from ..operations.session_root import SessionRootHandle, _b64
from ..operations.setup import CapabilityVerifier, OriginProfile, parse_base64url_32
from . import owner_auth_storage as storage
from .owner_admission import AdmissionRejected, PasswordBuckets, PasswordLane

PROFILE = "argon2id-v19-m65536-t3-p4-s16-h32"
_ERRORS = {"invalid_input", "credentials", "capacity", "unavailable", "setup_incomplete",
           "setup_unavailable", "unauthenticated", "access_denied", "conflict"}


class OwnerAuthError(RequestDenied):
    def __init__(self, code):
        self.code = code if code in _ERRORS else "unavailable"
        super().__init__(self.code)


def _closed_errors(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except OwnerAuthError:
            raise
        except Exception:  # noqa: BLE001 - public authority never exposes raw storage/native errors
            raise OwnerAuthError("unavailable") from None
    return invoke


def _scalar(value, maximum, *, minimum=1):
    try:
        valid = type(value) is str and minimum <= len(value) and len(value.encode("utf-8")) <= maximum
    except UnicodeError:
        valid = False
    if not valid:
        raise OwnerAuthError("invalid_input")
    return value


def validate_credentials(login_name, password, *, choosing=False):
    _scalar(login_name, 128)
    if login_name != login_name.strip() or any(unicodedata.category(c) == "Cc" for c in login_name):
        raise OwnerAuthError("invalid_input")
    _scalar(password, 1024, minimum=15 if choosing else 1)


def _stamp(milliseconds):
    return datetime.fromtimestamp(milliseconds / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class BootstrapExchange:
    session: AuthenticatedSession
    csrf_token: str = field(repr=False)
    token_b64u: str = field(repr=False)


class PersistentOwnerAuthority:
    def __init__(self, domain_store, *, root, configuration, serving_lock):
        if type(domain_store) is not DomainStore or type(root) is not SessionRootHandle:
            raise OwnerAuthError("unavailable")
        if version("argon2-cffi") != "25.1.0":
            raise OwnerAuthError("unavailable")
        self._domain, self._root, self._serving_lock = domain_store, root, serving_lock
        self.profile = OriginProfile.from_dict(configuration["origin_profile"])
        self._epoch = configuration["recovery_epoch"]
        self._verifier = CapabilityVerifier(configuration["verifier_b64u"])
        self._binding = {"vault_id": domain_store.vault_id, "instance_id": self.profile.instance_id,
                             "origin_digest": self.profile.digest, "generation_id": root.receipt["generation_id"],
                             "key_id": root.receipt["key_id"], "manifest_digest": root.manifest_digest, "epoch": self._epoch}
        self._lane, self._buckets = PasswordLane(), PasswordBuckets()
        self._hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4,
                                      hash_len=32, salt_len=16, type=Type.ID)
        self._identities, self._identity_lock = OrderedDict(), RLock()
        self._closed = False
        self._permission_host = None
        with _writer(), domain_store._connection(write=True) as db:
            existing = db.execute("SELECT 1 FROM sqlite_master WHERE name='owner_auth_migrations'").fetchone()
            storage.install(db)
            now = time.time_ns() // 1_000_000
            if not existing:
                storage.insert(db, "control", dict(singleton=1, **self._binding,
                                                   opened_at=now, deadline=now + 600000,
                                                   clock_floor=now, revision=1))
                storage.insert(db, "bootstrap_claims", {"epoch": self._epoch,
                    "verifier": self._verifier.verifier_b64u, "attempts": 0, "state": "available", "claim_id": None,
                    "consumed_at": None, "completed_at": None, "revision": 1})
                storage.audit(db, "opened", None, now)
            self._check(db)
            _install_event_schema(db, self._binding["vault_id"])

    @property
    def cookie_name(self):
        return "deeptwin_session" if self.profile.scheme == "http" else "__Host-deeptwin_session"

    def _check(self, db):
        if self._closed:
            raise OwnerAuthError("unavailable")
        storage.verify(db)
        control = db.execute("SELECT * FROM owner_auth_control").fetchone()
        claim = db.execute("SELECT * FROM owner_auth_bootstrap_claims").fetchone()
        if (control is None or claim is None or any(control[k] != v for k, v in self._binding.items())
                or claim["epoch"] != self._epoch or claim["verifier"] != self._verifier.verifier_b64u):
            raise OwnerAuthError("unavailable")
        account = db.execute("SELECT * FROM owner_auth_accounts").fetchone()
        if (account is None) != (claim["state"] != "completed"):
            raise OwnerAuthError("unavailable")
        if account is not None:
            ref = EntityRef.from_dict(json.loads(account["actor_ref"]))
            roots = self._domain._read_roots(db)
            record = self._domain._load(db, ref, roots)[0]
            if (record.body["actor_ref"] != roots.actor.as_dict()
                    or record.body["content"] != {"id": account["owner_id"], "kind": "human", "origin": "local_session"}
                    or ref.id != account["owner_id"] or ref == roots.actor):
                raise OwnerAuthError("unavailable")
        return control, claim, account

    @_closed_errors
    def setup_state(self):
        """The public setup state of this instance for its first screen: whether an
        owner exists and the bootstrap claim's state (`available`, `consumed`,
        `expired`, `exhausted`, `completed`). Read-only; nothing else leaves. An
        available claim past the deadline reads `expired` here without an attempt
        (the row itself is only written lazily by a bootstrap); a storage fault is
        the closed `unavailable`, never a bare error."""

        with self._domain._connection() as db:
            control, claim, account = self._check(db)
            state = claim["state"]
            if state == "available" and self._now(db) >= control["deadline"]:
                state = "expired"
            return account is not None, state

    def _now(self, db, *, write=False):
        control = db.execute("SELECT * FROM owner_auth_control").fetchone()
        now = max(time.time_ns() // 1_000_000, control["clock_floor"])
        if write and now > control["clock_floor"]:
            storage.update(db, "control", control, {"clock_floor": now}, identity="singleton")
        return now

    def _admit(self, source_key, account):
        _scalar(source_key, 256)
        try:
            self._buckets.admit(source_key, account)
            return self._lane.reserve()
        except AdmissionRejected:
            raise OwnerAuthError("capacity") from None

    def _hash(self, password):
        return self._hasher.hash(password)

    def _verify_password(self, encoded, password):
        try:
            if type(encoded) is not str or len(encoded) > 512:
                raise OwnerAuthError("unavailable")
            parameters = extract_parameters(encoded)
            if (parameters.type != Type.ID or parameters.version != 19
                    or parameters.salt_len != 16 or parameters.hash_len != 32
                    or parameters.memory_cost != 65536 or parameters.time_cost != 3 or parameters.parallelism != 4):
                raise OwnerAuthError("unavailable")
            return self._hasher.verify(encoded, password)
        except (InvalidHashError, ValueError):
            raise OwnerAuthError("unavailable") from None
        except VerificationError:
            return False

    def _publish(self, row):
        with self._identity_lock:
            current = self._identities.get(row["session_id"])
            if current is None:
                current = AuthenticatedSession(row["session_id"], Actor(row["owner_id"], "human", "local_session"),
                                               row["absolute_expires"] // 1000)
                self._identities[row["session_id"]] = current
            self._identities.move_to_end(row["session_id"])
            while len(self._identities) > 1024:
                self._identities.popitem(last=False)
            return current

    def _new_session(self, db, account, authenticator, now):
        token = _b64(secrets.token_bytes(32))
        row = storage.insert(db, "sessions", {"session_id": str(uuid4()), "owner_id": account["owner_id"],
            "token_digest": sha256(parse_base64url_32(token)).hexdigest(), "authenticator_revision": authenticator["revision"],
            "auth_epoch": account["auth_epoch"], "recovery_epoch": self._epoch, "origin_digest": self.profile.digest,
            "created_at": now, "last_seen": now, "idle_expires": now + 43200000, "absolute_expires": now + 604800000,
            "revoked_at": None, "revision": 1})
        return token, row

    def _event(self, db, account, kind, now):
        roots = self._domain._read_roots(db)
        _append_event_in_transaction(db, vault_id=roots.genesis.id, recorded_at_utc=_stamp(now),
            observed_at_utc=_stamp(now), actor_kind="human", actor_ref=EntityRef.from_dict(json.loads(account["actor_ref"])),
            event_type=kind, object_refs=(), correlation_id=str(uuid4()), causation_id=None,
            status="succeeded", error_code=None, public_metadata={"session_count": 1},
            private_evidence_refs=(), retention_class="core", policy_ref=roots.access_policy)

    def bootstrap(self, *, login_name, password, raw_capability_b64u, source_key):
        validate_credentials(login_name, password, choosing=True)
        try:
            parse_base64url_32(raw_capability_b64u)
        except ValueError:
            raise OwnerAuthError("invalid_input") from None
        reservation = self._admit(source_key, None)
        try:
            failure = None
            with _writer(), self._domain._connection(write=True) as db:
                control, claim, account = self._check(db)
                now = self._now(db, write=True)
                if claim["state"] == "consumed":
                    raise OwnerAuthError("setup_incomplete")
                if claim["state"] != "available" or account is not None:
                    raise OwnerAuthError("setup_unavailable")
                if now >= control["deadline"]:
                    storage.update(db, "bootstrap_claims", claim, {"state": "expired"}, identity="epoch")
                    failure = "setup_unavailable"
                else:
                    attempts = claim["attempts"] + 1
                    if not self._verifier.matches(raw_capability_b64u):
                        storage.update(db, "bootstrap_claims", claim, {"attempts": attempts,
                            "state": "exhausted" if attempts == 5 else "available"}, identity="epoch")
                        storage.audit(db, "guess", None, now)
                        failure = "credentials"
                    else:
                        claim_id = str(uuid4())
                        storage.update(db, "bootstrap_claims", claim, {"attempts": attempts, "state": "consumed",
                            "claim_id": claim_id, "consumed_at": now}, identity="epoch")
                        storage.audit(db, "claim", claim_id, now)
            if failure:
                raise OwnerAuthError(failure)
            # Durable claim commit precedes every native allocation.
            encoded = reservation.run(lambda: self._hash(password))
            with _writer(), self._domain._connection(write=True) as db:
                _, claim, account = self._check(db)
                now = self._now(db, write=True)
                if claim["state"] != "consumed" or claim["claim_id"] != claim_id or account is not None:
                    raise OwnerAuthError("setup_incomplete")
                roots = self._domain._read_roots(db)
                owner_id = str(uuid4())
                record = ImmutableRecord.create(kind="actor", id=owner_id, version=1, created_at_utc=_stamp(now),
                    actor_ref=roots.actor, parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
                    retention_policy_ref=roots.retention_policy,
                    content={"id": owner_id, "kind": "human", "origin": "local_session"})
                self._domain._put_in_transaction(db, record)
                if self._permission_host is None:
                    raise OwnerAuthError("unavailable")
                self._permission_host._register_record_in_transaction(db, record)
                account = storage.insert(db, "accounts", {"owner_id": owner_id, "singleton": 1,
                    "actor_ref": canonical_json(record.ref.as_dict()).decode(), "login_name": login_name, "state": "active",
                    "auth_epoch": 1, "recovery_epoch": self._epoch, "created_at": now, "updated_at": now, "revision": 1})
                authenticator = storage.insert(db, "authenticators", {"owner_id": owner_id, "revision": 1,
                    "previous_revision": None, "kind": "password", "profile": PROFILE, "encoded_hash": encoded,
                    "created_at": now, "revoked_at": None})
                token, row = self._new_session(db, account, authenticator, now)
                self._event(db, account, "owner.created", now)
                storage.update(db, "bootstrap_claims", claim, {"state": "completed", "completed_at": now}, identity="epoch")
                storage.audit(db, "owner", owner_id, now)
            return BootstrapExchange(self._publish(row), self._root.derive_csrf(token), token)
        except AdmissionRejected:
            raise OwnerAuthError("capacity") from None
        except OwnerAuthError:
            raise
        except Exception:  # noqa: BLE001 - consumed claims must fail closed on any native/storage failure
            raise OwnerAuthError("unavailable") from None
        finally:
            reservation.close()
            password = raw_capability_b64u = None

    @_closed_errors
    def login(self, *, login_name, password, source_key, prior_cookie=None):
        validate_credentials(login_name, password)
        _scalar(source_key, 256)
        started = time.monotonic()
        with self._domain._connection() as db:
            _, _, account = self._check(db)
            account = dict(account) if account is not None and account["login_name"] == login_name else None
            authenticator = None if account is None else db.execute(
                "SELECT * FROM owner_auth_authenticators WHERE owner_id=? ORDER BY revision DESC LIMIT 1",
                (account["owner_id"],)).fetchone()
            authenticator = None if authenticator is None else dict(authenticator)
        reservation = self._admit(source_key, None if account is None else account["owner_id"])
        try:
            if authenticator is None:
                reservation.run(lambda: self._hash(password))
                raise OwnerAuthError("credentials")
            correct = reservation.run(lambda: self._verify_password(authenticator["encoded_hash"], password))
            if not correct:
                raise OwnerAuthError("credentials")
            with _writer(), self._domain._connection(write=True) as db:
                _, _, current = self._check(db)
                now = self._now(db, write=True)
                current_auth = db.execute("SELECT * FROM owner_auth_authenticators WHERE owner_id=? ORDER BY revision DESC LIMIT 1",
                                          (account["owner_id"],)).fetchone()
                if (current is None or dict(current) != account or current["state"] != "active"
                        or current_auth is None or dict(current_auth) != authenticator or current_auth["revoked_at"] is not None):
                    raise OwnerAuthError("credentials")
                if prior_cookie is not None:
                    try:
                        prior = self._session_by_token(db, prior_cookie, now)
                    except OwnerAuthError:
                        prior = None
                    if prior is not None and prior["owner_id"] == account["owner_id"]:
                        storage.update(db, "sessions", prior, {"revoked_at": now}, identity="session_id")
                token, row = self._new_session(db, account, authenticator, now)
                self._event(db, account, "session.created", now)
                storage.audit(db, "login", row["session_id"], now)
            return BootstrapExchange(self._publish(row), self._root.derive_csrf(token), token)
        except AdmissionRejected:
            raise OwnerAuthError("capacity") from None
        finally:
            reservation.close()
            password = None
            remaining = 0.250 - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)

    def token_from_cookie(self, cookie_header):
        if type(cookie_header) is not str or len(cookie_header) > 8192:
            raise OwnerAuthError("unauthenticated")
        values = []
        for part in cookie_header.split(";"):
            name, separator, value = part.strip().partition("=")
            if name == self.cookie_name:
                if not separator:
                    raise OwnerAuthError("unauthenticated")
                values.append(value)
        if len(values) != 1:
            raise OwnerAuthError("unauthenticated")
        try:
            parse_base64url_32(values[0])
        except ValueError:
            raise OwnerAuthError("unauthenticated") from None
        return values[0]

    def _session_by_token(self, db, token, now, *, revoked=False):
        try:
            digest = sha256(parse_base64url_32(token)).hexdigest()
        except ValueError:
            raise OwnerAuthError("unauthenticated") from None
        row = db.execute("SELECT * FROM owner_auth_sessions WHERE token_digest=?", (digest,)).fetchone()
        self._valid_session(db, row, now, revoked=revoked)
        return row

    def _valid_session(self, db, row, now, *, revoked=False):
        if row is None:
            raise OwnerAuthError("unauthenticated")
        account = db.execute("SELECT * FROM owner_auth_accounts WHERE owner_id=?", (row["owner_id"],)).fetchone()
        auth = db.execute("SELECT * FROM owner_auth_authenticators WHERE owner_id=? AND revision=?",
                          (row["owner_id"], row["authenticator_revision"])).fetchone()
        if (account is None or auth is None or account["state"] != "active"
                or row["origin_digest"] != self.profile.digest
                or row["auth_epoch"] != account["auth_epoch"] or row["recovery_epoch"] != self._epoch
                or account["recovery_epoch"] != self._epoch or auth["revoked_at"] is not None
                or (not revoked and (row["revoked_at"] is not None or now >= row["idle_expires"]
                                     or now >= row["absolute_expires"]))):
            raise OwnerAuthError("unauthenticated")

    @_closed_errors
    def authenticate_request(self, *, method, host, origin, sec_fetch_site, cookie_header, csrf_token):
        if (host != self.profile.http_origin.split("://", 1)[1] or origin not in (None, self.profile.http_origin)
                or sec_fetch_site not in (None, "same-origin", "none")
                or (method not in {"GET", "HEAD"} and (origin != self.profile.http_origin or sec_fetch_site != "same-origin"))):
            raise OwnerAuthError("access_denied")
        token = self.token_from_cookie(cookie_header)
        if method not in {"GET", "HEAD"}:
            self.verify_csrf(token, csrf_token)
        failure = None
        with _writer(), self._domain._connection(write=True) as db:
            self._check(db)
            now = self._now(db, write=True)
            try:
                row = self._session_by_token(db, token, now)
            except OwnerAuthError as error:
                failure = error
            if failure is None and now > row["last_seen"]:
                row = storage.update(db, "sessions", row, {"last_seen": now,
                    "idle_expires": min(now + 43200000, row["absolute_expires"])}, identity="session_id")
        if failure is not None:
            raise failure
        return AuthenticatedRequest(method, host, origin, self._publish(row), method not in {"GET", "HEAD"})

    def verify_csrf(self, token, csrf):
        try:
            parse_base64url_32(csrf)
            if not hmac.compare_digest(self._root.derive_csrf(token), csrf):
                raise ValueError
        except ValueError:
            raise OwnerAuthError("access_denied") from None

    @_closed_errors
    def authenticate_bound(self, session, *, db=None):
        with self._identity_lock:
            if type(session) is not AuthenticatedSession or self._identities.get(session.session_id) is not session:
                raise OwnerAuthError("unauthenticated")
        if db is None:
            with self._domain._connection() as connection:
                return self._bound_in_connection(connection, session)
        self._domain._assert_write_transaction(db)
        return self._bound_in_connection(db, session)

    def _bound_in_connection(self, db, session):
        self._check(db)
        row = db.execute("SELECT * FROM owner_auth_sessions WHERE session_id=?", (session.session_id,)).fetchone()
        self._valid_session(db, row, self._now(db))
        if session.actor.id != row["owner_id"]:
            raise OwnerAuthError("unauthenticated")
        return session.actor

    @_closed_errors
    def session_view(self, request, *, token_b64u):
        self.authenticate_bound(request.session)
        with self._domain._connection() as db:
            self._check(db)
            row = self._session_by_token(db, token_b64u, self._now(db))
            if row["session_id"] != request.session.session_id:
                raise OwnerAuthError("unauthenticated")
        return {"state": "authenticated", "csrf_token": self._root.derive_csrf(token_b64u)}

    @_closed_errors
    def logout(self, request, *, command_id, token_b64u):
        try:
            uuid_string(command_id)
        except ValueError:
            raise OwnerAuthError("invalid_input") from None
        with _writer(), self._domain._connection(write=True) as db:
            self._check(db)
            now = self._now(db, write=True)
            row = self._session_by_token(db, token_b64u, now, revoked=True)
            digest = sha256(canonical_json({"command_id": command_id, "session_id": row["session_id"],
                "kind": "logout", "origin_digest": self.profile.digest, "epoch": self._epoch})).hexdigest()
            previous = db.execute("SELECT * FROM owner_auth_commands WHERE command_id=?", (command_id,)).fetchone()
            if previous is not None:
                if (previous["request_digest"] != digest or previous["session_id"] != row["session_id"]
                        or previous["epoch"] != self._epoch or row["revoked_at"] is None):
                    raise OwnerAuthError("conflict")
                return json.loads(previous["response_json"])
            if type(request) is not AuthenticatedRequest or not request.csrf_verified:
                raise OwnerAuthError("unauthenticated")
            self.authenticate_bound(request.session, db=db)
            if row["session_id"] != request.session.session_id:
                raise OwnerAuthError("unauthenticated")
            storage.update(db, "sessions", row, {"revoked_at": now}, identity="session_id")
            account = db.execute("SELECT * FROM owner_auth_accounts WHERE owner_id=?", (row["owner_id"],)).fetchone()
            self._event(db, account, "session.revoked", now)
            response = {"command_id": command_id, "state": "logged_out"}
            storage.insert(db, "commands", {"command_id": command_id, "session_id": row["session_id"],
                "kind": "logout", "request_digest": digest, "response_json": canonical_json(response).decode(),
                "created_at": now, "epoch": self._epoch})
            storage.audit(db, "logout", row["session_id"], now)
        with self._identity_lock:
            self._identities.pop(row["session_id"], None)
        return response

    def close(self):
        self._closed = True
        # Retain OS serving ownership until every admitted native operation ends.
        self._lane.close()
        with self._identity_lock:
            self._identities.clear()
        self._root.close()
        self._serving_lock.close()
