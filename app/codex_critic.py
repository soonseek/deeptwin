"""Internal raw critic transport; not a parser, judge, runner, or public API."""

from .codex_understanding import _CodexIsolatedModel
from .generation_profiles import GenerationPurpose


_CRITIC_PURPOSES = frozenset({
    GenerationPurpose.REVIEW,
    GenerationPurpose.COUNTEREXAMPLE_PROPOSAL,
    GenerationPurpose.COUNTEREXAMPLE_VALIDITY,
    GenerationPurpose.CANDIDATE_RESPONSE,
})


class CodexCriticTransport(_CodexIsolatedModel):
    def __init__(
            self, store, *, purpose, rpc_factory=None, timeout=120,
            version_reader=None):
        if type(purpose) is not GenerationPurpose or purpose not in _CRITIC_PURPOSES:
            raise ValueError("unsupported critic purpose")
        super().__init__(
            store,
            rpc_factory=rpc_factory,
            timeout=timeout,
            version_reader=version_reader,
            purpose=purpose,
        )
