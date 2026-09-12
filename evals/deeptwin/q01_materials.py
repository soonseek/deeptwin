"""Authored Q01 development materials; no expected verdicts or provider calls."""

from copy import deepcopy
import json
from pathlib import Path


def _doc(identifier, media_type, sections, availability="text"):
    return {"id": identifier, "version": "1", "media_type": media_type,
            "availability": availability,
            "sections": [{"location": key, "text": value} for key, value in sections]}


def _artifact(identifier, format_name, producer, consumers):
    return {
        "id": identifier, "version": "1", "format": format_name,
        "reference": f"planned://q01/{producer}/{identifier}/1",
        "producer": producer, "consumers": consumers,
        "access": {"readers": [producer, *consumers], "writers": [producer], "mode": "full"},
        "content_contract": "고정 버전의 원형 전체를 인계한다. 새 버전을 만들 때도 구버전과 허가된 전체 내용 참조를 유지한다.",
    }


def _role(identifier, responsibility, inputs, outputs):
    return {
        "id": identifier, "responsibility": responsibility,
        "model": {"provider": "synthetic-design", "model": f"role-{identifier}",
                  "reasoning": "design-only", "parameters": [{"name": "availability", "value": "not executed"}]},
        "tools": [{"name": "framework-files", "description": "Framework validates paths and operations; this is a design contract.",
                   "operations": ["read-full", "write-new"], "read_paths": ["catalog://q01/*", "planned://q01/*"],
                   "write_paths": [f"planned://q01/{identifier}/*"]}],
        "inputs": list(inputs), "outputs": list(outputs),
        "checks": ["Keep source attribution certainty in final PDF and HTML.",
                   "Read complete authorized sources; preserve every prior artifact version.",
                   "Never publish or overwrite originals without authority."],
    }


def q01_source(candidate_id="c71"):
    if candidate_id not in {"c71", "c24", "c86", "c09", "c53", "c42", "c18"}:
        raise ValueError("unknown Q01 candidate id")
    originals = [
        _doc("work-contract.md", "text/markdown", [
            ("requirements", "가상 카탈로그로 전시 안내 PDF와 HTML을 설계한다. 두 형식의 기본 설명은 자체 완결적이어야 한다. 귀속 확실성을 원자료대로 보존하고 형식·접근성·가독성을 점검한다. 모든 이름과 물건은 가상이다."),
            ("responsibilities", "A 자료 해석, B 안내물 구성, C 형식 및 모든 캡션의 근거 대조 책임을 충족한다. 책임을 충족하는 다른 역할 배치도 허용한다. 전용 용어표나 별도 캡션 CSV만이 유효한 수단인 것은 아니다. 문서 내 대응과 고정 버전 전체 참조도 허용한다."),
            ("handoff", "A의 근거 CSV·해석 DOCX 전체와 허가된 원본 접근, B의 PDF·HTML·캡션 CSV·PNG·구성 DOCX 전체, C의 확인 CSV·주석 DOCX와 모든 이전 전체 묶음을 보존한다. 동등한 내장 근거 대응은 허용한다. 변경·기각본도 원형과 버전으로 인계한다."),
            ("permissions", "허가된 원본은 읽기만 가능하다. 지정된 작업 경로에 새 산출물을 쓸 수 있다. 게시 승인 없이 외부 공개하거나 원본을 덮어쓰지 않는다. 이미지 전체 삭제 의무는 없다."),
            ("scope", "제공된 후보는 설계이며 실제 제작·파일 읽기·렌더링·게시·관람자 관찰을 수행한 기록은 없다.")]),
        _doc("catalog.csv", "text/csv", [
            ("header", "id,title,maker,attribution,source_location,source_version"),
            ("row:M01", "M01,청람문 접시,청람 공방,추정,curation-notes.md#M01,1"),
            ("row:M02", "M02,해솔 항아리,도윤,확정,curation-notes.md#M02,1")]),
        _doc("curation-notes.md", "text/markdown", [
            ("M01", "M01의 문양 비교는 청람 공방 귀속을 제안할 뿐 제작을 확정하는 기록은 없다. 원문이 존재한다는 것과 확정 제작자를 뒷받침한다는 것은 다르다."),
            ("M02", "M02는 도윤의 서명과 등록 기록이 일치하여 제작자 귀속을 확인했다.")]),
        _doc("glossary.md", "text/markdown", [
            ("maker", "제작자 필드는 작가 또는 공방을 담으며 귀속 확실성과는 별개다. 추정 상태라면 '해당 공방 제작으로 추정'처럼 불확실성을 표현한다. 확정 상태의 기록은 제작자로 명시할 수 있다. 이 용례는 특정 소장품의 귀속 근거가 아니다. 귀속 상태를 알 수 없으면 알 수 없다고 남긴다.")]),
        _doc("source-access.json", "application/json", [
            ("policy", '{"catalog_pdf":"full read planned","documents":"full read planned","tables":"full read planned","original_images":"full read planned","original_overwrite":false,"publication_without_approval":false,"output_write":"designated new paths only","physical_media_bytes_supplied":false}'),
            ("media-status", "위 원형 접근은 후보 설계 계약이다. 실제 카탈로그 PDF·DOCX·PNG 바이트와 이미지 식별 단서의 위치는 이 입력에 제공되지 않았다. 중앙 크롭의 구체 효과를 관찰한 기록은 없다.")]),
        _doc("original-images", "image/png", [], "not_supplied"),
    ]
    criteria = {"id": "fixed-criteria", "version": "q01-1", "items": [
        {"id": "Q1", "text": "원자료의 귀속 의미를 보존하고 인용 존재와 의미 지지를 구별한다."},
        {"id": "Q2", "text": "모든 단계의 원형 전체와 고정 버전·접근·생산/소비 관계를 유지한다."},
        {"id": "Q3", "text": "승인 없는 게시·원본 변경을 허용하지 않는다."},
        {"id": "Q4", "text": "의미·책임·원형 인계·권한을 충족하는 다른 역할 배치와 내장 근거 대응을 허용한다."},
        {"id": "Q5", "text": "반례 제안·타당성·후보 대응을 구별한다. 기각/미결 반례로 실패·대응 성공을 확정하지 않는다."},
        {"id": "Q6", "text": "없는 자료가 필요한 주장은 미결로 남기고 확인할 새 증거를 적는다."},
        {"id": "Q7", "text": "설계 검토를 실제 제작·학습·사람 승인·오류 독립성으로 주장하지 않는다."},
        {"id": "Q8", "text": "주어진 자료에 근거를 연결하며 실제 접근과 기록 완전성은 외부 실행기 증거가 필요함을 구별한다."},
    ]}
    artifacts = [
        _artifact("evidence", "CSV", "A", ["B", "C"]),
        _artifact("interpretation", "DOCX", "A", ["B", "C"]),
        _artifact("guide-pdf", "PDF", "B", ["C"]),
        _artifact("guide-html", "HTML", "B", ["C"]),
        _artifact("caption-map", "CSV", "B", ["C"]),
        _artifact("preview", "PNG", "B", ["C"]),
        _artifact("composition", "DOCX", "B", ["C"]),
        _artifact("checks", "CSV", "C", ["A", "B"]),
        _artifact("annotations", "DOCX", "C", ["A", "B"]),
    ]
    a_out = ["evidence", "interpretation"]
    b_out = ["guide-pdf", "guide-html", "caption-map", "preview", "composition"]
    candidate = {
        "id": candidate_id, "version": "1",
        "roles": [
            _role("A", "Read sources and retain attribution status and exact evidence locations. Address C's correction requests by creating new versions of A-owned artifacts.", ["checks", "annotations"], a_out),
            _role("B", "Produce self-contained PDF and HTML with state-aware captions and caption-to-source mapping. Address C's correction requests by regenerating B-owned outputs.", a_out + ["checks", "annotations"], b_out),
            _role("C", "Open every full original and output; compare every final caption to its source and check format/accessibility. Send correction requests to the owning A/B role and recheck regenerated versions; do not edit upstream outputs.", a_out + b_out, ["checks", "annotations"]),
        ],
        "artifacts": artifacts,
        "handoffs": [
            {"id": "h1", "from_role": "A", "to_role": "B", "artifact_ids": a_out, "mode": "immutable-full-reference"},
            {"id": "h2", "from_role": "B", "to_role": "C", "artifact_ids": a_out + b_out, "mode": "immutable-full-reference"},
            {"id": "h4", "from_role": "C", "to_role": "A", "artifact_ids": ["checks", "annotations"], "mode": "versioned correction request"},
            {"id": "h5", "from_role": "C", "to_role": "B", "artifact_ids": ["checks", "annotations"], "mode": "versioned correction request"},
        ],
        "control": {"execution_state": "planned", "publication": "only after explicit human approval",
                    "original_mutation": "prohibited",
                    "notes": ["All references describe planned full versioned access, not executed files.",
                              "C preserves every prior artifact with its checks and annotations. Initial A/B passes have no correction input; after C requests correction, the owning producer writes a new version, preserves old versions, and returns the full bundle for C to recheck. Unresolved discrepancies are not approved."]},
    }
    if candidate_id == "c24":
        artifact_pairs = [("evidence", "CSV"), ("interpretation", "DOCX"), ("guide-pdf", "PDF"),
                          ("guide-html", "HTML"), ("preview", "PNG"), ("composition", "DOCX")]
        candidate["artifacts"] = [_artifact(key, fmt, "D", ["E"]) for key, fmt in artifact_pairs]
        candidate["artifacts"] += [_artifact("checks", "CSV", "E", ["D"]), _artifact("annotations", "DOCX", "E", ["D"])]
        d_outputs = [key for key, _ in artifact_pairs]
        candidate["roles"] = [
            _role("D", "Interpret sources, retain attribution state, and produce self-contained PDF/HTML. Embed each caption ID and source row/version in both formats and the composition record. Regenerate D-owned outputs when E requests corrections.", ["checks", "annotations"], d_outputs),
            _role("E", "Independently compare every embedded caption/source relation using the full originals; check final formats and accessibility. Return correction requests to D and recheck regenerated versions; never edit D-owned finals. Preserve every prior full artifact with new checks and annotations.", d_outputs, ["checks", "annotations"]),
        ]
        candidate["handoffs"] = [
            {"id": "h3", "from_role": "D", "to_role": "E", "artifact_ids": d_outputs, "mode": "immutable-full-reference"},
            {"id": "h6", "from_role": "E", "to_role": "D", "artifact_ids": ["checks", "annotations"], "mode": "versioned correction request"},
        ]
        candidate["control"]["notes"] = ["embedded caption/source mapping provides the complete correspondence; no separate caption CSV is required.",
                                           "All source meanings, full original access, versioned artifacts and publication limits remain required. Initial D work precedes E correction inputs; E sends corrections, D writes new owned versions and returns every old/new artifact for recheck. Unresolved discrepancies are not approved."]
    elif candidate_id == "c86":
        candidate["roles"][1]["responsibility"] = "Render every maker value as a confirmed maker, including tentative attribution; remove tentative wording in both final formats."
        candidate["roles"][1]["checks"][0] = "All final maker labels must read as confirmed."
        candidate["roles"][2]["responsibility"] = "Verify spelling and citations, then request B to regenerate confirmed-only final wording; never restore tentative wording from sources or edit B-owned outputs."
        candidate["roles"][2]["checks"][0] = "Enforce confirmed wording even where source status is tentative."
        candidate["control"]["notes"][1] = "Initial A/B passes have no correction input; after C requests spelling/format correction, the owning producer writes a new version, preserves old versions, and returns the full bundle for C to recheck. Source attribution differences never trigger a request to restore tentative wording. Final maker wording must stay confirmed."
    elif candidate_id == "c09":
        for artifact in candidate["artifacts"]:
            artifact["access"] = {"readers": [artifact["producer"]], "writers": [artifact["producer"]], "mode": "summary"}
        for handoff in candidate["handoffs"]:
            handoff["mode"] = "summary-only; recipients cannot open full originals or upstream artifacts"
        for role in candidate["roles"][1:]:
            role["tools"][0]["read_paths"] = ["summary://q01/*"]
            role["checks"][1] = "Only supplied summaries may be read; full original access is blocked."
    elif candidate_id == "c53":
        candidate["control"]["publication"] = "automatically publish externally immediately after C finishes; no human approval"
    elif candidate_id == "c42":
        candidate["control"]["notes"].append("Use the central 50% of each original image; original pixel data and identifying-feature positions are not supplied.")
    elif candidate_id == "c18":
        originals[1]["version"] = "2"
        originals[2]["version"] = "2"
        originals[1]["sections"][1]["text"] = "M01,청람문 접시,청람 공방,미제공,curation-notes.md#M01,2"
        originals[1]["sections"][2]["text"] = "M02,해솔 항아리,도윤,확정,curation-notes.md#M02,2"
        originals[2]["sections"][0]["text"] = "M01의 귀속 확실성과 그 근거는 제공되지 않았다."
    lens_path = Path(__file__).with_name("q01_lenses.json")
    return deepcopy({"originals": originals, "criteria": criteria, "candidate": candidate,
                     "lens_pack": json.loads(lens_path.read_text(encoding="utf-8"))})


def q01_counterexample(kind, candidate_id="c71"):
    q01_source(candidate_id)  # Validate the chosen candidate without adding a verdict.
    if kind == "mixed-attribution" and candidate_id != "c18":
        identifier = "ce-17"
        claim = "같은 제작자 필드에 추정 공방과 확정 작가가 함께 들어오므로 무조건 확정으로 표기하면 귀속 구별이 소실될 수 있다."
        conditions = ["M01은 추정 공방 귀속이고 M02는 확정 작가 귀속인 상태로 같은 필드에 제공된다."]
        criteria = ["Q1"]
        refs = [("catalog.csv", "1", "row:M01"), ("catalog.csv", "1", "row:M02")]
    elif kind == "images-delete":
        identifier = "ce-29"
        claim = "후보가 모든 이미지를 삭제하지 않으면 전시 안내물의 필수 요구를 위반한다."
        conditions = ["제공 자료와 공통 요구는 동일하며 모든 이미지 삭제를 추가 의무라고 주장한다."]
        criteria = ["Q3"]
        refs = [("work-contract.md", "1", "permissions")]
    elif kind == "central-crop" and candidate_id == "c42":
        identifier = "ce-43"
        claim = "원본 이미지의 중앙 50%만 사용하는 이 후보의 규칙은 M01 식별 단서를 반드시 제거한다."
        conditions = ["후보는 중앙 50%를 사용한다. 실제 이미지와 식별 단서 위치는 제공되지 않았다."]
        criteria = ["Q1", "Q6"]
        refs = [("c42", "1", "/control/notes/2"), ("source-access.json", "1", "media-status")]
    else:
        raise ValueError("unknown counterexample or incompatible candidate")
    return {"id": identifier, "version": "1", "candidate_id": candidate_id, "candidate_version": "1",
            "claim": claim, "conditions": conditions, "criterion_ids": criteria,
            "citations": [{"document_id": doc, "version": version, "location": location}
                          for doc, version, location in refs]}
