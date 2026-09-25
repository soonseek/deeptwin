// T025 tail: the owner changes their password and ends their other sessions from the
// browser (api.md §1). A password change re-verifies the current password, ends every
// session that used the old one, and rotates this browser's session; the page takes
// the new CSRF value from the answer. Passwords live only in the form fields: they
// are never stored, logged or echoed, and the fields are cleared after every attempt.

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
  voids: '키를 교체하거나 삭제하면 그 전 바인딩의 모델 목록과 모델 선택은 무효가 됩니다. 새 바인딩의 목록은 명시적으로 새로 고친 뒤에만 생기며, 이 화면은 목록을 새로 고치거나 모델을 부르지 않습니다.',
});

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

function validConnection(entry) {
  return entry !== null && typeof entry === 'object' && CREDENTIAL_PROVIDERS.includes(entry.provider)
    && Object.hasOwn(CONNECTION_STATES, entry.state) && CREDENTIAL_HANDLE.test(entry.handle)
    && Number.isInteger(entry.binding_revision) && entry.binding_revision >= 1
    && PRESENCE.has(entry.catalog) && PRESENCE.has(entry.model_choice);
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
    element('h3', '제공자 연결'), element('p', CONNECTION_MESSAGES.voids), connectionList,
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

  // read-only: the binding head is ledger authority, never changed from here directly
  function renderConnections() {
    if (!connections.length) {
      connectionList.replaceChildren(element('li', CONNECTION_MESSAGES.empty));
      return;
    }
    connectionList.replaceChildren(...connections.map(head => {
      const item = element('li', undefined, { 'data-provider': head.provider, 'data-state': head.state,
        'data-binding-revision': String(head.binding_revision) });
      item.append(element('span', [head.provider, CONNECTION_STATES[head.state], `키 ${head.handle}`,
        CONNECTION_MESSAGES.revision(head.binding_revision)].join(' · ')));
      if (head.state === 'bound') {
        item.append(element('span', ` · ${CONNECTION_MESSAGES.catalog[head.catalog]}`, { 'data-catalog': head.catalog }),
          element('span', ` · ${CONNECTION_MESSAGES.model_choice[head.model_choice]}`, { 'data-model-choice': head.model_choice }));
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
      connections = (value.connections ?? []).map(({ provider: name, state, handle, binding_revision, catalog, model_choice }) =>
        ({ provider: name, state, handle, binding_revision, catalog, model_choice }));
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
  return Object.freeze({ load, store, remove, fence, startOver,
    get credentials() { return credentials.map(entry => ({ ...entry })); },
    get connections() { return connections.map(entry => ({ ...entry })); },
    get pendingActs() { return pendingActs.map(entry => ({ ...entry })); } });
}
