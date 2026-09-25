"""Test-only support for the T049 controlled producer→consumer E2E (2026-09-25).

The graph (`e2e_graph`): three entry producers run in parallel, an `all_selected` join
gathers them, the owner's gate holds the release, and one consumer reads everything:

- `page-reader` (agent) is bound to the ToolDefinition `browser_read` 1.0.0 and
  `page-shooter` (agent) to `browser_screenshot` 1.0.0. Each dispatches ONE attempt
  through the real `NodeAttemptDispatcher` and the product's `BrowserToolset`
  (`app.state.browser_tools`) to the sandboxed browser worker, which reaches the local
  fixture site only through the fetch service under the owner's persisted browser grant
  record (the compiled binding's `grant_ref`, re-checked against the run's approved
  tool permissions on every dispatch; never a grant supplied in code).
- `documents` (deterministic, handler `documents-render-v1`) renders a PDF, a CSV table
  and a PNG figure with the product's document adapter (`app/adapters/documents.py`:
  reportlab/pypdfium2/Pillow, each output reopened and inspected by the adapter).
- `gather` (join) seals the selection it was given; `release-gate` (human gate) forwards
  it once the owner approved.
- `consumer` (deterministic) receives the FULL bytes of every artifact the selected
  producers' results name — exactly what the run artifact routes list — re-hashes
  each, and consumes it: the page text, the screenshot's and the figure's pixels
  (decoded), the PDF's text layer (extracted by the isolated document worker, the PDF
  sent whole) and every CSV row. Its `report` artifact names each input's exact sha256
  and size, and the result record descends from the producer results.

`RuntimeE2EExecutor` is a code-owned TEST executor (the production executor compiles
no tools). Nothing here calls a model or leaves the machine. Test actor only.
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
import threading
import time
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.domain.permissions import Grant, Principal
from app.domain.refs import EntityRef
from app.domain.schemas import Actor, ImmutableRecord
from app.domain.store import _writer
from app.runtime import node_attempts as na
from app.runtime import scheduler as sch
from app.runtime.graph import compile_graph
from app.runtime.ledger import OwnerIdentity
from app.services.run_artifacts import _entries
from app.workers.browser_channel import BrowserRequest

SITE = "https://granted.test/"
READ_URL = SITE + "report"
SLOW_ONCE_URL = SITE + "slow-once"
SHOT_URL = SITE + "chart"
CONSUMER_SCHEMA = "runtime-e2e-consumer-v1"
DOCUMENTS_SCHEMA = "runtime-e2e-documents-v1"
SELECTION_SCHEMA = "runtime-e2e-selection-v1"
PRODUCERS = ("documents", "page-reader", "page-shooter")
CONTRACT = "run-material"
TABLE_ROWS = [["region", "quarter", "units"], ["north", "Q3", "120"], ["south", "Q3", "75"],
              ["east", "Q3", "42"], ["west", "Q3", "63"]]
DOCUMENT_SPEC = {
    "title": "T049 fixture brief",
    "paragraphs": ["Units shipped per region in Q3, as rendered by the document adapter.",
                   "The consumer extracts this text through the isolated document worker."],
    "tables": [{"rows": TABLE_ROWS}],
}
FIGURE_SPEC = {
    "width": 240, "height": 120, "background": [255, 255, 255],
    "shapes": [{"x": 10, "y": 20, "width": 50, "height": 100, "fill": [200, 30, 30]},
               {"x": 70, "y": 60, "width": 50, "height": 60, "fill": [30, 30, 200]},
               {"x": 130, "y": 90, "width": 50, "height": 30, "fill": [30, 160, 30]}],
}


def e2e_graph(grant_ref: EntityRef, *, recovery=False):
    """The graph, bound to the owner's persisted browser grant record `grant_ref`."""

    from app.tests.support.browser_grant_chain import _replace_grant
    from app.tests.test_graph_contract import (
        approval_edge,
        artifact_edge,
        graph_value,
        input_slot,
        node,
        output_slot,
        ref,
    )

    raw = graph_value()
    reader = "고정 사이트의 보고서 페이지를 읽는다"
    if recovery:
        reader = "첫 읽기가 시한을 넘기는 고정 페이지를 읽는다 (소유자 복구 경로)"

    def agent(node_id, responsibility, tool_binding):
        value = node(node_id, "agent", responsibility, outputs=[output_slot("capture", CONTRACT)])
        value["config"]["tool_binding_ids"] = [tool_binding]
        return value

    raw["nodes"] = [
        agent("page-reader", reader, "page-read"),
        agent("page-shooter", "고정 사이트의 차트 페이지를 캡처한다", "page-shot"),
        node("documents", "deterministic", "PDF·CSV 표·PNG 그림을 만든다",
             outputs=[output_slot("bundle", CONTRACT)], config={"handler_id": "documents-render-v1"}),
        node("gather", "join", "세 생산자의 산출물을 모은다",
             inputs=[input_slot("items", CONTRACT, multiplicity="many")],
             outputs=[output_slot("gathered", CONTRACT)]),
        node("release-gate", "human_gate", "사람이 소비 단계로의 전달을 승인한다",
             inputs=[input_slot("candidate", CONTRACT)], outputs=[output_slot("approved", CONTRACT)]),
        node("consumer", "deterministic", "생산자 산출물 전체를 읽고 정확한 digest로 보고한다",
             inputs=[input_slot("approved", CONTRACT)], outputs=[output_slot("result", CONTRACT)],
             config={"handler_id": "full-artifact-consumer-v1"},
             required_approval_scopes=["release-output"]),
    ]
    raw["entry_node_ids"] = sorted(PRODUCERS)
    raw["edges"] = [
        artifact_edge("p-documents", "documents", "bundle", "gather", "items", CONTRACT, multiplicity="many"),
        artifact_edge("p-reader", "page-reader", "capture", "gather", "items", CONTRACT, multiplicity="many"),
        artifact_edge("p-shooter", "page-shooter", "capture", "gather", "items", CONTRACT, multiplicity="many"),
        artifact_edge("g-gate", "gather", "gathered", "release-gate", "candidate", CONTRACT),
        artifact_edge("g-consumer", "release-gate", "approved", "consumer", "approved", CONTRACT),
        approval_edge("a-consumer", "release-gate", "consumer", "release-output"),
    ]
    raw["artifact_contracts"] = [{
        "artifact_contract_id": CONTRACT,
        "media_types": ["application/json", "application/pdf", "image/png", "text/csv", "text/plain"],
        "schema_ref": None, "min_items": 1, "max_items": 8, "max_total_bytes": 8_388_608,
    }]
    raw["tool_bindings"] = [
        {"binding_id": "page-read", "tool_definition_ref": ref("tool_definition", 4), "grant_ref": ref("grant", 6),
         "capabilities": ["read-source"]},
        {"binding_id": "page-shot", "tool_definition_ref": ref("tool_definition", 5), "grant_ref": ref("grant", 6),
         "capabilities": ["read-source"]},
    ]
    raw["completion_criteria"] = [{"criterion_id": "consumer-report", "node_id": "consumer",
                                   "output_slot": "result", "artifact_contract_id": CONTRACT, "min_items": 1}]
    return _replace_grant(raw, ref("grant", 6), grant_ref.as_dict())


def e2e_authority(grant_ref: EntityRef):
    """Both browser ToolDefinitions require exactly the owner's grant record."""

    from app.runtime.graph import CompilationAuthority
    from app.tests.test_graph_contract import ref, trusted_tool

    definitions = []
    for tool, number in (("browser_read", 4), ("browser_screenshot", 5)):
        definition = list(trusted_tool(tool_id=tool, number=number))
        definition[1] = grant_ref
        definitions.append(tuple(definition))
    return CompilationAuthority.from_trusted(
        model_choices=[(EntityRef.from_dict(ref("model_choice", 3)), ("text",))], tool_definitions=definitions,
        grant_refs=[grant_ref], approval_scopes=["release-output"],
        observation_contract_refs=[EntityRef.from_dict(ref("observation_contract", 7))],
        budget_policy_refs=[EntityRef.from_dict(ref("budget_policy", 8))], artifact_schema_refs=[])


def grant_command():
    """The owner's `browser-grant-command-v1` for the fixture site: the exact pages the
    roles open, pure navigation (no parameters, no source values)."""

    from app.tests.support.browser_grant_chain import future

    return {
        "schema_version": "browser-grant-command-v1", "command_id": str(uuid4()), "label": "T049 고정 사이트 읽기",
        "tools": ["browser_read", "browser_screenshot"], "sources": [SITE], "recipients": ["granted.test"],
        "entries": [{"url": url, "parameters": []} for url in (READ_URL, SHOT_URL, SLOW_ONCE_URL)],
        "data_sources": [],
        "limits": {"max_response_bytes": 1024 * 1024, "max_total_bytes": 4 * 1024 * 1024, "max_requests": 32,
                   "max_redirects": 3, "ttl_ms": 60_000},
        "expires_at_utc": future(),
    }


def _stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime())


def _png_facts(data):
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        image.load()
        rgb = image.convert("RGB")
        width, height = rgb.size
        return {"format": image.format, "width": width, "height": height,
                "center_rgb": list(rgb.getpixel((width // 2, height // 2))),
                "pixels_sha256": sha256(rgb.tobytes()).hexdigest()}


class RuntimeE2EExecutor:
    """Code-owned test executor; `bind` is called once the app exists."""

    def __init__(self, *, codec, state_path: Path):
        self.codec = codec
        self.state_path = state_path
        self.app = None
        self.refs = None
        self.reader_urls = {}
        self.owner = OwnerIdentity(str(uuid4()), 4321, 900, str(uuid4()))
        self._lock = threading.Lock()

    # --- wiring -------------------------------------------------------------------

    def bind(self, app, refs, graphs):
        from app.services.runs import PersistentRuns

        self.app, self.refs = app, refs
        self.grant_ref = EntityRef.from_dict(refs["grant"])
        domain = app.state.domain_store
        for name, raw in graphs.items():
            graph = PersistentRuns._graph(domain.get(EntityRef.from_dict(raw)))
            self.reader_urls[self.compile(graph).graph_digest] = SLOW_ONCE_URL if name == "recovery" else READ_URL

    def compile(self, graph):
        return compile_graph(graph, e2e_authority(self.grant_ref))

    def _context(self, ledger, run_id):
        """One attempt context per run (principal, grant, deadline), persisted so a
        restarted server rebuilds the same bindings."""

        with self._lock:
            state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
            if run_id not in state:
                later = int(time.time() * 1000) + 6 * 3_600_000
                state[run_id] = {"principal": str(uuid4()), "actor": str(uuid4()), "grant": str(uuid4()),
                                 "issuer": str(uuid4()), "deadline": later,
                                 "policy": ledger.get_run(run_id)["spec"]["budget_policy_ref"]}
                self.state_path.write_text(json.dumps(state))
            value = state[run_id]
        envelope = EntityRef.from_dict(self.refs["envelope"])
        principal = Principal(value["principal"], Actor(value["actor"], "test_actor", "test_fixture"), "runtime",
                              "operational", value["deadline"])
        grant = Grant(value["grant"], value["issuer"], principal.id, envelope, "read", "operational", None,
                      value["deadline"], 1)
        return principal, grant, value

    def scheduler(self, compiled, *, ledger, run_id, approvals, retry=False):
        domain = self.app.state.domain_store
        principal, grant, value = self._context(ledger, run_id)
        tools = self.app.state.browser_tools
        requests = {
            "page-reader": ("page-read", BrowserRequest(
                op="read", url=self.reader_urls.get(compiled.graph_digest, READ_URL), max_text_bytes=16_384,
                deadline_ms=3_000 if self.reader_urls.get(compiled.graph_digest) == SLOW_ONCE_URL else 20_000)),
            "page-shooter": ("page-shot", BrowserRequest(op="screenshot", url=SHOT_URL, width=320, height=200,
                                                         deadline_ms=20_000)),
        }
        transports, bindings = {}, {}
        for node_id, (binding_id, request) in requests.items():
            transport = tools.transport_for(domain_store=domain, ledger=ledger, compiled=compiled, node_id=node_id,
                                            binding_id=binding_id, request=request)
            transports[node_id] = transport
            bindings[node_id] = na.AttemptBinding.create(
                envelope_ref=EntityRef.from_dict(self.refs["envelope"]),
                profile_ref=EntityRef.from_dict(self.refs["profile"]),
                budget_policy_ref=EntityRef.from_dict(value["policy"]), deadline_at_ms=value["deadline"],
                lease_duration_ms=60_000, model_calls=0, tool_calls=1, node_visits=1, loop_rounds=0,
                output_bytes=transport.output_bytes_bound, candidates=0, api_microunits=None,
                principal=principal, grant=grant)
        dispatcher = na.NodeAttemptDispatcher.build(
            ledger=ledger, budget_book=self.app.state.budget_book, owner=self.owner, bindings=bindings,
            transports=transports, retry_after_terminal=retry)

        def dispatch(context, view):
            return context.attempt.dispatch()

        def deterministic(context, view):
            if context.node_id == "documents":
                return self._documents(run_id, context)
            if context.node_id == "consumer":
                return self._consume(run_id, context, view)
            raise RuntimeError("unknown deterministic node")

        def join(context, view):
            return self._selection(run_id, context, view)

        def forward(context, view):
            count = view["counters"].get("gather", 0)
            return view["results"][sch.execution_identity(run_id, "gather", count - 1)]

        handlers = {"core.agent": dispatch, "core.deterministic": deterministic, "core.join": join,
                    "core.human_gate": forward}
        return sch.build_scheduler(compiled, ledger=ledger, run_id=run_id,
                                   handlers={key: handlers[key] for _, key in compiled.handler_keys},
                                   approvals=approvals, attempts=dispatcher)

    # --- sealed records (one per visit; a replay finds the first) --------------------

    def _seal(self, record_id, content, parents=()):
        domain = self.app.state.domain_store
        with _writer(), domain._connection(write=True) as db:
            roots = domain._read_roots(db)
            existing = db.execute("SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind='artifact' "
                                  "AND id=?", (roots.genesis.id, record_id)).fetchone()
            if existing is not None:
                return EntityRef("artifact", record_id, existing["version"], existing["sha256"])
            record = ImmutableRecord.create(
                kind="artifact", id=record_id, version=1, created_at_utc=_stamp(), actor_ref=roots.actor,
                parent_refs=tuple(parents), purpose="operational", access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy, content=content)
            domain._put_in_transaction(db, record)
            return record.ref

    def _blob(self, data):
        return self.app.state.domain_store.put_blob(data, purpose="operational").as_dict()

    def _documents(self, run_id, context):
        from app.adapters.documents import render_csv, render_pdf, render_png

        with tempfile.TemporaryDirectory(prefix="dt-t049-documents-") as directory:
            folder = Path(directory)
            reports = {"paper": render_pdf(DOCUMENT_SPEC, folder / "brief.pdf"),
                       "table": render_csv(TABLE_ROWS, folder / "units.csv"),
                       "figure": render_png(FIGURE_SPEC, folder / "figure.png")}
            outputs = [("paper", "application/pdf", (folder / "brief.pdf").read_bytes()),
                       ("table", "text/csv", (folder / "units.csv").read_bytes()),
                       ("figure", "image/png", (folder / "figure.png").read_bytes())]
        artifacts, inspected = [], {}
        for index, (role, media, data) in enumerate(outputs):
            if sha256(data).hexdigest() != reports[role].sha256:
                raise RuntimeError("the adapter's inspected bytes are not the bytes sealed")
            artifacts.append({"ordinal": index, "role": role, "media_type": media, "blob": self._blob(data)})
            inspected[role] = {"sha256": reports[role].sha256, "byte_length": reports[role].byte_length,
                               "media": reports[role].media}
        return self._seal(str(uuid5(NAMESPACE_URL, f"deeptwin:t049:documents:{context.execution_id}")),
                          {"schema_version": DOCUMENTS_SCHEMA, "run_id": run_id, "node_id": context.node_id,
                           "adapter_inspection": inspected, "artifacts": artifacts})

    def _selection(self, run_id, context, view):
        chosen = []
        for source in context.inputs:
            count = view["counters"].get(source, 0)
            chosen.append({"node_id": source,
                           "result_ref": view["results"][sch.execution_identity(run_id, source, count - 1)].as_dict()})
        return self._seal(str(uuid5(NAMESPACE_URL, f"deeptwin:t049:selection:{context.execution_id}")),
                          {"schema_version": SELECTION_SCHEMA, "run_id": run_id, "join": context.node_id,
                           "selected": chosen},
                          parents=[EntityRef.from_dict(item["result_ref"]) for item in chosen])

    def _consume(self, run_id, context, view):
        """Every artifact of every selected producer, whole: bytes re-hashed, then read."""

        domain = self.app.state.domain_store
        sources = sorted(key.split(".", 2)[2] for key in view["counters"] if key.startswith("gather.selected."))
        if sources != sorted(PRODUCERS):
            raise RuntimeError("the join did not select every producer")
        consumed, parents = [], []
        for source in sources:
            ref = view["results"][sch.execution_identity(run_id, source, view["counters"][source] - 1)]
            parents.append(ref)
            record = domain.get(ref)
            for entry in _entries(record):
                blob = entry["blob"]
                data = domain.read_blob(blob, purpose=blob.purpose)
                digest = sha256(data).hexdigest()
                if digest != blob.sha256 or len(data) != blob.size:
                    raise RuntimeError("an input's bytes are not its registered digest")
                consumed.append({"producer": source, "result_ref": ref.as_dict(), "ordinal": entry["ordinal"],
                                 "role": entry["role"], "media_type": entry["media_type"], "sha256": digest,
                                 "size": len(data), "read": self._read(entry, data)})
        report = {"schema_version": CONSUMER_SCHEMA, "run_id": run_id, "inputs": consumed,
                  "input_count": len(consumed)}
        data = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        return self._seal(str(uuid5(NAMESPACE_URL, f"deeptwin:t049:consumer:{context.execution_id}")),
                          {"schema_version": CONSUMER_SCHEMA, "run_id": run_id, "node_id": context.node_id,
                           "consumed_inputs": [{key: item[key] for key in (
                               "producer", "result_ref", "ordinal", "role", "sha256", "size")} for item in consumed],
                           "artifacts": [{"ordinal": 0, "role": "report", "media_type": "application/json",
                                          "blob": self._blob(data)}]},
                          parents=parents)

    def _read(self, entry, data):
        media = entry["media_type"]
        if media == "application/pdf":
            extraction = self.codec.extract_pdf_text(data)  # the whole PDF, to the isolated worker
            text = "\n".join(extraction.pages)
            return {"by": "isolated document worker (extract_pdf_text)", "page_count": extraction.page_count,
                    "text_sha256": extraction.sha256, "truncated": extraction.truncated,
                    "has_title": "T049 fixture brief" in text, "has_every_region": all(
                        row[0] in text for row in TABLE_ROWS[1:])}
        if media == "text/csv":
            rows = list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))
            return {"by": "csv", "rows": len(rows), "columns": len(rows[0]) if rows else 0, "header": rows[0],
                    "units_total": sum(int(row[2]) for row in rows[1:])}
        if media == "image/png":
            return {"by": "Pillow", **_png_facts(data)}
        if media.startswith("text/"):
            text = data.decode("utf-8")
            return {"by": "utf-8", "chars": len(text), "lines": len(text.splitlines()),
                    "mentions_revenue": "Revenue grew 12 percent" in text}
        raise RuntimeError("an input the consumer cannot read")


# --- the fixture site ------------------------------------------------------------------

def _png(color, size=8):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()


def site_pages():
    html = "text/html; charset=utf-8"
    report = (b"<html><head><title>T049 fixture report</title></head><body><h1>Quarterly fixture report</h1>"
              b"<p>Revenue grew 12 percent in the third quarter.</p><p>North shipped the most units.</p>"
              b"<img src='/logo.png'></body></html>")
    chart = (b"<html><head><title>T049 chart</title><style>html,body{margin:0;height:100%;background:#ffffff}"
             b".l{position:absolute;left:0;top:0;width:160px;height:200px;background:#dc1e1e}"
             b".r{position:absolute;left:160px;top:0;width:160px;height:200px;background:#1e1edc}</style></head>"
             b"<body><div class='l'></div><div class='r'></div></body></html>")
    recovered = (b"<html><head><title>T049 recovered page</title></head><body><h1>Recovered fixture page</h1>"
                 b"<p>Revenue grew 12 percent in the third quarter.</p></body></html>")
    return {"/report": (html, report), "/logo.png": ("image/png", _png((0, 128, 0))), "/chart": (html, chart),
            "/slow-once": (html, recovered)}


# --- the table producer the Claude executor's graph starts from (T049 live path) --------

TABLE_HANDLER = "documents-table-v1"
TABLE_SCHEMA = "runtime-e2e-table-v1"


def table_producer(domain, run_id, context):
    """A host-owned producer for `ClaudeRunExecutor(producers=...)`: the CSV table the
    document adapter renders (and reopens) sealed as the node's one artifact."""

    from app.adapters.documents import render_csv

    with tempfile.TemporaryDirectory(prefix="dt-t049-table-") as directory:
        path = Path(directory) / "units.csv"
        report = render_csv(TABLE_ROWS, path)
        data = path.read_bytes()
    if sha256(data).hexdigest() != report.sha256:
        raise RuntimeError("the adapter's inspected bytes are not the bytes sealed")
    blob = domain.put_blob(data, purpose="operational")
    record_id = str(uuid5(NAMESPACE_URL, f"deeptwin:t049:table:{context.execution_id}"))
    with _writer(), domain._connection(write=True) as db:
        roots = domain._read_roots(db)
        existing = db.execute("SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind='artifact' "
                              "AND id=?", (roots.genesis.id, record_id)).fetchone()
        if existing is not None:
            return EntityRef("artifact", record_id, existing["version"], existing["sha256"])
        record = ImmutableRecord.create(
            kind="artifact", id=record_id, version=1, created_at_utc=_stamp(), actor_ref=roots.actor,
            parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            content={"schema_version": TABLE_SCHEMA, "run_id": run_id, "node_id": context.node_id,
                     "adapter_inspection": {"sha256": report.sha256, "byte_length": report.byte_length},
                     "artifacts": [{"ordinal": 0, "role": "table", "media_type": "text/csv",
                                    "blob": blob.as_dict()}]})
        domain._put_in_transaction(db, record)
        return record.ref


def table_consumer_graph(choice_ref):
    """`linear_graph()` whose entry node is the table producer and whose writer (the
    Claude role) consumes that table; no tools, no grants (the Claude profile)."""

    from app.tests.test_graph_execution import linear_graph

    raw = linear_graph()
    raw["model_bindings"][0]["model_choice_ref"] = choice_ref
    raw["tool_bindings"] = []
    raw["grant_refs"] = []
    raw["memory_policies"][0]["read_grant_refs"] = []
    for node in raw["nodes"]:
        node["grant_refs"] = []
        if node["kind"] == "agent":
            node["config"]["tool_binding_ids"] = []
            node["responsibility"] = ("Read the CSV table. Reply with one line: the region with the most "
                                      "units and the total of the units column.")
        if node["node_id"] == "intake":
            node["config"] = {"handler_id": TABLE_HANDLER}
            node["responsibility"] = "문서 도구로 CSV 표를 만든다"
    return raw
