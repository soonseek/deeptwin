// T048/T025: the shell mount on the supported factory. `observe.html` loads
// this module by a relative path, so it resolves under the deployment base
// path as under `/`. `boot` derives the base path from the document location,
// establishes the supported session client from the owner cookie the browser
// already holds (no login UI here — that is T025's shell), and only then
// mounts the run list (the public snapshot's runs) and the run panel; without
// a session it says so plainly and mounts nothing that could send a command.
// Every dependency (document, location, fetch, crypto) is injected so the
// boot is testable under node; the page passes the platform's own.

import { createAlternativeFileForm } from './alternative-file.mjs';
import { createAlternativeEditor } from './alternatives.mjs';
import { createArtifactViewer } from './artifacts.mjs';
import { createInquiryPanel } from './inquiry.mjs';
import { createRunList } from './run-list.mjs';
import { createRunPanel } from './run-panel.mjs';
import { basePathFrom, createSupportedSession } from './session.mjs';

export const ALTERNATIVE_MOUNT_ID = 'run-alternative';
export const ALTERNATIVE_FILE_MOUNT_ID = 'run-alternative-file';
export const INQUIRY_MOUNT_ID = 'run-inquiry';
export const MOUNT_IDS = Object.freeze({
  session: 'session-status', source: 'run-source', panel: 'run-panel', artifacts: 'run-artifacts',
});

// the codes GET {base}session can actually answer (app/api/web_boundary.py,
// owner_auth.authenticate_request): a session that stands, none (a fresh
// instance without an owner answers the same 401 — the start screen at `./`
// handles both setup and login, so the text names it), a host/origin refusal;
// anything else is reported by the status the page saw
const SESSION_MESSAGES = Object.freeze({
  authenticated: '브라우저 세션이 연결되어 있습니다. 관제할 실행을 선택해 주세요.',
  unauthenticated: '소유자 세션이 없습니다. 이 인스턴스의 시작 화면(./)에서 최초 소유자 설정 또는 로그인을 마친 뒤 이 화면을 다시 열어 주세요.',
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
    return Object.freeze({ established: false, basePath, session, list: null, panel: null, artifacts: null, commandId });
  }
  roots.session.dataset.state = 'authenticated';
  roots.session.textContent = SESSION_MESSAGES.authenticated;
  const panel = createRunPanel({ root: roots.panel, document, basePath, request: session.request, commandId });
  // the owner's in-place editor, the alternative-file form and the observed difference
  // mount only where the page offers their surfaces (T052/T053/T060)
  const inquiryRoot = document.getElementById(INQUIRY_MOUNT_ID);
  const inquiry = inquiryRoot !== null && typeof inquiryRoot?.replaceChildren === 'function'
    ? createInquiryPanel({ root: inquiryRoot, document, basePath, request: session.request, crypto })
    : null;
  const onFrozen = inquiry === null ? undefined : (runId, artifactId, alternativeId) => inquiry.show(runId, artifactId, alternativeId);
  const alternativeRoot = document.getElementById(ALTERNATIVE_MOUNT_ID);
  const editor = alternativeRoot !== null && typeof alternativeRoot?.replaceChildren === 'function'
    ? createAlternativeEditor({ root: alternativeRoot, document, basePath, request: session.request, crypto, onFrozen })
    : null;
  const fileRoot = document.getElementById(ALTERNATIVE_FILE_MOUNT_ID);
  const fileForm = fileRoot !== null && typeof fileRoot?.replaceChildren === 'function'
    ? createAlternativeFileForm({ root: fileRoot, document, basePath, request: session.request, crypto, onFrozen })
    : null;
  const artifacts = createArtifactViewer({ root: roots.artifacts, document, basePath, request: session.request,
    onEdit: editor === null ? undefined : (runId, item) => editor.open(runId, item),
    onAlternativeFile: fileForm === null ? undefined : (runId, item) => fileForm.open(runId, item) });
  const list = createRunList({
    root: roots.source, document, basePath, request: session.request,
    // each refusal is shown on its own surface
    onSelect: runId => Promise.all([panel.read(runId).catch(() => {}), artifacts.show(runId).catch(() => {})]),
  });
  try {
    await list.refresh();
  } catch {
    // the list's own status names the failure; the session stands
  }
  return Object.freeze({ established: true, basePath, session, list, panel, artifacts, commandId });
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
