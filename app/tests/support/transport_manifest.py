"""Test-only transport-manifest fixtures (T087/T090). Nothing in app imports this module.

`loopback_binding` is the shipped Claude API manifest's binding with only its origin
replaced by a loopback mock provider (the `from_manifest(loopback_port=...)` test
affordance). Its manifest digest is unchanged, so it needs the same qualification.

`synthetic_qualification` is a structurally complete `provider-transport-qualification-v1`
document whose installation-conformance references are synthetic. The gateway trusts the
authenticated control side for this document (as for `bind_head`), so gateway-side tests
adopt it directly. The real qualification act (installation conformance plus offline
transport conformance, sealed and published) is exercised in
test_provider_transport_manifest.py.
"""

from __future__ import annotations

from uuid import uuid4

from app.workers.provider_gateway import ProviderBinding
from app.workers.provider_transport_manifest import (
    QUALIFICATION_SCHEMA,
    claude_api_manifest,
)


def loopback_binding(port):
    return ProviderBinding.from_manifest(claude_api_manifest(), loopback_port=port)


def synthetic_qualification(*, revision=1, manifest_sha256=None, provider="claude"):
    command_id = str(uuid4())
    installation_id = str(uuid4())
    return {
        "schema_version": QUALIFICATION_SCHEMA, "provider": provider, "revision": revision,
        "manifest_sha256": (claude_api_manifest().manifest_sha256
                            if manifest_sha256 is None else manifest_sha256),
        "qualification_ref": {"kind": "validation_report", "id": str(uuid4()), "version": 1,
                              "sha256": "a" * 64},
        "installation_conformance": {
            "command_id": command_id,
            "staged_installation_ref": {"kind": "extension_installation", "id": installation_id,
                                        "version": 1, "sha256": "b" * 64},
            "verified_installation_ref": {"kind": "extension_installation",
                                          "id": installation_id, "version": 2,
                                          "sha256": "c" * 64},
            "result_ref": {"kind": "provider_conformance_run", "id": command_id, "version": 2,
                           "sha256": "d" * 64},
            "suite_sha256": "e" * 64, "completed_count": 4, "matched_count": 4},
        "transport_conformance": {"suite_sha256": "f" * 64, "result_sha256": "1" * 64,
                                  "completed_count": 4, "matched_count": 4},
    }


def qualify_vault(vault, **kwargs):
    """Adopt a synthetic qualification of the shipped manifest in a gateway vault."""
    return vault.bind_transport(qualification=synthetic_qualification(**kwargs))


def reservation_ref():
    """A digest-bound reservation label, fresh per send (the gateway consumes each once)."""
    return {"kind": "validation_report", "id": str(uuid4()), "version": 1, "sha256": "e" * 64}


__all__ = ["loopback_binding", "qualify_vault", "reservation_ref", "synthetic_qualification"]
