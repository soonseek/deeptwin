"""A module-scoped real owner session for value-level suites whose values
must be backed by owner-recorded decisions (`app/services/owner_decisions`).

Usage in a test module::

    SESSION = OwnerSession("retention-owner")
    retention_owner = SESSION.fixture()   # autouse, module scope

    def approve(subject):
        return SESSION.decide("deletion", subject)

Modules that import the helpers of such a module must also import its
fixture name so the session is open before their first test and closed
right after their last (a session-wide teardown of a TestClient hung the
process at exit; module scope does not).
"""

from uuid import uuid4

import pytest

from app.services.owner_decisions import PersistentOwnerDecisions


class OwnerSession:
    def __init__(self, name: str):
        self.name = name
        self.app = None
        self.request = None

    def fixture(self):
        @pytest.fixture(scope="module", autouse=True)
        def _owner_session(tmp_path_factory):
            from app.tests.test_extension_candidates_persistent import owner

            with owner(tmp_path_factory.mktemp(self.name)) as (
                app,
                _c,
                request,
                _p,
                _a,
            ):
                self.app, self.request = app, request
                yield self
            self.app = self.request = None

        return _owner_session

    def decisions(self) -> PersistentOwnerDecisions:
        if self.app is None:
            raise RuntimeError(f"import the {self.name!r} fixture into this module")
        return PersistentOwnerDecisions(
            self.app.state.domain_store, self.app.state.owner_authority
        )

    def decide(self, subject_kind: str, subject: dict, decision: str = "approve"):
        return self.decisions().record(
            self.request,
            {
                "schema_version": "owner-decision-command-v1",
                "command_id": str(uuid4()),
                "subject_kind": subject_kind,
                "subject": subject,
                "decision": decision,
            },
        )
