"""Pure originals-only profiles. Syntax and byte indications grant no read authority."""
import re
import unicodedata

from .refs import DomainContractError, EntityRef, positive_integer, uuid_string

MAX_FILE_BYTES = 10_485_760
MAX_SOURCES = 20
MAX_WORK_BYTES = 52_428_800
UPLOAD_SCHEMA = "owner-source-upload-v1"
ARTIFACT_SCHEMA = "source-original-artifact-v1"
SOURCE_SCHEMA = "owner-upload-source-v1"
REVISION_SCHEMA = "work-revision-v2"
MIME = r"[a-z0-9][a-z0-9!#$&^_.+\-]*/[a-z0-9][a-z0-9!#$&^_.+\-]*"
UPLOAD_FIELDS = {"schema_version", "command_id", "expected_revision", "name", "declared_media_type", "size", "sha256"}


def display_name(value):
    if (type(value) is not str or not 1 <= len(value.encode("utf-8")) <= 255
            or value in {".", ".."} or any(c in "/\\" or unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in value)):
        raise DomainContractError("Invalid original display name")
    return value


def declared_mime(value):
    if type(value) is not str or len(value) > 127 or re.fullmatch(MIME, value, flags=re.ASCII) is None:
        raise DomainContractError("Invalid declared media type")
    return value


def validate_upload(value):
    if type(value) is not dict or set(value) != UPLOAD_FIELDS or value["schema_version"] != UPLOAD_SCHEMA:
        raise DomainContractError("Expected closed original upload metadata")
    uuid_string(value["command_id"])
    positive_integer(value["expected_revision"])
    display_name(value["name"])
    declared_mime(value["declared_media_type"])
    if (type(value["size"]) is not int or not 0 <= value["size"] <= MAX_FILE_BYTES
            or type(value["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None):
        raise DomainContractError("Invalid original size/digest")
    return dict(value)


def indicate(data):
    """Only a bounded prefix signature; never a parser, format or polyglot validator."""
    prefix = data[:4096]
    stripped = prefix.lstrip().lower()
    matches = []
    for media, found in (
        ("application/pdf", prefix.startswith(b"%PDF-")),
        ("image/png", prefix.startswith(b"\x89PNG\r\n\x1a\n")),
        ("image/jpeg", prefix.startswith(b"\xff\xd8\xff")),
        ("application/zip", prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))),
        ("text/html", re.search(rb"<(?:!doctype\s+html|html)(?:\s|>)", stripped) is not None),
        ("image/svg+xml", re.search(rb"<svg(?:\s|>)", stripped) is not None),
    ):
        if found:
            matches.append(media)
    return {"method": "prefix-signature", "version": 1, "inspected_bytes": len(prefix),
            "media_type": matches[0] if len(matches) == 1 else None,
            "confidence": "signature_only" if len(matches) == 1 else "unknown"}


def _exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise DomainContractError("Expected closed original content profile")


def validate_body(body):
    content = body["content"]
    schema = content.get("schema_version")
    if type(schema) is not str or schema not in {ARTIFACT_SCHEMA, SOURCE_SCHEMA, REVISION_SCHEMA}:
        return  # unrelated and historical generic content remains valid
    if body["purpose"] != "operational":
        raise DomainContractError("Originals require operational purpose")
    if schema == ARTIFACT_SCHEMA:
        from .store import BlobRef

        _exact(content, ("schema_version", "blob_ref", "size", "sha256", "name", "declared_media_type",
                         "media_indication", "format_validation", "origin", "availability", "rights"))
        blob = BlobRef.from_dict(content["blob_ref"])
        if (body["kind"] != "artifact" or body["version"] != 1 or body["parent_refs"]
                or blob.purpose != "operational" or type(content["size"]) is not int
                or content["size"] != blob.size or blob.size > MAX_FILE_BYTES
                or content["sha256"] != blob.sha256 or content["format_validation"] != "not_performed"
                or content["origin"] != "owner_upload" or content["availability"] != "stored"
                or content["rights"] is not None):
            raise DomainContractError("Invalid original artifact")
        display_name(content["name"])
        declared_mime(content["declared_media_type"])
        indication = content["media_indication"]
        _exact(indication, ("method", "version", "inspected_bytes", "media_type", "confidence"))
        if (indication["method"] != "prefix-signature" or type(indication["version"]) is not int
                or indication["version"] != 1 or type(indication["inspected_bytes"]) is not int
                or indication["inspected_bytes"] != min(blob.size, 4096)
                or indication["media_type"] not in {None, "application/pdf", "image/png", "image/jpeg", "application/zip", "text/html", "image/svg+xml"}
                or indication["confidence"] != ("unknown" if indication["media_type"] is None else "signature_only")):
            raise DomainContractError("Invalid bounded indication")
    elif schema == SOURCE_SCHEMA:
        _exact(content, ("schema_version", "artifact_ref", "work_id", "upload_command_id", "supplied_by",
                         "source_kind", "acquisition_event_sequence", "name", "rights"))
        artifact = EntityRef.from_dict(content["artifact_ref"])
        uuid_string(content["work_id"])
        uuid_string(content["upload_command_id"])
        positive_integer(content["acquisition_event_sequence"])
        display_name(content["name"])
        if (body["kind"] != "source" or body["version"] != 1 or artifact.kind != "artifact"
                or body["parent_refs"] != [content["artifact_ref"]]
                or content["supplied_by"] != body["actor_ref"] or content["source_kind"] != "upload"
                or content["rights"] is not None):
            raise DomainContractError("Invalid owner source lineage")
    else:
        _exact(content, ("schema_version", "work_id", "revision", "command_id", "text", "source_refs", "input_origin"))
        uuid_string(content["command_id"])
        refs = content["source_refs"]
        if (body["kind"] != "work_revision" or content["work_id"] != body["id"]
                or type(content["revision"]) is not int or content["revision"] != body["version"]
                or type(content["text"]) is not str or len(content["text"]) > 20000
                or len(content["text"].encode()) > 65536 or content["input_origin"] not in {"owner_text", "owner_material"}
                or type(refs) is not list or len(refs) > MAX_SOURCES
                or any(EntityRef.from_dict(ref).kind != "source" for ref in refs)
                or len({EntityRef.from_dict(ref) for ref in refs}) != len(refs)):
            raise DomainContractError("Invalid owner work revision")
        parents = body["parent_refs"]
        if body["version"] == 1:
            valid_parent = not parents
        else:
            valid_parent = (len(parents) == 1 and parents[0]["kind"] == "work_revision"
                            and parents[0]["id"] == body["id"] and parents[0]["version"] == body["version"] - 1)
        if not valid_parent or (not content["text"] and not refs and content["input_origin"] != "owner_material"):
            raise DomainContractError("Invalid owner revision ancestry or empty text")


def content_schemas():
    from .schema_exports import _constant, _enum, _hash, _object, _positive, _ref, _uuid

    name = {"type": "string", "minLength": 1, "maxLength": 255,
            "$comment": "Runtime enforces 255 UTF-8 bytes and excludes dot names, separators and Unicode Cc/Cf/Cs."}
    mime = {"type": "string", "maxLength": 127, "pattern": "^" + MIME + "$"}
    size = {"type": "integer", "minimum": 0, "maximum": MAX_FILE_BYTES}
    blob = _object({"vault_id": _uuid(), "purpose": _constant("operational"), "sha256": _hash(), "size": size})
    indication = _object({"method": _constant("prefix-signature"), "version": _constant(1),
                         "inspected_bytes": {"type": "integer", "minimum": 0, "maximum": 4096},
                         "media_type": {"enum": [None, "application/pdf", "image/png", "image/jpeg", "application/zip", "text/html", "image/svg+xml"]},
                         "confidence": _enum(["signature_only", "unknown"])})
    return {
        ARTIFACT_SCHEMA: ("artifact", _object({"schema_version": _constant(ARTIFACT_SCHEMA), "blob_ref": blob,
            "size": size, "sha256": _hash(), "name": name, "declared_media_type": mime, "media_indication": indication,
            "format_validation": _constant("not_performed"), "origin": _constant("owner_upload"),
            "availability": _constant("stored"), "rights": {"type": "null"}})),
        SOURCE_SCHEMA: ("source", _object({"schema_version": _constant(SOURCE_SCHEMA), "artifact_ref": _ref("artifact"),
            "work_id": _uuid(), "upload_command_id": _uuid(), "supplied_by": _ref("actor"),
            "source_kind": _constant("upload"), "acquisition_event_sequence": _positive(), "name": name,
            "rights": {"type": "null"}})),
        REVISION_SCHEMA: ("work_revision", _object({"schema_version": _constant(REVISION_SCHEMA), "work_id": _uuid(),
            "revision": _positive(), "command_id": _uuid(), "text": {"type": "string", "maxLength": 20000},
            "source_refs": {"type": "array", "maxItems": MAX_SOURCES, "uniqueItems": True, "items": _ref("source")},
            "input_origin": _enum(["owner_text", "owner_material"])})),
    }
