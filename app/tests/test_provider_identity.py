"""Provider identity is a separately validated immutable declaration."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import pytest
from app.tests._provider_worker_fixture import encoded, identity_mapping, schema_bytes


def test_identity_exact_v2_and_schema_measurements():
    from app.extensions.provider_identity import (
        parse_provider_build_identity,
        validate_provider_schema_bytes,
    )
    from app.extensions.lineage_contracts import (
        parse_build_identity,
        LineageContractError,
        validate_schema_bytes,
    )

    raw = encoded(identity_mapping())
    identity = parse_provider_build_identity(raw)
    assert identity.content_bytes == raw and identity.digest == sha256(raw).hexdigest()
    validate_provider_schema_bytes(identity, schema_bytes())
    with pytest.raises(LineageContractError):
        parse_build_identity(raw)
    with pytest.raises(LineageContractError):
        validate_schema_bytes(identity, schema_bytes())


@pytest.mark.parametrize(
    "mutation", ["v1", "tool", "profile", "extra", "role", "bool", "version", "space"]
)
def test_identity_rejects_non_provider_or_malformed(mutation):
    from app.extensions.provider_identity import (
        parse_provider_build_identity,
        ProviderIdentityError,
    )

    value = deepcopy(identity_mapping())
    if mutation == "v1":
        value["schema_version"] = "extension-build-identity-v1"
    if mutation == "tool":
        value["port_contract_version"] = "tool-port-v1"
    if mutation == "profile":
        value["worker_profile"] = "other"
    if mutation == "extra":
        value["authority"] = True
    if mutation == "role":
        value["port_schemas"].reverse()
    if mutation == "bool":
        value["entrypoint"]["size_bytes"] = True
    if mutation == "version":
        value["extension_version"] = "2147483648.0.0"
    raw = encoded(value) + (b" " if mutation == "space" else b"")
    with pytest.raises(ProviderIdentityError):
        parse_provider_build_identity(raw)


def test_schema_validator_rejects_hollow_wrong_type_and_byte_drift():
    from app.extensions.provider_identity import (
        ProviderBuildIdentity,
        ProviderIdentityError,
        parse_provider_build_identity,
        validate_provider_schema_bytes,
    )

    identity = parse_provider_build_identity(encoded(identity_mapping()))
    for value, files in [
        (object.__new__(ProviderBuildIdentity), schema_bytes()),
        (identity, tuple(reversed(schema_bytes()))),
        (identity, (*schema_bytes()[:3], b"changed")),
        (identity, list(schema_bytes())),
    ]:
        with pytest.raises(ProviderIdentityError):
            validate_provider_schema_bytes(value, files)
    with pytest.raises(TypeError):
        ProviderBuildIdentity()


def test_export_matches_shipped_new_schema():
    from app.extensions.provider_identity_schema_exports import (
        provider_build_identity_schema,
    )

    path = (
        Path(__file__).resolve().parents[2]
        / "schemas/v2/extensions/provider-build-identity-v2.schema.json"
    )
    assert json.loads(path.read_bytes()) == provider_build_identity_schema()
