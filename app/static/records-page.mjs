// T073 (US7): the records page — the event log and the export entry. The log is the vault's
// public product events (GET {base}api/v1/events, paged by the server's cursor): one human
// sentence per event (ui-format.mjs), its outcome in words beside a glyph, "3분 전" beside
// the absolute local time, and how many records it names — never private evidence. The raw
// event type, sequence, UTC stamp and error code stay in each row's "기술 정보" disclosure.
// Export is per work and lives on the work screen, where its preview and consent are; this
// page says so and links there. Backup, retention, update guidance, account, connections,
// credentials and budgets live on the settings page (settings-page.mjs); they are reachable
// from every page's navigation, in any order, and none is a required final step.
// UI phase 3 (2026-09-26): `records.html#run=<id>` (the run detail's "전체 기록에서 이 실행 보기")
// narrows the log to that run through the server's `run_id` filter, which keeps only the events
// that carry the run (its start and stop, its attempts); the page says so and offers the full log.
// UI phase 4 (2026-09-26):
// - a `run.stopped` row's chip says what the stop means for the run (완료, 실패로 멈춤, …); the
//   event's own status only says the stop was recorded, so it moves beside the other raw fields;
// - "다음 기록 보기" shows only while more of the log exists: a short page is followed to the
//   log's end (a filtered read may scan past events that are not the run's) and the button hides
//   when the server's cursor stops moving;
// - "모든 산출물" (the vault-wide artifact index) lives here, each row linking to its run's screen
//   with the artifact previewed; the run screen shows only its own run.
// UI phase 5 (2026-09-26, redesign §5.7): the log is filtered by 업무, 실행, 종류 and 기간.
// - 업무 and 실행 go to the server (`work_id` / `run_id`, one at a time: picking one clears the other);
// - 종류 is a topic group of the ui-format dictionary, sent as the server's `event_type` filter;
// - 기간 has no server filter, so it is applied here over the pages read so far, and the page says so.
// The filter lives in the address (`#run=…`, `#work=…`, `&kind=…`, `&period=…`), so a link opens
// it and a reload keeps it. The artifact index follows a run or work filter.
// UI phase 6: a change of the hash alone (the back and forward buttons, an in-page link, an edited
// address) reads the log again under the filter the new hash names.
// All server text reaches the DOM through textContent only.

import { createArtifactIndex } from './artifacts.mjs';
import { recordsRoutes } from './records.mjs';
import { createRunSummaries, savedWorkIds } from './run-summaries.mjs';
import { basePathFrom, createSupportedSession } from './session.mjs';
import {
  EVENT_GROUPS, eventErrorLabel, eventSentence, eventStatusLabel, eventStatusTone, parseUtc, runStopOutcome, shortId,
  timeText,
} from './ui-format.mjs';
import { el, emptyState, statusChip, technicalDetails, timeStamp } from './ui-parts.mjs';
import { mountShell } from './ui-shell.mjs';

export const MOUNT_IDS = Object.freeze({ session: 'session-status', logs: 'records-logs', export: 'records-export' });
// the page's optional vault-wide artifact index (UI phase 4)
export const INDEX_MOUNT_ID = 'artifacts';
export const PAGE_SIZE = '50';
// UI phase 5: the filter bar's mount and the log's own mount inside the log section (optional)
export const FILTER_MOUNT_ID = 'records-filters';
export const LOG_MOUNT_ID = 'records-log';
export const MAX_FILTER_CHOICES = 50;
// how many reads one "next page" may take to fill a page or reach the log's end (each read
// scans at most 500 events on the server)
export const MAX_READS_PER_PAGE = 40;

export const MESSAGES = Object.freeze({
  loading: '기록을 불러오는 중…',
  empty: '아직 기록된 사건이 없습니다.',
  emptyNext: '업무를 저장하거나 실행하면 여기에 사건이 남습니다.',
  gap: '일부 사건이 보존 기간 등으로 빠져 있습니다. 빠진 구간은 사건으로 채워 넣지 않습니다.',
  more: '다음 기록 보기',
  failed: '기록을 불러오지 못했습니다.',
  unauthenticated: '소유자 세션이 없습니다. 시작 화면(./)에서 로그인한 뒤 다시 열어 주세요.',
  exportHere: '내보내기는 업무마다 업무 화면에서 합니다. 실제로 포함될 내용을 먼저 보여 드리고, 동의한 내용만 묶습니다. 내보내기는 선택 사항입니다.',
  exportLink: '업무 화면에서 내보내기',
  settingsHere: '백업·보존, 계정과 세션, 모델 연결, 실행 한도, 업데이트 안내는 설정 화면에 있습니다.',
  runFilter: '이 실행을 가리키는 사건만 봅니다(실행의 시작·멈춤과 시도). 승인 결정처럼 실행을 직접 가리키지 않는 사건은 전체 기록에 있습니다.',
  runEmpty: '이 실행을 가리키는 사건이 없습니다.',
  filteredEmpty: '고른 조건에 맞는 사건이 없습니다.',
  filterLimits: '업무와 실행, 종류는 서버가 거릅니다(업무와 실행은 한 번에 하나). 기간은 서버가 거르지 않아, 지금까지 불러온 기록 안에서만 거릅니다.',
  workFilter: '이 업무의 수정본을 가리키는 사건만 봅니다(업무 만들기·고치기, 원본 보관 등). 실행 사건은 실행을 골라 봅니다.',
});

// 기간: [id, label, milliseconds]
export const PERIODS = Object.freeze([
  ['', '전체 기간', null], ['1h', '최근 1시간', 3_600_000], ['24h', '최근 24시간', 86_400_000],
  ['7d', '최근 7일', 7 * 86_400_000], ['30d', '최근 30일', 30 * 86_400_000],
]);

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

// the run a `#run=<id>` names, or null
export function runFilterFrom(hash) {
  const named = new URLSearchParams(typeof hash === 'string' ? hash.replace(/^#/, '') : '').get('run');
  return typeof named === 'string' && UUID.test(named) ? named : null;
}

// the whole filter a hash names; anything outside the closed choices is no filter
export function filterFrom(hash) {
  const params = new URLSearchParams(typeof hash === 'string' ? hash.replace(/^#/, '') : '');
  const runId = runFilterFrom(hash);
  const work = params.get('work');
  const kind = params.get('kind');
  const period = params.get('period');
  return Object.freeze({
    runId,
    workId: runId === null && typeof work === 'string' && UUID.test(work) ? work : null,
    kind: EVENT_GROUPS.some(group => group.id === kind) ? kind : null,
    period: PERIODS.some(([id]) => id && id === period) ? period : null,
  });
}

export function filterHash(filter = {}) {
  const params = new URLSearchParams();
  if (filter.runId) params.set('run', filter.runId);
  else if (filter.workId) params.set('work', filter.workId);
  if (filter.kind) params.set('kind', filter.kind);
  if (filter.period) params.set('period', filter.period);
  const text = params.toString();
  return text ? `#${text}` : '';
}

export function filterActive(filter = {}) {
  return Boolean(filter.runId || filter.workId || filter.kind || filter.period);
}

function fail(message) {
  throw new Error(message);
}

// one event as the owner reads it; the raw fields ride along for the technical disclosure
export function eventRow(event, now = Date.now()) {
  if (typeof event !== 'object' || event === null || typeof event.event_type !== 'string'
      || typeof event.observed_at_utc !== 'string' || !Number.isInteger(event.sequence)) {
    fail('an event is malformed');
  }
  const refs = Array.isArray(event.object_refs) ? event.object_refs.length : 0;
  const sentence = eventSentence(event);
  const recorded = eventStatusLabel(event.status);
  const error = typeof event.error_code === 'string' ? event.error_code : null;
  const time = timeText(event.observed_at_utc, now);
  const meta = `관련 기록 ${refs}개${error ? ` · 오류: ${eventErrorLabel(error)}` : ''}`;
  // a stop's chip is the run's outcome; the record's own status is only that it was recorded
  const outcome = runStopOutcome(event);
  const status = outcome ? outcome.label : recorded;
  return Object.freeze({
    sequence: event.sequence, type: event.event_type, known: sentence.known, sentence: sentence.text,
    status, tone: outcome ? outcome.tone : eventStatusTone(event.status), error, refs, meta, time,
    recorded, outcome: outcome !== null,
    text: `${sentence.text} · ${status} · ${meta} · ${time.absolute || event.observed_at_utc}`,
  });
}

function eventItem(document, event, row) {
  const technical = [['사건 종류', row.type], ['순번', String(row.sequence)], ['기록 시각(UTC)', event.observed_at_utc]];
  if (row.outcome) technical.push(['사건 기록 상태', row.recorded]);
  if (typeof event.event_id === 'string') technical.push(['사건 ID', event.event_id]);
  if (row.error) technical.push(['오류 코드', row.error]);
  return el(document, 'li', { attrs: { 'data-sequence': String(row.sequence), 'data-event-type': row.type } }, [
    el(document, 'div', { className: 'event-main' }, [
      statusChip(document, { tone: row.tone, label: row.status }),
      el(document, 'span', { className: 'event-sentence', text: row.sentence }),
    ]),
    timeStamp(document, event.observed_at_utc),
    el(document, 'div', { className: 'event-meta', text: row.meta }),
    technicalDetails(document, technical),
  ]);
}

export function createEventLog({ root, document, request, basePath = '/', runId = null, filter = null,
  heading = true, now = () => Date.now() }) {
  if (typeof request !== 'function') fail('a request adapter is required');
  if (runId !== null && (typeof runId !== 'string' || !UUID.test(runId))) fail('run filter is not a run id');
  const chosen = filter ?? { runId };
  if (chosen.runId && runId === null) runId = chosen.runId;
  if (runId !== null && (typeof runId !== 'string' || !UUID.test(runId))) fail('run filter is not a run id');
  const workId = runId === null && typeof chosen.workId === 'string' && UUID.test(chosen.workId) ? chosen.workId : null;
  const group = EVENT_GROUPS.find(item => item.id === chosen.kind) ?? null;
  const period = PERIODS.find(([id]) => id && id === chosen.period) ?? null;
  const narrowed = runId !== null || workId !== null || group !== null || period !== null;
  const events = `${basePath.slice(0, -1)}/api/v1/events`;
  const status = el(document, 'p', { text: MESSAGES.loading, attrs: { role: 'status', 'aria-live': 'polite' } });
  const list = el(document, 'ol', { className: 'event-log', attrs: { 'aria-label': '사건 기록' } });
  const empty = !narrowed ? emptyState(document, { missing: MESSAGES.empty, next: MESSAGES.emptyNext })
    : runId !== null && group === null && period === null ? emptyState(document, { missing: MESSAGES.runEmpty })
      : emptyState(document, { missing: MESSAGES.filteredEmpty });
  empty.hidden = true;
  const more = el(document, 'button', { text: MESSAGES.more, attrs: { type: 'button' } });
  more.hidden = true;
  const filterBox = runId === null ? [] : [el(document, 'div', { className: 'records-filter', attrs: { role: 'region', 'aria-label': '기록 거르기' } }, [
    el(document, 'p', { className: 'records-filter-title', text: `실행 ${shortId(runId)}의 기록만 보는 중`, attrs: { title: runId } }),
    el(document, 'p', { className: 'records-filter-note', text: MESSAGES.runFilter }),
    el(document, 'p', { className: 'records-filter-links' }, [
      el(document, 'a', { text: '전체 기록 보기', attrs: { href: './records.html' } }),
      el(document, 'a', { text: '이 실행 화면으로 돌아가기', attrs: { href: `./observe.html#run=${runId}` } }),
    ]),
  ])];
  if (workId !== null) {
    filterBox.push(el(document, 'p', { className: 'records-filter-note', text: MESSAGES.workFilter }));
  }
  const title = runId === null ? '사건 기록' : '이 실행의 사건 기록';
  root.replaceChildren(...(heading ? [el(document, 'h2', { text: title })] : []), ...filterBox, status, list, empty, more);
  let cursor = null;
  let shown = 0;
  let scanned = 0;  // events read under the server filter, before the period is applied here
  const since = period === null ? null : now() - period[2];
  const inPeriod = event => {
    if (since === null) return true;
    const at = parseUtc(event.observed_at_utc);
    return at !== null && at.getTime() >= since;
  };

  // one page for the owner: read on from the cursor until the page is full or the log ends. A
  // short read is not the end by itself (a filtered read may scan past other events); the end is
  // a read that returns nothing and leaves the server's cursor where it was.
  async function load() {
    status.dataset.state = 'loading';
    try {
      const want = Number(PAGE_SIZE);
      let collected = 0;
      let reads = 0;
      let ended = false;
      let gap = false;
      let page = null;
      while (collected < want && reads < MAX_READS_PER_PAGE) {
        const from = cursor;
        const query = { limit: String(Math.max(1, want - collected)), ...(runId === null ? {} : { run_id: runId }),
          ...(workId === null ? {} : { work_id: workId }), ...(group === null ? {} : { event_type: [...group.types] }),
          ...(from === null ? {} : { cursor: from }) };
        page = await request(events, { query });
        reads += 1;
        if (!Array.isArray(page?.events)) fail('the event page is malformed');
        const at = Date.now();
        for (const event of page.events) {
          scanned += 1;
          if (!inPeriod(event)) continue;
          list.append(eventItem(document, event, eventRow(event, at)));
          shown += 1;
          collected += 1;
        }
        if (page.gap !== null && page.gap !== undefined) gap = true;
        const next = typeof page.next_cursor === 'string' ? page.next_cursor : null;
        if (next === null || (page.events.length === 0 && next === from)) {
          ended = true;
          break;
        }
        cursor = next;
      }
      const counted = period !== null ? `불러온 사건 ${scanned}개 중 기간에 맞는 ${shown}개` : `사건 ${shown}개`;
      status.textContent = [shown ? counted : !narrowed ? MESSAGES.empty
        : runId !== null && group === null && period === null ? MESSAGES.runEmpty
          : period !== null && scanned ? counted : MESSAGES.filteredEmpty,
      ...(gap ? [MESSAGES.gap] : [])].join(' ');
      status.dataset.state = gap ? 'gap' : 'listed';
      empty.hidden = shown > 0;
      more.hidden = ended;
      return page;
    } catch (error) {
      status.textContent = error?.code === 'unauthenticated' ? MESSAGES.unauthenticated : MESSAGES.failed;
      status.dataset.state = error?.code ?? 'unavailable';
      throw error;
    }
  }

  more.addEventListener('click', () => load().catch(() => {}));
  return Object.freeze({ load, get shown() { return shown; }, get scanned() { return scanned; }, runId, workId,
    kind: group?.id ?? null, period: period?.[0] ?? null });
}

// the filter bar above the log: 업무 · 실행 · 종류 · 기간, applied on change
export function createFilterBar({ root, document, filter = {}, works = [], runs = [], onChange = () => {} } = {}) {
  const field = (label, name, options, value) => {
    const select = el(document, 'select', { attrs: { name, 'aria-label': `${label} 거르기` } },
      options.map(([id, text]) => el(document, 'option', { text, attrs: { value: id } })));
    select.value = value ?? '';
    return [el(document, 'label', {}, [el(document, 'span', { text: label }), select]), select];
  };
  const [workLabel, workSelect] = field('업무', 'work', [['', '모든 업무'], ...works.map(item => [item.id, item.label])], filter.workId);
  const [runLabel, runSelect] = field('실행', 'run', [['', '모든 실행'], ...runs.map(item => [item.id, item.label])], filter.runId);
  const [kindLabel, kindSelect] = field('종류', 'kind', [['', '모든 종류'], ...EVENT_GROUPS.map(group => [group.id, group.label])], filter.kind);
  const [periodLabel, periodSelect] = field('기간', 'period', PERIODS.map(([id, label]) => [id, label]), filter.period);
  const clear = el(document, 'button', { text: '거르기 지우기', className: 'btn btn-quiet', attrs: { type: 'button' } });
  const summary = el(document, 'p', { className: 'records-filter-summary' });
  const limits = el(document, 'p', { className: 'records-filter-limits', text: MESSAGES.filterLimits });
  const form = el(document, 'form', { className: 'records-filters', attrs: { 'aria-label': '기록 거르기' } }, [
    el(document, 'div', { className: 'records-filter-fields' }, [workLabel, runLabel, kindLabel, periodLabel]),
    el(document, 'div', { className: 'records-filter-actions' }, [clear, summary]), limits]);
  root.replaceChildren(form);

  function value() {
    return Object.freeze({ runId: runSelect.value || null, workId: runSelect.value ? null : (workSelect.value || null),
      kind: kindSelect.value || null, period: periodSelect.value || null });
  }

  function describe(current) {
    const parts = [];
    if (current.runId) parts.push(`실행 ${shortId(current.runId)}`);
    if (current.workId) parts.push(`업무 ${works.find(item => item.id === current.workId)?.label ?? shortId(current.workId)}`);
    if (current.kind) parts.push(`종류 ${EVENT_GROUPS.find(group => group.id === current.kind)?.label ?? current.kind}`);
    if (current.period) parts.push(PERIODS.find(([id]) => id === current.period)?.[1] ?? current.period);
    summary.textContent = parts.length ? `거르는 중: ${parts.join(' · ')}` : '';
    clear.hidden = parts.length === 0;
  }

  // one subject at a time (the server takes one): picking a run clears the work and back
  workSelect.addEventListener('change', () => { if (workSelect.value) runSelect.value = ''; changed(); });
  runSelect.addEventListener('change', () => { if (runSelect.value) workSelect.value = ''; changed(); });
  kindSelect.addEventListener('change', () => changed());
  periodSelect.addEventListener('change', () => changed());
  clear.addEventListener('click', () => {
    for (const select of [workSelect, runSelect, kindSelect, periodSelect]) select.value = '';
    changed();
  });
  form.addEventListener('submit', event => { event.preventDefault?.(); changed(); });

  function changed() {
    const current = value();
    describe(current);
    onChange(current);
  }

  // a run the list never offered (a link to a run older than the list) is kept as its own option
  function adopt(next) {
    workSelect.value = next.workId ?? '';
    runSelect.value = next.runId ?? '';
    kindSelect.value = next.kind ?? '';
    periodSelect.value = next.period ?? '';
    for (const [select, id] of [[runSelect, next.runId], [workSelect, next.workId]]) {
      if (id && select.value !== id) {
        select.append(el(document, 'option', { text: `${select === runSelect ? '실행' : '업무'} ${shortId(id)}`, attrs: { value: id } }));
        select.value = id;
      }
    }
    describe(value());
  }
  adopt(filter);
  return Object.freeze({ root: form, value, set: adopt, selects: { work: workSelect, run: runSelect, kind: kindSelect, period: periodSelect },
    setRunLabel(id, label) {
      for (const option of runSelect.querySelectorAll?.('option') ?? []) if (option.value === id) option.textContent = label;
    } });
}

const sameFilter = (a, b) => ['runId', 'workId', 'kind', 'period'].every(key => (a?.[key] ?? null) === (b?.[key] ?? null));

export async function boot({ document, location, fetch, history = null, events = null } = {}) {
  if (typeof document?.getElementById !== 'function') fail('a document is required');
  if (typeof fetch !== 'function') fail('a fetch function is required');
  const roots = {};
  for (const [name, id] of Object.entries(MOUNT_IDS)) {
    const node = document.getElementById(id);
    if (node === null || typeof node.replaceChildren !== 'function') fail(`the page has no mount for ${id}`);
    roots[name] = node;
  }
  const basePath = basePathFrom(location.pathname);
  // the static section says what is true without any server call
  const sections = Object.fromEntries(recordsRoutes().map(route => [route.id, route]));
  roots.export.replaceChildren(el(document, 'h2', { text: '내보내기' }), el(document, 'p', { text: MESSAGES.exportHere }),
    el(document, 'p', {}, [el(document, 'a', { text: MESSAGES.exportLink, attrs: { href: './work.html#work-records' } })]),
    el(document, 'p', { className: 'records-export-note', text: MESSAGES.settingsHere }),
    el(document, 'p', {}, [el(document, 'a', { text: '설정 열기', attrs: { href: './settings.html' } })]));
  const session = createSupportedSession({ fetch, basePath });
  try {
    await session.establish();
  } catch (error) {
    roots.session.dataset.state = error?.code ?? 'unavailable';
    roots.session.textContent = error?.code === 'unauthenticated' ? MESSAGES.unauthenticated : MESSAGES.failed;
    return Object.freeze({ established: false, basePath, sections });
  }
  roots.session.dataset.state = 'authenticated';
  roots.session.textContent = '브라우저 세션이 연결되어 있습니다.';
  // every run's artifacts in one list; each opens on its own run's screen
  const indexRoot = document.getElementById(INDEX_MOUNT_ID);
  const index = indexRoot !== null && typeof indexRoot?.replaceChildren === 'function'
    ? createArtifactIndex({ root: indexRoot, document, basePath, request: session.request,
      linkTo: (runId, artifactId) => `./observe.html#run=${runId}&artifact=${artifactId}` })
    : null;
  let filter = filterFrom(location?.hash);
  // UI phase 5: where the page offers the filter mount, the log sits under the filter bar
  const filterRoot = document.getElementById(FILTER_MOUNT_ID);
  const logRoot = document.getElementById(LOG_MOUNT_ID);
  if (filterRoot === null || logRoot === null || typeof filterRoot.replaceChildren !== 'function') {
    const log = createEventLog({ root: roots.logs, document, request: session.request, basePath,
      runId: runFilterFrom(location?.hash) });
    await Promise.all([log.load().catch(() => {}), index?.refresh().catch(() => {})]);
    return Object.freeze({ established: true, basePath, sections, log, index });
  }
  const summaries = createRunSummaries({ request: session.request, basePath });
  let works = [];
  let runs = [];
  try {
    const snapshot = await session.request(`${basePath.slice(0, -1)}/api/v1/snapshot`, {});
    runs = (snapshot?.state?.runs ?? []).filter(item => UUID.test(item?.id ?? '')).slice(-MAX_FILTER_CHOICES).reverse();
  } catch {
    // no run choices: the filter bar still offers the rest, and a hash's run stays
  }
  try {
    // the saved works are named by their own `work.created` events (no route lists works)
    works = (await savedWorkIds({ request: session.request, basePath })).slice(-MAX_FILTER_CHOICES).reverse()
      .map(id => ({ id }));
  } catch {
    // no work choices: a hash's work stays
  }
  const workChoices = await Promise.all(works.map(async item => {
    try {
      const saved = await session.request(`${basePath.slice(0, -1)}/api/v1/works/${item.id}`);
      const line = String(saved?.text ?? '').split('\n').map(text => text.trim()).find(Boolean) ?? '';
      return { id: item.id, label: line ? ([...line].length > 28 ? `${[...line].slice(0, 27).join('')}…` : line) : `업무 ${shortId(item.id)}` };
    } catch {
      return { id: item.id, label: `업무 ${shortId(item.id)}` };
    }
  }));
  const runChoices = runs.map(item => ({ id: item.id, label: `실행 ${shortId(item.id)}` }));
  let log = null;
  const bar = createFilterBar({ root: filterRoot, document, filter, works: workChoices, runs: runChoices,
    onChange: next => {
      filter = next;
      try { history?.replaceState?.(null, '', filterHash(filter) || location.pathname); } catch { /* the page still filters */ }
      show().catch(() => {});
    } });
  // the run choices read better with their work's name, read from each run's own trace
  summaries.readAll(runChoices.map(item => item.id).slice(0, 20), (id, row) => {
    if (row) bar.setRunLabel(id, `${row.title} · 실행 ${shortId(id)}`);
  }).catch(() => {});

  async function scopeIndex() {
    if (index === null) return null;
    if (filter.runId) return index.setScope({ runId: filter.runId });
    if (filter.workId) {
      const ids = runs.map(item => item.id);
      const rows = await summaries.readAll(ids);
      const mine = new Set(ids.filter(id => rows.get(id)?.workId === filter.workId));
      const label = workChoices.find(item => item.id === filter.workId)?.label ?? `업무 ${shortId(filter.workId)}`;
      return index.setScope({ runIds: mine, label });
    }
    return index.setScope({});
  }

  async function show() {
    log = createEventLog({ root: logRoot, document, request: session.request, basePath, filter, heading: false });
    await Promise.all([log.load().catch(() => {}), scopeIndex().catch(() => {})]);
    return log;
  }
  await show();
  // a hash-only change names another filter: the bar follows it and the log is read again
  events?.addEventListener?.('hashchange', () => {
    const next = filterFrom(location?.hash);
    if (sameFilter(next, filter)) return;
    filter = next;
    bar.set(next);
    show().catch(() => {});
  });
  return Object.freeze({ established: true, basePath, sections, get log() { return log; }, index, bar,
    get filter() { return filter; } });
}

if (typeof globalThis.document === 'object' && globalThis.document !== null
    && typeof globalThis.document.getElementById === 'function'
    && globalThis.document.getElementById(MOUNT_IDS.logs) !== null) {
  mountShell({ document: globalThis.document, page: 'records' });
  boot({ document: globalThis.document, location: globalThis.location, history: globalThis.history, events: globalThis,
    fetch: (...args) => globalThis.fetch(...args) }).catch(() => {
    const status = globalThis.document.getElementById(MOUNT_IDS.session);
    if (status) status.textContent = '이 화면을 준비하지 못했습니다.';
  });
}
