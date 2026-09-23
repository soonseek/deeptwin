"""Keep a deleted file's inode number from being handed to the next file during a test.

Several fixtures map controlled owner identities by `(st_dev, st_ino)`. ext4 gives
a removed file's inode number straight to the next new file, so a file created
later in the same test (an upload lease, a publication stage) could inherit an
identity the fixture registered for a file that no longer exists. While pinning
is installed, an unlink, rmdir or replacing rename of a file whose identity a
fixture registered first opens an `O_PATH` descriptor on it: the inode stays
allocated, so its number cannot be reused, until the test ends and
`close_pins()` releases them. Unregistered files are never pinned, so the
descriptor budgets other tests assert are untouched. Hosts without
`O_PATH` (macOS) do not reuse numbers this way and install nothing.
"""

from __future__ import annotations

import os
import weakref

PINNED: list[int] = []
# the platform's own calls, taken before any fixture wraps them: a pin is never counted
# as a descriptor the code under test opened
_OPEN, _LSTAT = os.open, os.lstat
_MAPS: list[weakref.ref] = []  # identity, not equality: two empty maps are distinct


class IdentityMap(dict):
    """A fixture's `(st_dev, st_ino)` identities; only these inodes are ever pinned."""

    __slots__ = ("__weakref__",)


def _pin(path, dir_fd):
    try:
        info = _LSTAT(path, dir_fd=dir_fd)
        key = info.st_dev, info.st_ino
        if not any(key in mapping for ref in _MAPS if (mapping := ref()) is not None):
            return  # not an identity any fixture registered: nothing to protect
        PINNED.append(_OPEN(path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd))
    except (OSError, TypeError, ValueError):
        pass  # nothing there to pin: the operation itself reports what it must


def pin_deletions(monkeypatch) -> None:
    if not hasattr(os, "O_PATH") or getattr(os.unlink, "_pins_deletions", False):
        return
    unlink, rmdir, rename, replace = os.unlink, os.rmdir, os.rename, os.replace

    def pinned_unlink(path, *, dir_fd=None):
        _pin(path, dir_fd)
        return unlink(path, dir_fd=dir_fd)

    def pinned_rmdir(path, *, dir_fd=None):
        _pin(path, dir_fd)
        return rmdir(path, dir_fd=dir_fd)

    def moving(original):
        def pinned(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
            _pin(dst, dst_dir_fd)  # a replaced destination frees its inode
            return original(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        return pinned

    for function in (pinned_unlink, pinned_rmdir):
        function._pins_deletions = True
    monkeypatch.setattr(os, "unlink", pinned_unlink)
    monkeypatch.setattr(os, "remove", pinned_unlink)
    monkeypatch.setattr(os, "rmdir", pinned_rmdir)
    monkeypatch.setattr(os, "rename", moving(rename))
    monkeypatch.setattr(os, "replace", moving(replace))


def close_pins() -> None:
    while PINNED:
        try:
            os.close(PINNED.pop())
        except OSError:
            pass


def identity_map(monkeypatch) -> IdentityMap:
    """The `(st_dev, st_ino)` identity map of a fixture, with its deletions pinned."""

    pin_deletions(monkeypatch)
    mapping = IdentityMap()
    _MAPS[:] = [ref for ref in _MAPS if ref() is not None]
    _MAPS.append(weakref.ref(mapping))
    return mapping
