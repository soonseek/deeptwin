"""Real local catalog validation followed by structural turn freezing."""

import pytest

from app.model_catalog import ModelCatalog
from app.runtime.gateway import freeze_turn
from app.storage import Store
from app.tests.test_model_payloads import turn_value


class ControlledCodexCatalog:
    def __init__(self, store):
        self.store = store
        self.binding = "session-1:account-1"
        self.models = [self.model("gpt-fixture")]

    @staticmethod
    def model(model_id, efforts=("medium", "fixture-next")):
        return {
            "id": model_id,
            "model": model_id,
            "displayName": model_id,
            "hidden": False,
            "isDefault": True,
            "defaultReasoningEffort": efforts[0],
            "supportedReasoningEfforts": [
                {"reasoningEffort": effort, "description": effort}
                for effort in efforts
            ],
            "inputModalities": ["text"],
        }

    def snapshot(self):
        return {"connection": {"state": "connected"}, "billing": "subscription"}

    def read_model_catalog(self):
        with self.store._connection() as db:
            db.execute(
                """INSERT INTO model_catalog_account_state VALUES (?, ?)
                ON CONFLICT(provider) DO UPDATE SET binding = excluded.binding""",
                ("codex", self.binding),
            )
        return {
            "pages": [{"data": self.models, "nextCursor": None}],
            "binding": self.binding,
        }


@pytest.fixture
def controlled_catalog(tmp_path):
    store = Store(tmp_path)
    source = ControlledCodexCatalog(store)
    return ModelCatalog(store, source), source


def choice(catalog, *, model="gpt-fixture", effort="fixture-next"):
    return {
        "provider": "codex",
        "mode": "subscription",
        "catalog_id": catalog["catalog_id"],
        "model": model,
        "effort": effort,
    }


def freeze_validated_choice(validated):
    return freeze_turn(
        turn_value(
            provider="codex_subscription",
            model_id=validated["model"],
            effort=validated["effort"],
        )
    )


@pytest.mark.parametrize(
    "effort",
    (
        "ordinary",
        "Case Preserved",
        " leading and trailing ",
        "punctuation !?/+",
        "노력 단계",
        "e\u0301",
        "line\nbreak",
        "nul\x00value",
        "e" * 80,
    ),
)
def test_provider_advertised_effort_survives_real_catalog_validation_and_freeze(
    controlled_catalog, effort,
):
    subject, source = controlled_catalog
    source.models = [source.model("gpt-fixture", efforts=(effort,))]
    catalog = subject.refresh("codex")

    validated = subject.validate_choice(choice(catalog, effort=effort))
    frozen = freeze_validated_choice(validated)

    assert validated["validated_catalog_id"] == catalog["catalog_id"]
    assert frozen.model_id == "gpt-fixture"
    assert frozen.effort == effort


def test_explicit_none_survives_real_catalog_validation_and_freeze(controlled_catalog):
    subject, _ = controlled_catalog
    catalog = subject.refresh("codex")

    validated = subject.validate_choice(choice(catalog, effort=None))

    assert freeze_validated_choice(validated).effort is None


def test_real_catalog_rejects_well_shaped_unadvertised_effort(controlled_catalog):
    subject, _ = controlled_catalog
    catalog = subject.refresh("codex")

    with pytest.raises(ValueError, match="unknown|unsupported"):
        subject.validate_choice(choice(catalog, effort="not-advertised"))


@pytest.mark.parametrize("effort", [True, 1, {}, [], "", "e" * 81])
def test_real_catalog_rejects_invalid_effort_shape(controlled_catalog, effort):
    subject, _ = controlled_catalog
    catalog = subject.refresh("codex")

    with pytest.raises(ValueError, match="Invalid model choice"):
        subject.validate_choice(choice(catalog, effort=effort))


def test_real_catalog_rejects_choice_after_model_removal(controlled_catalog):
    subject, source = controlled_catalog
    original = subject.refresh("codex")
    selected = choice(original)
    source.models = [source.model("gpt-replacement")]

    subject.refresh("codex")

    with pytest.raises(ValueError, match="current catalog"):
        subject.validate_choice(selected)


def test_real_catalog_rejects_choice_after_binding_change(controlled_catalog):
    subject, source = controlled_catalog
    original = subject.refresh("codex")
    selected = choice(original)
    source.binding = "session-2:account-2"

    subject.refresh("codex")

    with pytest.raises(ValueError, match="stale|binding changed"):
        subject.validate_choice(selected)
