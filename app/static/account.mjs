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
