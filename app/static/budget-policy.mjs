// T023: the owner's run budgets on the settings page, over `budget-policies-v1`. A budget
// is exact finite limits the runtime enforces for a run the owner consents to — model
// calls, tool calls, node visits, loop rounds, output bytes, concurrency, wall seconds,
// candidates — and, for an API-key connection only, a currency and cost cap. A
// subscription budget never shows or claims an API bill. Saving a budget calls no model,
// checks no connection and starts nothing. Server text reaches the DOM through
// textContent only.

const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
export const COMMAND_SCHEMA = 'budget-policy-command-v1';
export const LIMITS = Object.freeze([
  ['max_model_calls', '모델 호출', 4], ['max_tool_calls', '도구 호출', 8], ['max_node_visits', '노드 방문', 16],
  ['max_loop_rounds', '반복 라운드', 2], ['max_output_bytes', '출력 바이트', 1_000_000],
  ['max_concurrency', '동시 실행', 2], ['max_wall_seconds', '실행 시간(초)', 900], ['max_candidates', '후보 수', 1],
]);
export const MESSAGES = Object.freeze({
  intro: '실행 한도는 소유자가 동의한 실행에서 런타임이 그대로 지키는 유한한 상한입니다. 저장만으로는 모델을 부르거나 연결을 확인하거나 실행을 시작하지 않습니다.',
  subscription: '구독 연결 한도는 호출·시간·출력 같은 사용량으로만 정하며 API 청구액을 표시하지 않습니다.',
  api: 'API 키 연결 한도에는 통화와 비용 상한(백만분의 1 단위)이 반드시 필요합니다.',
  saved: '실행 한도를 이 인스턴스에 기록했습니다.',
  none: '저장된 실행 한도가 없습니다.',
  invalid: '모든 한도는 1 이상의 정수여야 하며, API 연결은 통화(예: USD)와 비용 상한이 필요합니다.',
  failed: '실행 한도를 처리하지 못했습니다.',
});

function fail(message) {
  throw new Error(message);
}

export function budgetPayload({ commandId, profile = 'execution', mode, limits, currency, microunits }) {
  const payload = { schema_version: COMMAND_SCHEMA, command_id: commandId, profile, provider_mode: mode };
  for (const [name] of LIMITS) {
    const value = Number(limits[name]);
    if (!Number.isSafeInteger(value) || value < 1) throw new TypeError(MESSAGES.invalid);
    payload[name] = value;
  }
  if (mode === 'api') {
    const cap = Number(microunits);
    if (!/^[A-Z]{3}$/.test(currency ?? '') || !Number.isSafeInteger(cap) || cap < 1) throw new TypeError(MESSAGES.invalid);
    payload.currency = currency;
    payload.max_api_microunits = cap;
  } else if (mode === 'subscription') {
    payload.currency = null;
    payload.max_api_microunits = null;
  } else {
    throw new TypeError(MESSAGES.invalid);
  }
  return payload;
}

export function createBudgetPolicies({ root, document, request, crypto, basePath = '/' } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function' || typeof crypto?.randomUUID !== 'function') fail('request and crypto are required');
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const path = `${basePath.slice(0, -1)}/api/v1/budget-policies`;

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', '', { role: 'status', 'aria-live': 'polite', id: 'budget-status' });
  const list = element('ul', undefined, { class: 'budget-list', 'aria-label': '저장된 실행 한도' });
  const mode = element('select', undefined, { id: 'budget-mode' });
  mode.append(element('option', '구독 연결', { value: 'subscription' }), element('option', 'API 키 연결', { value: 'api' }));
  const inputs = {};
  const fields = element('div', undefined, { class: 'budget-fields' });
  for (const [name, label, initial] of LIMITS) {
    const input = element('input', undefined, { id: `budget-${name}`, type: 'number', min: '1', step: '1', inputmode: 'numeric' });
    input.value = String(initial);
    inputs[name] = input;
    fields.append(element('label', label, { for: `budget-${name}` }), input);
  }
  const currency = element('input', undefined, { id: 'budget-currency', type: 'text', maxlength: '3', autocomplete: 'off' });
  const microunits = element('input', undefined, { id: 'budget-microunits', type: 'number', min: '1', step: '1' });
  const apiFields = element('div', undefined, { class: 'budget-api' });
  apiFields.append(element('label', '통화', { for: 'budget-currency' }), currency,
    element('label', '비용 상한(백만분의 1 단위)', { for: 'budget-microunits' }), microunits);
  const note = element('p', MESSAGES.subscription);
  const save = element('button', '실행 한도 저장', { type: 'button' });
  function showMode() {
    apiFields.hidden = mode.value !== 'api';
    note.textContent = mode.value === 'api' ? MESSAGES.api : MESSAGES.subscription;
  }
  mode.addEventListener('change', showMode);
  showMode();
  root.replaceChildren(element('h2', '실행 한도'), element('p', MESSAGES.intro), status,
    element('label', '연결 방식', { for: 'budget-mode' }), mode, note, fields, apiFields, save, list);

  function say(text, code) {
    status.textContent = text;
    status.dataset.state = code;
  }

  function describe(policy) {
    const parts = LIMITS.map(([name, label]) => `${label} ${policy[name]}`);
    const bill = policy.provider_mode === 'api' ? ` · 비용 상한 ${policy.max_api_microunits} ${policy.currency}(백만분의 1)` : '';
    return `${policy.provider_mode === 'api' ? 'API 키 연결' : '구독 연결'} · ${parts.join(' · ')}${bill}`;
  }

  async function load() {
    try {
      const value = await request(path, {});
      list.replaceChildren(...(value.policies.length ? value.policies.map(policy => element('li', describe(policy),
        { 'data-policy-hash': policy.policy_hash })) : [element('li', MESSAGES.none)]));
      return value;
    } catch {
      say(MESSAGES.failed, 'unavailable');
      return null;
    }
  }

  save.addEventListener('click', async () => {
    let payload;
    try {
      payload = budgetPayload({ commandId: crypto.randomUUID(), mode: mode.value,
        limits: Object.fromEntries(Object.entries(inputs).map(([name, input]) => [name, input.value])),
        currency: currency.value.trim().toUpperCase(), microunits: microunits.value });
    } catch (error) {
      say(error.message, 'invalid_input');
      return;
    }
    try {
      await request(path, { method: 'POST', body: payload });
      say(MESSAGES.saved, 'saved');
    } catch (error) {
      say(error?.code === 'invalid_input' ? MESSAGES.invalid : MESSAGES.failed, error?.code ?? 'unavailable');
    }
    await load();
  });

  return Object.freeze({ load });
}
