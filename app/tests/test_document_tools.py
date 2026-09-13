"""US3 bounded declarative document creation with real render inspection.

DOCX, CSV and JSON creation is declarative and bounded; every render is
verified by REOPENING the produced file and inspecting its actual content —
a file's existence is never the evidence (SC-004). Formula-looking CSV
values remain data: the default writer preserves them verbatim, and the
optional safe-spreadsheet export records every escaping transformation it
applied. Format validation sniffs real bytes, not extensions: JSON bytes
declared as DOCX refuse, NUL-poisoned text refuses, and a plain ZIP is not
a DOCX (runtime.md §6 artifact tools; T044 partial — PDF/image rendering
needs libraries this environment does not carry and stays deferred).
"""

import json

import pytest

from app.adapters.documents import (
    DocumentToolError,
    render_csv,
    render_docx,
    render_json,
    validate_format,
)


def docx_spec(**overrides):
    value = {
        "title": "주간 대본 보고",
        "paragraphs": [
            "research 노드가 수집한 출처 요약이다.",
            "writer 노드의 최종 대본 개요이다.",
        ],
        "tables": [
            {
                "rows": [
                    ["항목", "값"],
                    ["출처 수", "12"],
                ],
            },
        ],
    }
    value.update(overrides)
    return value


def test_docx_renders_and_is_inspected_by_reopening(tmp_path):
    path = tmp_path / "report.docx"
    report = render_docx(docx_spec(), path)
    # the report's facts come from REOPENING the produced file
    assert report.paragraph_count >= 3  # title + two paragraphs
    assert report.table_count == 1
    assert report.inspected_cells[("t0", 1, 1)] == "12"
    assert report.byte_length == path.stat().st_size
    assert len(report.sha256) == 64
    from docx import Document

    reopened = Document(str(path))
    texts = [p.text for p in reopened.paragraphs]
    assert "research 노드가 수집한 출처 요약이다." in texts


def test_docx_bounds_are_enforced(tmp_path):
    with pytest.raises(DocumentToolError):
        render_docx(docx_spec(paragraphs=["x"] * 501), tmp_path / "a.docx")
    with pytest.raises(DocumentToolError):
        render_docx(docx_spec(
            tables=[{"rows": [["c"] * 51]}],
        ), tmp_path / "b.docx")
    with pytest.raises(DocumentToolError):
        render_docx(docx_spec(paragraphs=["y" * 10_000]), tmp_path / "c.docx")
    with pytest.raises(DocumentToolError):
        render_docx({"unexpected": True}, tmp_path / "d.docx")


def test_csv_keeps_formula_looking_values_as_data(tmp_path):
    path = tmp_path / "table.csv"
    rows = [["name", "total"], ["=SUM(A1:A9)", "+82"], ["@cmd", "-3"]]
    report = render_csv(rows, path)
    assert report.transformations == ()  # data stays data by default
    import csv as _csv

    with open(path, newline="", encoding="utf-8") as handle:
        read_back = list(_csv.reader(handle))
    assert read_back == rows  # verified by reopening, byte-faithful


def test_safe_spreadsheet_export_records_every_transformation(tmp_path):
    path = tmp_path / "safe.csv"
    rows = [["=SUM(A1)", "plain"], ["ok", "@risky"]]
    report = render_csv(rows, path, safe_spreadsheet=True)
    assert report.transformations == (
        (0, 0, "prefixed_apostrophe"),
        (1, 1, "prefixed_apostrophe"),
    )
    import csv as _csv

    with open(path, newline="", encoding="utf-8") as handle:
        read_back = list(_csv.reader(handle))
    assert read_back[0][0] == "'=SUM(A1)"
    assert read_back[0][1] == "plain"


def test_json_round_trips_and_bounds(tmp_path):
    path = tmp_path / "value.json"
    value = {"이름": "DeepTwin", "숫자": [1, 2, 3]}
    report = render_json(value, path)
    assert report.byte_length == path.stat().st_size
    assert json.loads(path.read_text(encoding="utf-8")) == value
    with pytest.raises(DocumentToolError):
        render_json({"nan": float("nan")}, tmp_path / "bad.json")
    deep = value
    for _ in range(100):
        deep = [deep]
    with pytest.raises(DocumentToolError):
        render_json(deep, tmp_path / "deep.json")


def test_format_validation_sniffs_real_bytes(tmp_path):
    docx_path = tmp_path / "real.docx"
    render_docx(docx_spec(), docx_path)
    assert validate_format(docx_path, "docx") is True
    json_path = tmp_path / "fake.docx"
    json_path.write_text('{"not": "a docx"}', encoding="utf-8")
    with pytest.raises(DocumentToolError):
        validate_format(json_path, "docx")
    import zipfile

    plain_zip = tmp_path / "plain.docx"
    with zipfile.ZipFile(plain_zip, "w") as archive:
        archive.writestr("hello.txt", "not a document")
    with pytest.raises(DocumentToolError):
        validate_format(plain_zip, "docx")  # a plain zip is not a DOCX
    nul_csv = tmp_path / "evil.csv"
    nul_csv.write_bytes(b"a,b\x00c\n")
    with pytest.raises(DocumentToolError):
        validate_format(nul_csv, "csv")
    good_csv = tmp_path / "good.csv"
    render_csv([["a", "b"]], good_csv)
    assert validate_format(good_csv, "csv") is True
    with pytest.raises(DocumentToolError):
        validate_format(docx_path, "json")
    with pytest.raises(DocumentToolError):
        validate_format(docx_path, "pdf")  # unsupported here stays explicit
