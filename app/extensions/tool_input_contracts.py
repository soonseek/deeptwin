"""The ports contract's per-tool artifact-input declaration (T087;
extension-ports.md §3.9 `T-tool`: `ToolArtifactInputContractV1`).

A core-owned ToolDefinition declares exactly what a call of the tool takes as
artifact inputs: either `{mode:none}` or `{mode:bounded, min_items, max_items,
role, allowed_media_types, selector_policy}`. A call's supplied inputs must
match that declaration exactly — the count inside the interval, every entry
the literal role, every media type a listed one, selector nullability as the
policy says — or it is refused before dispatch with one closed reason.

The value and its check are pure (no I/O, no worker or runtime import), so
the dispatcher (control) and the worker each declare their own table of these
values and apply the same check; tests pin the two tables equal. Catalog
membership grants nothing: the check only refuses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "MAX_TOOL_ARTIFACT_INPUTS",
    "MISMATCH_CODES",
    "SELECTOR_POLICIES",
    "ToolArtifactInputContract",
    "ToolInputMismatch",
    "check_tool_inputs",
]

# the ports contract's T-tool bound (the execute wire carries at most 8 today)
MAX_TOOL_ARTIFACT_INPUTS = 32
SELECTOR_POLICIES = frozenset({"forbidden", "optional", "required"})
# closed refusal reasons, in the order the check applies them
MISMATCH_CODES = ("missing_input", "extra_input", "wrong_role", "wrong_media", "selector_mismatch")
# the ports contract's identifier and media-type grammars (port_schema_generator's patterns)
_IDENTIFIER = re.compile(r"[a-z][a-z0-9._:-]{0,127}\Z")
_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+\-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+\-]{0,126}\Z")


class ToolInputMismatch(ValueError):
    """The supplied inputs are not the tool's declaration; `code` says how."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if code not in MISMATCH_CODES:
            raise ValueError("unknown tool input mismatch code")
        super().__init__(f"the supplied inputs are not the tool's input contract: {code}")
        self.code = code


@dataclass(frozen=True, slots=True)
class ToolArtifactInputContract:
    """One closed `ToolArtifactInputContractV1` value."""

    mode: str
    min_items: int = 0
    max_items: int = 0
    role: str | None = None
    allowed_media_types: tuple[str, ...] = ()
    selector_policy: str | None = None

    def __post_init__(self) -> None:
        if self.mode == "none":
            if (self.min_items, self.max_items, self.role, self.allowed_media_types,
                    self.selector_policy) != (0, 0, None, (), None):
                raise ValueError("a mode:none contract carries nothing else")
            return
        if self.mode != "bounded":
            raise ValueError("the contract mode is none or bounded")
        if (type(self.min_items) is not int or type(self.max_items) is not int
                or not 0 <= self.min_items <= self.max_items <= MAX_TOOL_ARTIFACT_INPUTS):
            raise ValueError("the contract bounds are invalid")
        if type(self.role) is not str or _IDENTIFIER.fullmatch(self.role) is None:
            raise ValueError("the contract role is not an identifier")
        media = self.allowed_media_types
        if (type(media) is not tuple or not media
                or any(type(item) is not str or _MEDIA_TYPE.fullmatch(item) is None for item in media)
                or media != tuple(sorted(set(media)))):
            raise ValueError("the contract media types are not a sorted unique non-empty set")
        if self.selector_policy not in SELECTOR_POLICIES:
            raise ValueError("the contract selector policy is outside the closed set")

    @classmethod
    def bounded(cls, *, min_items, max_items, role, allowed_media_types, selector_policy):
        return cls("bounded", min_items, max_items, role, tuple(allowed_media_types), selector_policy)

    def as_dict(self) -> dict:
        """The ports contract's closed object, as a ToolDefinition carries it."""

        if self.mode == "none":
            return {"mode": "none"}
        return {"mode": "bounded", "min_items": self.min_items, "max_items": self.max_items,
                "role": self.role, "allowed_media_types": list(self.allowed_media_types),
                "selector_policy": self.selector_policy}


def check_tool_inputs(contract, inputs) -> None:
    """Refuse (raise `ToolInputMismatch`) unless the supplied inputs — an ordered
    sequence of `(role, media_type, selector)` triples, `selector` None when the
    input names no selection — are exactly what `contract` declares."""

    if type(contract) is not ToolArtifactInputContract:
        raise TypeError("an exact ToolArtifactInputContract is required")
    items = tuple(inputs)
    if any(type(item) is not tuple or len(item) != 3 for item in items):
        raise TypeError("inputs are (role, media_type, selector) triples")
    if len(items) < contract.min_items:
        raise ToolInputMismatch("missing_input")
    if len(items) > contract.max_items:
        raise ToolInputMismatch("extra_input")
    for role, media_type, selector in items:
        if role != contract.role:
            raise ToolInputMismatch("wrong_role")
        if media_type not in contract.allowed_media_types:
            raise ToolInputMismatch("wrong_media")
        if ((contract.selector_policy == "forbidden" and selector is not None)
                or (contract.selector_policy == "required" and selector is None)):
            raise ToolInputMismatch("selector_mismatch")
