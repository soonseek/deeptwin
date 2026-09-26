# Browser responsiveness under the declared workload (T080, 2026-09-25)

Status: **browser command, event, records-log and run-view responsiveness is measured and
within every plan target on this hardware. STT is not measured.** No speech engine exists in
this environment, and real microphone input is excluded. T080 stays open for STT and for the
two clean deployment hosts (T083).

## How it was measured

`app/tests/browser-performance.test.mjs` runs headless Chromium against the real supported
server started by `app/tests/fixtures/performance_server.py`. Every seeded fact is synthetic
test-actor data. The workload is the plan's declared one:
- one recorded run over a **20-node / 40-edge** graph: 19 artifact hand-offs and 21
  observation edges, executed by the code-owned test executor
- **1,000 seeded public events** on the real event journal, with more written by the test
  itself

Timings are taken inside the page with `performance.now()`. Main-thread long tasks come from
`PerformanceObserver('longtask')`. The raw results are in
[performance-2026-09-25.json](performance-2026-09-25.json).

**Environment:**
- Chromium 141.0.7390.37, headless
- 4 × Intel Xeon @ 2.10 GHz, 16 GiB, Linux 6.18
- uvicorn with one process on local loopback: server and browser share the machine, and there
  is no network hop

## Results

| Measure | Samples | p50 | p95 | max | Plan target |
| --- | --- | --- | --- | --- | --- |
| Command acknowledgment: type a description, save, until the status names the new revision | 30 | 95.9 ms | **126.8 ms** | 129.5 ms | p95 < 500 ms |
| Core event visible after commit: a committed revision until the first event read returns it | 30 | 43.7 ms | **60.1 ms** | 66.0 ms | p95 < 1 s |
| Records log: each "다음 기록 보기" page (50 rows) | 21 | 82.2 ms | 98.6 ms | 99.5 ms | none stated |
| Records log: first page / all 1,062 rows | 1 | 153 ms / 1,805 ms | | | none stated |
| Main-thread long tasks while typing 2,000 characters | 1 | none observed | | | none > 200 ms |
| Main-thread long tasks while opening the 20-node run on the observe page | 1 | none observed (open 843 ms wall) | | | none > 200 ms |

## What these numbers do not show

- **Event visibility is a read-after-commit delay, not a live update.** The server has no
  push channel: `/api/v1/events/stream` returns one page in the SSE format. No screen refreshes
  itself when an event commits; the records log shows events when it is loaded or paged. A live
  event view is not built, and its latency is not claimed.
- **There is no graph canvas.** The observe page lists one row per node. "Graph selection"
  was measured as opening the 20-node run in that list; the large graph view (T037) does not
  exist yet.
- **STT: not measured.** No `faster-whisper` engine or model is installed here, and real
  microphone input is out of scope. The targets (provisional p95 < 2 s, final < 3 s) and any
  recognition-accuracy claim stay unverified.
- The run is a single session on one host, with the server on the same machine. The declared
  clean deployment hosts (T083) are not measured.

## 2026-09-26 re-run: the graph view

The run's graph view (`graph.mjs` on the observe page, T037/T048) now exists, and the test measures it
(step 5). It draws the run's 20 nodes and 40 edges, then clicks every node and waits for the next
frame, checking that the details name that node. The re-run is in
[performance-2026-09-26.json](performance-2026-09-26.json). It used the same host and workload.

| Measure | Samples | p50 | p95 | max | Plan target |
| --- | --- | --- | --- | --- | --- |
| Command acknowledgment | 30 | 148.2 ms | **181.5 ms** | 181.7 ms | p95 < 500 ms |
| Core event visible after commit | 30 | 40.0 ms | **48.2 ms** | 49.1 ms | p95 < 1 s |
| Records log: each next page (50 rows) | 21 | 49.5 ms | 49.7 ms | 66.2 ms | none stated |
| Graph view: node selection until the next frame shows its details | 20 | 16.6 ms | **17.0 ms** | 17.1 ms | none stated (no long task > 200 ms) |
| Long tasks while typing / opening the run / selecting every graph node | 1 each | none observed (run open 1,343 ms wall) | | | none > 200 ms |

The selection timing is bounded below by the frame interval (about 16.7 ms). It shows that
selection completes within one frame, not a finer latency. The graph is drawn once per run
open; there is no live-updating graph.

**Speech recognition:** on 2026-09-26 the owner skipped the STT measurement (decisions.md). STT
latency and recognition quality are **not measured** and are not claimed. The "no graph canvas"
note above is superseded by this section. The event-visibility caveat is unchanged: there is
still no push view. The clean deployment hosts (T083) are still not measured.
