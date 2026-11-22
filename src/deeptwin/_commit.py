"""빌드한 패키지의 커밋 해시.

저장소에서는 늘 `None`이다. 빌드 훅(`hatch_build.py`)이 sdist와 wheel 안의 이 파일에서만 값을
바꾼다. 읽는 곳은 `deeptwin.provenance.package_commit`이다.
"""

COMMIT: str | None = None
