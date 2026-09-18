// T023/T025 (experience.md §5.1 items 4–6): the first work screen on the
// supported factory over `works-v1`. After the owner session is established
// the page states the retention notices (what stays on this instance, when an
// external model transmission happens, nothing sent to the maker), asks
// `어떤 일을 맡기고 싶으세요?`, keeps an unsaved draft in this browser only —
// said so, never claimed as instance storage — and saves the explanation on
// the instance as a work revision. Every save is one command id persisted with
// the text it was minted for: a retry replays it, and an edit made after a lost
// send is saved as the next revision only after that send is settled, so no
// sentence is orphaned. A draft carries the revision it was based on, so a
// revision saved from another screen is a conflict the owner resolves — the
// draft stays until the saved revision is reopened on purpose. A work the
// instance no longer has is forgotten, never the draft. Without a session
// nothing that could send a command is mounted. Every dependency (document,
// location, fetch, crypto, storage) is injected; the page passes the
// platform's own. Materials and the microphone are not on this factory yet
// and the page says so instead of pretending.

import { basePathFrom, createSupportedSession } from './session.mjs';

export const MOUNT_IDS = Object.freeze({ session: 'session-status', notice: 'intake-notice', form: 'work-form',
  save: 'save-status', materials: 'materials', link: 'observe-link' });
export const MAX_TEXT_CHARS = 20_000;  // app/services/works.py MAX_TEXT_CHARS
export const MAX_TEXT_BYTES = 65_536;  // app/services/works.py MAX_TEXT_BYTES (raw UTF-8)
const CREATE_SCHEMA = 'work-create-command-v1';
const REVISE_SCHEMA = 'work-revise-command-v1';
const PROMPT = '어떤 일을 맡기고 싶으세요?';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const utf8 = new TextEncoder();

export function storageKey(basePath) {
  return `deeptwin:intake:${basePath}`;
}

// the codes GET {base}session can answer (app/api/web_boundary.py)
const SESSION_TEXT = Object.freeze({
  unauthenticated: '소유자 세션이 없습니다. 이 인스턴스의 시작 화면(./)에서 로그인한 뒤 이 화면을 다시 열어 주세요.',
  access_denied: '이 화면은 이 배포의 주소에서만 열 수 있습니다.',
});
// the codes the works routes answer (app/api/works.py); a save failure never loses the draft
const ERROR_TEXT = Object.freeze({
  invalid_input: '입력 형식이 맞지 않습니다. 입력은 이 브라우저에 임시 보관됩니다.',
  unauthenticated: '세션이 끝났습니다. 시작 화면(./)에서 다시 로그인해 주세요. 입력은 이 브라우저에 임시 보관됩니다.',
  access_denied: '세션 확인에 실패했습니다. 이 화면을 다시 열어 주세요. 입력은 이 브라우저에 임시 보관됩니다.',
  not_found: '저장된 업무를 이 인스턴스에서 더는 찾지 못했습니다. 입력은 이 브라우저에 임시 보관되며, 다시 저장하면 새 업무로 저장됩니다.',
  conflict: '다른 화면에서 이 업무가 먼저 수정되었습니다. 현재 입력은 이 브라우저에만 임시 보관됩니다. 저장본을 다시 열면 그 내용으로 바뀝니다.',
  too_large: '설명이 너무 깁니다. 입력은 이 브라우저에 임시 보관됩니다.',
  unavailable: '서버가 요청을 처리하지 못했습니다. 입력은 이 브라우저에 임시 보관됩니다.',
});
const CREATE_CONFLICT_TEXT = '이 저장 명령은 이미 다른 내용으로 처리되었습니다. 현재 입력은 이 브라우저에만 임시 보관됩니다. 다시 저장하면 새 명령으로 보냅니다.';
const OFFLINE_TEXT = '서버에 연결하지 못했습니다. 입력은 이 브라우저에 임시 보관됩니다.';
const BOOT_FAILED_TEXT = '이 화면을 준비하지 못했습니다. 세션을 확인하지 못했습니다.';
// item 4: the notices, short, with the detail beneath — each claims only what this screen holds
const NOTICES = Object.freeze([
  '저장한 설명은 이 인스턴스의 저장소에만 남습니다. 저장 전 입력은 이 브라우저에만 임시 보관됩니다.',
  '외부 모델로의 전송은 제공자를 연결한 뒤 실행을 명시적으로 시작하는 시점에만 일어납니다. 이 화면은 어떤 제공자에도 연결하지 않으며 아무것도 전송하지 않습니다.',
  '제작자에게 자동으로 보내는 것은 없습니다.',
]);
const NOTICE_DETAIL = '저장한 설명은 이 인스턴스의 저장소에 수정본 단위로 남고, 이전 수정본은 덮어쓰지 않습니다. '
  + '아직 저장하지 않은 입력은 이 브라우저에만 임시 보관되며 다른 기기나 인스턴스에 있지 않습니다. '
  + '외부 모델·도구로 무엇이 전송되는지는 실행을 시작하기 전에 대상과 범위를 표시합니다.';

function fail(message) {
  throw new Error(message);
}

function sessionFailureText(error) {
  if (Object.hasOwn(SESSION_TEXT, error?.code)) return [error.code, SESSION_TEXT[error.code]];
  if (Number.isInteger(error?.status)) return ['unavailable', `세션을 확인하지 못했습니다 (서버 응답 ${error.status}).`];
  return ['unavailable', '서버에 연결하지 못했습니다. 잠시 후 다시 열어 주세요.'];
}

function textProblem(text) {
  if (!text) return '설명을 입력해 주세요.';
  if ([...text].length > MAX_TEXT_CHARS) return `설명은 ${MAX_TEXT_CHARS.toLocaleString('en-US')}자 이하여야 합니다.`;
  if (utf8.encode(text).length > MAX_TEXT_BYTES) return `설명은 UTF-8 ${MAX_TEXT_BYTES.toLocaleString('en-US')}바이트 이하여야 합니다.`;
  return null;
}

const isCount = value => Number.isInteger(value) && value >= 1;
const isUuid = value => typeof value === 'string' && UUID.test(value);

// what the browser store may hold, field by field; anything else is dropped (a tampered or
// corrupt store never steers a request); a work is kept only with its known revision
function validState(value) {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return {};
  const state = {};
  if (isUuid(value.work_id) && isCount(value.revision)) {
    state.work_id = value.work_id;
    state.revision = value.revision;
    if (isCount(value.base_revision)) state.base_revision = value.base_revision;
  }
  if (typeof value.draft_text === 'string') state.draft_text = value.draft_text;
  if (isUuid(value.pending_command_id) && typeof value.pending_text === 'string') {
    state.pending_command_id = value.pending_command_id;
    state.pending_text = value.pending_text;
  }
  return state;
}

function draftStore(storage, key) {
  // a per-browser convenience: every read and write is guarded, a blocked store is a no-op
  function read() {
    try {
      return validState(JSON.parse(storage?.getItem?.(key) ?? 'null'));
    } catch {
      return {};
    }
  }
  function write(state) {
    try {
      if (Object.keys(state).length === 0) storage?.removeItem?.(key);
      else storage?.setItem?.(key, JSON.stringify(state));
    } catch {
      // nothing: the page never depends on the browser store
    }
  }
  return { read, write };
}

export async function boot({ document, location, fetch, crypto, storage } = {}) {
  if (typeof document !== 'object' || document === null || typeof document.getElementById !== 'function'
      || typeof document.createElement !== 'function') fail('a document is required');
  if (typeof fetch !== 'function') fail('a fetch function is required');
  if (typeof location !== 'object' || location === null) fail('a location is required');
  if (typeof crypto !== 'object' || crypto === null || typeof crypto.randomUUID !== 'function') fail('a crypto with randomUUID is required');
  const roots = {};
  for (const [name, id] of Object.entries(MOUNT_IDS)) {
    const element = document.getElementById(id);
    if (element === null || typeof element.replaceChildren !== 'function') fail(`the page has no mount for ${id}`);
    roots[name] = element;
  }
  const basePath = basePathFrom(location.pathname);
  const prefix = basePath.slice(0, -1);
  const session = createSupportedSession({ fetch, basePath });
  const store = draftStore(storage, storageKey(basePath));
  const works = `${prefix}/api/v1/works`;
  roots.form.hidden = true;

  function element(tag, attributes = {}, text) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  function status(text, state) {
    roots.session.textContent = text;
    roots.session.dataset.state = state;
  }

  const notice = NOTICES.map(text => element('p', {}, text));
  const detail = element('details');
  detail.append(element('summary', {}, '자세히'), element('p', {}, NOTICE_DETAIL));
  roots.notice.replaceChildren(...notice, detail);

  status('브라우저 세션을 확인하는 중…', 'checking');
  try {
    await session.establish();
  } catch (error) {
    const [code, text] = sessionFailureText(error);
    status(text, code);
    return Object.freeze({ mode: code === 'unauthenticated' ? 'unauthenticated' : 'unavailable', basePath, session });
  }
  status('브라우저 세션이 연결되어 있습니다.', 'authenticated');

  // the form: the prompt, the explanation, the save
  const form = roots.form;
  form.replaceChildren();
  const label = element('label', {}, PROMPT);
  const area = element('textarea', { name: 'text', rows: '8', placeholder: '맡길 일을 문장으로 설명해 주세요.',
    autocapitalize: 'off', spellcheck: 'false' });
  area.dataset.field = 'text';
  label.append(area);
  const submit = element('button', { type: 'submit' }, '이 인스턴스에 저장');
  form.append(label, submit);
  // item 5: materials and the microphone — not on this factory yet, said plainly
  const addMaterials = element('button', { type: 'button' }, '자료 추가');
  addMaterials.disabled = true;
  roots.materials.replaceChildren(addMaterials,
    element('p', {}, '이 인스턴스에는 아직 자료·파일 입력과 마이크 입력이 없습니다. 지금은 설명만 저장됩니다.'));
  roots.link.replaceChildren(element('a', { href: './observe.html' }, '기록된 실행 관제 화면'));

  let state = store.read();

  function keep(changes) {
    state = { ...state, ...changes };
    for (const name of Object.keys(state)) if (state[name] === undefined) delete state[name];
    store.write(state);
  }

  function forgetWork() {
    keep({ work_id: undefined, revision: undefined, base_revision: undefined,
      pending_command_id: undefined, pending_text: undefined });
  }

  function savedText() {
    return `이 인스턴스에 저장됨 · 수정본 ${state.revision}`;
  }

  function saveStatus(text, code, { reopen = false } = {}) {
    roots.save.replaceChildren(element('span', {}, text));
    roots.save.dataset.state = code;
    if (reopen && state.work_id) {
      const button = element('button', { type: 'button' }, '저장본 다시 열기');
      button.addEventListener('click', reopenSaved);
      const rebase = element('button', { type: 'button' }, '현재 입력을 최신 수정본 위에 저장하기로 두기');
      rebase.addEventListener('click', rebaseDraft);
      roots.save.append(button, rebase);
    }
  }

  function draftStatus() {
    if (state.work_id) saveStatus(`이 브라우저에만 임시 보관된 미저장 초안 (인스턴스에 저장되지 않음) · 저장본은 수정본 ${state.revision}`, 'draft');
    else saveStatus('저장되지 않은 변경 — 이 브라우저에만 임시 보관됨 (인스턴스에 저장되지 않음)', 'draft');
  }

  function baseConflictStatus() {
    saveStatus(`다른 화면에서 수정본 ${state.revision}이(가) 저장되었습니다. 현재 입력은 수정본 ${state.base_revision}을(를) 기준으로 한 초안이며 이 브라우저에만 임시 보관됩니다. 저장본을 다시 열면 그 내용으로 바뀝니다.`, 'conflict', { reopen: true });
  }

  function failureText(error) {
    if (error?.code === 'unavailable' && !Number.isInteger(error?.status)) return ['unavailable', OFFLINE_TEXT];
    if (Object.hasOwn(ERROR_TEXT, error?.code)) return [error.code, ERROR_TEXT[error.code]];
    if (Number.isInteger(error?.status)) return ['unavailable', ERROR_TEXT.unavailable];
    return ['unavailable', OFFLINE_TEXT];
  }

  function revisionShape(saved, workId) {
    if (typeof saved?.text !== 'string' || !isCount(saved?.revision) || !isUuid(saved?.work_id)
        || (workId !== undefined && saved.work_id !== workId)) {
      throw Object.assign(new Error('the saved work could not be read'), { code: 'unavailable', status: 200 });
    }
    return saved;
  }

  async function readSaved() {
    return revisionShape(await session.request(`${works}/${state.work_id}`), state.work_id);
  }

  // a command: on a 403 the token no longer matches the cookie (the owner logged in again
  // elsewhere) — re-establish once and retry; a second refusal is reported as such
  async function command(path, body) {
    try {
      return await session.request(path, { method: 'POST', body });
    } catch (error) {
      if (error?.code !== 'access_denied') throw error;
      await session.establish();
      return await session.request(path, { method: 'POST', body });
    }
  }

  let busy = false;
  let savedValue = null;  // the text of the revision last read or saved, in memory only

  async function reopenSaved() {
    if (busy) return;
    busy = true;
    try {
      const saved = await readSaved();
      area.value = saved.text;
      savedValue = saved.text;
      keep({ revision: saved.revision, base_revision: undefined, draft_text: undefined,
        pending_command_id: undefined, pending_text: undefined });
      saveStatus(savedText(), 'saved');
    } catch (error) {
      const [code, text] = failureText(error);
      saveStatus(text, code);
    } finally {
      busy = false;
    }
  }

  // the owner keeps the draft and takes the latest revision as its base: the next save
  // seals it on top (the other screen's revision stays, immutable)
  async function rebaseDraft() {
    if (busy) return;
    busy = true;
    try {
      const saved = await readSaved();
      savedValue = saved.text;
      keep({ revision: saved.revision, base_revision: saved.revision, draft_text: area.value,
        pending_command_id: undefined, pending_text: undefined });
      draftStatus();
    } catch (error) {
      const [code, text] = failureText(error);
      saveStatus(text, code);
    } finally {
      busy = false;
    }
  }

  let mode = 'new';
  if (state.work_id) {
    try {
      const saved = await readSaved();
      savedValue = saved.text;
      keep({ revision: saved.revision });
      if (state.pending_command_id !== undefined && state.pending_text === saved.text) {
        // the send whose answer was lost is what the instance holds: settled here, and a
        // draft edited since is an edit on that revision — never another screen's doing
        keep({ pending_command_id: undefined, pending_text: undefined, base_revision: saved.revision });
      }
      if (typeof state.draft_text === 'string' && state.draft_text !== saved.text) {
        area.value = state.draft_text;
        if (state.base_revision === undefined) keep({ base_revision: saved.revision });
        if (state.base_revision !== saved.revision) baseConflictStatus();
        else draftStatus();
      } else {
        area.value = saved.text;
        keep({ draft_text: undefined, base_revision: undefined });
        saveStatus(savedText(), 'saved');
      }
      mode = 'open';
    } catch (error) {
      if (error?.code === 'not_found') {
        // the instance no longer has the work: forgotten — never the draft, the only copy
        forgetWork();
        area.value = typeof state.draft_text === 'string' ? state.draft_text : '';
        if (area.value) draftStatus();
        else saveStatus('저장된 업무가 이 인스턴스에 없어 새 업무로 시작합니다.', 'new');
      } else {
        area.value = typeof state.draft_text === 'string' ? state.draft_text : '';
        const [code, text] = failureText(error);
        saveStatus(text, code);
        mode = 'open';
      }
    }
  } else if (typeof state.draft_text === 'string' && state.draft_text) {
    area.value = state.draft_text;
    draftStatus();
  } else {
    saveStatus('아직 저장된 업무가 없습니다.', 'new');
  }
  form.hidden = false;

  area.addEventListener('input', () => {
    keep({ draft_text: area.value, base_revision: state.work_id && state.base_revision === undefined ? state.revision : state.base_revision });
    draftStatus();
  });

  // one send of one command with its own text; the answer becomes the work's state
  async function send(commandId, text) {
    const saved = state.work_id
      ? revisionShape(await command(`${works}/${state.work_id}/revisions`, {
        schema_version: REVISE_SCHEMA, command_id: commandId, expected_revision: state.base_revision ?? state.revision, text }), state.work_id)
      : revisionShape(await command(works, { schema_version: CREATE_SCHEMA, command_id: commandId, text }));
    keep({ work_id: saved.work_id, revision: saved.revision, base_revision: undefined,
      pending_command_id: undefined, pending_text: undefined });
    savedValue = saved.text;
    return saved;
  }

  // after a send: text typed meanwhile stays a browser draft on the revision just saved
  function settled() {
    if (area.value === savedValue) {
      keep({ draft_text: undefined });
      saveStatus(savedText(), 'saved');
    } else {
      keep({ draft_text: area.value, base_revision: state.revision });
      draftStatus();
    }
  }

  function sendFailed(error) {
    const [code, text] = failureText(error);
    if (code === 'conflict' || code === 'invalid_input' || code === 'too_large') {
      // a refused or conflicting command is spent: the server holds it to its content and target
      keep({ pending_command_id: undefined, pending_text: undefined });
    }
    if (code === 'not_found') forgetWork();
    if (code === 'conflict' && !state.work_id) saveStatus(CREATE_CONFLICT_TEXT, code);
    else saveStatus(text, code, { reopen: code === 'conflict' });
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    const text = area.value;
    const problem = textProblem(text);
    if (problem) {
      saveStatus(problem, 'invalid_input');
      return;
    }
    if (state.work_id && state.pending_command_id === undefined && text === savedValue) {
      // nothing to seal: the instance already holds this sentence
      keep({ draft_text: undefined, base_revision: undefined });
      saveStatus(savedText(), 'saved');
      return;
    }
    busy = true;
    try {
      saveStatus('이 인스턴스에 저장하는 중…', 'sending');
      // a send whose answer was lost is settled first, with the text it was minted for: the
      // server replays it or seals it; only then is a newer draft saved as the next revision
      if (state.pending_command_id !== undefined) {
        const pendingText = state.pending_text;
        await send(state.pending_command_id, pendingText);
        if (pendingText === text) {
          settled();
          return;
        }
      }
      const commandId = crypto.randomUUID();
      keep({ draft_text: text, pending_command_id: commandId, pending_text: text });
      await send(commandId, text);
      settled();
    } catch (error) {
      sendFailed(error);
    } finally {
      busy = false;
    }
  });

  return Object.freeze({ mode, basePath, session });
}

// the page's entry: a boot that fails before the exchange still reaches the status line
export async function bootPage(globals) {
  try {
    return await boot(globals);
  } catch {
    const status = globals?.document?.getElementById?.(MOUNT_IDS.session);
    if (status && typeof status === 'object') {
      status.dataset.state = 'unavailable';
      status.textContent = BOOT_FAILED_TEXT;
    }
    return null;
  }
}

if (typeof globalThis.document === 'object' && globalThis.document !== null
    && typeof globalThis.document.getElementById === 'function'
    && globalThis.document.getElementById(MOUNT_IDS.form) !== null) {
  let storage = null;
  try {
    storage = globalThis.localStorage ?? null;
  } catch {
    storage = null;
  }
  bootPage({ document: globalThis.document, location: globalThis.location, crypto: globalThis.crypto,
    storage, fetch: (...args) => globalThis.fetch(...args) });
}
