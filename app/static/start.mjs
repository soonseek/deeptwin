// T025 / UX-AC01 (experience.md §5.1.3): the instance's first screen. On an
// instance without an owner the page shows the first-owner setup form — the
// one-time capability is typed in (never part of a URL, never logged) and the
// owner password is created (fifteen characters or more); on an instance
// with an owner it shows the login form. The server alone decides: the page
// reads the public setup state from {base}health, posts to the establishment
// routes (`session/bootstrap`, `session/login`) with same-origin credentials
// and no CSRF (they are the public establishment), and on success moves to
// the observation page. An established session skips the page. Every
// dependency (document, location, fetch) is injected; the page passes the
// platform's own. Inputs are cleared after every exchange, success or not.

import { basePathFrom } from './session.mjs';

export const MOUNT_IDS = Object.freeze({ status: 'start-status', setup: 'setup-form', login: 'login-form' });
export const MIN_PASSWORD_CHARS = 15;  // app/services/owner_auth.py validate_credentials(choosing=True)
// the one-time capability: strict base64url, no padding, 32 bytes → 43 characters
// (the server also requires a canonical last character; a non-canonical one is its
// `invalid_input`, refused before any attempt is counted)
export const CAPABILITY = /^[A-Za-z0-9_-]{43}$/;
const SETUP_STATES = Object.freeze(['available', 'consumed', 'expired', 'exhausted', 'completed']);
// the server's byte bounds (app/services/owner_auth.py _scalar): UTF-8 bytes
const MAX_LOGIN_NAME_BYTES = 128;
const MAX_PASSWORD_BYTES = 1_024;
const utf8 = new TextEncoder();

const STATUS_TEXT = Object.freeze({
  checking: '이 인스턴스의 상태를 확인하는 중…',
  setup: '이 인스턴스에는 아직 소유자가 없습니다. 최초 소유자를 설정해 주세요. 일회용 capability는 배포 준비물에서 받은 값을 직접 입력합니다.',
  login: '이 인스턴스의 소유자로 로그인해 주세요.',
  consumed: '최초 소유자 설정이 완료되지 않은 채 남아 있습니다. 이 화면을 다시 열어도 같다면 여기서는 설정을 마칠 수 없으며, 배포 운영자의 복구 절차가 필요합니다.',
  expired: '최초 소유자 설정 기한이 만료되었습니다. 배포 준비물에서 새 capability를 받아 인스턴스를 다시 준비해 주세요.',
  exhausted: '최초 소유자 설정 시도 횟수가 소진되었습니다. 배포 준비물에서 새 capability를 받아 인스턴스를 다시 준비해 주세요.',
  offline: '서버에 연결하지 못했습니다. 잠시 후 다시 열어 주세요.',
  unreadable: '이 인스턴스의 상태를 확인하지 못했습니다.',
  sending: '확인하는 중…',
});
// the codes the establishment routes answer (app/api/web_boundary.py auth_error)
const ERROR_TEXT = Object.freeze({
  credentials: '이름 또는 비밀번호가 맞지 않습니다. 최초 설정이라면 capability가 맞지 않습니다.',
  capacity: '시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.',
  setup_incomplete: '최초 소유자 설정이 완료되지 않은 채 남아 있습니다. 여기서는 마칠 수 없으며 배포 운영자의 복구 절차가 필요합니다.',
  setup_unavailable: '최초 소유자 설정을 지금 사용할 수 없습니다 (이미 완료되었거나 만료·소진되었습니다). 이 화면을 다시 열어 상태를 확인해 주세요.',
  invalid_input: '입력 형식이 맞지 않습니다.',
  unavailable: '서버가 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.',
  access_denied: '이 화면은 이 배포의 주소에서만 사용할 수 있습니다.',
  unauthenticated: '세션을 만들지 못했습니다. 다시 시도해 주세요.',
});
const CODE_BY_STATUS = Object.freeze({ 400: 'invalid_input', 401: 'credentials', 403: 'access_denied',
  409: 'setup_unavailable', 429: 'capacity', 503: 'unavailable' });

function fail(message) {
  throw new Error(message);
}

export function setupState(health) {
  if (typeof health !== 'object' || health === null || health.state !== 'available') fail('not a health reading');
  if (typeof health.owner !== 'boolean' || !SETUP_STATES.includes(health.setup)) fail('health carries no setup state');
  return Object.freeze({ owner: health.owner, setup: health.setup });
}

function nameProblem(name) {
  if (!name || name !== name.trim()) return '소유자 이름 형식이 맞지 않습니다 (앞뒤 공백 없이).';
  if (utf8.encode(name).length > MAX_LOGIN_NAME_BYTES) return `소유자 이름은 UTF-8 ${MAX_LOGIN_NAME_BYTES}바이트 이하여야 합니다.`;
  return null;
}

function passwordBytesProblem(password) {
  if (utf8.encode(password).length > MAX_PASSWORD_BYTES) return `비밀번호는 UTF-8 ${MAX_PASSWORD_BYTES}바이트 이하여야 합니다.`;
  return null;
}

function partition(payload, status) {
  if (typeof payload?.code === 'string' && Object.hasOwn(ERROR_TEXT, payload.code)) return payload.code;
  return CODE_BY_STATUS[status] ?? 'unavailable';
}

async function readJson(response) {
  try { return await response.json(); } catch { return undefined; }
}

export async function boot({ document, location, fetch } = {}) {
  if (typeof document !== 'object' || document === null || typeof document.getElementById !== 'function'
      || typeof document.createElement !== 'function') fail('a document is required');
  if (typeof fetch !== 'function') fail('a fetch function is required');
  if (typeof location !== 'object' || location === null || typeof location.assign !== 'function') fail('a location is required');
  const roots = {};
  for (const [name, id] of Object.entries(MOUNT_IDS)) {
    const element = document.getElementById(id);
    if (element === null) fail(`the page has no mount for ${id}`);
    roots[name] = element;
  }
  const basePath = basePathFrom(location.pathname);
  const prefix = basePath.slice(0, -1);
  const observe = `${prefix}/observe.html`;
  roots.setup.hidden = true;
  roots.login.hidden = true;

  function status(text, state = '') {
    roots.status.textContent = text;
    roots.status.dataset.state = state;
  }

  function element(tag, attributes = {}, text) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  function input(form, field, { type, label, autocomplete }) {
    const wrapper = element('label', {}, label);
    const box = element('input', { name: field, autocomplete, required: 'required',
      ...(type === 'text' ? { autocapitalize: 'off', spellcheck: 'false' } : {}) });
    box.type = type;
    box.dataset.field = field;
    wrapper.append(box);
    form.append(wrapper);
    return box;
  }

  async function establish(route, body) {
    status(STATUS_TEXT.sending, 'sending');
    let response;
    try {
      response = await fetch(route, { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    } catch {
      status(STATUS_TEXT.offline, 'unavailable');
      return false;
    }
    const payload = await readJson(response);
    if (!response.ok || payload?.state !== 'authenticated') {
      const code = response.ok ? 'unavailable' : partition(payload, response.status);
      status(ERROR_TEXT[code], code);
      return false;
    }
    location.assign(observe);
    return true;
  }

  async function sessionStands() {
    let response;
    try {
      response = await fetch(`${prefix}/session`, { method: 'GET', credentials: 'same-origin', headers: {} });
    } catch {
      return null;  // offline
    }
    const payload = await readJson(response);
    return response.ok && payload?.state === 'authenticated';
  }

  status(STATUS_TEXT.checking, 'checking');
  const standing = await sessionStands();
  if (standing === null) {
    status(STATUS_TEXT.offline, 'unavailable');
    return Object.freeze({ mode: 'unavailable', basePath });
  }
  if (standing) {
    location.assign(observe);
    return Object.freeze({ mode: 'established', basePath });
  }
  let state;
  try {
    const response = await fetch(`${prefix}/health`, { method: 'GET', credentials: 'same-origin', headers: {} });
    state = setupState(await readJson(response));
  } catch {
    status(STATUS_TEXT.unreadable, 'unavailable');
    return Object.freeze({ mode: 'unavailable', basePath });
  }
  if (state.owner) {
    const form = roots.login;
    form.replaceChildren();
    const name = input(form, 'login_name', { type: 'text', label: '소유자 이름', autocomplete: 'username' });
    const password = input(form, 'password', { type: 'password', label: '비밀번호', autocomplete: 'current-password' });
    const submit = element('button', { type: 'submit' }, '로그인');
    form.append(submit);
    form.hidden = false;
    status(STATUS_TEXT.login, 'login');
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const body = { login_name: name.value, password: password.value };
      password.value = '';
      const problem = nameProblem(body.login_name) ?? (body.password ? passwordBytesProblem(body.password) : '비밀번호를 입력해 주세요.');
      if (problem) {
        status(problem, 'invalid_input');
        return;
      }
      await establish(`${prefix}/session/login`, body);
    });
    return Object.freeze({ mode: 'login', basePath });
  }
  if (state.setup !== 'available') {
    status(STATUS_TEXT[state.setup] ?? STATUS_TEXT.unreadable, state.setup);
    return Object.freeze({ mode: 'unavailable', basePath });
  }
  const form = roots.setup;
  form.replaceChildren();
  const capability = input(form, 'capability', { type: 'password', label: '일회용 capability', autocomplete: 'off' });
  const name = input(form, 'login_name', { type: 'text', label: '소유자 이름', autocomplete: 'username' });
  const password = input(form, 'password', { type: 'password', label: `비밀번호 (${MIN_PASSWORD_CHARS}자 이상)`,
    autocomplete: 'new-password' });
  form.append(element('button', { type: 'submit' }, '최초 소유자 설정'));
  form.hidden = false;
  status(STATUS_TEXT.setup, 'setup');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const body = { login_name: name.value, password: password.value, raw_capability_b64u: capability.value };
    password.value = '';
    capability.value = '';
    if (!CAPABILITY.test(body.raw_capability_b64u)) {
      status('capability 형식이 맞지 않습니다: 43자의 base64url 값이어야 합니다.', 'invalid_input');
      return;
    }
    const problem = nameProblem(body.login_name) ?? passwordBytesProblem(body.password);
    if (problem) {
      status(problem, 'invalid_input');
      return;
    }
    if ([...body.password].length < MIN_PASSWORD_CHARS) {
      status(`비밀번호는 ${MIN_PASSWORD_CHARS}자 이상이어야 합니다.`, 'invalid_input');
      return;
    }
    await establish(`${prefix}/session/bootstrap`, body);
  });
  return Object.freeze({ mode: 'setup', basePath });
}

// the page's entry: a boot that fails before the exchange still reaches the status line
export async function bootPage(globals) {
  try {
    return await boot(globals);
  } catch {
    const status = globals?.document?.getElementById?.(MOUNT_IDS.status);
    if (status && typeof status === 'object') {
      status.dataset.state = 'unavailable';
      status.textContent = STATUS_TEXT.unreadable;
    }
    return null;
  }
}

if (typeof globalThis.document === 'object' && globalThis.document !== null
    && typeof globalThis.document.getElementById === 'function'
    && globalThis.document.getElementById(MOUNT_IDS.setup) !== null) {
  bootPage({ document: globalThis.document, location: globalThis.location,
    fetch: (...args) => globalThis.fetch(...args) });
}
