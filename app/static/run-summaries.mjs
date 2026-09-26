// UI phase 5 (docs/ui/2026-09-26-product-ux-redesign.md §5.2): the run list as a table, and the
// work page's "이 업무의 실행". The public snapshot (GET {base}api/v1/snapshot) lists every run
// by id with only its durable ledger phase; what a row says beyond that — the work it ran for,
// its status, start, duration, cost and whether it waits on a person — comes from that run's own
// trace (GET {base}api/v1/runs/{run}/trace, run-trace-v1), read one run at a time with a small
// concurrency and only for the rows on screen. No route carries a run's environment version (the
// trace names its graph, not its environment), so that column says "—" and the table says why;
// nothing is computed that the server did not record. A cost is "미확인" unless the trace
// recorded one, and an estimate says so. All text reaches the DOM through textContent.

import { runList, snapshotRoute } from './run-list.mjs';
import { pendingApprovals, runSummary, traceRoute, traceView } from './run-trace.mjs';
import { NOT_RECORDED, costText, shortId } from './ui-format.mjs';
import { el, emptyState, statusChip, timeStamp } from './ui-parts.mjs';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export const PAGE_SIZE = 20;
export const MAX_WORK_EVENT_PAGES = 20;
export const CONCURRENCY = 4;
export const COLUMNS = Object.freeze([
  ['work', '업무'], ['environment', '환경 버전'], ['status', '상태'], ['started', '시작'],
  ['duration', '걸린 시간'], ['cost', '비용'], ['waiting', '사람 대기'],
]);
export const MESSAGES = Object.freeze({
  loading: '실행 목록을 읽는 중…',
  empty: '아직 기록된 실행이 없습니다.',
  emptyNext: '업무 화면의 ④ 준비·시작에서 준비된 환경으로 업무를 시작하면 여기에 나옵니다.',
  failed: '실행 목록을 읽지 못했습니다.',
  reading: '읽는 중…',
  unreadable: '이 실행의 기록을 읽지 못했습니다.',
  environmentNote: '환경 버전: 실행 목록과 실행 기록(트레이싱)이 환경 버전을 싣지 않아 “—”로 둡니다. 실행 상세의 기술 정보에서 그래프를 볼 수 있습니다.',
  costNote: '비용: 제공자가 정산한 값이 없으면 “미확인”, 한도 요율로 잡은 값은 “추정”입니다.',
  more: '이전 실행 더 보기',
  noWorkRuns: '이 업무로 시작한 실행이 아직 없습니다.',
  workRunsScope: '최근 실행 {n}개 가운데 이 업무의 것입니다.',
});

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

const recorded = value => value !== NOT_RECORDED && value !== null && value !== undefined;

// one run's row, from its trace: only what the trace recorded
export function runRow(trace) {
  const facts = runSummary(trace);
  const waiting = trace.phase === 'awaiting_human' ? pendingApprovals(trace).length : 0;
  const workTitle = recorded(trace.work?.title) ? trace.work.title : null;
  return Object.freeze({
    runId: trace.run_id,
    workId: typeof trace.work?.work_id === 'string' ? trace.work.work_id : null,
    workRevision: Number.isSafeInteger(trace.work?.revision) ? trace.work.revision : null,
    workTitle,
    title: workTitle ?? `실행 ${shortId(trace.run_id)}`,
    phase: trace.phase, phaseLabel: facts.phaseLabel, tone: facts.tone,
    startedAt: facts.startedAt, endedAt: facts.endedAt,
    duration: facts.endedAt ? facts.duration : null,
    cost: costText(trace.totals?.cost),
    costState: trace.totals?.cost?.state ?? 'unknown',
    waiting,
    waitingText: trace.phase === 'awaiting_human' ? `승인 대기 ${Math.max(waiting, 1)}건` : '없음',
  });
}

// the snapshot's runs and each run's trace row, read on demand and remembered for the page
export function createRunSummaries({ request, basePath = '/', concurrency = CONCURRENCY } = {}) {
  if (typeof request !== 'function') fail('a request adapter is required');
  const snapshot = snapshotRoute(basePath);
  const rows = new Map();  // run id -> Promise<row>

  // every run id, newest first (the snapshot lists them in recorded order)
  async function runIds() {
    return runList(await request(snapshot, {})).map(run => run.runId).reverse();
  }

  function row(runId, { fresh = false } = {}) {
    if (fresh || !rows.has(runId)) {
      const read = request(traceRoute(basePath, runId), {}).then(value => runRow(traceView(value)));
      read.catch(() => rows.delete(runId));  // a failed read is tried again next time
      rows.set(runId, read);
    }
    return rows.get(runId);
  }

  // read many rows, a few at a time; each settles through `onRow(runId, row | null, error)`
  async function readAll(ids, onRow = () => {}, { fresh = false } = {}) {
    const queue = [...ids];
    const results = new Map();
    async function worker() {
      while (queue.length) {
        const id = queue.shift();
        try {
          const value = await row(id, { fresh });
          results.set(id, value);
          onRow(id, value, null);
        } catch (error) {
          results.set(id, null);
          onRow(id, null, error);
        }
      }
    }
    await Promise.all(Array.from({ length: Math.max(1, Math.min(concurrency, queue.length)) }, worker));
    return results;
  }

  return Object.freeze({ runIds, row, readAll });
}

// explicit table roles: a narrow screen lays the rows out as cards, which would drop the table's
// own semantics; the cells keep their column's name for screen readers too
function cell(document, name, children) {
  const label = COLUMNS.find(([id]) => id === name)?.[1] ?? '';
  return el(document, 'td', { className: `run-cell-${name}`, attrs: { 'data-label': label, role: 'cell' } }, children);
}

function textCell(document, name, text) {
  return cell(document, name, [el(document, 'span', { text })]);
}

// the saved works of this instance, oldest first. No route lists works: each `work.created` event
// names its work's first revision record (`work_revision`, whose id is the work id), so the ids are
// read from those events — only what the server recorded, bounded to a few pages
export async function savedWorkIds({ request, basePath = '/', maxPages = MAX_WORK_EVENT_PAGES } = {}) {
  if (typeof request !== 'function') fail('a request adapter is required');
  const route = `${basePath.slice(0, -1)}/api/v1/events/work.created`;
  const ids = [];
  let cursor = null;
  for (let page = 0; page < maxPages; page += 1) {
    const value = await request(route, { query: { limit: '100', ...(cursor ? { cursor } : {}) } });
    const events = Array.isArray(value?.events) ? value.events : [];
    for (const event of events) {
      for (const ref of Array.isArray(event?.object_refs) ? event.object_refs : []) {
        if (ref?.kind === 'work_revision' && typeof ref.id === 'string' && UUID.test(ref.id) && !ids.includes(ref.id)) ids.push(ref.id);
      }
    }
    const next = typeof value?.next_cursor === 'string' ? value.next_cursor : null;
    if (!events.length || next === null || next === cursor) break;
    cursor = next;
  }
  return ids;
}

// the run list (observe.html without `#run=`): a table whose rows open the run detail
export function createRunTable({ root, document, request, basePath = '/', summaries = null, linkTo = runId => `#run=${runId}`,
  pageSize = PAGE_SIZE } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof document?.createElement !== 'function') fail('a document is required');
  const source = summaries ?? createRunSummaries({ request, basePath });
  const status = el(document, 'p', { text: '', attrs: { role: 'status', 'aria-live': 'polite' } });
  const head = el(document, 'thead', { attrs: { role: 'rowgroup' } }, [el(document, 'tr', { attrs: { role: 'row' } },
    COLUMNS.map(([id, label]) => el(document, 'th', {
      text: id === 'environment' || id === 'cost' ? `${label}*` : label, attrs: { scope: 'col', role: 'columnheader', 'data-column': id } })))]);
  const body = el(document, 'tbody', { attrs: { role: 'rowgroup' } });
  const table = el(document, 'table', { className: 'run-table', attrs: { 'aria-label': '실행 목록', role: 'table' } }, [head, body]);
  const wrap = el(document, 'div', { className: 'run-table-wrap' }, [table]);
  const notes = el(document, 'div', { className: 'run-table-notes' }, [
    el(document, 'p', { text: `* ${MESSAGES.environmentNote}` }), el(document, 'p', { text: `* ${MESSAGES.costNote}` })]);
  const more = el(document, 'button', { text: MESSAGES.more, className: 'btn btn-secondary', attrs: { type: 'button' } });
  more.hidden = true;
  const empty = emptyState(document, { missing: MESSAGES.empty, next: MESSAGES.emptyNext });
  empty.hidden = true;
  root.replaceChildren(status, wrap, notes, more, empty);
  let ids = [];
  let shown = 0;
  let generation = 0;
  const rowsById = new Map();

  function placeholder(runId) {
    const link = el(document, 'a', { text: `실행 ${shortId(runId)}`, className: 'run-link',
      attrs: { href: linkTo(runId), 'data-run-id': runId, title: runId } });
    const tr = el(document, 'tr', { attrs: { 'data-run-row': runId, 'data-state': 'loading', role: 'row' } }, [
      cell(document, 'work', [link, el(document, 'span', { className: 'run-cell-sub', text: MESSAGES.reading })]),
      ...COLUMNS.slice(1).map(([id]) => textCell(document, id, '…')),
    ]);
    // the whole row opens the run; the link is the keyboard and screen-reader path
    tr.addEventListener('click', event => {
      if (event?.target?.closest?.('a')) return;
      link.click?.();
    });
    return tr;
  }

  function fill(tr, runId, value) {
    if (value === null) {
      tr.dataset.state = 'unreadable';
      const link = tr.querySelector?.('a.run-link') ?? null;
      tr.replaceChildren(cell(document, 'work', [link ?? el(document, 'span', { text: `실행 ${shortId(runId)}` }),
        el(document, 'span', { className: 'run-cell-sub', text: MESSAGES.unreadable })]),
      ...COLUMNS.slice(1).map(([id]) => textCell(document, id, '—')));
      return;
    }
    tr.dataset.state = 'read';
    tr.dataset.phase = value.phase;
    // two runs of one work share a title: the link is described by its own run's line (UI phase 6)
    const subId = `run-row-${runId}-sub`;
    const link = el(document, 'a', { text: value.title, className: 'run-link',
      attrs: { href: linkTo(runId), 'data-run-id': runId, title: runId, 'aria-describedby': subId } });
    const sub = `실행 ${shortId(runId)}${value.workRevision ? ` · 업무 수정본 ${value.workRevision}` : ''}`;
    tr.replaceChildren(
      cell(document, 'work', [link, el(document, 'span', { className: 'run-cell-sub', text: sub, attrs: { id: subId } })]),
      textCell(document, 'environment', '—'),
      cell(document, 'status', [statusChip(document, { tone: value.tone, label: value.phaseLabel })]),
      cell(document, 'started', [value.startedAt ? timeStamp(document, value.startedAt) : el(document, 'span', { text: '—' })]),
      textCell(document, 'duration', value.duration ?? (value.phase === 'running' || value.phase === 'awaiting_human' ? '진행 중' : '—')),
      textCell(document, 'cost', value.cost),
      cell(document, 'waiting', [value.phase === 'awaiting_human'
        ? statusChip(document, { tone: 'warn', label: value.waitingText }) : el(document, 'span', { text: '없음' })]),
    );
  }

  async function showMore(mine) {
    const next = ids.slice(shown, shown + pageSize);
    shown += next.length;
    for (const runId of next) {
      const tr = placeholder(runId);
      rowsById.set(runId, tr);
      body.append(tr);
    }
    more.hidden = shown >= ids.length;
    await source.readAll(next, (runId, value) => {
      if (mine === generation) fill(rowsById.get(runId), runId, value);
    }, { fresh: true });
  }

  async function load() {
    const mine = ++generation;
    status.textContent = MESSAGES.loading;
    status.dataset.state = 'loading';
    try {
      ids = await source.runIds();
    } catch (error) {
      if (mine === generation) {
        status.textContent = MESSAGES.failed;
        status.dataset.state = error?.code ?? 'unavailable';
      }
      throw error;
    }
    if (mine !== generation) return ids;
    shown = 0;
    rowsById.clear();
    body.replaceChildren();
    empty.hidden = ids.length > 0;
    wrap.hidden = ids.length === 0;
    notes.hidden = ids.length === 0;
    status.textContent = ids.length ? `기록된 실행 ${ids.length}개 · 최근 것부터` : '';
    status.dataset.state = ids.length ? 'listed' : 'empty';
    await showMore(mine);
    return ids;
  }

  more.addEventListener('click', () => { showMore(generation).catch(() => {}); });
  return Object.freeze({ load, get ids() { return ids; }, summaries: source });
}

// the work page's "이 업무의 실행": the newest runs whose trace names this work
export function createWorkRuns({ root, document, request, basePath = '/', summaries = null, workId, scan = 50 } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof workId !== 'function') fail('a work id source is required');
  const source = summaries ?? createRunSummaries({ request, basePath });
  const status = el(document, 'p', { text: '', attrs: { role: 'status', 'aria-live': 'polite' } });
  const list = el(document, 'ul', { className: 'work-run-list', attrs: { 'aria-label': '이 업무의 실행' } });
  const scope = el(document, 'p', { className: 'work-runs-scope' });
  scope.hidden = true;
  root.replaceChildren(el(document, 'h2', { text: '이 업무의 실행' }), status, list, scope);
  let generation = 0;
  let found = [];

  async function load() {
    const mine = ++generation;
    const id = workId();
    list.replaceChildren();
    found = [];
    if (typeof id !== 'string') {
      status.textContent = '업무를 저장하고 시작한 실행이 여기에 나옵니다.';
      status.dataset.state = 'no_work';
      return found;
    }
    status.textContent = MESSAGES.reading;
    status.dataset.state = 'loading';
    let ids;
    try {
      ids = await source.runIds();
    } catch {
      if (mine === generation) {
        status.textContent = MESSAGES.failed;
        status.dataset.state = 'unavailable';
      }
      return found;
    }
    const recent = ids.slice(0, scan);
    const rows = await source.readAll(recent, () => {}, { fresh: true });
    if (mine !== generation) return found;
    found = recent.map(runId => rows.get(runId)).filter(row => row && row.workId === id);
    list.replaceChildren(...found.map(row => el(document, 'li', { attrs: { 'data-run-id': row.runId } }, [
      el(document, 'a', { text: `실행 ${shortId(row.runId)}`, attrs: { href: `./observe.html#run=${row.runId}`, title: row.runId } }),
      statusChip(document, { tone: row.tone, label: row.phaseLabel }),
      row.startedAt ? timeStamp(document, row.startedAt) : el(document, 'span', { text: '—' }),
    ])));
    status.textContent = found.length ? `실행 ${found.length}개` : MESSAGES.noWorkRuns;
    status.dataset.state = found.length ? 'listed' : 'empty';
    scope.hidden = ids.length <= scan;
    scope.textContent = MESSAGES.workRunsScope.replace('{n}', String(scan));
    return found;
  }

  return Object.freeze({ load, get runs() { return found; } });
}
