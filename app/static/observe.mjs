// T048/T025: the shell mount on the supported factory. `observe.html` loads
// this module by a relative path, so it resolves under the deployment base
// path as under `/`. `boot` derives the base path from the document location,
// establishes the supported session client from the owner cookie the browser
// already holds (no login UI here — that is T025's shell), and only then
// mounts the run list (the public snapshot's runs) and the run panel; without
// a session it says so plainly and mounts nothing that could send a command.
// Every dependency (document, location, fetch, crypto) is injected so the
// boot is testable under node; the page passes the platform's own.

import { createRunList } from './run-list.mjs';
import { createRunPanel } from './run-panel.mjs';
import { basePathFrom, createSupportedSession } from './session.mjs';

export const MOUNT_IDS = Object.freeze({ session: 'session-status', source: 'run-source', panel: 'run-panel' });

// the codes GET {base}session can actually answer (app/api/web_boundary.py,
// owner_auth.authenticate_request): a session that stands, none (a fresh
// instance without an owner answers the same 401 — the setup/login screen is
// still pending, so the text states the fact and names no screen), a
// host/origin refusal; anything else is reported by the status the page saw
const SESSION_MESSAGES = Object.freeze({
  authenticated: '브라우저 세션이 연결되어 있습니다. 관제할 실행을 선택해 주세요.',
  unauthenticated: '소유자 세션이 없습니다. 소유자 설정·로그인 화면은 아직 구현 중입니다.',
  access_denied: '이 화면은 이 배포의 주소에서만 열 수 있습니다.',
});
const OFFLINE_MESSAGE = '서버에 연결하지 못했습니다. 잠시 후 다시 열어 주세요.';
const BOOT_FAILED_MESSAGE = '이 화면을 준비하지 못했습니다. 세션을 확인하지 못했습니다.';

function fail(message) {
  throw new Error(message);
}

function sessionFailureText(error) {
  if (Object.hasOwn(SESSION_MESSAGES, error?.code)) return [error.code, SESSION_MESSAGES[error.code]];
  if (Number.isInteger(error?.status)) return ['unavailable', `세션을 확인하지 못했습니다 (서버 응답 ${error.status}).`];
  return ['unavailable', OFFLINE_MESSAGE];
}

export async function boot({ document, location, fetch, crypto } = {}) {
  if (typeof document !== 'object' || document === null || typeof document.getElementById !== 'function'
      || typeof document.createElement !== 'function') fail('a document is required');
  if (typeof fetch !== 'function') fail('a fetch function is required');
  if (typeof crypto !== 'object' || crypto === null || typeof crypto.randomUUID !== 'function') fail('a crypto with randomUUID is required');
  const roots = {};
  for (const [name, id] of Object.entries(MOUNT_IDS)) {
    const element = document.getElementById(id);
    if (element === null || typeof element.replaceChildren !== 'function') fail(`the page has no mount for ${id}`);
    roots[name] = element;
  }
  const basePath = basePathFrom(location?.pathname);
  const session = createSupportedSession({ fetch, basePath });
  const commandId = () => crypto.randomUUID();
  try {
    await session.establish();
  } catch (error) {
    const [code, text] = sessionFailureText(error);
    roots.session.dataset.state = code;
    roots.session.textContent = text;
    return Object.freeze({ established: false, basePath, session, list: null, panel: null, commandId });
  }
  roots.session.dataset.state = 'authenticated';
  roots.session.textContent = SESSION_MESSAGES.authenticated;
  const panel = createRunPanel({ root: roots.panel, document, basePath, request: session.request, commandId });
  const list = createRunList({
    root: roots.source, document, basePath, request: session.request,
    onSelect: runId => panel.read(runId).catch(() => {}),  // the refusal is on the panel
  });
  try {
    await list.refresh();
  } catch {
    // the list's own status names the failure; the session stands
  }
  return Object.freeze({ established: true, basePath, session, list, panel, commandId });
}

// the page's entry: a boot that fails before or beside the session exchange
// (no crypto, a mount that throws) still reaches the status line, so the
// HTML's initial text never stands for a failure
export async function bootPage(globals) {
  try {
    return await boot(globals);
  } catch {
    const status = globals?.document?.getElementById?.(MOUNT_IDS.session);
    if (status && typeof status === 'object') {
      status.dataset.state = 'unavailable';
      status.textContent = BOOT_FAILED_MESSAGE;
    }
    return null;
  }
}

// in a browser the page boots itself; under node there is no document
if (typeof globalThis.document === 'object' && globalThis.document !== null
    && typeof globalThis.document.getElementById === 'function'
    && globalThis.document.getElementById(MOUNT_IDS.panel) !== null) {
  bootPage({ document: globalThis.document, location: globalThis.location,
    fetch: (...args) => globalThis.fetch(...args), crypto: globalThis.crypto });
}
