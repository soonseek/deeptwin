// T025 tail: the owner changes their password and ends their other sessions from the
// browser (api.md §1). A password change re-verifies the current password, ends every
// session that used the old one, and rotates this browser's session; the page takes
// the new CSRF value from the answer. Passwords live only in the form fields: they
// are never stored, logged or echoed, and the fields are cleared after every attempt.

import { technicalDetails } from './ui-parts.mjs';

export const MIN_PASSWORD_SCALARS = 15;

export const MESSAGES = Object.freeze({
  changed: '비밀번호를 바꿨습니다. 다른 곳의 세션은 모두 끝났고, 이 브라우저는 새 세션으로 이어집니다.',
  revoked: count => (count ? `다른 세션 ${count}개를 끝냈습니다.` : '끝낼 다른 세션이 없습니다.'),
  mismatch: '새 비밀번호와 확인이 서로 다릅니다.',
  short: `새 비밀번호는 ${MIN_PASSWORD_SCALARS}자 이상이어야 합니다.`,
  same: '새 비밀번호가 지금 비밀번호와 같습니다.',
  working: '처리하는 중…',
});

export const ERROR_MESSAGES = Object.freeze({
  credentials: '지금 비밀번호가 맞지 않습니다.',
  invalid_input: '입력을 확인해 주세요.',
  unauthenticated: '세션이 끝났습니다. 시작 화면(./)에서 다시 로그인해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다.',
  capacity: '요청이 너무 많습니다. 잠시 뒤 다시 시도해 주세요.',
  conflict: '다른 곳에서 먼저 바뀌었습니다. 다시 로그인해 주세요.',
  unavailable: '처리하지 못했습니다.',
});

function fail(message) {
  throw new Error(message);
}

// the new password's own rule, checked before any work (api.md: ≥15 Unicode scalars)
export function passwordProblem(current, next, confirm) {
  if (next !== confirm) return MESSAGES.mismatch;
  if ([...next].length < MIN_PASSWORD_SCALARS) return MESSAGES.short;
  if (next === current) return MESSAGES.same;
  return null;
}

export function createAccountPanel({ root, document, fetch, basePath = '/', session } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof fetch !== 'function') fail('a fetch function is required');
  if (typeof session?.csrfToken !== 'function' || typeof session?.adopt !== 'function') fail('a session adapter is required');
  const prefix = basePath.slice(0, -1);

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  function field(id, label) {
    const input = element('input', undefined, { id, type: 'password', autocomplete: id === 'account-current'
      ? 'current-password' : 'new-password', maxlength: '1024' });
    return [element('label', label, { for: id }), input];
  }

  const status = element('p', '', { role: 'status', 'aria-live': 'polite' });
  const [currentLabel, current] = field('account-current', '지금 비밀번호');
  const [nextLabel, next] = field('account-new', '새 비밀번호 (15자 이상)');
  const [confirmLabel, confirm] = field('account-confirm', '새 비밀번호 확인');
  const change = element('button', '비밀번호 바꾸기', { type: 'button' });
  const revoke = element('button', '다른 세션 모두 끝내기', { type: 'button' });
  root.replaceChildren(element('h2', '계정과 세션'), status, currentLabel, current, nextLabel, next,
    confirmLabel, confirm, change, revoke);

  function say(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  async function post(path, body) {
    const response = await fetch(`${prefix}${path}`, { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrfToken() }, body: JSON.stringify(body) });
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    if (!response.ok) {
      const code = response.status === 401 && path.endsWith('/password') && payload?.code === 'unauthenticated'
        ? 'unauthenticated' : payload?.code;
      throw Object.assign(new Error('refused'), { code: code ?? 'unavailable', status: response.status });
    }
    return payload;
  }

  function refusal(error) {
    const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
    say(ERROR_MESSAGES[code], code);
  }

  async function changePassword() {
    const problem = passwordProblem(current.value, next.value, confirm.value);
    if (problem) {
      say(problem, 'invalid_input');
      return null;
    }
    const body = { current_password: current.value, new_password: next.value };
    current.value = next.value = confirm.value = '';  // never kept past the attempt
    say(MESSAGES.working, 'working');
    try {
      const answer = await post('/session/password', body);
      session.adopt(answer.csrf_token);  // the rotated session's CSRF value
      say(MESSAGES.changed, 'changed');
      return answer;
    } catch (error) {
      refusal(error);
      throw error;
    } finally {
      body.current_password = body.new_password = '';
    }
  }

  async function revokeOthers() {
    say(MESSAGES.working, 'working');
    try {
      const answer = await post('/session/revoke-others', {});
      say(MESSAGES.revoked(answer.revoked), 'revoked');
      return answer;
    } catch (error) {
      refusal(error);
      throw error;
    }
  }

  change.addEventListener('click', () => changePassword().catch(() => {}));
  revoke.addEventListener('click', () => revokeOthers().catch(() => {}));
  return Object.freeze({ changePassword, revokeOthers });
}

// T090: the owner's stored provider credentials (/api/v1/credentials). The status read is
// the committed ledger only (zero gateway effect): the redacted credential list (handle,
// provider, custody state), each provider connection's binding head (state, binding
// revision, whether a catalog snapshot / model choice exists for that revision) and every
// unfinished or fenced act. Connections and acts are shown read-only; the only act the
// page offers on them is the owner's explicit fence of a store whose result stayed
// unconfirmed, and only once the server's `fence_available_at` has passed (the server
// still decides: an early fence is refused `fence_not_due`).
// A secret is typed into a masked field, read once when the owner submits, and the field
// is cleared before the request leaves; the page never writes it to an attribute, the DOM
// or browser storage. Deleting retires DeepTwin's local encrypted copy only: it does NOT
// revoke the key at the provider (every answer says `provider_revocation: "not_performed"`).
// An answer the gateway could not confirm (`command_pending`) is retried under the same
// intent, which only looks the earlier request up; a secret lost before it was stored
// (`secret_input_lost`) or a fenced act needs a new request.

export const CREDENTIAL_PROVIDERS = Object.freeze(['claude', 'codex']);

// custody state of the stored record; whether it is the provider's bound key is shown
// separately, from the connection's binding head
export const CREDENTIAL_STATES = Object.freeze({
  stored_unbound: '보관됨 (게이트웨이에 암호화 저장)',
  pending: '저장 결과 확인 중',
  cleanup_pending: '삭제됨 (로컬 사본 정리 대기)',
  secret_input_lost: '저장 전에 유실됨',
  erasure_completed: '로컬 사본 삭제 완료',
});

export const CONNECTION_STATES = Object.freeze({
  bound: '연결됨',
  revoked_pending_erasure: '연결 해제됨 (삭제 진행 중, 이 키로는 더 연결하지 않음)',
});

export const CONNECTION_MESSAGES = Object.freeze({
  empty: '연결된 제공자가 없습니다.',
  boundKey: revision => `이 제공자 연결에 쓰이는 키 (바인딩 수정본 ${revision})`,
  revision: revision => `바인딩 수정본 ${revision}`,
  catalog: Object.freeze({ current: '이 바인딩의 모델 목록: 있음', absent: '이 바인딩의 모델 목록: 없음' }),
  model_choice: Object.freeze({ current: '이 바인딩의 모델 선택: 있음', absent: '이 바인딩의 모델 선택: 없음' }),
  voids: '키를 교체하거나 삭제하면 그 전 바인딩의 모델 목록과 모델 선택은 무효가 됩니다. 새 바인딩의 목록은 "모델 목록 새로 고침"을 누를 때만 생깁니다. 그때만 게이트웨이가 보관한 키로 제공자의 모델 목록을 읽습니다(과금되는 모델 호출은 아님). 키 저장·교체·삭제와 상태 읽기는 목록을 새로 고치지 않습니다.',
  independent: '이 게이트웨이 키와 모델 선택은 "Claude 연결"(서버 메모리에만 두는 키)과 별개입니다. 여기서 키를 교체하거나 삭제해도 그쪽 키는 바뀌지 않고, 그쪽에서 잊어도 여기는 바뀌지 않습니다. 지금 실행은 이 게이트웨이 키가 아니라 그쪽 키를 씁니다.',
  gatewayPending: '게이트웨이 반영 대기: 게이트웨이가 이 바인딩을 확인하기 전까지 이 키로는 요청을 보내지 않습니다.',
  chosen: model => `선택된 모델: ${model}`,
  notListable: '이 제공자의 모델 목록은 게이트웨이로 읽을 수 없습니다.',
});

export const CATALOG_RESULTS = Object.freeze({
  refreshed: (revision, count) => `바인딩 수정본 ${revision}의 모델 목록을 새로 고쳤습니다 (${count}개).`,
  chosen: model => `모델을 선택했습니다: ${model}`,
});

// providers whose model list the gateway's send path can read
const LISTABLE_PROVIDERS = new Set(['claude']);
const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

export const ACT_KINDS = Object.freeze({ create: '새 키 저장', rotate: '키 교체', delete: '삭제' });

export const PENDING_MESSAGES = Object.freeze({
  empty: '끝나지 않은 요청이 없습니다.',
  command_pending: '결과 미확인 (게이트웨이가 아직 처리 중이거나 명령 상태를 모름: pending/unknown)',
  fenceAt: stamp => `차단 가능 시각: ${stamp}`,
  fenceNow: '지금 차단할 수 있습니다. 차단하면 이 요청은 끝나며, 키를 다시 보내지 않고 연결하지도 않습니다.',
  noFence: '차단 대상이 아닌 요청입니다. 같은 요청을 다시 보내면 결과만 확인합니다.',
  fenced: '차단됨',
  uncertain: Object.freeze({
    unknown: '게이트웨이의 기록 상태는 여전히 모릅니다. 나중에 저장되더라도 연결하지 않고 정리합니다(unbound_orphan).',
    secret_input_lost: '키 값이 저장되기 전에 유실됐습니다.',
    retirement_pending: '늦게 저장된 기록을 연결하지 않고 정리하는 중입니다(unbound_orphan).',
    cleanup_pending: '늦게 저장된 기록을 연결하지 않고 정리했습니다(unbound_orphan, 로컬 사본 정리 대기).',
  }),
});

export const FENCE_RESULTS = Object.freeze({
  fenced: '요청을 차단했습니다. 게이트웨이의 기록 상태는 모르며, 늦게 저장되더라도 연결하지 않고 정리합니다.',
  orphan_retired: '요청을 차단했습니다. 게이트웨이에 저장돼 있던 기록은 연결하지 않고 정리했습니다(unbound_orphan). 제공자 쪽의 키는 폐기되지 않았습니다.',
  orphan_retiring: '요청을 차단했습니다. 게이트웨이에 저장돼 있던 기록은 연결하지 않으며, 정리(unbound_orphan)는 다음 요청 때 이어집니다. 제공자 쪽의 키는 폐기되지 않았습니다.',
  secret_input_lost: '차단하려고 확인해 보니 키 값이 저장되기 전에 유실됐습니다. 새 요청으로 키를 다시 입력해 주세요.',
  still_pending: '게이트웨이가 이 요청을 아직 처리 중이라 차단하지 않았습니다. 요청은 여전히 결과 미확인입니다.',
  fence_not_due: '아직 차단할 수 없습니다. 차단 가능 시각이 지난 뒤 다시 시도하세요.',
});

export const CREDENTIAL_MESSAGES = Object.freeze({
  intro: '제공자 API 키를 이 배포의 자격증명 게이트웨이에 암호화해 보관합니다. 화면에는 키 값이 다시 나오지 않습니다.',
  revocation: '여기서 삭제해도 제공자 쪽의 키는 폐기되지 않습니다. 키를 더 이상 쓰지 않으려면 제공자 콘솔에서 직접 폐기하세요.',
  confirmDelete: handle => `자격증명 ${handle}의 로컬 사본을 삭제합니다. 제공자 쪽의 키는 폐기되지 않습니다(provider_revocation: not_performed).`,
  empty: '저장된 자격증명이 없습니다.',
  working: '처리하는 중…',
  created: '키를 저장했습니다.',
  rotated: '키를 교체했습니다. 이전 키의 로컬 사본은 정리 대기 상태이고, 이전 바인딩의 모델 목록과 모델 선택은 무효가 됐습니다.',
  deleted: '로컬 사본을 삭제했습니다. 제공자 쪽의 키는 폐기되지 않았습니다.',
  rotating: handle => `자격증명 ${handle}의 새 키를 입력하세요.`,
  noSecret: '키 값을 입력하세요.',
  retryPending: '같은 요청의 결과를 다시 조회하려면 키를 다시 입력하고 "결과 다시 확인"을 누르세요. 조회만 하며, 다시 입력한 값은 저장되지 않습니다.',
});

export const CREDENTIAL_ERRORS = Object.freeze({
  invalid_input: '자격증명 요청 형식을 확인해 주세요.',
  not_found: '그 자격증명을 찾지 못했습니다.',
  conflict: '이미 다른 내용으로 처리됐거나, 같은 자격증명의 이전 요청이 아직 끝나지 않았습니다.',
  command_pending: '요청 결과를 아직 확인하지 못했습니다. 같은 요청으로 다시 확인할 수 있습니다.',
  secret_input_lost: '키 값이 저장되기 전에 유실됐습니다. 새 요청으로 키를 다시 입력해 주세요.',
  connection_bound: '이 제공자에는 이미 연결된 키가 있습니다. 새 키로 바꾸려면 교체를 사용하세요.',
  connection_conflict: '저장하는 동안 제공자 연결이 바뀌었습니다. 이번 키는 연결하지 않고 정리합니다.',
  fenced: '이 요청은 결과를 확인하지 못해 차단됐습니다. 새 요청으로 다시 시도해 주세요.',
  fence_not_due: FENCE_RESULTS.fence_not_due,
  catalog_stale: '요청하는 동안 제공자 연결이 바뀌어 이 결과는 쓰지 않았습니다. 현재 연결로 다시 새로 고쳐 주세요.',
  model_not_listed: '현재 바인딩의 모델 목록에 없는 모델입니다.',
  binding_refused: '게이트웨이가 이 연결의 키 사용을 거부했습니다. 상태를 다시 읽어 주세요.',
  transport_unqualified: '게이트웨이의 제공자 전송 매니페스트가 검증되지 않았거나 검증 뒤 바뀌어, 아무 요청도 보내지 않았습니다.',
  budget_refused: '이 새로 고침의 예산 예약이 한도를 넘었거나 이미 쓰여, 제공자에게 보내지 않았습니다. 다시 새로 고쳐 주세요.',
  provider_rejected: '제공자가 이 키로 모델 목록을 읽는 것을 거부했습니다.',
  provider_unavailable: '제공자의 모델 목록을 읽지 못했습니다. 잠시 뒤 다시 시도해 주세요.',
  connection_unbound: '이 제공자에는 연결된 키가 없습니다.',
  catalog_unsupported: '이 제공자의 모델 목록은 게이트웨이로 읽을 수 없습니다.',
  dependency_unavailable: '자격증명 게이트웨이를 쓸 수 없습니다. 이 배포에 연결되어 있지 않거나 응답하지 않습니다.',
  unauthenticated: '세션이 끝났습니다. 시작 화면(./)에서 다시 로그인해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다.',
  unavailable: '처리하지 못했습니다.',
});

const CREDENTIAL_HANDLE = /^[0-9a-f]{32}$/;
const INTENT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const LEDGER_STAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/;
const UNCERTAIN = new Set(Object.keys(PENDING_MESSAGES.uncertain));
const PRESENCE = new Set(['current', 'absent']);
const MAX_TIMER_MS = 2 ** 31 - 1;

// the ledger's microsecond UTC stamp, as epoch milliseconds and as shown to the owner
function stampMillis(stamp) { return Date.parse(`${stamp.slice(0, 23)}Z`); }
function stampText(stamp) { return `${stamp.slice(0, 19).replace('T', ' ')} UTC`; }

function validModels(value, catalog) {
  if (value === undefined) return true;
  return Array.isArray(value) && (catalog === 'absent' ? value.length === 0
    : value.length >= 1 && value.length <= 200 && new Set(value).size === value.length
      && value.every(model => typeof model === 'string' && MODEL_ID.test(model)));
}

function validConnection(entry) {
  return entry !== null && typeof entry === 'object' && CREDENTIAL_PROVIDERS.includes(entry.provider)
    && Object.hasOwn(CONNECTION_STATES, entry.state) && CREDENTIAL_HANDLE.test(entry.handle)
    && Number.isInteger(entry.binding_revision) && entry.binding_revision >= 1
    && PRESENCE.has(entry.catalog) && PRESENCE.has(entry.model_choice)
    && (entry.gateway_head === undefined || ['applied', 'pending'].includes(entry.gateway_head))
    && validModels(entry.models, entry.catalog)
    && (entry.chosen_model === undefined || entry.chosen_model === null
      || (entry.model_choice === 'current' && (entry.models ?? []).includes(entry.chosen_model)));
}

function validPending(entry) {
  return entry !== null && typeof entry === 'object' && INTENT_ID.test(entry.intent_id)
    && Object.hasOwn(ACT_KINDS, entry.kind) && CREDENTIAL_HANDLE.test(entry.handle)
    && CREDENTIAL_PROVIDERS.includes(entry.provider) && ['command_pending', 'fenced'].includes(entry.state)
    && (entry.fence_available_at === null || (typeof entry.fence_available_at === 'string'
      && LEDGER_STAMP.test(entry.fence_available_at) && Number.isFinite(stampMillis(entry.fence_available_at))))
    && (entry.uncertain_record === null || UNCERTAIN.has(entry.uncertain_record));
}

export function createCredentialsPanel({ root, document, fetch, basePath = '/', session,
  randomUUID = () => globalThis.crypto.randomUUID(), now = () => Date.now(),
  setTimer = (callback, ms) => globalThis.setTimeout(callback, ms),
  clearTimer = handle => globalThis.clearTimeout(handle) } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof fetch !== 'function') fail('a fetch function is required');
  if (typeof session?.csrfToken !== 'function') fail('a session adapter is required');
  if (typeof randomUUID !== 'function') fail('a UUID source is required');
  if (typeof now !== 'function' || typeof setTimer !== 'function' || typeof clearTimer !== 'function') fail('a clock is required');
  const path = `${basePath.slice(0, -1)}/api/v1/credentials`;
  let credentials = [];
  let connections = [];
  let pendingActs = [];
  let timer = null;  // re-renders (no request) when the next fence becomes available
  let rotateFrom = null;  // the handle the next submit rotates, or null to create
  let pendingStore = null;  // {intent_id, provider, rotate_from} of an unconfirmed store act
  let pendingDelete = null;  // {intent_id, handle} of an unconfirmed delete act

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', '', { role: 'status', 'aria-live': 'polite' });
  const list = element('ul', undefined, { 'aria-label': '저장된 자격증명' });
  const connectionList = element('ul', undefined, { 'aria-label': '제공자 연결' });
  const actList = element('ul', undefined, { 'aria-label': '끝나지 않은 요청' });
  const refresh = element('button', '상태 다시 읽기', { type: 'button' });
  const provider = element('select', undefined, { id: 'credential-provider' });
  for (const name of CREDENTIAL_PROVIDERS) provider.append(element('option', name, { value: name }));
  provider.value = CREDENTIAL_PROVIDERS[0];
  const secret = element('input', undefined, { id: 'credential-secret', type: 'password', autocomplete: 'off',
    spellcheck: 'false', maxlength: '65536' });
  const mode = element('p', '');
  const submit = element('button', '키 저장', { type: 'button' });
  const reset = element('button', '새 요청으로 시작', { type: 'button' });
  const confirmBox = element('div');
  root.replaceChildren(element('h2', 'API 자격증명'), element('p', CREDENTIAL_MESSAGES.intro),
    element('p', CREDENTIAL_MESSAGES.revocation), status, list,
    element('h3', '제공자 연결'), element('p', CONNECTION_MESSAGES.voids),
    element('p', CONNECTION_MESSAGES.independent), connectionList,
    element('h3', '끝나지 않은 요청'), actList, refresh,
    element('label', '제공자', { for: 'credential-provider' }), provider,
    element('label', 'API 키', { for: 'credential-secret' }), secret, mode, submit, reset, confirmBox);

  function say(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  function refusal(error) {
    const code = Object.hasOwn(CREDENTIAL_ERRORS, error?.code) ? error.code : 'unavailable';
    say(CREDENTIAL_ERRORS[code], code);
    return code;
  }

  async function call(method, target, body) {
    const options = { method, credentials: 'same-origin', headers: {} };
    if (body !== undefined) {
      options.headers = { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrfToken() };
      options.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(target, options);
    } catch {
      throw Object.assign(new Error('refused'), { code: 'unavailable' });
    } finally {
      options.body = undefined;
    }
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    if (!response.ok) {
      const code = typeof payload?.code === 'string' ? payload.code
        : response.status === 503 ? 'dependency_unavailable' : 'unavailable';
      throw Object.assign(new Error('refused'), { code, status: response.status });
    }
    return payload;
  }

  function renderMode() {
    const retrying = pendingStore !== null;
    submit.textContent = retrying ? '결과 다시 확인' : rotateFrom === null ? '키 저장' : '키 교체';
    mode.textContent = retrying ? CREDENTIAL_MESSAGES.retryPending
      : rotateFrom === null ? '' : CREDENTIAL_MESSAGES.rotating(rotateFrom);
    provider.disabled = retrying || rotateFrom !== null;
  }

  function askDelete(handle) {
    const yes = element('button', '삭제 확인', { type: 'button' });
    const no = element('button', '취소', { type: 'button' });
    yes.addEventListener('click', () => remove(handle).catch(() => {}));
    no.addEventListener('click', () => confirmBox.replaceChildren());
    confirmBox.replaceChildren(element('p', CREDENTIAL_MESSAGES.confirmDelete(handle)), yes, no);
  }

  function renderCredentials() {
    if (!credentials.length) {
      list.replaceChildren(element('li', CREDENTIAL_MESSAGES.empty));
      return;
    }
    list.replaceChildren(...credentials.map(entry => {
      const item = element('li', undefined, { 'data-handle': entry.handle });
      const bound = connections.find(head => head.state === 'bound' && head.handle === entry.handle
        && head.provider === entry.provider);
      const parts = [entry.provider, entry.handle, CREDENTIAL_STATES[entry.state] ?? entry.state];
      if (bound !== undefined) parts.push(CONNECTION_MESSAGES.boundKey(bound.binding_revision));
      item.append(element('span', parts.join(' · ')));
      if (entry.state === 'stored_unbound') {
        const rotate = element('button', '교체', { type: 'button' });
        rotate.addEventListener('click', () => {
          rotateFrom = entry.handle;
          provider.value = entry.provider;
          renderMode();
        });
        const drop = element('button', '삭제', { type: 'button' });
        drop.addEventListener('click', () => askDelete(entry.handle));
        item.append(rotate, drop);
      }
      return item;
    }));
  }

  // the binding head is ledger authority and never changed from here; the only acts on a
  // bound head are the owner's explicit catalog refresh and a model choice from that catalog
  function renderConnections() {
    if (!connections.length) {
      connectionList.replaceChildren(element('li', CONNECTION_MESSAGES.empty));
      return;
    }
    connectionList.replaceChildren(...connections.map(head => {
      const item = element('li', undefined, { 'data-provider': head.provider, 'data-state': head.state,
        'data-binding-revision': String(head.binding_revision), 'data-gateway-head': head.gateway_head });
      item.append(element('span', [head.provider, CONNECTION_STATES[head.state], `키 ${head.handle}`,
        CONNECTION_MESSAGES.revision(head.binding_revision)].join(' · ')));
      if (head.state !== 'bound') return item;
      item.append(element('span', ` · ${CONNECTION_MESSAGES.catalog[head.catalog]}`, { 'data-catalog': head.catalog }),
        element('span', ` · ${CONNECTION_MESSAGES.model_choice[head.model_choice]}`, { 'data-model-choice': head.model_choice }));
      if (head.gateway_head === 'pending') item.append(element('span', ` · ${CONNECTION_MESSAGES.gatewayPending}`));
      if (head.chosen_model !== null) {
        item.append(element('span', ` · ${CONNECTION_MESSAGES.chosen(head.chosen_model)}`,
          { 'data-chosen-model': head.chosen_model }));
      }
      if (!LISTABLE_PROVIDERS.has(head.provider)) {
        item.append(element('span', ` · ${CONNECTION_MESSAGES.notListable}`));
        return item;
      }
      const refreshButton = element('button', '모델 목록 새로 고침', { type: 'button', 'data-act': 'catalog-refresh' });
      refreshButton.addEventListener('click', () => refreshCatalog(head.provider).catch(() => {}));
      item.append(refreshButton);
      if (head.catalog === 'current' && head.models.length) {
        const selectId = `credential-model-${head.provider}`;
        const select = element('select', undefined, { id: selectId, 'data-models-for': head.provider });
        for (const model of head.models) select.append(element('option', model, { value: model }));
        select.value = head.chosen_model ?? head.models[0];
        const chooseButton = element('button', '이 모델 선택', { type: 'button', 'data-act': 'model-choice' });
        chooseButton.addEventListener('click', () =>
          chooseModel(head.provider, head.binding_revision, select.value).catch(() => {}));
        item.append(element('label', ' 모델 ', { for: selectId }), select, chooseButton);
      }
      return item;
    }));
  }

  function renderActs() {
    if (timer !== null) { clearTimer(timer); timer = null; }
    if (!pendingActs.length) {
      actList.replaceChildren(element('li', PENDING_MESSAGES.empty));
      return;
    }
    const at = now();
    let soonest = Infinity;
    actList.replaceChildren(...pendingActs.map(act => {
      const item = element('li', undefined, { 'data-intent': act.intent_id, 'data-state': act.state });
      item.append(element('span', [ACT_KINDS[act.kind], act.provider, act.handle, `요청 ${act.intent_id}`].join(' · ')));
      if (act.state === 'fenced') {
        item.append(element('span', ` · ${PENDING_MESSAGES.fenced}: ${PENDING_MESSAGES.uncertain[act.uncertain_record] ?? ''}`,
          { 'data-uncertain-record': String(act.uncertain_record) }));
        return item;
      }
      item.append(element('span', ` · ${PENDING_MESSAGES.command_pending}`));
      if (act.fence_available_at === null) {
        item.append(element('span', ` · ${PENDING_MESSAGES.noFence}`));
        return item;
      }
      const due = stampMillis(act.fence_available_at);
      item.append(element('span', ` · ${PENDING_MESSAGES.fenceAt(stampText(act.fence_available_at))}`,
        { 'data-fence-available-at': act.fence_available_at }));
      if (at >= due) {
        item.append(element('span', ` · ${PENDING_MESSAGES.fenceNow}`));
        const button = element('button', '이 요청 차단', { type: 'button' });
        button.addEventListener('click', () => fence(act.intent_id).catch(() => {}));
        item.append(button);
      } else {
        soonest = Math.min(soonest, due);
      }
      return item;
    }));
    if (soonest !== Infinity) {
      // the button appears on its own once due: a re-render of what was read, no request
      timer = setTimer(() => { timer = null; renderActs(); },
        Math.min(MAX_TIMER_MS, Math.max(0, soonest - at) + 250));
    }
  }

  function render() {
    renderCredentials();
    renderConnections();
    renderActs();
  }

  function valid(value) {
    return value !== null && typeof value === 'object' && Array.isArray(value.credentials)
      && value.credentials.every(entry => entry && CREDENTIAL_HANDLE.test(entry.handle)
        && typeof entry.provider === 'string' && typeof entry.state === 'string')
      && (value.connections === undefined
        || (Array.isArray(value.connections) && value.connections.every(validConnection)))
      && (value.pending_acts === undefined
        || (Array.isArray(value.pending_acts) && value.pending_acts.every(validPending)));
  }

  function clear() {
    credentials = [];
    connections = [];
    pendingActs = [];
    if (timer !== null) { clearTimer(timer); timer = null; }
    list.replaceChildren();
    connectionList.replaceChildren();
    actList.replaceChildren();
  }

  async function load() {
    try {
      const value = await call('GET', path);
      if (!valid(value)) throw Object.assign(new Error('refused'), { code: 'unavailable' });
      credentials = value.credentials.map(({ handle, provider: name, state }) => ({ handle, provider: name, state }));
      connections = (value.connections ?? []).map(({ provider: name, state, handle, binding_revision, catalog,
        model_choice, gateway_head = 'applied', models = [], chosen_model = null }) =>
        ({ provider: name, state, handle, binding_revision, catalog, model_choice, gateway_head,
          models: [...models], chosen_model }));
      pendingActs = (value.pending_acts ?? []).map(({ intent_id, kind, handle, provider: name, state,
        fence_available_at, uncertain_record }) =>
        ({ intent_id, kind, handle, provider: name, state, fence_available_at, uncertain_record }));
      render();
      return credentials;
    } catch (error) {
      clear();
      refusal(error);
      throw error;
    }
  }

  // a store act that ended (fenced, lost) is never retried under its intent
  function settle(intentId) {
    if (pendingStore?.intent_id === intentId) {
      pendingStore = null;
      rotateFrom = null;
      renderMode();
    }
  }

  async function store() {
    const value = String(secret.value ?? '');
    secret.value = '';  // cleared before the request leaves; never kept by the page
    if (!value) {
      say(CREDENTIAL_MESSAGES.noSecret, 'invalid_input');
      return null;
    }
    const act = pendingStore ?? { intent_id: randomUUID(), provider: provider.value, rotate_from: rotateFrom };
    const body = { intent_id: act.intent_id, provider: act.provider, secret: value };
    if (act.rotate_from !== null) body.rotate_from = act.rotate_from;
    say(CREDENTIAL_MESSAGES.working, 'working');
    try {
      const answer = await call('POST', path, body);
      pendingStore = null;
      rotateFrom = null;
      say(act.rotate_from === null ? CREDENTIAL_MESSAGES.created : CREDENTIAL_MESSAGES.rotated, 'stored');
      return answer;
    } catch (error) {
      const code = refusal(error);
      // only an unconfirmed act is retried under its intent; anything else starts over
      pendingStore = code === 'command_pending' ? act : null;
      if (code !== 'command_pending') rotateFrom = null;
      throw error;
    } finally {
      body.secret = '';
      renderMode();
      await load().catch(() => {});
    }
  }

  async function remove(handle) {
    if (!CREDENTIAL_HANDLE.test(handle)) fail('handle');
    confirmBox.replaceChildren();
    const act = pendingDelete?.handle === handle ? pendingDelete : { intent_id: randomUUID(), handle };
    say(CREDENTIAL_MESSAGES.working, 'working');
    try {
      const answer = await call('DELETE', `${path}/${handle}`, { intent_id: act.intent_id });
      pendingDelete = null;
      if (rotateFrom === handle) rotateFrom = null;
      say(CREDENTIAL_MESSAGES.deleted, 'deleted');
      return answer;
    } catch (error) {
      pendingDelete = refusal(error) === 'command_pending' ? act : null;
      throw error;
    } finally {
      renderMode();
      await load().catch(() => {});
    }
  }

  // the owner's explicit fence of an unconfirmed store act: only the intent is sent
  async function fence(intentId) {
    if (!INTENT_ID.test(intentId)) fail('intent');
    say(CREDENTIAL_MESSAGES.working, 'working');
    try {
      const answer = await call('POST', `${path}/fences`, { intent_id: intentId });
      if (answer?.intent_id !== intentId || answer?.state !== 'fenced' || !UNCERTAIN.has(answer?.uncertain_record)) {
        throw Object.assign(new Error('refused'), { code: 'unavailable' });
      }
      const outcome = answer.uncertain_record === 'unknown' ? 'fenced'
        : answer.uncertain_record === 'secret_input_lost' ? 'secret_input_lost'
          : answer.uncertain_record === 'cleanup_pending' ? 'orphan_retired' : 'orphan_retiring';
      say(FENCE_RESULTS[outcome], outcome);
      settle(intentId);
      return { intent_id: intentId, outcome, uncertain_record: answer.uncertain_record };
    } catch (error) {
      if (error?.code === 'command_pending') {
        say(FENCE_RESULTS.still_pending, 'still_pending');
      } else if (error?.code === 'secret_input_lost') {
        say(FENCE_RESULTS.secret_input_lost, 'secret_input_lost');
        settle(intentId);
      } else {
        if (refusal(error) === 'fenced') settle(intentId);
      }
      throw error;
    } finally {
      await load().catch(() => {});
    }
  }

  // the owner's explicit catalog refresh for the connection's current binding: the gateway
  // reads the provider's model list with the key it holds; only a fresh intent is sent
  async function refreshCatalog(name) {
    if (!LISTABLE_PROVIDERS.has(name)) fail('provider');
    say(CREDENTIAL_MESSAGES.working, 'working');
    try {
      const answer = await call('POST', `${path}/connections/${name}/catalog-refresh`, { intent_id: randomUUID() });
      if (answer?.provider !== name || !Number.isInteger(answer?.binding_revision) || answer.binding_revision < 1
          || answer?.catalog !== 'current' || !validModels(answer?.models, 'current')) {
        throw Object.assign(new Error('refused'), { code: 'unavailable' });
      }
      say(CATALOG_RESULTS.refreshed(answer.binding_revision, answer.models.length), 'catalog_refreshed');
      return { binding_revision: answer.binding_revision, models: [...answer.models] };
    } catch (error) {
      refusal(error);
      throw error;
    } finally {
      await load().catch(() => {});
    }
  }

  // a model choice names the binding revision whose catalog listed it
  async function chooseModel(name, revision, model) {
    if (!CREDENTIAL_PROVIDERS.includes(name) || !Number.isInteger(revision) || !MODEL_ID.test(String(model))) {
      fail('model choice');
    }
    say(CREDENTIAL_MESSAGES.working, 'working');
    try {
      const answer = await call('POST', `${path}/connections/${name}/model-choice`,
        { binding_revision: revision, model });
      if (answer?.provider !== name || answer?.binding_revision !== revision || answer?.model !== model) {
        throw Object.assign(new Error('refused'), { code: 'unavailable' });
      }
      say(CATALOG_RESULTS.chosen(model), 'model_chosen');
      return { binding_revision: revision, model };
    } catch (error) {
      refusal(error);
      throw error;
    } finally {
      await load().catch(() => {});
    }
  }

  function startOver() {
    pendingStore = null;
    rotateFrom = null;
    secret.value = '';
    renderMode();
    say('', 'loaded');
  }

  submit.addEventListener('click', () => store().catch(() => {}));
  reset.addEventListener('click', startOver);
  refresh.addEventListener('click', () => load().catch(() => {}));
  renderMode();
  return Object.freeze({ load, store, remove, fence, refreshCatalog, chooseModel, startOver,
    get credentials() { return credentials.map(entry => ({ ...entry })); },
    get connections() { return connections.map(entry => ({ ...entry, models: [...entry.models] })); },
    get pendingActs() { return pendingActs.map(entry => ({ ...entry })); } });
}

// T087 -> T090: the owner's qualification of the gateway's provider-transport manifest
// (/api/v1/extensions/provider-transport-qualification). The gateway refuses every send
// (`transport_unqualified`) until it has adopted a qualification naming the digest of the
// manifest its transport was built from. The read shows that digest, what a qualification
// requires, whether the prerequisite (a matched 4/4 conformance run over a verified
// installation whose admission is still current) is met, the newest sealed qualification
// and what the gateway adopted. "전송 매니페스트 검증" names the run the read offered (or
// none, and the server then says which prerequisite is missing); the server runs the
// offline transport conformance against its own loopback mock provider, seals the record
// and publishes it to the gateway. No provider is contacted. An answer the page could not
// read is retried under the same command id, which only returns the same qualification.

export const TRANSPORT_QUALIFICATION_MESSAGES = Object.freeze({
  intro: '게이트웨이는 제공자 전송 매니페스트의 검증을 채택하기 전까지 저장된 키로 어떤 요청도 보내지 않습니다. 검증에는 검증된 제공자 설치에서 4개 벡터를 모두 통과한 적합성 검사와, 이 매니페스트를 로컬 모의 제공자에 대고 오프라인으로 돌리는 전송 적합성 검사가 필요합니다. 검증하는 동안 실제 제공자에게는 아무것도 보내지 않습니다.',
  // UI phase 6: the digest reads short; the full value is one fold away under "기술 정보"
  manifest: digest => `전송 매니페스트 SHA-256: ${String(digest).slice(0, 12)}…`,
  requirement: '요구 조건: 검증된 설치에서 4개 벡터를 모두 통과한(4/4) 적합성 검사, 그 설치의 헤드와 릴리스 소스가 검사 뒤 그대로일 것, 오프라인 전송 적합성 검사 4/4.',
  prerequisite: Object.freeze({
    met: run => `충족: 검증된 설치에서 4/4로 통과한 적합성 검사가 있습니다 (실행 ${run}).`,
    verified_installation_missing: '미충족: 검증된 제공자 설치가 없습니다.',
    conformance_run_missing: '미충족: 검증된 설치에 대한 적합성 검사 실행이 없습니다.',
    conformance_run_unmatched: '미충족: 검증된 설치에서 4/4로 통과한 적합성 검사가 없습니다.',
    conformance_admission_stale: '미충족: 적합성 검사 뒤 설치 헤드나 릴리스 소스가 바뀌었습니다.',
  }),
  sealed: (revision, run) => `봉인된 검증 기록: 수정본 ${revision} (적합성 검사 ${run})`,
  unsealed: '봉인된 검증 기록: 없음',
  gateway: Object.freeze({
    adopted: revision => `게이트웨이가 이 매니페스트의 검증을 채택했습니다 (수정본 ${revision}).`,
    adopted_other_manifest: revision => `게이트웨이가 채택한 검증(수정본 ${revision})은 다른 매니페스트의 것입니다.`,
    not_adopted: () => '게이트웨이가 채택한 검증이 없습니다.',
    unavailable: () => '게이트웨이 상태를 읽지 못했습니다(연결되어 있지 않거나 응답하지 않음).',
  }),
  state: Object.freeze({
    qualified: '검증됨: 게이트웨이가 이 매니페스트로 요청을 보낼 수 있습니다.',
    gateway_unavailable: '검증되지 않음: 자격증명 게이트웨이를 쓸 수 없습니다.',
    manifest_changed: '검증되지 않음: 게이트웨이가 채택한 검증이 지금 매니페스트와 다릅니다.',
    not_published: '검증되지 않음: 검증 기록은 봉인됐지만 게이트웨이가 아직 채택하지 않았습니다. 다시 검증하면 같은 기록을 다시 보냅니다.',
    not_qualified: '검증되지 않음: 이 매니페스트의 검증 기록이 없습니다.',
  }),
  working: '검증하는 중… (오프라인 전송 적합성 검사)',
  published: revision => `전송 매니페스트를 검증했고 게이트웨이가 채택했습니다 (수정본 ${revision}).`,
  unpublished: revision => `검증 기록(수정본 ${revision})은 봉인했지만 게이트웨이에 반영하지 못했습니다. 다시 누르면 같은 기록을 다시 보냅니다.`,
});

// the server's exact refusal texts (the route answers the same message for each code)
export const TRANSPORT_QUALIFICATION_ERRORS = Object.freeze({
  verified_installation_missing: '검증된 제공자 설치가 없어 전송 매니페스트를 검증하지 않았습니다. 먼저 제공자 설치를 검증하고, 그 설치로 제공자 적합성 검사를 실행해 주세요.',
  conformance_run_missing: '검증된 설치에 대한 제공자 적합성 검사(conformance) 실행이 없어 전송 매니페스트를 검증하지 않았습니다. 먼저 적합성 검사를 실행해 주세요.',
  conformance_run_unmatched: '검증된 설치에서 4개 벡터를 모두 통과한(4/4) 제공자 적합성 검사가 없어 전송 매니페스트를 검증하지 않았습니다.',
  conformance_admission_stale: '적합성 검사 뒤 설치 헤드나 릴리스 소스가 바뀌어 그 검사로는 검증하지 않았습니다. 현재 설치로 적합성 검사를 다시 실행해 주세요.',
  manifest_changed: '검토한 전송 매니페스트가 지금 배포된 매니페스트와 다릅니다. 상태를 다시 읽고 다시 검증해 주세요.',
  transport_conformance_failed: '전송 매니페스트가 오프라인 전송 적합성 검사(로컬 모의 제공자)를 통과하지 못해 검증하지 않았습니다.',
  command_conflict: '이 요청 ID는 이미 다른 내용으로 쓰였습니다. 새 요청으로 다시 시도해 주세요.',
  invalid_input: '전송 매니페스트 검증 요청 형식을 확인해 주세요.',
  unauthenticated: '세션이 끝났습니다. 시작 화면(./)에서 다시 로그인해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다.',
  unavailable: '전송 매니페스트 검증을 처리하지 못했습니다.',
});

const SHA256_HEX = /^[0-9a-f]{64}$/;
const QUALIFICATION_REASONS = new Set(['gateway_unavailable', 'manifest_changed', 'not_published', 'not_qualified']);

function validQualificationState(value) {
  return value !== null && typeof value === 'object'
    && value.schema_version === 'provider-transport-qualification-state-v1'
    && SHA256_HEX.test(value.manifest_sha256)
    && Object.hasOwn(TRANSPORT_QUALIFICATION_MESSAGES.prerequisite, value.prerequisite)
    && ((value.prerequisite === 'met') === (value.eligible_conformance !== null))
    && (value.eligible_conformance === null || INTENT_ID.test(value.eligible_conformance?.command_id))
    && (value.qualification === null || (Number.isInteger(value.qualification?.revision)
      && INTENT_ID.test(value.qualification?.conformance_command_id)))
    && Object.hasOwn(TRANSPORT_QUALIFICATION_MESSAGES.gateway, value.gateway?.state)
    && (value.gateway.revision === null || Number.isInteger(value.gateway.revision))
    && (value.reason === null ? value.state === 'qualified'
      : QUALIFICATION_REASONS.has(value.reason) && value.state === 'unqualified');
}

export function createTransportQualificationPanel({ root, document, fetch, basePath = '/', session,
  randomUUID = () => globalThis.crypto.randomUUID() } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof fetch !== 'function') fail('a fetch function is required');
  if (typeof session?.csrfToken !== 'function') fail('a session adapter is required');
  if (typeof randomUUID !== 'function') fail('a UUID source is required');
  const path = `${basePath.slice(0, -1)}/api/v1/extensions/provider-transport-qualification`;
  let current = null;
  let unanswered = null;  // the body of an act whose answer the page could not read

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  // not role=status: the credentials panel above keeps the section's one status line
  const line = element('p', '', { 'aria-live': 'polite', 'data-transport-line': '' });
  const facts = element('ul', undefined, { 'aria-label': '전송 매니페스트 검증 상태' });
  const qualify = element('button', '전송 매니페스트 검증', { type: 'button', 'data-act': 'transport-qualify' });
  const reread = element('button', '검증 상태 다시 읽기', { type: 'button' });
  root.replaceChildren(element('h3', '제공자 전송 매니페스트 검증'),
    element('p', TRANSPORT_QUALIFICATION_MESSAGES.intro), facts, line, qualify, reread);

  function say(text, state) {
    line.textContent = text;
    line.dataset.state = state;
  }

  function refusal(error) {
    const code = Object.hasOwn(TRANSPORT_QUALIFICATION_ERRORS, error?.code) ? error.code : 'unavailable';
    say(TRANSPORT_QUALIFICATION_ERRORS[code], code);
    return code;
  }

  async function call(method, body) {
    const options = { method, credentials: 'same-origin', headers: {} };
    if (body !== undefined) {
      options.headers = { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrfToken() };
      options.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, options);
    } catch {
      throw Object.assign(new Error('refused'), { code: 'unavailable', unanswered: true });
    }
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    if (!response.ok) {
      throw Object.assign(new Error('refused'), {
        code: typeof payload?.code === 'string' ? payload.code : 'unavailable',
        unanswered: response.status >= 500 });
    }
    return payload;
  }

  function render() {
    const value = current;
    facts.dataset.state = value.state;
    facts.dataset.reason = value.reason ?? '';
    facts.dataset.prerequisite = value.prerequisite;
    facts.dataset.gateway = value.gateway.state;
    const prerequisite = TRANSPORT_QUALIFICATION_MESSAGES.prerequisite[value.prerequisite];
    const manifest = element('li', TRANSPORT_QUALIFICATION_MESSAGES.manifest(value.manifest_sha256),
      { 'data-manifest-sha256': value.manifest_sha256 });
    manifest.append(technicalDetails(document, [['전송 매니페스트 SHA-256', value.manifest_sha256]]));
    facts.replaceChildren(
      manifest,
      element('li', TRANSPORT_QUALIFICATION_MESSAGES.requirement),
      element('li', typeof prerequisite === 'function' ? prerequisite(value.eligible_conformance.command_id)
        : prerequisite, { 'data-prerequisite': value.prerequisite }),
      element('li', value.qualification === null ? TRANSPORT_QUALIFICATION_MESSAGES.unsealed
        : TRANSPORT_QUALIFICATION_MESSAGES.sealed(value.qualification.revision, value.qualification.conformance_command_id),
      { 'data-sealed-revision': value.qualification === null ? '' : String(value.qualification.revision) }),
      element('li', TRANSPORT_QUALIFICATION_MESSAGES.gateway[value.gateway.state](value.gateway.revision),
        { 'data-gateway-revision': value.gateway.revision === null ? '' : String(value.gateway.revision) }),
      element('li', TRANSPORT_QUALIFICATION_MESSAGES.state[value.reason ?? 'qualified'],
        { 'data-qualification-state': value.state }));
  }

  async function load() {
    try {
      const value = await call('GET');
      if (!validQualificationState(value)) throw Object.assign(new Error('refused'), { code: 'unavailable' });
      current = value;
      render();
      return { state: value.state, reason: value.reason, prerequisite: value.prerequisite,
        gateway: { ...value.gateway } };
    } catch (error) {
      current = null;
      facts.replaceChildren();
      refusal(error);
      throw error;
    }
  }

  // the owner's qualification act: the run the read offered, or none (the server then
  // names the missing prerequisite); an unread answer is retried under the same command
  async function run() {
    const body = unanswered ?? { command_id: randomUUID(),
      manifest_sha256: current?.manifest_sha256 ?? '0'.repeat(64),
      conformance_command_id: current?.eligible_conformance?.command_id ?? null };
    say(TRANSPORT_QUALIFICATION_MESSAGES.working, 'working');
    try {
      const answer = await call('POST', body);
      unanswered = null;
      const revision = answer?.qualification?.revision;
      if (answer?.command_id !== body.command_id || !Number.isInteger(revision)
          || typeof answer?.published !== 'boolean') {
        throw Object.assign(new Error('refused'), { code: 'unavailable' });
      }
      say(answer.published ? TRANSPORT_QUALIFICATION_MESSAGES.published(revision)
        : TRANSPORT_QUALIFICATION_MESSAGES.unpublished(revision), answer.published ? 'published' : 'unpublished');
      return { revision, published: answer.published };
    } catch (error) {
      unanswered = error?.unanswered === true ? body : null;
      refusal(error);
      throw error;
    } finally {
      // re-read the state; the act's own outcome stays on the line
      const said = [line.textContent, line.dataset.state];
      await load().catch(() => {});
      [line.textContent, line.dataset.state] = said;
    }
  }

  qualify.addEventListener('click', () => run().catch(() => {}));
  reread.addEventListener('click', () => load().catch(() => {}));
  return Object.freeze({ load, qualify: run,
    get state() { return current === null ? null : JSON.parse(JSON.stringify(current)); } });
}
