from __future__ import annotations

import pytest

from deeptwin.errors import DeeptwinError
from deeptwin.llm import FakeProvider, Provider


def test_answers_in_order() -> None:
    provider = FakeProvider(["첫 답", "둘째 답"])

    assert provider.complete("지침 1", "과제 1") == "첫 답"
    assert provider.complete("지침 2", "과제 2", temperature=0.5, timeout=3) == "둘째 답"
    assert provider.calls == [("지침 1", "과제 1"), ("지침 2", "과제 2")]


def test_raises_when_answers_run_out() -> None:
    provider = FakeProvider(["하나뿐인 답"])
    provider.complete("지침", "과제")

    with pytest.raises(DeeptwinError) as info:
        provider.complete("지침", "과제")

    assert info.value.code == "fake_answers_exhausted"
    assert provider.calls == [("지침", "과제")]


def test_raises_without_answers() -> None:
    with pytest.raises(DeeptwinError) as info:
        FakeProvider([]).complete("지침", "과제")

    assert info.value.code == "fake_answers_exhausted"


def test_fake_provider_is_a_provider() -> None:
    provider = FakeProvider(["답"])

    assert isinstance(provider, Provider)
    assert provider.name == "fake"


def test_other_objects_are_not_providers() -> None:
    assert not isinstance(object(), Provider)
