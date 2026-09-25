// T043: the settings page's browser grants section (settings.html#settings-grants) — what
// the browser tools may reach and which data may travel there, from the server's own
// records (GET {base}api/v1/browser-grants). For each grant: the recipients (hosts every
// request may reach), the navigation sources, the projection (each exact address the
// browser may open, and for a query parameter the owner-declared values it may carry —
// shown only as a count: the server keeps their SHA-256 digests, never the values), the
// covered tools, the expiry and the state. The owner creates a grant (one exact address,
// optionally one query parameter with the values it may carry) and revokes one; a revoked
// or expired grant authorizes no later browser call. All server text reaches the DOM
// through textContent or attributes only.

import { basePathFrom, createSupportedSession } from './session.mjs';

export const GRANTS_MOUNT_ID = 'settings-grants';
export const COMMAND_SCHEMA = 'browser-grant-command-v1';
export const REVOCATION_SCHEMA = 'browser-grant-revocation-command-v1';
export const OWNER_SOURCE = 'owner_values';
export const TOOLS = Object.freeze(['browser_navigate', 'browser_read', 'browser_screenshot']);
export const TOOL_LABELS = Object.freeze({
  browser_navigate: '열기', browser_read: '본문 읽기', browser_screenshot: '화면 캡처',
});
export const STATE_LABELS = Object.freeze({ active: '유효', revoked: '철회됨', expired: '만료됨' });
export const DEFAULT_LIMITS = Object.freeze({
  max_response_bytes: 2 * 1024 * 1024, max_total_bytes: 8 * 1024 * 1024, max_requests: 64, max_redirects: 3,
  ttl_ms: 60_000,
});
export const MESSAGES = Object.freeze({
  intro: '브라우저 도구가 요청을 보낼 수 있는 곳과, 그 요청에 실릴 수 있는 값을 정합니다. 여기에 없는 주소나 선언하지 않은 값은 보내지 않습니다.',
  loading: '브라우저 접근 허가를 불러오는 중…',
  none: '아직 만든 브라우저 접근 허가가 없습니다. 허가가 없으면 브라우저 도구는 아무 곳에도 요청하지 않습니다.',
  unauthenticated: '소유자 세션이 있어야 브라우저 접근 허가를 보고 만들 수 있습니다.',
  failed: '브라우저 접근 허가를 불러오지 못했습니다.',
  creating: '허가를 기록하는 중…',
  created: '허가를 만들었습니다.',
  revoking: '허가를 철회하는 중…',
  revoked: '허가를 철회했습니다. 이후의 브라우저 호출은 이 허가로 실행되지 않습니다.',
  invalid: '입력한 허가 내용을 확인해 주세요.',
  refused: '서버가 이 허가를 받아들이지 않았습니다.',
  pureNavigation: '원본 데이터 없음(순수 탐색)',
  valuesOnlyDigests: '값은 SHA-256 요약으로만 저장되어 다시 보이지 않습니다',
});

const HOST = /^[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})*$/;
const PARAMETER = /^[A-Za-z0-9_.~-]{1,64}$/;

function stamp(date) {
  return date.toISOString().replace(/\.(\d{3})Z$/, '.$1000Z');
}

function localTime(value) {
  const parsed = new Date(typeof value === 'string' ? value.replace(/(\.\d{3})\d{3}Z$/, '$1Z') : NaN);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString('ko-KR', { timeZone: 'UTC' }) + ' UTC';
}

// the owner's form → one exact `browser-grant-command-v1`; throws TypeError on anything else
export function grantCommand(form, { now = new Date(), commandId } = {}) {
  if (!form || typeof form !== 'object') throw new TypeError(MESSAGES.invalid);
  const label = typeof form.label === 'string' ? form.label.trim() : '';
  if (!label || label.length > 120) throw new TypeError(MESSAGES.invalid);
  const tools = [...new Set(Array.isArray(form.tools) ? form.tools : [])].filter(tool => TOOLS.includes(tool)).sort();
  if (!tools.length) throw new TypeError('허가할 브라우저 도구를 하나 이상 고르세요.');
  let url;
  try {
    url = new URL(String(form.url ?? '').trim());
  } catch {
    throw new TypeError('https 주소를 입력하세요.');
  }
  if (url.protocol !== 'https:' || url.username || url.password || url.port || url.hash || url.search) {
    throw new TypeError('쿼리·포트·계정 없는 https 주소를 입력하세요.');
  }
  const entry = url.origin + url.pathname;
  const source = url.origin + url.pathname.slice(0, url.pathname.lastIndexOf('/') + 1);
  const extra = String(form.recipients ?? '').split(/[\s,]+/).filter(Boolean).map(host => host.toLowerCase());
  if (!extra.every(host => HOST.test(host))) throw new TypeError('받는 곳은 호스트 이름으로 입력하세요.');
  const recipients = [...new Set([url.hostname, ...extra])];
  const parameter = String(form.parameter ?? '').trim();
  const values = String(form.values ?? '').split('\n').map(value => value.trim()).filter(Boolean);
  let entries = [{ url: entry, parameters: [] }];
  let dataSources = [];
  if (parameter) {
    if (!PARAMETER.test(parameter) || !values.length || new Set(values).size !== values.length) {
      throw new TypeError('매개변수 이름과, 그 매개변수에 실릴 수 있는 값을 한 줄에 하나씩 입력하세요.');
    }
    entries = [{ url: entry, parameters: [{ name: parameter, source: OWNER_SOURCE }] }];
    dataSources = [{ source_id: OWNER_SOURCE, values }];
  } else if (values.length) {
    throw new TypeError('값을 허가하려면 그 값이 실릴 매개변수 이름을 입력하세요.');
  }
  const days = Number(form.days);
  if (!Number.isInteger(days) || days < 1 || days > 90) throw new TypeError('유효 기간은 1~90일입니다.');
  return {
    schema_version: COMMAND_SCHEMA, command_id: commandId ?? globalThis.crypto.randomUUID(), label, tools,
    sources: [source], recipients, entries, data_sources: dataSources, limits: { ...DEFAULT_LIMITS },
    expires_at_utc: stamp(new Date(now.getTime() + days * 86_400_000)),
  };
}

// one grant view → the lines the screen shows (plain strings)
export function grantLines(view) {
  const sources = Object.fromEntries((view?.projection?.data_sources ?? []).map(item => [item.source_id, item]));
  const projection = (view?.projection?.entries ?? []).map(entry => {
    if (!entry.parameters.length) return `${entry.url} · ${MESSAGES.pureNavigation}`;
    const parameters = entry.parameters.map(item => {
      const count = sources[item.source]?.value_count ?? 0;
      return `${item.name} ← 선언한 값 ${count}개`;
    });
    return `${entry.url}?${parameters.join(' & ')} · ${MESSAGES.valuesOnlyDigests}`;
  });
  return Object.freeze({
    recipients: `받는 곳: ${(view?.recipients ?? []).join(', ')}`,
    sources: `탐색 범위: ${(view?.sources ?? []).join(', ')}`,
    projection,
    tools: `도구: ${(view?.tools ?? []).map(tool => TOOL_LABELS[tool] ?? tool).join(', ')}`,
    expiry: `만료: ${localTime(view?.expires_at_utc)}`,
    state: STATE_LABELS[view?.state] ?? String(view?.state),
  });
}

export function renderGrants({ root, document, state, status = '', onRevoke, onCreate }) {
  if (typeof root?.replaceChildren !== 'function') throw new TypeError('a grants mount is required');
  const element = (tag, text, attributes = {}) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  };
  const children = [element('h2', '브라우저 접근 허가', { id: 'settings-grants-title' }), element('p', MESSAGES.intro)];
  const grants = Array.isArray(state?.grants) ? state.grants : null;
  if (grants !== null) {
    if (!grants.length) children.push(element('p', MESSAGES.none, { class: 'grant-none' }));
    const list = element('ul', undefined, { class: 'grant-list', 'aria-label': '브라우저 접근 허가 목록' });
    for (const view of grants) {
      const lines = grantLines(view);
      const row = element('li', undefined, { 'data-grant-id': String(view.grant_id), 'data-state': String(view.state) });
      row.append(element('strong', String(view.label)), element('span', ` · ${lines.state}`, { class: 'grant-state' }),
        element('p', lines.recipients, { class: 'grant-recipients' }),
        element('p', lines.sources, { class: 'grant-sources' }));
      const projection = element('ul', undefined, { class: 'grant-projection', 'aria-label': '허용 요청' });
      for (const line of lines.projection) projection.append(element('li', line));
      row.append(projection, element('p', lines.tools, { class: 'grant-tools' }),
        element('p', lines.expiry, { class: 'grant-expiry' }));
      if (view.state === 'active' && typeof onRevoke === 'function') {
        const button = element('button', '이 허가 철회', { type: 'button' });
        button.addEventListener('click', () => onRevoke(view));
        row.append(button);
      }
      list.append(row);
    }
    children.push(list);
    if (typeof onCreate === 'function') children.push(createForm(element, onCreate));
  }
  children.push(element('p', status, { role: 'status', 'aria-live': 'polite', class: 'grant-status' }));
  root.replaceChildren(...children);
  return root;
}

function createForm(element, onCreate) {
  const form = element('form', undefined, { class: 'grant-form', 'aria-label': '새 브라우저 접근 허가' });
  const field = (label, input) => {
    const wrapper = element('label', label);
    wrapper.append(input);
    return wrapper;
  };
  const label = element('input', undefined, { name: 'label', required: '', maxlength: '120' });
  const url = element('input', undefined, { name: 'url', type: 'url', required: '', placeholder: 'https://example.org/search' });
  const parameter = element('input', undefined, { name: 'parameter', placeholder: '예: q (비우면 순수 탐색)' });
  const values = element('textarea', undefined, { name: 'values', rows: '3' });
  const recipients = element('input', undefined, { name: 'recipients', placeholder: '예: cdn.example.org' });
  const days = element('input', undefined, { name: 'days', type: 'number', min: '1', max: '90', value: '7' });
  const tools = element('fieldset');
  tools.append(element('legend', '허가할 도구'));
  for (const tool of TOOLS) {
    const box = element('input', undefined, { type: 'checkbox', name: 'tools', value: tool });
    if (tool === 'browser_read') box.setAttribute('checked', '');
    const wrapper = element('label', ` ${TOOL_LABELS[tool]}`);
    wrapper.prepend(box);
    tools.append(wrapper);
  }
  form.append(element('h3', '새 허가'), field('이름 ', label), field('열 수 있는 정확한 주소 ', url),
    field('값이 실릴 수 있는 쿼리 매개변수 ', parameter), field('그 매개변수에 실릴 수 있는 값(한 줄에 하나) ', values),
    field('추가로 받을 수 있는 호스트 ', recipients), tools, field('유효 기간(일) ', days),
    element('button', '이 내용으로 허가 만들기', { type: 'submit' }));
  form.addEventListener('submit', event => {
    event.preventDefault();
    const checked = [...form.querySelectorAll('input[name="tools"]')].filter(box => box.checked).map(box => box.value);
    onCreate({ label: label.value, url: url.value, parameter: parameter.value, values: values.value,
      recipients: recipients.value, days: Number(days.value), tools: checked });
  });
  return form;
}

export async function bootGrants({ document, location, fetch, now = () => new Date() } = {}) {
  const root = document.getElementById(GRANTS_MOUNT_ID);
  if (root === null) return null;
  renderGrants({ root, document, state: null, status: MESSAGES.loading });
  const basePath = basePathFrom(location.pathname);
  const prefix = basePath.slice(0, -1);
  const path = `${prefix}/api/v1/browser-grants`;
  const session = createSupportedSession({ fetch, basePath });
  try {
    await session.establish();
  } catch (error) {
    renderGrants({ root, document, state: null,
      status: error?.code === 'unauthenticated' ? MESSAGES.unauthenticated : MESSAGES.failed });
    return Object.freeze({ established: false });
  }
  let state = null;
  const draw = status => renderGrants({ root, document, state, status, onRevoke: revoke, onCreate: create });
  async function reload(status) {
    try {
      state = await session.request(path);
      draw(status);
    } catch {
      draw(MESSAGES.failed);
    }
  }
  async function create(form) {
    let body;
    try {
      body = grantCommand(form, { now: now() });
    } catch (error) {
      draw(error?.message ?? MESSAGES.invalid);
      return;
    }
    draw(MESSAGES.creating);
    try {
      await session.request(path, { method: 'POST', body });
      await reload(MESSAGES.created);
    } catch (error) {
      draw(error?.code === 'invalid_input' ? MESSAGES.invalid : MESSAGES.refused);
    }
  }
  async function revoke(view) {
    draw(MESSAGES.revoking);
    try {
      await session.request(`${path}/${view.grant_id}/revoke`, { method: 'POST',
        body: { schema_version: REVOCATION_SCHEMA, command_id: globalThis.crypto.randomUUID() } });
      await reload(MESSAGES.revoked);
    } catch {
      draw(MESSAGES.refused);
    }
  }
  await reload('');
  return Object.freeze({ established: true });
}

if (typeof globalThis.document === 'object' && globalThis.document !== null
    && typeof globalThis.document.getElementById === 'function'
    && globalThis.document.getElementById(GRANTS_MOUNT_ID) !== null) {
  bootGrants({ document: globalThis.document, location: globalThis.location,
    fetch: (...args) => globalThis.fetch(...args) }).catch(() => {
    const root = globalThis.document.getElementById(GRANTS_MOUNT_ID);
    if (root) root.textContent = MESSAGES.failed;
  });
}
