"""Independent process upload ownership and fail-closed file discipline."""
import os
import subprocess
import sys

import pytest

from app.services.owner_material_upload_lock import UploadLock
from app.services.works import WorkServiceError


def test_independent_holder_contends_and_abrupt_exit_releases_same_inode(tmp_path):
    os.chmod(tmp_path, 0o700)
    code = "from app.services.owner_material_upload_lock import UploadLock; import sys; lock=UploadLock(sys.argv[1]); print('held',flush=True); sys.stdin.read()"
    process = subprocess.Popen([sys.executable, "-B", "-c", code, str(tmp_path)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        import select
        assert select.select([process.stdout], [], [], 5)[0]
        assert process.stdout.readline() == "held\n"
        inode = (tmp_path / "owner-material-upload.lock").stat().st_ino
        with pytest.raises(WorkServiceError, match="capacity"):
            UploadLock(tmp_path)
        process.kill()
        process.wait(timeout=5)
        lock = UploadLock(tmp_path)
        lock.close()
        assert (tmp_path / "owner-material-upload.lock").stat().st_ino == inode
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


@pytest.mark.parametrize("case", ["symlink", "hardlink", "mode", "nonempty", "directory", "parent_mode"])
def test_unsafe_lock_paths_are_refused_without_repair(tmp_path, case):
    os.chmod(tmp_path, 0o700)
    path = tmp_path / "owner-material-upload.lock"
    if case == "symlink":
        target = tmp_path / "target"
        target.write_bytes(b"")
        path.symlink_to(target)
    elif case == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"x" if case == "nonempty" else b"")
        path.chmod(0o644 if case == "mode" else 0o600)
        if case == "hardlink":
            os.link(path, tmp_path / "alias")
        if case == "parent_mode":
            tmp_path.chmod(0o755)
    before = path.lstat()
    with pytest.raises(WorkServiceError, match="unavailable"):
        UploadLock(tmp_path)
    after = path.lstat()
    assert (after.st_ino, after.st_mode, after.st_size) == (before.st_ino, before.st_mode, before.st_size)
