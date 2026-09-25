// T073 (US7): the records page — logs, export, backup and retention, each reachable
// from any screen and in any order (records.mjs recordsRoutes), none a required
// step. The log is the vault's public product events (GET {base}api/v1/events,
// paged by the server's cursor): time, kind, outcome and how many records an
// event names — never private evidence. Export is per work and lives on the work
// screen, where its preview and consent are; this page says so and links there.
// Backup and retention state only what this server actually does: no backup is
// claimed where no backup worker is connected, and nothing is deleted
// automatically. With a session, the backup section is the server's own state and
// commands (records-backup.mjs): create through the isolated backup-crypto worker with
// an actual-content preview and bound consent, downloads of the encrypted bundle and
// its external receipt, and a restore staged as `restored_review` (instance key, or a
// portable backup with the owner's one-shot recovery identity). The retention section
// is the server's own per-category state and the owner's cleanup with an actual
// preview and bound consent (records-retention.mjs).
// All server text reaches the DOM through textContent only.

import { createAccountPanel, createCredentialsPanel } from './account.mjs';
import { createBackupPanel } from './records-backup.mjs';
import { createRetentionPanel } from './records-retention.mjs';
import { createUpdatePanel } from './records-update.mjs';
import { createClaudeConnection } from './claude-connection.mjs';
import { recordsRoutes } from './records.mjs';
import { basePathFrom, createSupportedSession } from './session.mjs';

export const MOUNT_IDS = Object.freeze({
  session: 'session-status', logs: 'records-logs', export: 'records-export',
  backup: 'records-backup', retention: 'records-retention',
});
export const PAGE_SIZE = '50';
export const ACCOUNT_MOUNT_ID = 'records-account';
export const CONNECTION_MOUNT_ID = 'records-connection';
export const CREDENTIALS_MOUNT_ID = 'records-credentials';
// T072: the read-only web-release update guidance (records-update.mjs)
export const UPDATE_MOUNT_ID = 'records-update';

export const STATUS_LABELS = Object.freeze({
  succeeded: '성공', failed: '실패', cancelled: '취소', pending: '대기', unknown: '결과 미상',
});

export const MESSAGES = Object.freeze({
  loading: '기록을 불러오는 중…',
  empty: '아직 기록된 사건이 없습니다.',
  gap: '일부 사건이 보존 기간 등으로 빠져 있습니다. 빠진 구간은 사건으로 채워 넣지 않습니다.',
  more: '다음 기록 보기',
  failed: '기록을 불러오지 못했습니다.',
  unauthenticated: '소유자 세션이 없습니다. 시작 화면(./)에서 로그인한 뒤 다시 열어 주세요.',
  exportHere: '내보내기는 업무마다 작업 화면에서 합니다. 실제로 포함될 내용을 먼저 보여 드리고, 동의한 내용만 묶습니다. 내보내기는 선택 사항입니다.',
  backupState: '이 서버에는 백업 워커가 아직 연결되어 있지 않습니다. 그래서 이 화면에서 백업을 만들거나 복원하지 않으며, 백업이 있다고 표시하지도 않습니다.',
  backupHow: '백업은 배포 관리자가 격리된 백업 워커와 별도 backup-key 볼륨을 연결해야 만들 수 있습니다. 같은 배포용 키로 만든 백업은 그 볼륨을 잃으면 복구할 수 없고, 다른 곳에서 복원하려면 따로 보관한 복구 키가 필요합니다.',
  retentionState: '자동 삭제는 없습니다. 기록과 원본은 명시적으로 지우기 전까지 보존됩니다.',
  retentionHow: '저장한 원본은 작업 화면의 "원본 삭제"에서 미리보기와 동의를 거쳐 지울 수 있습니다. 지운 자리에는 삭제 표시(tombstone)가 남고, 이전 백업과 이미 보낸 사본에는 닿지 않습니다. 오래된 백업과 스테이징된 복원본은 로그인한 뒤 이 화면에서 미리보기와 동의를 거쳐 정리할 수 있습니다. 핵심 기록은 지우지 않습니다.',
});

function fail(message) {
  throw new Error(message);
}

export function eventRow(event) {
  if (typeof event !== 'object' || event === null || typeof event.event_type !== 'string'
      || typeof event.observed_at_utc !== 'string' || !Number.isInteger(event.sequence)) {
    fail('an event is malformed');
  }
  const refs = Array.isArray(event.object_refs) ? event.object_refs.length : 0;
  const status = STATUS_LABELS[event.status] ?? String(event.status);
  const error = typeof event.error_code === 'string' ? ` · 오류 ${event.error_code}` : '';
  return {
    sequence: event.sequence,
    text: `${event.observed_at_utc} · ${event.event_type} · ${status}${error} · 관련 기록 ${refs}개`,
  };
}

export function createEventLog({ root, document, request, basePath = '/' }) {
  if (typeof request !== 'function') fail('a request adapter is required');
  const events = `${basePath.slice(0, -1)}/api/v1/events`;

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', MESSAGES.loading, { role: 'status', 'aria-live': 'polite' });
  const list = element('ol', undefined, { class: 'event-log', 'aria-label': '사건 기록' });
  const more = element('button', MESSAGES.more, { type: 'button' });
  more.hidden = true;
  root.replaceChildren(element('h2', '기록'), status, list, more);
  let cursor = null;
  let shown = 0;

  async function load() {
    status.dataset.state = 'loading';
    try {
      const page = await request(events, cursor === null ? { query: { limit: PAGE_SIZE } }
        : { query: { limit: PAGE_SIZE, cursor } });
      if (!Array.isArray(page?.events)) fail('the event page is malformed');
      for (const event of page.events) {
        const row = eventRow(event);
        list.append(element('li', row.text, { 'data-sequence': String(row.sequence) }));
        shown += 1;
      }
      const notes = [];
      if (page.gap !== null && page.gap !== undefined) notes.push(MESSAGES.gap);
      status.textContent = [shown ? `사건 ${shown}개` : MESSAGES.empty, ...notes].join(' ');
      status.dataset.state = page.gap ? 'gap' : 'listed';
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

export async function boot({ document, location, fetch, crypto = globalThis.crypto } = {}) {
  if (typeof document?.getElementById !== 'function') fail('a document is required');
  if (typeof fetch !== 'function') fail('a fetch function is required');
  const roots = {};
  for (const [name, id] of Object.entries(MOUNT_IDS)) {
    const node = document.getElementById(id);
    if (node === null || typeof node.replaceChildren !== 'function') fail(`the page has no mount for ${id}`);
    roots[name] = node;
  }
  const basePath = basePathFrom(location.pathname);
  const element = (tag, text, attributes = {}) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  };
  // the static sections say what is true without any server call
  const sections = Object.fromEntries(recordsRoutes().map(route => [route.id, route]));
  roots.export.replaceChildren(element('h2', '내보내기'), element('p', MESSAGES.exportHere),
    element('a', '작업 화면에서 내보내기', { href: './work.html' }));
  roots.backup.replaceChildren(element('h2', '백업'), element('p', MESSAGES.backupState),
    element('p', MESSAGES.backupHow));
  roots.retention.replaceChildren(element('h2', '보존과 삭제'), element('p', MESSAGES.retentionState),
    element('p', MESSAGES.retentionHow));
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
  const accountRoot = document.getElementById(ACCOUNT_MOUNT_ID);
  const account = accountRoot !== null && typeof accountRoot?.replaceChildren === 'function'
    ? createAccountPanel({ root: accountRoot, document, fetch, basePath, session }) : null;
  const connectionRoot = document.getElementById(CONNECTION_MOUNT_ID);
  const connection = connectionRoot !== null && typeof connectionRoot?.replaceChildren === 'function'
    ? createClaudeConnection({ root: connectionRoot, document, request: session.request, basePath }) : null;
  if (connection !== null) await connection.load().catch(() => {});
  const credentialsRoot = document.getElementById(CREDENTIALS_MOUNT_ID);
  const credentials = credentialsRoot !== null && typeof credentialsRoot?.replaceChildren === 'function'
    ? createCredentialsPanel({ root: credentialsRoot, document, fetch, basePath, session }) : null;
  if (credentials !== null) await credentials.load().catch(() => {});
  const backup = createBackupPanel({ root: roots.backup, document, basePath, request: session.request,
    upload: session.uploadBackupBundle, crypto });
  await backup.load().catch(() => {});
  // a cleanup changes what the backup section lists: it re-reads the server's state
  const retention = createRetentionPanel({ root: roots.retention, document, basePath, request: session.request, crypto,
    onCleaned: () => backup.load() });
  await retention.load().catch(() => {});
  const updateRoot = document.getElementById(UPDATE_MOUNT_ID);
  const update = updateRoot !== null && typeof updateRoot?.replaceChildren === 'function'
    ? createUpdatePanel({ root: updateRoot, document, basePath, request: session.request }) : null;
  if (update !== null) await update.load().catch(() => {});
  const log = createEventLog({ root: roots.logs, document, request: session.request, basePath });
  await log.load().catch(() => {});
  return Object.freeze({ established: true, basePath, sections, log, account, connection, credentials, backup,
    retention, update });
}

if (typeof globalThis.document === 'object' && globalThis.document !== null
    && typeof globalThis.document.getElementById === 'function'
    && globalThis.document.getElementById(MOUNT_IDS.logs) !== null) {
  boot({ document: globalThis.document, location: globalThis.location,
    fetch: (...args) => globalThis.fetch(...args) }).catch(() => {
    const status = globalThis.document.getElementById(MOUNT_IDS.session);
    if (status) status.textContent = '이 화면을 준비하지 못했습니다.';
  });
}
