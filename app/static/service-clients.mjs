// 설정 > 서비스 클라이언트 (T025 bearer slice, evidence/bearer-service-clients-2026-09-26.md;
// docs/ui/2026-09-26-product-ux-redesign.md §5.8, UI phase 6). The owner lists, creates,
// rotates and revokes the durable scoped clients behind `service-clients-v1`
// (`GET|POST /api/v1/service-clients`, `…/{id}`, `…/{id}/rotate`, `…/{id}/revoke`) from the
// authenticated browser session; every write goes through the session adapter with CSRF.
//
// - The only scopes offered are the ones the server grants a bearer (`GRANTABLE_SCOPES`,
//   mirrored against the composed route descriptors by test_service_client_bearer.py); the
//   expiry choices stay under the server's 24-hour limit.
// - The one-time secret of a create or a rotation is shown exactly once, in a read-only field
//   with a copy button and a warning. It lives only in that field and this closure until the
//   owner hides it; it is never written to localStorage, sessionStorage, an attribute, a
//   title, the address or a log.
// - Rotation and revocation each ask for a confirmation first.
// - A refusal is shown as the server gave it: on an instance that is not on the portable
//   HTTPS profile the server refuses creation, and the page says so with the server's status,
//   code and message folded under "기술 정보". Nothing is guessed from the page alone.
// All text reaches the DOM through textContent (ui-parts.mjs); nothing here writes markup.

import { button, el, statusChip, technicalDetails } from './ui-parts.mjs';
import { absoluteTime } from './ui-format.mjs';

export const SERVICE_CLIENTS_MOUNT_ID = 'service-clients';
export const SERVICE_CLIENTS_PATH = '/api/v1/service-clients';
// the portable HTTPS profile is the only one on which a bearer is ever admitted (ADR-010)
export const NETWORK_PROFILE = 'portable_https';
// the scopes a composed route declares for a bearer (app/api/router_composition.py); no
// command, artifact or extension scope is grantable yet (an open owner decision)
export const GRANTABLE_SCOPES = Object.freeze({
  'snapshot.read': '현재 상태 스냅샷 읽기',
  'events.read': '사건 기록 읽기',
});
// the server refuses an expiry more than 24 hours ahead of its own clock; the longest choice
// leaves an hour for a device clock that runs ahead of the server's
export const MAX_SERVER_TTL_SECONDS = 86_400;
export const EXPIRY_CHOICES = Object.freeze([
  Object.freeze({ hours: 1, label: '1시간' }),
  Object.freeze({ hours: 8, label: '8시간' }),
  Object.freeze({ hours: 23, label: '23시간 (가장 긺)' }),
]);
const NAME_MAX_BYTES = 128;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export const MESSAGES = Object.freeze({
  title: '서비스 클라이언트',
  intro: '서비스 클라이언트는 다른 프로그램이 비밀 값(Bearer)으로 이 인스턴스의 읽기 경로를 쓰게 합니다. 지금 허용되는 것은 현재 상태 스냅샷과 사건 기록 읽기뿐이며, 명령이나 승인은 할 수 없습니다.',
  limits: 'HTTPS(portable) 배포에서만 만들 수 있고, 만료는 24시간을 넘지 않습니다. 비밀 값은 만들 때 한 번만 보이며 서버에는 그 지문만 남습니다.',
  loading: '서비스 클라이언트 목록을 읽는 중…',
  listed: count => (count === 0 ? '아직 만든 서비스 클라이언트가 없습니다.' : `서비스 클라이언트 ${count}개`),
  listFailed: '서비스 클라이언트 목록을 읽지 못했습니다.',
  more: '목록이 길어 앞의 100개만 보입니다.',
  createTitle: '새 클라이언트 만들기',
  name: '이름',
  nameHint: '이 클라이언트를 알아볼 이름입니다. 비밀 값을 넣지 마세요.',
  scopes: '허용할 읽기',
  expiry: '만료',
  expiryHint: '서버는 24시간을 넘는 만료를 받지 않습니다. 기기 시계와 서버 시계가 조금 다를 수 있어 가장 긴 선택은 23시간입니다.',
  create: '클라이언트 만들기',
  creating: '만드는 중…',
  created: name => `“${name}” 클라이언트를 만들었습니다. 아래 비밀 값은 지금 한 번만 보입니다.`,
  nameMissing: '이름을 적어 주세요.',
  nameInvalid: `이름은 ${NAME_MAX_BYTES}바이트 이하의 글자여야 하고 줄바꿈이나 제어 문자를 넣을 수 없습니다.`,
  scopeMissing: '허용할 읽기를 하나 이상 골라 주세요.',
  // the server refused creation: certain for a page served over plain http (the portable HTTPS
  // profile never serves one), otherwise the server's own answer is all the page knows
  refusedHere: '이 배포에서는 서비스 클라이언트를 만들 수 없습니다.',
  refusedHereWhy: '서비스 클라이언트는 HTTPS(portable) 배포에서만 만들 수 있고, 서버가 만들기를 거절했습니다. 이 화면은 HTTPS가 아닌 주소로 열렸습니다.',
  refused: '서버가 이 클라이언트를 만들지 않았습니다.',
  refusedWhy: '서버는 HTTPS(portable) 배포에서, 허용된 읽기만, 24시간 이내 만료로 만들 때에만 클라이언트를 만듭니다. 이 배포가 그 조건에 맞지 않거나 요청이 거절되었습니다.',
  failed: '요청을 처리하지 못했습니다.',
  secretTitle: name => `새 비밀 값 — ${name}`,
  secretWarning: '이 비밀 값은 지금 한 번만 보입니다. 서버에는 지문만 남아 다시 볼 수 없습니다. 쓸 곳에 옮겨 둔 뒤 숨기세요. 이 화면을 떠나거나 새로 고치면 사라집니다.',
  secretLabel: '비밀 값',
  copy: '복사',
  copied: '비밀 값을 복사했습니다.',
  copyFailed: '복사하지 못했습니다. 비밀 값 칸이 선택되어 있으니 직접 복사해 주세요.',
  hide: '다 옮겼습니다 · 숨기기',
  hidden: '비밀 값을 화면에서 지웠습니다. 다시 볼 수 없습니다.',
  rotate: '비밀 값 다시 만들기',
  rotateAsk: name => `“${name}”의 지금 비밀 값은 바로 쓸 수 없게 됩니다. 새 비밀 값으로 바꿀까요?`,
  rotateYes: '새 비밀 값으로 바꾸기',
  rotated: name => `“${name}”의 비밀 값을 바꿨습니다. 이전 비밀 값은 더 이상 쓰이지 않습니다.`,
  revoke: '폐기',
  revokeAsk: name => `“${name}”을(를) 폐기하면 이 클라이언트는 더 이상 읽을 수 없고 되돌릴 수 없습니다. 폐기할까요?`,
  revokeYes: '폐기하기',
  revoked: name => `“${name}” 클라이언트를 폐기했습니다.`,
  cancel: '취소',
  conflict: '다른 곳에서 먼저 바뀌었습니다. 목록을 다시 읽었습니다.',
  reload: '목록 다시 읽기',
});

const STATE_TEXT = Object.freeze({
  active: ['사용 중', 'ok'], expired: ['만료됨', 'warn'], revoked: ['폐기됨', 'neutral'],
});

function fail(message) {
  throw new TypeError(message);
}

function utf8Length(value) {
  return new TextEncoder().encode(value).length;
}

// the name the server accepts: 1–128 UTF-8 bytes, no control characters or lone surrogates
export function validName(value) {
  if (typeof value !== 'string') return null;
  const name = value.trim();
  if (!name || utf8Length(name) > NAME_MAX_BYTES) return null;
  if ([...name].some(character => {
    const code = character.codePointAt(0);
    return code < 32 || code === 127 || (code >= 0xD800 && code <= 0xDFFF);
  })) return null;
  return name;
}

// the exact create body (`service-clients-v1`); expiry in whole seconds on the server's epoch
export function creationBody({ clientId, name, scopes, hours, nowMs }) {
  if (typeof clientId !== 'string' || !UUID.test(clientId)) fail('a client id must be a UUID');
  const valid = validName(name);
  if (valid === null) fail('the name is not one the server accepts');
  if (!Array.isArray(scopes) || scopes.length === 0 || scopes.some(scope => !Object.hasOwn(GRANTABLE_SCOPES, scope))
      || new Set(scopes).size !== scopes.length) fail('scopes must be grantable');
  const choice = EXPIRY_CHOICES.find(item => item.hours === hours);
  if (!choice) fail('unknown expiry choice');
  if (!Number.isFinite(nowMs)) fail('a clock is required');
  const seconds = choice.hours * 3600;
  if (seconds >= MAX_SERVER_TTL_SECONDS) fail('the expiry exceeds the server limit');
  return { client_id: clientId, name: valid, scopes: [...scopes].sort(),
    allowed_network_profile: NETWORK_PROFILE, expires_at: Math.floor(nowMs / 1000) + seconds };
}

// active, expired (the server keeps the state `active` past the expiry) or revoked
export function clientState(client, nowMs) {
  if (client?.state === 'revoked') return 'revoked';
  if (client?.state === 'active' && Number.isSafeInteger(client.expires_at) && client.expires_at * 1000 <= nowMs) return 'expired';
  return client?.state === 'active' ? 'active' : 'revoked';
}

// "3시간 뒤" / "12분 뒤" for an expiry ahead, "지남" for one behind
export function untilText(seconds, nowMs) {
  if (!Number.isSafeInteger(seconds)) return '';
  const left = Math.floor((seconds * 1000 - nowMs) / 1000);
  if (left <= 0) return '지남';
  const minutes = Math.max(1, Math.floor(left / 60));
  if (minutes < 60) return `${minutes}분 뒤`;
  return `${Math.floor(minutes / 60)}시간 ${minutes % 60 ? `${minutes % 60}분 ` : ''}뒤`;
}

function localTime(seconds) {
  return Number.isSafeInteger(seconds) ? absoluteTime(new Date(seconds * 1000)) : '';
}

function validClient(value) {
  return value !== null && typeof value === 'object' && typeof value.client_id === 'string' && UUID.test(value.client_id)
    && typeof value.name === 'string' && Array.isArray(value.scopes) && value.scopes.every(scope => typeof scope === 'string')
    && Number.isSafeInteger(value.revision) && value.revision >= 1 && ['active', 'revoked'].includes(value.state)
    && Number.isSafeInteger(value.created_at) && Number.isSafeInteger(value.expires_at);
}

// `heading: false` when the page already titles the panel (settings.html does, so the panel is
// named even before a session exists)
export function createServiceClientsPanel({ root, document, request, basePath = '/', crypto = globalThis.crypto,
  now = () => Date.now(), clipboard = globalThis.navigator?.clipboard ?? null, pageProtocol = globalThis.location?.protocol ?? '',
  heading = true } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  if (typeof crypto?.randomUUID !== 'function') fail('a crypto with randomUUID is required');
  const path = `${basePath.slice(0, -1)}${SERVICE_CLIENTS_PATH}`;
  const idPrefix = 'service-client';

  // three lines, each said once: the list read (live only while reading or failing), the
  // count (not live: it changes with every act), and an act's outcome (live); a refusal is an
  // alert block with the server's answer folded under it
  const status = el(document, 'p', { className: 'service-clients-status', attrs: { role: 'status', 'aria-live': 'polite' } });
  const count = el(document, 'p', { className: 'service-clients-count' });
  const notice = el(document, 'p', { className: 'service-clients-notice', attrs: { role: 'status', 'aria-live': 'polite' } });
  const list = el(document, 'ul', { className: 'service-client-list', attrs: { 'aria-label': '서비스 클라이언트 목록' } });
  const reveal = el(document, 'div', { className: 'service-client-secret-mount' });
  const outcome = el(document, 'div', { className: 'service-clients-outcome' });
  const reload = button(document, { label: MESSAGES.reload, variant: 'quiet' });

  // the create form: a name, the grantable reads, an expiry
  const form = el(document, 'form', { className: 'service-client-form', attrs: { 'aria-labelledby': `${idPrefix}-create-title`, novalidate: true } });
  const nameInput = el(document, 'input', { attrs: { id: `${idPrefix}-name`, type: 'text', autocomplete: 'off',
    spellcheck: 'false', maxlength: '64', 'aria-describedby': `${idPrefix}-name-hint` } });
  const scopeBoxes = Object.entries(GRANTABLE_SCOPES).map(([scope, label]) => {
    const box = el(document, 'input', { attrs: { type: 'checkbox', id: `${idPrefix}-scope-${scope.replace('.', '-')}`, value: scope } });
    return { scope, box, row: el(document, 'label', { attrs: { for: box.getAttribute('id') } }, [box, el(document, 'span', { text: label })]) };
  });
  const expiry = el(document, 'select', { attrs: { id: `${idPrefix}-expiry`, 'aria-describedby': `${idPrefix}-expiry-hint` } });
  for (const choice of EXPIRY_CHOICES) {
    const option = el(document, 'option', { text: choice.label });
    option.value = String(choice.hours);
    expiry.append(option);
  }
  expiry.value = '8';
  const formError = el(document, 'p', { className: 'service-client-form-error', attrs: { id: `${idPrefix}-form-error` } });
  const submit = button(document, { label: MESSAGES.create, variant: 'primary', type: 'submit' });
  form.append(
    el(document, 'h3', { text: MESSAGES.createTitle, attrs: { id: `${idPrefix}-create-title` } }),
    el(document, 'div', { className: 'service-client-field' }, [
      el(document, 'label', { text: MESSAGES.name, attrs: { for: `${idPrefix}-name` } }), nameInput,
      el(document, 'p', { className: 'field-note', text: MESSAGES.nameHint, attrs: { id: `${idPrefix}-name-hint` } })]),
    el(document, 'fieldset', { className: 'service-client-scopes' }, [
      el(document, 'legend', { text: MESSAGES.scopes }), ...scopeBoxes.map(item => item.row)]),
    el(document, 'div', { className: 'service-client-field' }, [
      el(document, 'label', { text: MESSAGES.expiry, attrs: { for: `${idPrefix}-expiry` } }), expiry,
      el(document, 'p', { className: 'field-note', text: MESSAGES.expiryHint, attrs: { id: `${idPrefix}-expiry-hint` } })]),
    formError, submit);

  root.replaceChildren(...[
    heading ? el(document, 'h2', { text: MESSAGES.title }) : null,
    el(document, 'p', { className: 'settings-panel-intro', text: MESSAGES.intro }),
    el(document, 'p', { className: 'field-note', text: MESSAGES.limits }),
    status, notice, outcome, reveal, el(document, 'div', { className: 'service-clients-bar' }, [count, reload]), list, form,
  ].filter(Boolean));

  let clients = [];
  let secret = null;   // the one-time secret on screen, held only until the owner hides it
  let busy = false;

  function say(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  function tell(text, state) {
    notice.textContent = text;
    notice.dataset.state = state;
  }

  // a refusal in words, with the server's own answer one fold away
  function refusalBlock(error, { headline, why, alert = true }) {
    const facts = [['응답', String(error?.status ?? '없음')], ['서버 코드', error?.serverCode ?? error?.code ?? '없음'],
      ['서버 메시지', typeof error?.message === 'string' && error.message ? error.message : '없음']];
    if (error?.correlationId) facts.push(['상관 ID', error.correlationId]);
    if (pageProtocol) facts.push(['이 화면의 주소 방식', pageProtocol.replace(/:$/, '')]);
    return el(document, 'div', { className: 'service-clients-refusal', attrs: alert ? { role: 'alert' } : {} }, [
      el(document, 'p', { className: 'refusal-headline', text: headline }),
      why ? el(document, 'p', { text: why }) : null,
      technicalDetails(document, facts),
    ]);
  }

  function hideSecret({ announce = true } = {}) {
    const field = reveal.querySelector?.('input');
    if (field) field.value = '';
    secret = null;
    reveal.replaceChildren();
    if (announce) tell(MESSAGES.hidden, 'hidden');
  }

  function showSecret(value, client, returnTo) {
    hideSecret({ announce: false });
    secret = value;
    const field = el(document, 'input', { attrs: { id: `${idPrefix}-secret`, type: 'text', readonly: true,
      autocomplete: 'off', spellcheck: 'false', 'aria-describedby': `${idPrefix}-secret-warning` } });
    field.value = secret;
    const copyStatus = el(document, 'p', { className: 'secret-copy-status', attrs: { role: 'status', 'aria-live': 'polite' } });
    const copy = button(document, { label: MESSAGES.copy, variant: 'primary' });
    copy.addEventListener('click', async () => {
      try {
        if (typeof clipboard?.writeText !== 'function' || secret === null) throw new Error('no clipboard');
        await clipboard.writeText(secret);
        copyStatus.textContent = MESSAGES.copied;
        copyStatus.dataset.state = 'copied';
      } catch {
        field.focus?.();
        field.select?.();
        copyStatus.textContent = MESSAGES.copyFailed;
        copyStatus.dataset.state = 'copy_failed';
      }
    });
    const done = button(document, { label: MESSAGES.hide });
    done.addEventListener('click', () => {
      hideSecret();
      const target = returnTo?.();
      (target ?? nameInput).focus?.();
    });
    const title = el(document, 'h3', { text: MESSAGES.secretTitle(client.name),
      attrs: { tabindex: '-1', id: `${idPrefix}-secret-title` } });
    reveal.replaceChildren(el(document, 'section', { className: 'service-client-secret', attrs: { 'aria-labelledby': `${idPrefix}-secret-title` } }, [
      title,
      el(document, 'p', { className: 'secret-warning', text: MESSAGES.secretWarning, attrs: { id: `${idPrefix}-secret-warning` } }),
      el(document, 'label', { text: MESSAGES.secretLabel, attrs: { for: `${idPrefix}-secret` } }),
      el(document, 'div', { className: 'secret-row' }, [field, copy]),
      copyStatus, done,
    ]));
    title.focus?.();
  }

  // in the form's order, whatever order the server stored them in; an unknown scope stays raw
  function scopeText(scopes) {
    const order = Object.keys(GRANTABLE_SCOPES);
    const rank = scope => (order.includes(scope) ? order.indexOf(scope) : order.length);
    return [...scopes].sort((a, b) => rank(a) - rank(b)).map(scope => GRANTABLE_SCOPES[scope] ?? scope).join(' · ');
  }

  // one confirmation row under a client: the act's own button, and 취소 back to where it began
  function confirmRow(item, { question, yes, danger, act, back }) {
    for (const old of list.querySelectorAll?.('.service-client-confirm') ?? []) old.remove?.();
    const confirm = button(document, { label: yes, variant: danger ? 'danger' : 'primary' });
    const cancel = button(document, { label: MESSAGES.cancel });
    const row = el(document, 'div', { className: 'service-client-confirm', attrs: { role: 'group', 'aria-label': yes } }, [
      el(document, 'p', { text: question }), confirm, cancel]);
    cancel.addEventListener('click', () => { row.remove?.(); back.focus?.(); });
    confirm.addEventListener('click', () => { act().catch(() => {}); });
    item.append(row);
    confirm.focus?.();
  }

  function render() {
    const nowMs = now();
    count.textContent = MESSAGES.listed(clients.length);
    list.replaceChildren(...clients.map(client => {
      const state = clientState(client, nowMs);
      const [label, tone] = STATE_TEXT[state];
      const item = el(document, 'li', { className: 'service-client', attrs: { 'data-client': client.client_id, 'data-state': state } });
      const head = el(document, 'div', { className: 'service-client-head' }, [
        el(document, 'h3', { className: 'service-client-name', text: client.name }), statusChip(document, { tone, label })]);
      const facts = el(document, 'dl', { className: 'kv-list service-client-facts' }, [
        el(document, 'dt', { text: '허용' }), el(document, 'dd', { text: scopeText(client.scopes) }),
        el(document, 'dt', { text: '만료' }), el(document, 'dd', { text: `${localTime(client.expires_at)} (${untilText(client.expires_at, nowMs)})` }),
        el(document, 'dt', { text: '만듦' }), el(document, 'dd', { text: localTime(client.created_at) }),
      ]);
      const actions = el(document, 'div', { className: 'service-client-actions' });
      if (state === 'active') {
        const rotate = button(document, { label: MESSAGES.rotate });
        rotate.addEventListener('click', () => confirmRow(item, { question: MESSAGES.rotateAsk(client.name), yes: MESSAGES.rotateYes,
          act: () => rotateClient(client), back: rotate }));
        actions.append(rotate);
      }
      if (state !== 'revoked') {
        const revoke = button(document, { label: MESSAGES.revoke, variant: 'danger' });
        revoke.addEventListener('click', () => confirmRow(item, { question: MESSAGES.revokeAsk(client.name), yes: MESSAGES.revokeYes,
          danger: true, act: () => revokeClient(client), back: revoke }));
        actions.append(revoke);
      }
      item.append(head, facts, actions, technicalDetails(document, [['클라이언트 ID', client.client_id],
        ['수정본', String(client.revision)], ['허용 범위', client.scopes.join(' ')],
        ['네트워크 프로필', String(client.allowed_network_profile ?? '')], ['만료 (epoch 초)', String(client.expires_at)]]));
      return item;
    }));
  }

  async function load() {
    say(MESSAGES.loading, 'loading');
    try {
      const page = await request(path, { query: { limit: '100' } });
      const items = Array.isArray(page?.items) ? page.items.filter(validClient) : [];
      clients = items;
      render();
      say('', 'listed');
      outcome.replaceChildren(...(page?.next_cursor ? [el(document, 'p', { className: 'field-note', text: MESSAGES.more })] : []));
      return clients.map(client => ({ ...client }));
    } catch (error) {
      clients = [];
      list.replaceChildren();
      count.textContent = '';
      say(MESSAGES.listFailed, error?.code ?? 'unavailable');
      outcome.replaceChildren(refusalBlock(error, { headline: MESSAGES.listFailed, alert: false }));
      throw error;
    }
  }

  async function create() {
    if (busy) return null;
    formError.textContent = '';
    nameInput.removeAttribute('aria-invalid');
    const name = validName(nameInput.value);
    if (!String(nameInput.value ?? '').trim()) {
      formError.textContent = MESSAGES.nameMissing;
      nameInput.setAttribute('aria-invalid', 'true');
      nameInput.setAttribute('aria-describedby', `${idPrefix}-name-hint ${idPrefix}-form-error`);
      nameInput.focus?.();
      return null;
    }
    if (name === null) {
      formError.textContent = MESSAGES.nameInvalid;
      nameInput.setAttribute('aria-invalid', 'true');
      nameInput.setAttribute('aria-describedby', `${idPrefix}-name-hint ${idPrefix}-form-error`);
      nameInput.focus?.();
      return null;
    }
    const scopes = scopeBoxes.filter(item => item.box.checked === true).map(item => item.scope);
    if (scopes.length === 0) {
      formError.textContent = MESSAGES.scopeMissing;
      scopeBoxes[0].box.focus?.();
      return null;
    }
    const body = creationBody({ clientId: crypto.randomUUID(), name, scopes, hours: Number(expiry.value), nowMs: now() });
    busy = true;
    submit.disabled = true;
    outcome.replaceChildren();
    tell(MESSAGES.creating, 'creating');
    try {
      const answer = await request(path, { method: 'POST', body });
      if (!validClient(answer?.client) || typeof answer?.secret !== 'string' || answer.secret_available_once !== true) {
        throw Object.assign(new Error('the answer is malformed'), { code: 'unavailable' });
      }
      nameInput.value = '';
      for (const item of scopeBoxes) item.box.checked = false;
      clients = [...clients.filter(client => client.client_id !== answer.client.client_id), answer.client];
      render();
      tell(MESSAGES.created(answer.client.name), 'created');
      showSecret(answer.secret, answer.client, () => list.querySelector?.(`[data-client="${answer.client.client_id}"] button`));
      return { client: { ...answer.client }, shown: true };
    } catch (error) {
      const certain = error?.status === 422 && pageProtocol === 'http:';
      const refused = error?.status === 422;
      // the alert below says it; the act line is cleared rather than saying it twice
      tell('', refused ? 'refused' : (error?.code ?? 'unavailable'));
      outcome.replaceChildren(refusalBlock(error, refused
        ? (certain ? { headline: MESSAGES.refusedHere, why: MESSAGES.refusedHereWhy } : { headline: MESSAGES.refused, why: MESSAGES.refusedWhy })
        : { headline: MESSAGES.failed }));
      throw error;
    } finally {
      busy = false;
      submit.disabled = false;
    }
  }

  async function changed(error) {
    if (error?.status === 409) {
      await load().catch(() => {});
      tell(MESSAGES.conflict, 'conflict');
      return;
    }
    tell('', error?.code ?? 'unavailable');
    outcome.replaceChildren(refusalBlock(error, { headline: MESSAGES.failed }));
  }

  async function rotateClient(client) {
    outcome.replaceChildren();
    try {
      const answer = await request(`${path}/${client.client_id}/rotate`, { method: 'POST', body: { expected_revision: client.revision } });
      if (!validClient(answer?.client) || typeof answer?.secret !== 'string') {
        throw Object.assign(new Error('the answer is malformed'), { code: 'unavailable' });
      }
      clients = clients.map(item => (item.client_id === client.client_id ? answer.client : item));
      render();
      tell(MESSAGES.rotated(answer.client.name), 'rotated');
      showSecret(answer.secret, answer.client, () => list.querySelector?.(`[data-client="${answer.client.client_id}"] button`));
      return { client: { ...answer.client }, shown: true };
    } catch (error) {
      await changed(error);
      throw error;
    }
  }

  async function revokeClient(client) {
    outcome.replaceChildren();
    try {
      const answer = await request(`${path}/${client.client_id}/revoke`, { method: 'POST', body: { expected_revision: client.revision } });
      if (!validClient(answer)) throw Object.assign(new Error('the answer is malformed'), { code: 'unavailable' });
      clients = clients.map(item => (item.client_id === client.client_id ? answer : item));
      render();
      tell(MESSAGES.revoked(answer.name), 'revoked');
      // the keyboard lands on the client it just revoked
      const row = list.querySelector?.(`[data-client="${answer.client_id}"] h3`);
      row?.setAttribute('tabindex', '-1');
      row?.focus?.();
      return { ...answer };
    } catch (error) {
      await changed(error);
      throw error;
    }
  }

  form.addEventListener('submit', event => {
    event.preventDefault?.();
    create().catch(() => {});
  });
  reload.addEventListener('click', () => { load().catch(() => {}); });

  return Object.freeze({ load, create, rotate: rotateClient, revoke: revokeClient, hideSecret,
    get clients() { return clients.map(client => ({ ...client })); }, get secretShown() { return secret !== null; } });
}
