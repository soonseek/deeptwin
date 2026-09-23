"""Suite-wide test plumbing (no fixtures of product behaviour live here)."""

import pytest

from app.tests.support.inode_pins import close_pins


@pytest.fixture(autouse=True)
def _release_inode_pins():
    # descriptors pinned by identity-map fixtures (support/inode_pins.py) end with the test
    yield
    close_pins()
