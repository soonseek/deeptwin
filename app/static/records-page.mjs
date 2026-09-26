// T073 (US7): the records page — the event log and the export entry. The log is the vault's
// public product events (GET {base}api/v1/events, paged by the server's cursor): one human
// sentence per event (ui-format.mjs), its outcome in words beside a glyph, "3분 전" beside
// the absolute local time, and how many records it names — never private evidence. The raw
// event type, sequence, UTC stamp and error code stay in each row's "기술 정보" disclosure.
// Export is per work and lives on the work screen, where its preview and consent are; this
// page says so and links there. Backup, retention, update guidance, account, connections,
// credentials and budgets live on the settings page (settings-page.mjs); they are reachable
// from every page's navigation, in any order, and none is a required final step.
// All server text reaches the DOM through textContent only.

import { recordsRoutes } from './records.mjs';
import { basePathFrom, createSupportedSession } from './session.mjs';
import { eventErrorLabel, eventSentence, eventStatusLabel, eventStatusTone, timeText } from './ui-format.mjs';
import { el, emptyState, statusChip, technicalDetails, timeStamp } from './ui-parts.mjs';
import { mountShell } from './ui-shell.mjs';

export const MOUNT_IDS = Object.freeze({ session: 'session-status', logs: 'records-logs', export: 'records-export' });
export const PAGE_SIZE = '50';

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
});

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
  const status = eventStatusLabel(event.status);
  const error = typeof event.error_code === 'string' ? event.error_code : null;
  const time = timeText(event.observed_at_utc, now);
  const meta = `관련 기록 ${refs}개${error ? ` · 오류: ${eventErrorLabel(error)}` : ''}`;
  return Object.freeze({
    sequence: event.sequence, type: event.event_type, known: sentence.known, sentence: sentence.text,
    status, tone: eventStatusTone(event.status), error, refs, meta, time,
    text: `${sentence.text} · ${status} · ${meta} · ${time.absolute || event.observed_at_utc}`,
  });
}

function eventItem(document, event, row) {
  const technical = [['사건 종류', row.type], ['순번', String(row.sequence)], ['기록 시각(UTC)', event.observed_at_utc]];
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

export function createEventLog({ root, document, request, basePath = '/' }) {
  if (typeof request !== 'function') fail('a request adapter is required');
  const events = `${basePath.slice(0, -1)}/api/v1/events`;
  const status = el(document, 'p', { text: MESSAGES.loading, attrs: { role: 'status', 'aria-live': 'polite' } });
  const list = el(document, 'ol', { className: 'event-log', attrs: { 'aria-label': '사건 기록' } });
  const empty = emptyState(document, { missing: MESSAGES.empty, next: MESSAGES.emptyNext });
  empty.hidden = true;
  const more = el(document, 'button', { text: MESSAGES.more, attrs: { type: 'button' } });
  more.hidden = true;
  root.replaceChildren(el(document, 'h2', { text: '사건 기록' }), status, list, empty, more);
  let cursor = null;
  let shown = 0;

  async function load() {
    status.dataset.state = 'loading';
    try {
      const page = await request(events, cursor === null ? { query: { limit: PAGE_SIZE } }
        : { query: { limit: PAGE_SIZE, cursor } });
      if (!Array.isArray(page?.events)) fail('the event page is malformed');
      const now = Date.now();
      for (const event of page.events) {
        list.append(eventItem(document, event, eventRow(event, now)));
        shown += 1;
      }
      const notes = [];
      if (page.gap !== null && page.gap !== undefined) notes.push(MESSAGES.gap);
      status.textContent = [shown ? `사건 ${shown}개` : MESSAGES.empty, ...notes].join(' ');
      status.dataset.state = page.gap ? 'gap' : 'listed';
      empty.hidden = shown > 0;
      cursor = typeof page.next_cursor === 'string' && page.events.length ? page.next_cursor : null;
      more.hidden = cursor === null;
      return page;
    } catch (error) {
      status.textContent = error?.code === 'unauthenticated' ? MESSAGES.unauthenticated : MESSAGES.failed;
      status.dataset.state = error?.code ?? 'unavailable';
      throw error;
    }
  }

  more.addEventListener('click', () => load().catch(() => {}));
  return Object.freeze({ load, get shown() { return shown; } });
}

export async function boot({ document, location, fetch } = {}) {
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
    el(document, 'p', { className: 'records-export-note', text: MESSAGES.settingsHere }));
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
  const log = createEventLog({ root: roots.logs, document, request: session.request, basePath });
  await log.load().catch(() => {});
  return Object.freeze({ established: true, basePath, sections, log });
}

if (typeof globalThis.document === 'object' && globalThis.document !== null
    && typeof globalThis.document.getElementById === 'function'
    && globalThis.document.getElementById(MOUNT_IDS.logs) !== null) {
  mountShell({ document: globalThis.document, page: 'records' });
  boot({ document: globalThis.document, location: globalThis.location,
    fetch: (...args) => globalThis.fetch(...args) }).catch(() => {
    const status = globalThis.document.getElementById(MOUNT_IDS.session);
    if (status) status.textContent = '이 화면을 준비하지 못했습니다.';
  });
}
