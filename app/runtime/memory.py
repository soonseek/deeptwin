"""Policy compilation of active knowledge (US5, T058, FR-021/032).

Compilation turns one active knowledge entry into exactly one allowlisted
target — node instructions, retrieval rules, tool restrictions, handoff
schemas or graph/gate configuration — never a growing prompt and never an
unknown surface. The compiler refuses autonomous relaxation of the protected
requirement classes (constitutional, safety, authority, final human
approval, current tests); ordinary authorized work-policy changes remain
valid candidates but must state before/after criteria. Direct H_phi/S_phi
inputs and current-alternative leakage are blocked both as references and as
verbatim (whitespace-normalized) spans. Every compiled field carries its own
supporting behavior refs. Policies are issued values bound to the exact
knowledge entry; only an *active* issued entry compiles anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain.refs import DomainContractError, EntityRef
from ..services.knowledge import is_issued_knowledge

COMPILATION_TARGETS = frozenset({
    "node_instructions", "retrieval_rules", "tool_restrictions",
    "handoff_schemas", "graph_gate_config",
})
PROTECTED_REQUIREMENTS = frozenset({
    "constitutional", "safety", "authority",
    "final_human_approval", "current_test",
})
_FORBIDDEN_REF_KINDS = frozenset({
    "own_alternative", "difference", "hypothesis", "selector", "inquiry",
})
_WHITESPACE = re.compile(r"\s+")
_ISSUE_TOKEN = object()


class MemoryCompilationError(ValueError):
    """A compilation request is invalid or forbidden."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _text(value, label, maximum):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise MemoryCompilationError(f"invalid {label}")
    return value


def _normalized(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


@dataclass(frozen=True, slots=True, init=False)
class CompiledField:
    """One compiled field with its own behavior provenance."""

    text: str
    provenance: tuple[EntityRef, ...]


@dataclass(frozen=True, slots=True, init=False)
class CompiledPolicy:
    """One knowledge entry compiled into one allowlisted target."""

    knowledge_id: str
    target: str
    fields: tuple[tuple[str, CompiledField], ...]
    removed_requirements: tuple[str, ...]
    before_after_criteria: str | None
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self) -> dict:
        return {
            "schema_version": "compiled-policy-v1",
            "knowledge_id": self.knowledge_id,
            "target": self.target,
            "fields": {
                name: {
                    "text": item.text,
                    "provenance_refs": [
                        ref.as_dict() for ref in item.provenance
                    ],
                }
                for name, item in self.fields
            },
            "removed_requirements": list(self.removed_requirements),
            "before_after_criteria": self.before_after_criteria,
        }


def compile_knowledge(entry, value, *, forbidden_spans=None) -> CompiledPolicy:
    """Compile one active entry into one allowlisted target, or refuse."""

    if not is_issued_knowledge(entry):
        raise MemoryCompilationError(
            "a framework-issued knowledge entry is required"
        )
    if entry.lifecycle != "active":
        # Suspended, superseded or retired knowledge compiles nothing.
        raise MemoryCompilationError(
            "only active knowledge can compile a policy"
        )
    if type(value) is not dict or set(value) != {
        "target", "fields", "removes_requirements", "before_after_criteria",
    }:
        raise MemoryCompilationError(
            "expected the exact compilation request object"
        )
    target = value["target"]
    if target not in COMPILATION_TARGETS:
        raise MemoryCompilationError("unknown compilation target")
    removes = value["removes_requirements"]
    if (
        type(removes) is not list or len(removes) > 16
        or any(type(item) is not str for item in removes)
    ):
        raise MemoryCompilationError("removed requirements are out of bounds")
    for item in removes:
        if item in PROTECTED_REQUIREMENTS:
            raise MemoryCompilationError(
                "protected requirements are never relaxed autonomously"
            )
    criteria = value["before_after_criteria"]
    if removes:
        # Ordinary authorized policy changes stay valid candidates, with
        # stated before/after criteria.
        criteria = _text(criteria, "before/after criteria", 2_048)
    elif criteria is not None and type(criteria) is not str:
        raise MemoryCompilationError("invalid before/after criteria")
    elif criteria is not None:
        criteria = _text(criteria, "before/after criteria", 2_048)

    if forbidden_spans is None:
        forbidden_spans = []
    if type(forbidden_spans) is not list or len(forbidden_spans) > 256:
        raise MemoryCompilationError("forbidden spans are out of bounds")
    forbidden = tuple(
        _normalized(_text(item, "forbidden span", 4_096))
        for item in forbidden_spans
    )

    fields_value = value["fields"]
    if (
        type(fields_value) is not dict
        or not 1 <= len(fields_value) <= 32
    ):
        raise MemoryCompilationError(
            "a compilation requires bounded named fields"
        )
    compiled = []
    for name in sorted(fields_value):
        item = fields_value[name]
        label = _text(name, "field name", 128)
        if type(item) is not dict or set(item) != {"text", "provenance"}:
            raise MemoryCompilationError(
                f"expected the exact {label} field object"
            )
        text = _text(item["text"], f"{label} text", 4_096)
        flattened = _normalized(text)
        for span in forbidden:
            if span and span in flattened:
                # Copying alternative or philosophy wording into an
                # operational surface is the absorption shortcut (G-05).
                raise MemoryCompilationError(
                    f"the {label} text copies forbidden source material"
                )
        provenance = item["provenance"]
        if type(provenance) is not list or not 1 <= len(provenance) <= 32:
            raise MemoryCompilationError(
                f"the {label} field requires behavior provenance"
            )
        refs = []
        for raw in provenance:
            try:
                ref = EntityRef.from_dict(raw)
            except (DomainContractError, TypeError) as exc:
                raise MemoryCompilationError(
                    f"invalid {label} provenance reference"
                ) from exc
            if ref.kind in _FORBIDDEN_REF_KINDS:
                # H_phi/S_phi interpretations and the alternative store are
                # audit material, never compiler input.
                raise MemoryCompilationError(
                    "draft or interpretation stores never enter a policy"
                )
            refs.append(ref)
        compiled.append((label, _issue(
            CompiledField, text=text, provenance=tuple(refs),
        )))
    return _issue(
        CompiledPolicy,
        knowledge_id=entry.knowledge_id,
        target=target,
        fields=tuple(compiled),
        removed_requirements=tuple(removes),
        before_after_criteria=criteria,
        _issuer_token=_ISSUE_TOKEN,
    )


__all__ = [
    "COMPILATION_TARGETS",
    "PROTECTED_REQUIREMENTS",
    "CompiledField",
    "CompiledPolicy",
    "MemoryCompilationError",
    "compile_knowledge",
]
