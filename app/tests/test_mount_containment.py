"""The boundary checks' containment helper agrees exactly with ``is_relative_to``."""

from pathlib import Path, PurePosixPath

from hypothesis import given, settings
from hypothesis import strategies as st

from app.deployment import mounts as m

_segment = st.sampled_from(["run", "deeptwin", "a", "ab", "b", "run-x", "."])


def _path(absolute, segments):
    text = "/".join(segments)
    return Path(("/" if absolute else "") + text) if text or absolute else Path(".")


@settings(max_examples=2000, deadline=None)
@given(
    st.booleans(),
    st.lists(_segment, max_size=5),
    st.booleans(),
    st.lists(_segment, max_size=5),
)
def test_within_matches_is_relative_to(path_abs, path_parts, root_abs, root_parts):
    path, root = _path(path_abs, path_parts), _path(root_abs, root_parts)
    assert m.within(path, root) is path.is_relative_to(root)


def test_within_edges():
    assert m.within(Path("/run/deeptwin"), Path("/run"))
    assert m.within(Path("/run"), Path("/run"))
    assert m.within(Path("/run"), Path("/"))
    assert not m.within(Path("/run-x"), Path("/run"))
    assert not m.within(Path("/run"), Path("/run/deeptwin"))
    assert not m.within(Path("/run"), Path("."))
    assert m.within(Path("a"), Path("."))
    assert not m.within(Path("a"), Path("/"))
    assert m.within(PurePosixPath("/x/y"), Path("/x"))
