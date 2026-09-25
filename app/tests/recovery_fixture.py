"""Offline owner-recovery fixtures: Ed25519 keys generated in-test, no network, no real keys.

A test builds a `deployment-public-trust-set-v2`, seals an `owner_recovery` request against
the current session-root generation and signs the matching `deployment-recovery-receipt-v1`
exactly as an instance operator's recovery adapter would.
"""

import os
import time
from base64 import urlsafe_b64encode
from hashlib import sha256
from uuid import uuid4

from nacl.signing import SigningKey

from app.deployment.prepare_contracts import stamp
from app.deployment.recovery_contracts import (
    make_recovery_request,
    manifest_core_sha256,
    receipt_preimage,
    recovered_manifest_core,
    verifier_sha256,
)
from app.deployment.recovery_schema_exports import RECOVERY_ADAPTER, STAGE_ADAPTER
from app.domain.refs import canonical_json
from app.operations.session_root import advance_session_root, open_session_root
from app.operations.setup import (
    build_recovered_configuration,
    derive_capability_verifier,
)

ACTOR = {"kind": "actor", "id": "5" * 8 + "-5555-4555-8555-" + "5" * 12, "version": 1, "sha256": "a" * 64}


def b64(raw):
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class Signer:
    def __init__(self, adapters=(RECOVERY_ADAPTER, STAGE_ADAPTER)):
        self.key = SigningKey.generate()
        self.key_id = str(uuid4())
        self.adapters = tuple(sorted(adapters))

    def entry(self):
        return {"key_id": self.key_id, "algorithm": "ed25519",
                "public_key": b64(bytes(self.key.verify_key)),
                "trust_class": "instance_operator", "adapter_ids": list(self.adapters)}

    def sign(self, unsigned):
        return b64(self.key.sign(receipt_preimage(unsigned)).signature)


def trust_v2(profile, *signers, previous=None, adapters=None):
    keys = sorted((signer.entry() for signer in signers), key=lambda item: item["key_id"])
    value = {
        "schema": "deployment-public-trust-set-v2",
        "domain": "deeptwin-deployment-public-trust-set-v2",
        "version": 2,
        "instance_id": profile.instance_id,
        "origin_profile_digest": b64(bytes.fromhex(profile.digest)),
        "previous_trust_set_digest": None if previous is None else b64(sha256(previous).digest()),
        "keys": keys,
        "adapters": adapters if adapters is not None else [
            {"operator_adapter": adapter, "operator_version": "1.0.0",
             "deployment_profile_id": profile.deployment_profile_id}
            for adapter in (STAGE_ADAPTER, RECOVERY_ADAPTER)],
    }
    return canonical_json(value)


def current_generation(root_dir, profile, epoch):
    handle = open_session_root(root_dir, profile=profile, recovery_epoch=epoch,
                               expected_uid=os.getuid(), expected_gid=os.getgid())
    try:
        return handle.receipt["generation_id"], handle.manifest_digest
    finally:
        handle.close()


def request_for(profile, *, epoch, generation_id, manifest_sha256, created_ms=None, ttl_seconds=600,
                nonce=None):
    created = time.time_ns() // 1_000_000 - 1_000 if created_ms is None else created_ms
    return make_recovery_request(
        profile=profile, request_id=str(uuid4()), nonce=nonce or os.urandom(32), actor_ref=ACTOR,
        created_ms=created - created % 1000, ttl_seconds=ttl_seconds, current_epoch=epoch,
        current_generation_id=generation_id, current_manifest_sha256=manifest_sha256)


def receipt_for(profile, request_bytes, signer, trust_bytes, *, new_verifier, completed_ms=None,
                sign=True, **changes):
    from app.domain.refs import parse_canonical

    request = parse_canonical(request_bytes)
    preconditions = request["preconditions"]
    completed = time.time_ns() // 1_000_000 if completed_ms is None else completed_ms
    unsigned = {
        "schema": "deployment-recovery-receipt-v1",
        "domain": "deeptwin-deployment-recovery-receipt-v1",
        "request_id": request["request_id"],
        "request_digest": request["request_digest"],
        "request_nonce": request["request_nonce"],
        "kind": "owner_recovery",
        "instance_id": request["instance_id"],
        "origin_profile_digest": request["origin_profile_digest"],
        "deployment_profile_id": profile.deployment_profile_id,
        "operator_adapter": RECOVERY_ADAPTER,
        "operator_version": "1.0.0",
        "previous_epoch": preconditions["current_recovery_epoch"],
        "previous_generation_id": preconditions["current_session_root_generation_id"],
        "previous_manifest_sha256": preconditions["current_session_root_manifest_sha256"],
        "new_epoch": request["effect_payload"]["target_recovery_epoch"],
        "new_generation_id": str(uuid4()),
        "new_manifest_sha256": "0" * 64,
        "new_verifier_sha256": verifier_sha256(new_verifier),
        "completed_at": stamp(completed),
        "key_id": signer.key_id,
        "trust_set_digest": b64(sha256(trust_bytes).digest()),
        "trust_class": "instance_operator",
    }
    unsigned["new_manifest_sha256"] = manifest_core_sha256(recovered_manifest_core(unsigned, profile=profile))
    unsigned.update(changes)
    signature = signer.sign(unsigned) if sign else b64(bytes(64))
    return canonical_json({**unsigned, "signature": signature})


class Recovery:
    """One complete N→N+1 recovery of a configured instance's stopped root."""

    def __init__(self, profile, arguments, *, epoch=1, signer=None, nonce=None):
        self.profile, self.epoch = profile, epoch
        self.root_dir = arguments["session_root_dir"]
        self.signer = signer or Signer()
        self.trust = trust_v2(profile, self.signer)
        self.capability = b64(os.urandom(32))
        self.verifier = derive_capability_verifier(self.capability)
        generation_id, digest = current_generation(self.root_dir, profile, epoch)
        self.request = request_for(profile, epoch=epoch, generation_id=generation_id, manifest_sha256=digest,
                                   nonce=nonce)
        self.receipt = receipt_for(profile, self.request, self.signer, self.trust, new_verifier=self.verifier)
        self.arguments = {**arguments, "deployment_config": build_recovered_configuration(
            profile=profile, verifier_b64u=self.verifier, recovery_epoch=epoch + 1)}

    def advance(self):
        return advance_session_root(self.root_dir, profile=self.profile, receipt_bytes=self.receipt,
                                    request_bytes=self.request, trust_bytes=self.trust,
                                    expected_uid=os.getuid(), expected_gid=os.getgid())
