// The owner's Claude API connection (direct-adapter profile). The key is typed into a
// masked field, sent once in a same-origin POST and cleared from the field right away.
// The server keeps it only in its own memory (it is gone after a restart) and never
// returns it. Refreshing the catalog is an explicit, free models read. Choosing a model
// seals the owner's choice of a model the refreshed catalog listed; generation happens
// only in a run the owner consented to, within its budget. Server text reaches the DOM
// through textContent only. This key is independent of the credential gateway's key
// (records page): neither path ever changes the other, and the page says so.

const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;

export const MESSAGES = Object.freeze({
  intro: 'Claude API 키는 이 서버의 메모리에만 보관됩니다. 서버를 다시 시작하면 다시 입력해야 합니다. 키를 저장하거나 모델 목록을 읽는 것만으로는 과금되는 모델 호출이 일어나지 않습니다.',
  independent: '이 키는 아래 API 자격증명(자격증명 게이트웨이)의 키와 별개입니다. 게이트웨이에서 키를 교체하거나 삭제해도 이 키는 바뀌지 않으니, 더 쓰지 않을 키라면 여기서도 따로 잊으세요. 실행은 이 키를 씁니다.',
  noKey: '저장된 키가 없습니다.',
  keyStored: '키가 이 서버의 메모리에 있습니다.',
  noCatalog: '모델 목록을 아직 읽지 않았습니다.',
  choose: '실행에 쓸 모델을 고르세요.',
  chosen: '모델 선택을 기록했습니다.',
});

export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '입력한 값을 받을 수 없습니다.',
  unauthenticated: '브라우저 세션이 없습니다.',
  not_found: '그 모델은 방금 읽은 목록에 없습니다.',
  provider_unavailable: 'Claude에 연결할 수 없습니다. 키가 저장되어 있는지 확인하세요.',
  provider_rejected: 'Claude가 이 키를 받아들이지 않았습니다.',
  unavailable: '처리하지 못했습니다.',
});

function fail(message) {
  throw new Error(message);
}

export function createClaudeConnection({ root, document, request, basePath = '/' } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const path = `${basePath.slice(0, -1)}/api/v1/connections/claude`;
  let state = null;

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', '', { role: 'status', 'aria-live': 'polite' });
  const body = element('div');
  root.replaceChildren(element('h2', 'Claude 연결'), element('p', MESSAGES.intro),
    element('p', MESSAGES.independent), status, body);

  function say(text, code) {
    status.textContent = text;
    status.dataset.state = code;
  }

  async function command(name, payload) {
    try {
      state = await request(`${path}/${name}`, { method: 'POST', body: payload ?? {} });
      render();
      return state;
    } catch (error) {
      const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
      say(ERROR_MESSAGES[code], code);
      throw error;
    }
  }

  function render() {
    const parts = [element('p', state.key_present ? MESSAGES.keyStored : MESSAGES.noKey)];
    const key = element('input', undefined, { type: 'password', id: 'claude-key', autocomplete: 'off',
      spellcheck: 'false', 'aria-label': 'Claude API 키' });
    const store = element('button', state.key_present ? '키 바꾸기' : '키 저장', { type: 'button' });
    store.addEventListener('click', () => {
      const secret = String(key.value ?? '');
      key.value = '';  // never left in the page
      if (!secret) return;
      command('key', { secret }).then(() => say(MESSAGES.keyStored, 'stored')).catch(() => {});
    });
    parts.push(element('label', 'Claude API 키', { for: 'claude-key' }), key, store);
    if (state.key_present) {
      const forget = element('button', '키 지우기', { type: 'button' });
      forget.addEventListener('click', () => command('forget').then(() => say(MESSAGES.noKey, 'forgotten')).catch(() => {}));
      const refresh = element('button', '모델 목록 읽기', { type: 'button' });
      refresh.addEventListener('click', () => command('catalog').then(() => say(MESSAGES.choose, 'catalog')).catch(() => {}));
      parts.push(forget, refresh);
      if (state.catalog === null) {
        parts.push(element('p', MESSAGES.noCatalog));
      } else {
        const select = element('select', undefined, { id: 'claude-model', 'aria-label': '실행에 쓸 모델' });
        for (const id of state.catalog.model_ids) select.append(element('option', id, { value: id }));
        const choose = element('button', '이 모델 선택', { type: 'button' });
        choose.addEventListener('click', () => command('model-choice', { model_id: select.value })
          .then(() => say(`${MESSAGES.chosen} (${select.value})`, 'chosen')).catch(() => {}));
        parts.push(element('label', '실행에 쓸 모델', { for: 'claude-model' }), select, choose);
      }
    }
    body.replaceChildren(...parts);
  }

  async function load() {
    try {
      state = await request(path, {});
      render();
      say('', 'loaded');
      return state;
    } catch (error) {
      const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
      say(ERROR_MESSAGES[code], code);
      throw error;
    }
  }

  return Object.freeze({ load, get state() { return state; } });
}
