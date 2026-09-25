"""T073: the records GUI constant lists must mirror the server contracts.

app/static/records.mjs carries the closed export-category, missing-reason
and deletion-reason sets for client-side validation; a drift between the
GUI copy and app/operations would let the GUI offer a category the
server refuses (or hide one it supports). This test parses the .mjs
constants and compares them set-for-set against the Python contracts.
"""

import re
from pathlib import Path

from app.operations.export import EXPORT_CATEGORIES, MISSING_REASONS
from app.operations.retention import DELETION_REASONS

_RECORDS = Path(__file__).resolve().parents[1] / "static" / "records.mjs"


def _mjs_list(name):
    source = _RECORDS.read_text(encoding="utf-8")
    match = re.search(
        rf"export const {name} = Object\.freeze\(\[(.*?)\]\);",
        source, re.DOTALL,
    )
    assert match is not None, f"{name} is missing from records.mjs"
    return set(re.findall(r"'([a-z_]+)'", match.group(1)))


def test_export_categories_mirror_the_server_contract():
    assert _mjs_list("EXPORT_CATEGORIES") == set(EXPORT_CATEGORIES)


def test_missing_reasons_mirror_the_server_contract():
    assert _mjs_list("MISSING_REASONS") == set(MISSING_REASONS)


def test_deletion_reasons_mirror_the_server_contract():
    assert _mjs_list("DELETION_REASONS") == set(DELETION_REASONS)


def test_backup_key_modes_mirror_the_manifest_contract():
    # operations.md §5: BackupManifest key_mode instance_backup_key|portable_recovery
    assert _mjs_list("BACKUP_KEY_MODES") == {
        "instance_backup_key", "portable_recovery",
    }


def test_backup_preview_categories_and_reasons_mirror_the_backup_contract():
    from app.operations import backup

    groups = {group for _prefix, group in backup._INCLUDED_GROUPS} | {"work_history", "other_history", "originals"}
    assert _mjs_list("BACKUP_INCLUDED") == groups
    assert _mjs_list("BACKUP_EXCLUDED_REASONS") == set(backup.EXCLUDED_REASONS.values())
    # every category a backup can exclude has a stated reason
    categories = {category for _prefix, category in backup.EXCLUDED} | set(backup.OUT_OF_SCOPE_CATEGORIES)
    assert categories | {"deleted_originals"} == set(backup.EXCLUDED_REASONS)
    assert _mjs_list("RESTORE_REQUIREMENTS") == {
        "new_owner_bootstrap", "recreate_connections_and_service_clients", "review_and_activate_exact_environment"}


def test_retention_vocabularies_mirror_the_retention_service():
    from app.services import retention_cleanup as retention

    assert _mjs_list("RETENTION_CATEGORIES") == set(retention.CATEGORIES)
    assert _mjs_list("RETENTION_KEPT") == set(retention.KEPT)
    assert _mjs_list("RETENTION_OWNER_CLEANUP") == set(retention.OWNER_CLEANUP)
    assert _mjs_list("CLEANUP_REASONS") == set(retention.REASONS)
