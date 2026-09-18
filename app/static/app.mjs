import { createSpeechInput } from './speech-input.mjs';
import { createConversationController } from './chat.mjs';
import {
  catalogURL, connectionOptions, mixedUsagePolicyPayload, modelSelectionPayload,
  usagePolicyPayload,
} from './settings.mjs';

const $ = selector => document.querySelector(selector);
const app = $('#app');
const input = $('#work-text');
const picker = $('#work-select');
const filesInput = $('#work-files');
const saveStatus = $('#save-status');
const selectedKey = 'deeptwin.selected-work';
let csrf = '';
let works = [];
let current = null;
let savedText = '';
let composing = false;
let inputVersion = 0;
let timer;
let pending = 0;
let queue = Promise.resolve();
let ready = false;
let understandingProviderReady = false;
let providerRecords = [];
const apiConnections = new Map();
let connectionBusy = false;
let apiConnectionBusy = '';
let connectionTimer;
let connectionPolls = 0;
let connectionPollEpoch = 0;
let connectionView = 0;
let connectionVersion = 0;
const MAX_CONNECTION_POLLS = 60;
const readLabels = { read: '글자 읽음', partial: '일부 글자 읽음', unreadable: '읽지 못함', unsupported: '자동 읽기 미지원', pending: '읽기 대기', reading: '읽는 중' };
const understandingRecords = new Map();
const understandingIntents = new Map();
const understandingBusy = new Set();
let understandingView = 0;
let understandingRead = 0;
let understandingTimer;
let understandingPolls = 0;
let selectedUnderstanding = '';
let renderedUnderstanding = '';
const understandingLabels = { queued: '준비 중', running: '이해하는 중', succeeded: '검토할 초안', failed: '완료하지 못함', cancelled: '취소됨' };
const modelCatalogs = new Map();
let savedModel = { version: 0, selection: null };
let modelConnections = [];
let modelDraft = { provider: 'codex', mode: 'subscription', model: '', effort: '', thinking: '' };
let modelSettingsReady = false;
let savedUsage = { version: 0, profile: 'design', policy: null };
let usageSettingsReady = false;
let usageDirty = false;
let usageBusy = false;
let modelSettingsView = 0;
let modelCatalogRead = 0;
let modelCatalogBusy = false;
let speechInput;
let conversation;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function setStatus(state, message) {
  saveStatus.dataset.state = state;
  saveStatus.textContent = message;
}

function hasContent() { return input.value.length > 0 || Boolean(current?.files.length); }
function unsaved() { return current ? input.value !== savedText : input.value.length > 0; }

function setWorkStageView(hasUnderstanding) {
  const view = hasUnderstanding ? 'understanding' : 'intake';
  const firstUnderstandingTransition = $('#work-stage').dataset.view === 'intake' && view === 'understanding';
  if (firstUnderstandingTransition) {
    $('#model-settings').open = false;
    $('#usage-limits').open = false;
    $('#transfer-preview').open = false;
  }
  $('#work-stage').dataset.view = view;
  app.dataset.workspaceView = view;
}

function updateControls() {
  $('#save-work').disabled = !ready || pending > 0 || composing || !unsaved();
  const intent = understandingIntents.get(current?.id);
  const understandingPathReady = intent
    ? understandingProviderReady
    : understandingProviderReady && canUseSupportedUnderstandingModel();
  $('#prepare-design').disabled = !ready || !understandingPathReady || pending > 0 || composing || !hasContent()
    || understandingBusy.has(current?.id) || (!intent && activeUnderstanding());
  $('#prepare-design').textContent = intent ? '같은 요청 확인하기' : '업무 이해하기';
  updateUnderstandingReadiness(intent);
  $('#new-work').disabled = !ready || pending > 0 || composing;
  picker.disabled = !ready || pending > 0 || composing;
  filesInput.disabled = !ready || pending > 0 || composing;
  $('#open-connections').disabled = !ready;
  updateConnectionControls();
  updateModelControls();
  if (conversation) renderConversation(conversation.snapshot());
  speechInput?.updateControls();
}

async function api(path, { method = 'GET', body, raw = false, contentType } = {}) {
  const headers = {};
  if (method !== 'GET') headers['X-DeepTwin-CSRF'] = csrf;
  if (body !== undefined) headers['Content-Type'] = raw ? contentType || 'application/octet-stream' : 'application/json';
  const response = await fetch(path, { method, headers, body: body === undefined ? undefined : raw ? body : JSON.stringify(body), credentials: 'same-origin' });
  let payload;
  try { payload = await response.json(); } catch { throw new Error('서버 응답을 읽지 못했습니다. 입력은 이 화면에 남아 있습니다.'); }
  if (!response.ok) {
    if (response.status === 409) throw Object.assign(new Error('다른 화면에서 저장본이 바뀌었습니다. 현재 입력은 유지했습니다. 새로고침하기 전에 수정 내용을 따로 보관해 주세요.'), { status: response.status });
    const message = [payload.detail, payload.message, payload.error].find(value => typeof value === 'string');
    throw Object.assign(new Error(message || `요청을 완료하지 못했습니다 (${response.status}).`), { status: response.status });
  }
  return payload;
}

function renderConversation(state) {
  const visible = Boolean(state.workId);
  $('#work-chat').hidden = !visible;
  $('#chat-panel').dataset.workId = state.workId;
  $('#chat-panel').dataset.busy = String(state.busy);
  $('#chat-panel').setAttribute('aria-busy', String(state.busy));
  if ($('#chat-draft').value !== state.draft) $('#chat-draft').value = state.draft;
  const messages = $('#chat-messages');
  messages.replaceChildren();
  for (const message of state.messages) {
    const item = node('li', undefined, 'chat-message');
    item.dataset.sequence = String(message.sequence);
    const actor = message.actor.kind === 'human' ? '내가 남김'
      : message.actor.kind === 'agent' ? 'DeepTwin이 남김' : '시스템 기록';
    item.append(node('p', actor, 'chat-message-meta'), node('p', message.content));
    messages.append(item);
  }
  const status = $('#chat-status');
  status.dataset.state = state.error ? 'error' : state.busy ? 'loading' : 'idle';
  status.textContent = state.error
    ? `남기지 못했습니다. 초안은 이 업무에 남아 있습니다. ${state.error}`
    : state.busy ? '이 업무의 기록을 확인하는 중…'
      : state.messages.length ? `${state.messages.length}개 기록됨` : '아직 덧붙인 말이 없습니다.';
  $('#chat-draft').disabled = !visible || state.busy;
  $('#chat-send').disabled = !visible || state.busy || pending > 0 || composing || !state.draft.trim();
}

function syncConversation(work) {
  const selected = work ? { id: work.id, revision: work.revision } : null;
  const state = conversation.snapshot();
  if ((selected?.id || '') === state.workId && (selected?.revision || null) === state.revision) {
    renderConversation(state);
    return Promise.resolve(state);
  }
  return conversation.setWork(selected).catch(() => conversation.snapshot());
}

async function establishBrowserSession() {
  const fragment = new URLSearchParams(location.hash.slice(1));
  const capability = fragment.get('bootstrap');
  if (!capability) {
    const response = await fetch('/api/session/csrf', { credentials: 'same-origin' });
    let result;
    try { result = await response.json(); } catch { throw new Error('브라우저 세션 응답을 읽지 못했습니다.'); }
    if (!response.ok || typeof result.csrf_token !== 'string') {
      throw new Error('브라우저 세션이 종료됐습니다. DeepTwin 인스턴스에서 이 화면을 다시 열어 주세요.');
    }
    csrf = result.csrf_token;
    return;
  }
  const response = await fetch('/api/session/bootstrap', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ capability }),
  });
  let result;
  try { result = await response.json(); } catch { throw new Error('브라우저 세션 응답을 읽지 못했습니다.'); }
  if (!response.ok || typeof result.csrf_token !== 'string') {
    throw new Error(typeof result.detail === 'string' ? result.detail : '브라우저 세션을 만들지 못했습니다.');
  }
  csrf = result.csrf_token;
  history.replaceState(null, '', location.pathname + location.search);
}

function rememberSelection(id) {
  try { if (id) localStorage.setItem(selectedKey, id); else localStorage.removeItem(selectedKey); } catch { /* Server storage does not depend on this optional navigation preference. */ }
}

function renderPicker() {
  picker.replaceChildren();
  const empty = node('option', '새 업무');
  empty.value = '';
  picker.append(empty);
  for (const work of works) {
    const title = work.text.split('\n').find(line => line.trim()) || work.files[0]?.name || '작성 중인 업무';
    const option = node('option', title.slice(0, 46));
    option.value = work.id;
    picker.append(option);
  }
  picker.value = current?.id || '';
  picker.hidden = works.length === 0;
}

async function refreshWorks() {
  const result = await api('/api/works');
  works = Array.isArray(result) ? result : result.works;
  renderPicker();
}

function renderFiles() {
  const list = $('#file-list');
  list.replaceChildren();
  const labels = { read: '글자 읽음', partial: '일부 글자 읽음', unreadable: '읽지 못함', unsupported: '원본 저장 · 자동 읽기 미지원', pending: '읽기 대기', reading: '읽는 중' };
  for (const file of current?.files || []) {
    const item = node('li', undefined, 'file-item');
    item.dataset.fileId = file.id;
    const heading = node('div', undefined, 'file-heading');
    heading.append(node('span', file.name, 'file-name'));
    const link = node('a', '원본 받기');
    link.href = `/api/works/${encodeURIComponent(current.id)}/files/${encodeURIComponent(file.id)}`;
    link.download = file.name;
    heading.append(link);
    item.append(heading, node('p', `${file.size.toLocaleString()} bytes · ${file.media_type}`, 'file-meta'));
    item.append(node('p', labels[file.read_status] || '읽기 상태 미확인', 'file-status'));
    if (file.read_note) item.append(node('p', file.read_note, 'file-status'));
    if (file.text) {
      const details = node('details');
      details.append(node('summary', '읽은 글자 확인'), node('pre', file.text));
      item.append(details);
    }
    list.append(item);
  }
  $('.materials').hidden = !list.children.length && !$('#upload-results').children.length;
}

function acceptWork(work) {
  current = work;
  savedText = work.text;
  app.dataset.workId = work.id;
  rememberSelection(work.id);
  const index = works.findIndex(item => item.id === work.id);
  if (index >= 0) works[index] = work; else works.unshift(work);
  renderPicker();
  renderFiles();
  renderTransfer();
  updateUnderstandingRevision();
  void syncConversation(work);
}

async function flushText({ allowBlank = false } = {}) {
  clearTimeout(timer);
  try {
    while (true) {
      if (composing) {
        setStatus('unsaved', '글자 입력 중 · 입력을 마치면 저장합니다');
        await new Promise(resolve => input.addEventListener('compositionend', resolve, { once: true }));
      }
      if (!current && !input.value.length && !allowBlank) return null;
      const text = input.value;
      if (current && text === savedText) break;
      setStatus('saving', 'DeepTwin 인스턴스에 저장하는 중…');
      const work = current
        ? await api(`/api/works/${encodeURIComponent(current.id)}`, { method: 'PUT', body: { text, expected_revision: current.revision } })
        : await api('/api/works', { method: 'POST', body: { text } });
      acceptWork(work);
    }
    setStatus('saved', `DeepTwin 인스턴스에 저장됨 · 저장본 ${current.revision}`);
    return current;
  } catch (error) {
    setStatus('error', '저장하지 못했습니다 · 입력은 이 화면에 남아 있습니다');
    throw error;
  }
}

function action(operation, { freeze = false } = {}) {
  pending++;
  updateControls();
  if (freeze) input.readOnly = true;
  const task = queue.then(operation);
  queue = task.catch(() => {});
  return task.catch(error => { $('#page-message').textContent = error.message || '요청을 마치지 못했습니다. 다시 시도해 주세요.'; })
    .finally(() => { pending--; if (freeze) input.readOnly = false; updateControls(); speechInput?.flushPending(); });
}

function resetRequest() {
  stopConnectionPolling();
  connectionView++;
  connectionVersion++;
  connectionBusy = false;
  $('#provider-panel').hidden = true;
  $('#connection-message').textContent = '';
  resetUnderstanding();
}

async function chooseWork(id) {
  await flushText();
  const work = id ? await api(`/api/works/${encodeURIComponent(id)}`) : null;
  current = work;
  savedText = work?.text || '';
  input.value = savedText;
  app.dataset.workId = work?.id || '';
  rememberSelection(work?.id);
  $('#upload-results').replaceChildren();
  $('#upload-status').textContent = '';
  $('#page-message').textContent = '';
  resetRequest();
  renderPicker();
  renderFiles();
  renderTransfer();
  void loadUnderstandings();
  // Keep the work-switch operation open until this work's model state has replaced
  // the previous work's status.  Otherwise an observer can mistake the old `saved`
  // marker for completion and act on a model that belongs to another work.
  await Promise.all([loadModelSettings(), syncConversation(work)]);
  setStatus(work ? 'saved' : 'empty', work ? `DeepTwin 인스턴스에 저장됨 · 저장본 ${work.revision}` : '내용을 입력하면 이 DeepTwin 인스턴스에 저장됩니다');
}

function beginWorkSwitch() {
  // Invalidate async model reads and clear the previous work's terminal marker in
  // the same event turn. Consumers must never observe `saved` from work A while a
  // requested switch to work B is waiting in the serialized action queue.
  modelSettingsView++;
  modelCatalogRead++;
  modelSettingsReady = false;
  modelCatalogBusy = false;
  modelSelectionStatus('loading', '선택한 업무의 모델 설정을 불러오는 중…');
  updateModelControls();
}

async function uploadFiles(files) {
  await flushText({ allowBlank: true });
  const results = $('#upload-results');
  results.replaceChildren();
  $('.materials').hidden = false;
  const status = $('#upload-status');
  status.dataset.state = 'uploading';
  let succeeded = 0;
  for (const [index, file] of files.entries()) {
    const item = node('li', `${file.name} · 추가하는 중…`);
    results.append(item);
    status.textContent = `자료 추가 중 · ${index + 1}/${files.length}`;
    try {
      await flushText();
      const work = await api(`/api/works/${encodeURIComponent(current.id)}/files?name=${encodeURIComponent(file.name)}&expected_revision=${current.revision}`, { method: 'POST', body: file, raw: true, contentType: file.type });
      acceptWork(work);
      item.textContent = `${file.name} · 원본 저장됨`;
      item.dataset.status = 'saved';
      succeeded++;
    } catch (error) {
      item.textContent = `${file.name} · 추가 실패 · ${error.message}`;
      item.dataset.status = 'error';
    }
  }
  await flushText();
  await refreshWorks();
  status.dataset.state = 'done';
  status.textContent = `${succeeded}개 추가됨${succeeded < files.length ? ` · ${files.length - succeeded}개 실패. 저장된 자료는 유지됩니다.` : ''}`;
}

function renderProviders(providers) {
  providerRecords = providers;
  const list = $('#providers');
  list.replaceChildren();
  for (const id of ['claude', 'codex']) {
    const provider = providers.find(item => item.id === id);
    if (id === 'codex') {
      const section = codexCard(provider);
      section.append(apiKeyCard('codex', 'Codex 별도 API'));
      list.append(section);
    } else {
      const section = node('section', undefined, 'provider claude-provider');
      section.append(node('h3', provider?.label || 'Claude'));
      section.append(node('p', 'Claude는 별도 API 키로 연결하며 Claude 구독 로그인은 지원하지 않습니다.'));
      section.append(apiKeyCard('claude', 'Claude API'));
      list.append(section);
    }
  }
  updateControls();
}

function apiConnectionState(provider) {
  return apiConnections.get(`${provider}:api`) || {
    provider, mode: 'api', state: 'loading', key_present: false, version: 0,
    cleanup_pending: false,
  };
}

function apiKeyCard(provider, label) {
  const record = apiConnectionState(provider);
  const key = `${provider}:api`;
  const labels = {
    loading: '연결 상태를 확인하는 중…', not_configured: 'API 키를 연결하지 않음',
    configured: 'API 키가 안전하게 연결됨', needs_unlock: '보호된 키 저장소 잠금 해제 필요',
    blocked: '보호된 키 저장소 접근이 차단됨', missing: '보관된 API 키를 찾지 못함',
    error: '연결 상태를 확인하지 못함',
  };
  const section = node('section', undefined, 'api-key-connection');
  section.dataset.provider = provider;
  section.dataset.state = record.state;
  section.setAttribute('aria-busy', String(apiConnectionBusy === key));
  section.append(node('h4', label));
  section.append(node('p', labels[record.state] || '연결 상태를 확인하지 못함', 'connection-state'));
  if (record.cleanup_pending) section.append(node('p', '이전 키 정리를 다시 시도할 수 있습니다. 현재 연결 정보는 유지됩니다.', 'connection-warning'));

  const form = node('form', undefined, 'api-key-form');
  form.dataset.provider = provider;
  const keyLabel = node('label', 'API 키');
  const input = node('input');
  input.type = 'password';
  input.name = 'api-key';
  input.autocomplete = 'new-password';
  input.spellcheck = false;
  input.placeholder = record.key_present ? '새 키를 입력하면 교체됩니다' : 'API 키 입력';
  input.required = true;
  input.maxLength = 16384;
  keyLabel.append(input);
  form.append(keyLabel);

  const details = node('details', undefined, 'api-account-fields');
  details.append(node('summary', '선택 입력 · 계정 범위'));
  if (provider === 'claude') {
    const workspace = node('label', 'Workspace ID');
    const field = node('input'); field.name = 'workspace_id'; field.autocomplete = 'off'; field.maxLength = 200;
    workspace.append(field); details.append(workspace);
  } else {
    for (const [name, text] of [['project_id', 'Project ID'], ['organization_id', 'Organization ID']]) {
      const item = node('label', text);
      const field = node('input'); field.name = name; field.autocomplete = 'off'; field.maxLength = 200;
      item.append(field); details.append(item);
    }
  }
  form.append(details);
  const actions = node('div', undefined, 'connection-actions');
  const save = node('button', record.key_present ? '새 키로 교체' : 'API 키 연결');
  save.type = 'submit'; save.disabled = apiConnectionBusy !== '' || record.state === 'loading';
  actions.append(save);
  if (record.key_present || record.cleanup_pending) {
    const remove = node('button', record.key_present ? '키 삭제' : '정리 다시 시도', 'quiet-button');
    remove.type = 'button'; remove.disabled = apiConnectionBusy !== '';
    remove.addEventListener('click', () => removeAPIConnection(provider, record.version));
    actions.append(remove);
  }
  form.append(actions);
  form.addEventListener('submit', event => {
    event.preventDefault();
    saveAPIConnection(provider, record.version, form);
  });
  section.append(form);
  return section;
}

async function readAPIConnection(provider) {
  try {
    const record = await api(`/api/v1/connections/${provider}/api`);
    apiConnections.set(`${provider}:api`, record);
  } catch (error) {
    apiConnections.set(`${provider}:api`, {
      provider, mode: 'api', state: 'error', key_present: false, version: 0,
      cleanup_pending: false, message: error.message,
    });
  }
}

async function saveAPIConnection(provider, expectedVersion, form) {
  const keyId = `${provider}:api`;
  if (apiConnectionBusy) return;
  const input = form.elements.namedItem('api-key');
  let secret = input.value;
  input.value = '';
  const request = {
    expected_version: expectedVersion,
    key: secret,
    workspace_id: provider === 'claude' ? form.elements.namedItem('workspace_id')?.value || null : null,
    project_id: provider === 'codex' ? form.elements.namedItem('project_id')?.value || null : null,
    organization_id: provider === 'codex' ? form.elements.namedItem('organization_id')?.value || null : null,
  };
  apiConnectionBusy = keyId;
  $('#connection-message').textContent = `${provider === 'claude' ? 'Claude' : 'Codex'} API 키를 보호된 저장소에 보관하는 중…`;
  renderProviders(providerRecords);
  try {
    const record = await api(`/api/v1/connections/${provider}/api`, { method: 'PUT', body: request });
    apiConnections.set(keyId, record);
    $('#connection-message').textContent = 'API 키를 연결했습니다. 모델 목록 조회와 실제 실행은 별도 동작입니다.';
    modelCatalogs.delete(keyId);
    void loadModelSettings();
  } catch (error) {
    await readAPIConnection(provider);
    $('#connection-message').textContent = error.message || 'API 키를 연결하지 못했습니다.';
  } finally {
    request.key = '';
    secret = '';
    apiConnectionBusy = '';
    renderProviders(providerRecords);
  }
}

async function removeAPIConnection(provider, expectedVersion) {
  const key = `${provider}:api`;
  if (apiConnectionBusy) return;
  apiConnectionBusy = key;
  $('#connection-message').textContent = '보관된 API 키 연결을 삭제하는 중…';
  renderProviders(providerRecords);
  try {
    const record = await api(`/api/v1/connections/${provider}/api`, {
      method: 'DELETE', body: { expected_version: expectedVersion },
    });
    apiConnections.set(key, record);
    modelCatalogs.delete(key);
    $('#connection-message').textContent = record.cleanup_pending
      ? '연결은 해제했습니다. 보호된 저장소 정리는 다시 시도할 수 있습니다.'
      : 'API 키 연결을 삭제했습니다.';
    void loadModelSettings();
  } catch (error) {
    await readAPIConnection(provider);
    $('#connection-message').textContent = error.message || 'API 키 연결을 삭제하지 못했습니다.';
  } finally {
    apiConnectionBusy = '';
    renderProviders(providerRecords);
  }
}

function currentConnection() {
  return providerRecords.find(provider => provider.id === 'codex')?.connection;
}

function safeAuthURL(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || !['auth.openai.com', 'chatgpt.com'].includes(url.hostname)
        || url.username || url.password || (url.port && url.port !== '443')) return null;
    return url.href;
  } catch { return null; }
}

function connectionButton(label, actionName) {
  const button = node('button', label);
  button.type = 'button';
  button.dataset.connectionAction = actionName;
  button.addEventListener('click', () => {
    const loginId = currentConnection()?.login?.login_id;
    if (actionName === 'cancel' && !loginId) return;
    const path = actionName === 'check' ? 'check' : actionName === 'login' ? 'login' : 'login/cancel';
    connectionAction(path, actionName === 'cancel' ? { login_id: loginId } : {});
  });
  return button;
}

function codexCard(provider) {
  const connection = provider?.connection || { state: 'unchecked', login: { status: 'idle' }, rate_limits: [] };
  const labels = {
    unchecked: '아직 연결을 확인하지 않았습니다', checking: '연결 확인 중', disconnected: 'ChatGPT 로그인 필요',
    connected: 'ChatGPT 계정 연결 확인됨', api_key: 'API 키 계정 · 구독 연결 아님', unavailable: 'Codex 연결을 사용할 수 없음', error: '연결을 확인하지 못했습니다',
  };
  const section = node('section', undefined, 'provider codex-provider');
  section.id = 'codex-connection';
  section.dataset.state = connection.state;
  section.dataset.loginStatus = connection.login?.status || 'idle';
  section.append(node('h3', 'Codex'));
  section.append(node('p', labels[connection.state] || '연결 상태 미확인', 'connection-state'));
  const connectionMessage = connection.message;
  if (connectionMessage) section.append(node('p', connectionMessage));
  section.append(node('p', '현재 개발 미리보기는 개발 호스트의 Codex 설치·로그인을 확인하는 사전 출시 호스트 어댑터를 사용합니다. 웹 릴리스에서는 인스턴스 소유의 격리된 관리형 실행기로 대체하며, 브라우저 기기의 Codex 로그인과 자동 공유하지 않습니다.', 'shared-login-note'));
  if (connection.state === 'api_key') section.append(node('p', '현재 API 키 계정은 구독 연결로 사용하지 않습니다. ChatGPT 구독을 사용하려면 직접 로그인해 주세요.'));
  if (connection.plan_type) section.append(node('p', `확인된 플랜 · ${connection.plan_type}`));
  const controls = node('div', undefined, 'connection-actions');
  controls.append(connectionButton('연결 확인', 'check'));
  if (connection.login?.status === 'pending') {
    const url = safeAuthURL(connection.login.auth_url);
    if (url) {
      const link = node('a', '공식 로그인 열기', 'official-login-link');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      controls.append(link);
    } else {
      $('#connection-message').textContent = '공식 로그인 주소를 확인하지 못했습니다. 다시 연결을 확인해 주세요.';
    }
    controls.append(connectionButton('로그인 취소', 'cancel'));
    section.append(node('p', '공식 로그인 화면을 마친 뒤 이 업무 공간으로 돌아오세요. 대기 중에만 완료 여부를 확인합니다.'));
  } else if (connection.state !== 'connected') controls.append(connectionButton('ChatGPT로 로그인', 'login'));
  section.append(controls);
  if (connection.state === 'connected') {
    const limits = node('div', undefined, 'connection-limits');
    limits.append(node('h4', '확인 시점의 남은 사용량'));
    if (!connection.rate_limits?.length) limits.append(node('p', '사용량을 아직 확인하지 못했습니다. 0%나 무제한을 뜻하지 않습니다.'));
    for (const limit of connection.rate_limits || []) {
      const remaining = typeof limit.remaining_percent === 'number' && Number.isFinite(limit.remaining_percent)
        ? `${Math.max(0, Math.min(100, limit.remaining_percent))}% 남음` : '남은 사용량 미확인';
      let text = `${limit.label || limit.id} · ${remaining}`;
      if (typeof limit.window_minutes === 'number' && limit.window_minutes > 0) text += ` · ${limit.window_minutes}분 구간`;
      if (typeof limit.resets_at === 'number' && Number.isFinite(limit.resets_at)) {
        const reset = new Date(limit.resets_at * 1000);
        if (!Number.isNaN(reset.valueOf())) text += ` · 갱신 ${reset.toLocaleString('ko-KR')}`;
      }
      limits.append(node('p', text));
    }
    section.append(limits);
  }
  section.append(node('p', '로그인 연결과 별개로 환경 설계·실행 엔진은 아직 미연결입니다.', 'engine-boundary'));
  return section;
}

function updateConnectionControls() {
  const connection = currentConnection();
  for (const button of $('#providers').querySelectorAll('[data-connection-action]')) {
    const actionName = button.dataset.connectionAction;
    button.disabled = !ready || connectionBusy
      || (actionName === 'login' && connection?.state === 'unavailable')
      || (actionName === 'cancel' && !connection?.login?.login_id);
  }
  $('#codex-connection')?.setAttribute('aria-busy', String(connectionBusy));
  for (const control of $('#providers').querySelectorAll('.api-key-form input, .api-key-form button')) {
    const state = control.closest('.api-key-connection')?.dataset.state;
    control.disabled = !ready || connectionBusy || apiConnectionBusy !== '' || state === 'loading';
  }
}

function acceptProvider(provider) {
  providerRecords = providerRecords.filter(item => item.id !== 'codex').concat(provider);
  const old = $('#codex-connection');
  const actionName = old?.contains(document.activeElement) ? document.activeElement.dataset.connectionAction : null;
  const focusedLoginLink = old?.contains(document.activeElement) && document.activeElement.matches('.official-login-link');
  const section = codexCard(provider);
  if (old) old.replaceWith(section); else $('#providers').append(section);
  updateControls();
  if (actionName) section.querySelector(`[data-connection-action="${actionName}"]`)?.focus({ preventScroll: true });
  else if (focusedLoginLink) (section.querySelector('.official-login-link') || section.querySelector('[data-connection-action="check"]'))?.focus({ preventScroll: true });
}

function restoreConnectionFocus(actionName) {
  if (!actionName || document.activeElement !== document.body) return;
  const section = $('#codex-connection');
  const target = section?.querySelector(`[data-connection-action="${actionName}"]`)
    || section?.querySelector('.official-login-link, [data-connection-action="check"]');
  target?.focus({ preventScroll: true });
}

function stopConnectionPolling() {
  clearTimeout(connectionTimer);
  connectionTimer = undefined;
  connectionPollEpoch++;
}

function scheduleConnectionPoll() {
  if (connectionTimer || connectionBusy || document.hidden || $('#provider-panel').hidden || currentConnection()?.login?.status !== 'pending') return;
  if (connectionPolls >= MAX_CONNECTION_POLLS) {
    $('#connection-message').textContent = '로그인이 계속 대기 중입니다. 자동 확인은 멈췄습니다. 로그인 후 ‘연결 확인’을 눌러 주세요.';
    return;
  }
  const epoch = connectionPollEpoch;
  const view = connectionView;
  connectionTimer = setTimeout(async () => {
    connectionTimer = undefined;
    if (epoch !== connectionPollEpoch || document.hidden || $('#provider-panel').hidden) return;
    const version = ++connectionVersion;
    connectionPolls++;
    try {
      const provider = await api('/api/providers/codex');
      if (epoch !== connectionPollEpoch || view !== connectionView || version !== connectionVersion) return;
      acceptProvider(provider);
      scheduleConnectionPoll();
    } catch {
      if (view === connectionView && epoch === connectionPollEpoch && version === connectionVersion) $('#connection-message').textContent = '로그인 상태를 불러오지 못했습니다. 자동 확인은 멈췄습니다. ‘연결 확인’을 다시 눌러 주세요.';
    }
  }, 2000);
}

async function connectionAction(path, body) {
  if (connectionBusy) return;
  const focusAction = document.activeElement?.dataset.connectionAction;
  stopConnectionPolling();
  const view = connectionView;
  const version = ++connectionVersion;
  connectionBusy = true;
  $('#connection-message').textContent = path === 'check' ? 'Codex에 연결 상태를 확인하는 중…' : path === 'login' ? '공식 로그인 요청 중…' : '로그인 취소 요청 중…';
  updateConnectionControls();
  try {
    const provider = await api(`/api/providers/codex/${path}`, { method: 'POST', body });
    if (view !== connectionView || version !== connectionVersion) return;
    $('#connection-message').textContent = '';
    acceptProvider(provider);
    connectionPolls = 0;
  } catch (error) {
    if (view === connectionView) $('#connection-message').textContent = error.message || '연결 요청을 완료하지 못했습니다. 다시 확인해 주세요.';
  } finally {
    if (view === connectionView && version === connectionVersion) {
      connectionBusy = false;
      updateConnectionControls();
      restoreConnectionFocus(focusAction);
      scheduleConnectionPoll();
    }
  }
}

async function openConnections() {
  if (connectionBusy) {
    $('#provider-panel').hidden = false;
    $('#provider-panel').scrollIntoView({ block: 'nearest' });
    $('#provider-title').focus({ preventScroll: true });
    return;
  }
  const view = connectionView;
  const version = ++connectionVersion;
  $('#provider-panel').hidden = false;
  renderProviders(providerRecords);
  $('#provider-panel').scrollIntoView({ block: 'nearest' });
  $('#provider-title').focus({ preventScroll: true });
  try {
    const [result] = await Promise.all([
      api('/api/providers'),
      readAPIConnection('claude'),
      readAPIConnection('codex'),
    ]);
    if (view !== connectionView || version !== connectionVersion) return;
    renderProviders(result.providers);
    scheduleConnectionPoll();
  } catch (error) {
    if (view === connectionView && version === connectionVersion) $('#connection-message').textContent = error.message || '연결 상태를 불러오지 못했습니다.';
  }
}

function renderTransfer() {
  $('#transfer-description').textContent = input.value;
  const files = $('#transfer-files');
  files.replaceChildren();
  for (const file of current?.files || []) {
    const section = node('section', undefined, 'transfer-file');
    section.append(node('h3', file.name), node('p', `${readLabels[file.read_status] || '읽기 상태 미확인'} · ${file.read_note || '추가 읽기 안내 없음'}`));
    if (['read', 'partial'].includes(file.read_status) && file.text) section.append(node('pre', file.text));
    else section.append(node('p', '이 파일의 내용은 보내지 않습니다. 파일 이름과 읽기 상태만 보냅니다.'));
    files.append(section);
  }
}

function modelConnectionKey(value = modelDraft) { return `${value.provider}:${value.mode}`; }
function currentModelConnection() {
  return modelConnections.find(item => modelConnectionKey(item) === modelConnectionKey());
}
function emptyModelDraft() {
  const selected = modelConnections.find(item => item.is_default) || modelConnections[0];
  return {
    provider: selected?.provider || '', mode: selected?.mode || '', model: '', effort: '', thinking: '',
  };
}
function draftFromSelection(selection) {
  return {
    provider: selection.provider, mode: selection.mode, model: selection.model,
    effort: selection.effort, thinking: selection.thinking || '',
  };
}
function modelCatalog() { return modelCatalogs.get(modelConnectionKey()); }
function draftModel() { return modelCatalog()?.models.find(item => item.model === modelDraft.model); }
function thinkingOptions() {
  const types = draftModel()?.raw_capability_claims?.thinking?.types;
  if (!types || Object.getPrototypeOf(types) !== Object.prototype) return [];
  return Object.entries(types).filter(([, value]) => value === true || value?.supported === true)
    .map(([value]) => value);
}
function validModelDraft() {
  return modelCatalog()?.status === 'ready'
    && draftModel()?.reasoning_efforts.some(item => item.value === modelDraft.effort)
    && (!modelDraft.thinking || thinkingOptions().includes(modelDraft.thinking));
}
function modelChoiceChanged() {
  return !savedModel.selection || ['provider', 'mode', 'model', 'effort', 'thinking']
    .some(key => (savedModel.selection[key] || '') !== (modelDraft[key] || ''));
}
function canUseSavedModel() { return modelSettingsReady && savedModel.selection && !modelChoiceChanged() && validModelDraft(); }

function isSupportedUnderstandingSelection(selection) {
  return selection?.provider === 'codex' && selection?.mode === 'subscription';
}

function canUseSupportedUnderstandingModel() {
  return canUseSavedModel() && isSupportedUnderstandingSelection(savedModel.selection);
}

function understandingPathLabel(selection) {
  if (selection?.provider === 'codex' && selection?.mode === 'subscription') return 'Codex ChatGPT 구독';
  if (selection?.provider === 'codex' && selection?.mode === 'api') return 'Codex API';
  if (selection?.provider === 'claude' && selection?.mode === 'api') return 'Claude API';
  return '선택한 모델 연결';
}

function updateUnderstandingReadiness(intent) {
  const target = $('#understanding-readiness');
  if (intent) {
    target.textContent = understandingProviderReady
      ? '앞서 보낸 동일한 Codex ChatGPT 구독 요청의 접수 여부만 확인합니다. 현재 입력과 자료를 새로 보내지 않습니다.'
      : '앞서 보낸 동일한 요청을 확인할 실행 연결이 준비되지 않았습니다. 현재 입력과 자료를 새로 보내지 않습니다.';
    return;
  }
  if (!modelSettingsReady) {
    target.textContent = '사용할 모델 설정을 확인하는 중입니다. 입력과 자료를 보내지 않습니다.';
    return;
  }
  if (!savedModel.selection) {
    target.textContent = '사용할 모델을 선택해 이 업무에 저장해 주세요. 모델을 저장하기 전에는 입력과 자료를 보내지 않습니다.';
    return;
  }
  if (modelChoiceChanged()) {
    const label = understandingPathLabel(modelDraft);
    target.textContent = isSupportedUnderstandingSelection(modelDraft)
      ? `${label} 모델 선택을 먼저 이 업무에 저장해 주세요. 저장 전에는 입력과 자료를 보내지 않습니다.`
      : `${label} 모델은 아직 저장되지 않았고 현재 업무 이해 실행 경로에도 연결되지 않았습니다. 입력과 자료를 보내지 않습니다.`;
    return;
  }
  const label = understandingPathLabel(savedModel.selection);
  if (!isSupportedUnderstandingSelection(savedModel.selection)) {
    target.textContent = `${label} 모델 선택은 저장됐지만 현재 업무 이해 실행 경로에는 아직 연결되지 않았습니다. 입력과 자료를 보내지 않습니다.`;
  } else if (!validModelDraft()) {
    target.textContent = `${label} 모델 선택은 저장됐지만 현재 모델 목록에서 사용할 수 있는지 확인되지 않았습니다. 입력과 자료를 보내지 않습니다.`;
  } else if (!understandingProviderReady) {
    target.textContent = `${label} 모델은 저장됐지만 이 인스턴스의 업무 이해 실행 연결이 준비되지 않았습니다. 입력과 자료를 보내지 않습니다.`;
  } else {
    target.textContent = `버튼을 누르면 이 저장본을 ${label} 연결로 보내 업무 이해 초안을 만듭니다. ChatGPT 구독 사용량이 소모될 수 있습니다.`;
  }
}

function modelSelectionStatus(state, text) {
  $('#model-selection-status').dataset.state = state;
  $('#model-selection-status').textContent = text;
}

function updateModelControls() {
  const busy = !ready || modelCatalogBusy || pending > 0;
  $('#model-settings').setAttribute('aria-busy', String(modelCatalogBusy));
  $('#model-connection').disabled = busy || !modelConnections.length;
  $('#refresh-model-catalog').disabled = !ready || modelCatalogBusy || !currentModelConnection();
  $('#model-choice').disabled = busy || modelCatalog()?.status !== 'ready';
  $('#model-effort').disabled = busy || !draftModel();
  $('#model-thinking').disabled = busy || !thinkingOptions().length;
  $('#save-model-selection').disabled = busy || composing || !modelSettingsReady || !hasContent() || !validModelDraft() || !modelChoiceChanged();
  $('#reload-model-selection').disabled = busy || composing;
}

function renderUsageLimits() {
  const connection = currentModelConnection();
  const apiMode = connection?.billing === 'api';
  $('#usage-api-fields').hidden = !apiMode;
  $('#usage-limits').dataset.mode = connection?.mode || '';
  const integer = id => Number($(id).value);
  const common = {
    provider_mode: connection?.mode || 'subscription',
    max_model_calls: integer('#usage-model-calls'),
    max_tool_calls: integer('#usage-tool-calls'),
    max_wall_seconds: integer('#usage-wall-seconds'),
    max_output_bytes: integer('#usage-output-bytes'),
  };
  const cap = Number($('#usage-api-cap').value);
  try {
    const policy = usagePolicyPayload(apiMode ? {
      ...common, currency: $('#usage-currency').value,
      max_api_microunits: Number.isFinite(cap) ? Math.round(cap * 1_000_000) : 0,
    } : common);
    $('#usage-limits-summary').textContent = `이번 요청 한도 · 모델 ${policy.max_model_calls}회 · 브라우저 미저장 초안`;
    $('#usage-status').textContent = apiMode
      ? `API 비용 한도 ${cap} ${policy.currency} · 이 브라우저의 미저장 초안이며 아직 저장되거나 적용되지 않습니다.`
      : '구독 한도는 이 브라우저의 미저장 초안입니다. 구독은 API 사용 금액으로 표시하지 않으며 아직 저장되거나 적용되지 않습니다.';
  } catch (error) {
    $('#usage-status').textContent = apiMode
      ? 'API 모드는 통화와 양수 비용 한도가 필요합니다. 이 값은 아직 저장되거나 적용되지 않습니다.'
      : `${error.message} 이 값은 아직 저장되거나 적용되지 않습니다.`;
  }
}

function renderModelSettings() {
  const catalog = modelCatalog();
  const models = catalog?.models || [];
  $('#model-settings').dataset.ready = String(modelSettingsReady);
  $('#model-settings').dataset.catalogStatus = catalog?.status || 'unqueried';
  const savedConnection = modelConnections.find(item => savedModel.selection
    && modelConnectionKey(item) === modelConnectionKey(savedModel.selection));
  $('#model-settings-summary').textContent = `사용할 모델 · ${savedConnection?.label || '연결 선택 안 됨'} · ${savedModel.selection?.display_name || savedModel.selection?.model || '모델 선택 안 됨'}`;
  const connectionSelect = $('#model-connection');
  const connectionSignature = JSON.stringify(modelConnections.map(item => [modelConnectionKey(item), item.label]));
  if (connectionSelect.dataset.options !== connectionSignature) {
    connectionSelect.dataset.options = connectionSignature;
    connectionSelect.replaceChildren();
    for (const connection of modelConnections) {
      const option = node('option', connection.label);
      option.value = modelConnectionKey(connection);
      connectionSelect.append(option);
    }
    if (!modelConnections.length) {
      const option = node('option', '지원되는 연결 정보를 확인하지 못했습니다.');
      option.value = '';
      connectionSelect.append(option);
    }
  }
  connectionSelect.value = currentModelConnection() ? modelConnectionKey() : '';
  const options = $('#model-choice'); options.replaceChildren();
  if (!modelDraft.model && models.length) {
    const initial = models.find(item => item.is_default) || models[0];
    modelDraft.model = initial.model; modelDraft.effort = initial.default_reasoning_effort;
  }
  if (!models.length || (modelDraft.model && !models.some(item => item.model === modelDraft.model))) {
    const absent = node('option', modelDraft.model ? `${savedModel.selection?.display_name || modelDraft.model} · 현재 목록 미확인` : '목록을 먼저 조회해 주세요');
    absent.value = modelDraft.model; absent.disabled = Boolean(modelDraft.model); options.append(absent);
  }
  for (const model of models) {
    const option = node('option', model.display_name); option.value = model.model; options.append(option);
  }
  options.value = modelDraft.model;
  const efforts = $('#model-effort'); efforts.replaceChildren();
  const supported = draftModel()?.reasoning_efforts || [];
  if (!supported.length || (modelDraft.effort && !supported.some(item => item.value === modelDraft.effort))) {
    const absent = node('option', modelDraft.effort ? `${modelDraft.effort} · 현재 목록 미확인` : '모델을 먼저 선택해 주세요');
    absent.value = modelDraft.effort; absent.disabled = Boolean(modelDraft.effort); efforts.append(absent);
  }
  for (const effort of supported) {
    const option = node('option', effort.label); option.value = effort.value; efforts.append(option);
  }
  efforts.value = modelDraft.effort;
  const thinking = $('#model-thinking'); thinking.replaceChildren();
  const automatic = node('option', '자동'); automatic.value = ''; thinking.append(automatic);
  for (const value of thinkingOptions()) {
    const option = node('option', value); option.value = value; thinking.append(option);
  }
  thinking.value = modelDraft.thinking;
  $('#model-catalog-message').textContent = catalog?.message || '목록 조회는 로그인이나 업무 실행을 시작하지 않습니다.';
  const selectedConnection = currentModelConnection();
  $('#model-billing-note').textContent = selectedConnection?.billing === 'subscription'
    ? 'Codex ChatGPT 구독 연결 경로입니다. 별도 API 사용 금액으로 표시하거나 자동 전환하지 않습니다.'
    : selectedConnection?.billing === 'api'
      ? `${selectedConnection.provider === 'codex' ? 'Codex' : 'Claude'} API 경로를 선택했습니다. API 키 연결은 아직 이 화면에 연결되지 않았고, 비용과 한도는 구독과 따로 관리합니다.`
      : '실제 제공자 연결 방식을 확인하지 못해 모델을 선택할 수 없습니다.';
  renderUsageLimits();
  if (modelSettingsReady && $('#model-selection-status').dataset.state !== 'error') {
    if (!savedModel.selection) modelSelectionStatus('empty', '선택을 저장하면 이 업무에서 사용할 모델로 보관됩니다.');
    else if (modelChoiceChanged()) modelSelectionStatus('unsaved', '아직 저장하지 않은 모델 선택입니다.');
    else if (!validModelDraft()) modelSelectionStatus('unavailable', '저장된 선택은 유지했습니다. 현재 목록에서 모델과 추론 강도를 다시 확인해 주세요.');
    else modelSelectionStatus('saved', '이 업무에 저장됨');
  }
  updateUnderstandingRevision();
  updateControls();
}

async function loadModelCatalog(refresh = false) {
  const { provider, mode } = modelDraft;
  const key = modelConnectionKey();
  const view = modelSettingsView;
  const read = ++modelCatalogRead;
  if (!currentModelConnection()) {
    modelCatalogs.set(key, { provider, mode, status: 'error', models: [], message: '지원되는 실제 연결 정보를 확인하지 못했습니다.' });
    renderModelSettings();
    return;
  }
  modelCatalogBusy = true; updateModelControls();
  $('#model-settings').dataset.catalogStatus = 'loading';
  $('#model-catalog-message').textContent = refresh ? '사용 가능한 모델을 조회하는 중…' : '저장된 모델 목록을 불러오는 중…';
  try {
    const catalog = await api(catalogURL(provider, mode, { refresh }), refresh ? { method: 'POST', body: {} } : {});
    if (catalog?.provider !== provider || catalog?.mode !== mode) throw new Error('선택한 연결 방식과 다른 모델 목록을 받았습니다.');
    if (view !== modelSettingsView || read !== modelCatalogRead || key !== modelConnectionKey()) return;
    modelCatalogs.set(key, catalog);
  } catch (error) {
    if (view !== modelSettingsView || read !== modelCatalogRead || key !== modelConnectionKey()) return;
    modelCatalogs.set(key, { provider, mode, status: 'error', models: [], message: `목록을 불러오지 못했습니다. ${error.message}` });
  } finally {
    if (view === modelSettingsView && read === modelCatalogRead) {
      modelCatalogBusy = false; renderModelSettings();
    }
  }
}

async function loadModelSettings() {
  const view = ++modelSettingsView;
  modelCatalogRead++;
  modelCatalogBusy = false;
  const workId = current?.id;
  modelSettingsReady = !workId;
  savedModel = { version: 0, selection: null };
  try {
    modelConnections = connectionOptions(
      providerRecords.filter(provider => Array.isArray(provider?.modes)),
    );
  }
  catch { modelConnections = []; }
  modelDraft = emptyModelDraft();
  modelSelectionStatus('loading', workId ? '저장된 모델을 불러오는 중…' : '사용할 모델을 선택해 주세요.');
  $('#reload-model-selection').hidden = true;
  renderModelSettings();
  if (workId) {
    try {
      const record = await api(`/api/works/${encodeURIComponent(workId)}/model-selection`);
      if (view !== modelSettingsView || current?.id !== workId) return;
      savedModel = record;
      if (record.selection) modelDraft = draftFromSelection(record.selection);
      modelSettingsReady = true;
    } catch (error) {
      if (view !== modelSettingsView) return;
      modelSelectionStatus('error', `저장된 모델을 읽지 못했습니다. ${error.message}`);
      $('#reload-model-selection').hidden = false;
      renderModelSettings(); return;
    }
  }
  await loadModelCatalog();
}

function modelDraftChanged() {
  modelSelectionStatus('unsaved', '아직 저장하지 않은 모델 선택입니다.');
  renderModelSettings();
}

async function saveSelectedModel() {
  if (!modelSettingsReady || !hasContent() || composing || pending || !validModelDraft() || !modelChoiceChanged()) return;
  const draft = {
    provider: modelDraft.provider, mode: modelDraft.mode, model: modelDraft.model,
    effort: modelDraft.effort, catalog_id: modelCatalog().catalog_id,
  };
  if (modelDraft.thinking) draft.thinking = modelDraft.thinking;
  const selection = modelSelectionPayload(draft);
  const expectedVersion = savedModel.version;
  await action(async () => {
    let savingSelection = false;
    try {
      const work = await flushText();
      if (!work) return;
      modelSelectionStatus('saving', '모델 선택을 저장하는 중…');
      savingSelection = true;
      const record = await api(`/api/works/${encodeURIComponent(work.id)}/model-selection`, { method: 'PUT', body: { expected_version: expectedVersion, selection } });
      savedModel = record;
      modelDraft = draftFromSelection(record.selection);
      modelSelectionStatus('saved', '이 업무에 저장됨');
      $('#reload-model-selection').hidden = true;
      renderModelSettings();
    } catch (error) {
      modelSelectionStatus('error', savingSelection && error.status === 409
        ? '다른 화면에서 모델 선택이 바뀌었습니다. 현재 선택은 그대로 두었습니다. 저장된 모델을 다시 불러와 확인해 주세요.'
        : `모델 선택을 저장하지 못했습니다. ${error.message}`);
      $('#reload-model-selection').hidden = false;
    }
  });
}

function recordsForCurrent() { return understandingRecords.get(current?.id) || []; }
function activeUnderstanding() { return recordsForCurrent().some(record => ['queued', 'running'].includes(record.status)); }
function selectedRecord() { return recordsForCurrent().find(record => record.id === selectedUnderstanding); }

function stopUnderstandingPolling() {
  clearTimeout(understandingTimer);
  understandingTimer = undefined;
  understandingRead++;
}

function resetUnderstanding() {
  stopUnderstandingPolling();
  understandingView++;
  understandingPolls = 0;
  selectedUnderstanding = '';
  renderedUnderstanding = '';
  const intent = understandingIntents.get(current?.id);
  setUnderstandingMessage(intent ? uncertainRequestMessage(intent) : '');
  $('#refresh-understanding').hidden = true;
  renderUnderstanding();
}

function uncertainRequestMessage(intent) {
  return `저장본 ${intent.revision} 요청의 접수 여부를 확인하지 못했습니다. ‘같은 요청 확인하기’는 같은 요청 번호로 확인하며 새 입력을 보내지 않습니다.`;
}

function setUnderstandingMessage(text, kind = 'request') {
  $('#understanding-message').textContent = text;
  $('#understanding-message').dataset.kind = text ? kind : '';
}

function clearTransientUnderstandingMessage() {
  if (!['read', 'poll', 'cancel'].includes($('#understanding-message').dataset.kind)) return;
  const intent = understandingIntents.get(current?.id);
  setUnderstandingMessage(intent ? uncertainRequestMessage(intent) : '');
}

function updateUnderstandingRevision() {
  const record = selectedRecord();
  const target = $('#understanding-record');
  if (!record || !target) return;
  const changedModel = modelSettingsReady && record.model_selection_version !== savedModel.version;
  const stale = record.revision !== current?.revision || unsaved() || changedModel;
  target.dataset.stale = String(stale);
  $('#understanding-revision').textContent = `저장본 ${record.revision} 기준 · ${changedModel ? '사용할 모델이 바뀌기 전의 결과입니다. 새 선택으로 자동 요청하지 않습니다.' : stale ? '현재 입력과 다른 이전 저장본의 결과입니다. 수정한 내용은 자동으로 보내지 않습니다.' : '현재 저장본의 요청입니다.'}`;
}

function evidenceList(evidence, sources) {
  const list = node('div', undefined, 'understanding-evidence');
  for (const ref of evidence || []) {
    const source = sources.find(item => item.source_id === ref.source_id);
    const quote = node('blockquote', ref.quote);
    quote.dataset.sourceId = ref.source_id;
    list.append(node('p', source?.name || '출처 미확인', 'evidence-source'), quote);
  }
  return list;
}

function readableFormat(mediaType) {
  const types = {
    'pdf': 'PDF', 'csv': 'CSV 표',
    'text/plain': '일반 텍스트', 'text/markdown': '마크다운 문서', 'application/pdf': 'PDF',
    'text/csv': 'CSV 표', 'image/png': 'PNG 이미지', 'image/jpeg': 'JPEG 이미지',
    'image/svg+xml': 'SVG 이미지', 'image/webp': 'WebP 이미지',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word 문서',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel 표',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PowerPoint 슬라이드',
    'unspecified': '형식 미정',
  };
  return types[mediaType.split(';')[0].trim().toLowerCase()] || `형식: ${mediaType}`;
}

function renderUnderstanding() {
  const records = recordsForCurrent();
  if (!records.some(record => record.id === selectedUnderstanding)) selectedUnderstanding = records.at(-1)?.id || '';
  const record = selectedRecord();
  const key = JSON.stringify(record || null);
  $('#understanding-panel').hidden = !records.length;
  setWorkStageView(Boolean(records.length));
  const history = $('#understanding-history');
  const historyKey = JSON.stringify(records.map(item => [item.id, item.status]));
  if (history.dataset.records !== historyKey) {
    history.dataset.records = historyKey;
    history.replaceChildren();
    for (const item of [...records].reverse()) {
      const option = node('option', `저장본 ${item.revision} · ${understandingLabels[item.status] || item.status}`);
      option.value = item.id; history.append(option);
    }
  }
  history.value = selectedUnderstanding;
  $('#understanding-history-label').hidden = records.length < 2;
  if (key !== renderedUnderstanding) {
    renderedUnderstanding = key;
    const content = $('#understanding-content');
    const focusedAction = content.contains(document.activeElement) ? document.activeElement.dataset.understandingAction : null;
    content.replaceChildren();
    if (record) {
      const section = node('article');
      section.id = 'understanding-record';
      section.dataset.requestId = record.id;
      section.dataset.status = record.status;
      section.dataset.reason = record.reason || '';
      const revision = node('p', '', 'understanding-revision'); revision.id = 'understanding-revision';
      const status = node('p', record.status === 'succeeded'
        ? '이해 초안입니다. 틀린 부분은 업무 설명에서 바로잡아 주세요.'
        : `${understandingLabels[record.status] || record.status} · ${record.message}`, 'understanding-status');
      status.setAttribute('role', 'status');
      section.append(revision, status);
      if (record.model_selection) section.append(node('p', `${record.model_selection.display_name || record.model_selection.model} · ${record.model_selection.effort}`, 'request-model-note'));
      if (record.status === 'failed' && ['subscription_required', 'provider_unavailable'].includes(record.reason)) {
        const connect = node('button', 'Codex 연결 살펴보기'); connect.type = 'button';
        connect.addEventListener('click', openConnections); section.append(connect);
      }
      if (['queued', 'running'].includes(record.status)) {
        const cancel = node('button', '업무 이해 취소'); cancel.type = 'button'; cancel.dataset.understandingAction = 'cancel';
        cancel.addEventListener('click', () => cancelUnderstanding(record)); section.append(cancel);
      }
      if (record.result) {
        const result = record.result;
        section.append(node('p', result.summary.text, 'understanding-summary'));
        const summaryEvidence = node('details', undefined, 'summary-evidence');
        summaryEvidence.append(node('summary', '원문 근거'), evidenceList(result.summary.evidence, record.sources));
        section.append(summaryEvidence);
        for (const [title, items, kind] of [['필요한 산출물', result.deliverables, 'deliverable'], ['지켜야 할 조건', result.constraints, 'constraint']]) {
          if (!items.length) continue;
          const group = node('section', undefined, 'understanding-group'); group.append(node('h3', title));
          for (const item of items) {
            const row = node('div', undefined, 'understanding-claim');
            if (kind === 'deliverable') {
              const format = node('p', readableFormat(item.media_type), 'file-meta');
              format.title = item.media_type;
              format.dataset.mediaType = item.media_type;
              row.append(node('h4', item.name), format, node('p', item.description));
            }
            else row.append(node('p', item.text));
            const details = node('details'); details.append(node('summary', '원문 근거'), evidenceList(item.evidence, record.sources));
            row.append(details); group.append(row);
          }
          section.append(group);
        }
        if (result.open_questions.length) {
          const questions = node('section', undefined, 'understanding-questions');
          questions.append(node('h3', '아직 중요한 빈칸'), node('p', '필요한 부분만 업무 설명에 더해 주세요.', 'section-note'));
          for (const question of result.open_questions) questions.append(node('h4', question.question), node('p', question.why_needed));
          section.append(questions);
        }
        if (result.assumptions.length) {
          const assumptions = node('details', undefined, 'understanding-assumptions'); assumptions.append(node('summary', '확인되지 않은 가정'));
          const list = node('ul'); for (const text of result.assumptions) list.append(node('li', text));
          assumptions.append(list); section.append(assumptions);
        }
        const correct = node('button', '원 입력에서 바로잡기'); correct.type = 'button'; correct.dataset.understandingAction = 'correct';
        correct.addEventListener('click', () => { input.focus(); input.scrollIntoView({ block: 'center' }); }); section.append(correct);
      }
      if (record.sources?.length) {
        const limits = node('details', undefined, 'understanding-sources'); limits.append(node('summary', '이 요청에서 사용한 자료와 읽기 한계'));
        for (const source of record.sources) limits.append(node('p', `${source.name} · ${readLabels[source.read_status] || '읽기 상태 미확인'}${source.read_note ? ` · ${source.read_note}` : ''}`));
        limits.append(node('p', '읽지 못한 파일 내용은 이 요청의 근거가 아닙니다. 인용 일치 확인은 내용의 정확성 검증과 다릅니다.')); section.append(limits);
      }
      content.append(section);
      if (focusedAction) (section.querySelector(`[data-understanding-action="${focusedAction}"]`) || $('#prepare-design')).focus({ preventScroll: true });
    }
  }
  updateUnderstandingRevision();
  updateControls();
}

async function loadUnderstandings() {
  const workId = current?.id;
  if (!workId) { renderUnderstanding(); return; }
  const view = understandingView;
  const read = ++understandingRead;
  try {
    const records = await api(`/api/works/${encodeURIComponent(workId)}/understanding-requests`);
    if (view !== understandingView || read !== understandingRead || current?.id !== workId) return;
    understandingRecords.set(workId, records);
    clearTransientUnderstandingMessage();
    $('#refresh-understanding').hidden = true;
    renderUnderstanding();
    scheduleUnderstandingPoll();
  } catch {
    if (view !== understandingView || read !== understandingRead) return;
    $('#understanding-panel').hidden = false;
    setWorkStageView(true);
    $('#refresh-understanding').hidden = false;
    setUnderstandingMessage('이해 요청 기록을 읽지 못했습니다. 자동으로 다시 보내지 않습니다. ‘결과 다시 확인’으로 저장된 기록만 불러올 수 있습니다.', 'read');
  }
}

function scheduleUnderstandingPoll() {
  if (understandingTimer || document.hidden || !activeUnderstanding()) return;
  if (understandingPolls >= 120) {
    setUnderstandingMessage('응답이 계속 대기 중입니다. 자동 확인은 멈췄습니다. 저장된 결과를 다시 확인할 수 있습니다.', 'poll');
    $('#refresh-understanding').hidden = false;
    return;
  }
  const view = understandingView;
  understandingTimer = setTimeout(() => {
    understandingTimer = undefined;
    if (view !== understandingView || document.hidden) return;
    understandingPolls++;
    void loadUnderstandings();
  }, 1500);
}

function acceptUnderstanding(record) {
  const records = understandingRecords.get(record.work_id) || [];
  understandingRecords.set(record.work_id, records.some(item => item.id === record.id)
    ? records.map(item => item.id === record.id ? record : item) : [...records, record]);
  if (current?.id !== record.work_id) return;
  stopUnderstandingPolling();
  clearTransientUnderstandingMessage();
  if (!activeUnderstanding()) $('#refresh-understanding').hidden = true;
  selectedUnderstanding = record.id;
  renderUnderstanding();
  scheduleUnderstandingPoll();
}

async function requestUnderstanding() {
  let intent = understandingIntents.get(current?.id);
  if (!understandingProviderReady || !hasContent() || composing || pending || understandingBusy.has(current?.id)
      || (!intent && (activeUnderstanding() || !canUseSupportedUnderstandingModel()))) return;
  const requestView = understandingView;
  const requestInputVersion = inputVersion;
  const clickedAction = document.activeElement === $('#prepare-design');
  if (!intent) {
    // Freeze only the short save/snapshot boundary, never the model's response time.
    await action(async () => {
      const work = await flushText();
      if (work) intent = { workId: work.id, revision: work.revision, model_selection_version: savedModel.version, request_key: crypto.randomUUID() };
    }, { freeze: true });
    if (!intent) return;
    understandingIntents.set(intent.workId, intent);
  }
  const workId = intent.workId;
  understandingBusy.add(workId);
  stopUnderstandingPolling();
  setUnderstandingMessage(`저장본 ${intent.revision}을 보내는 중…`);
  updateControls();
  try {
    const record = await api(`/api/works/${encodeURIComponent(workId)}/understanding-requests`, {
      method: 'POST', body: { revision: intent.revision, model_selection_version: intent.model_selection_version, request_key: intent.request_key, allow_transfer: true },
    });
    understandingIntents.delete(workId);
    if (current?.id === workId) setUnderstandingMessage('');
    understandingPolls = 0;
    const reveal = clickedAction && requestView === understandingView && current?.id === workId
      && requestInputVersion === inputVersion && !document.hidden
      && (document.activeElement === document.body || document.activeElement === $('#prepare-design'));
    acceptUnderstanding(record);
    if (reveal) $('#understanding-panel').scrollIntoView({ block: 'nearest' });
  } catch (error) {
    // HTTP rejection is known. A lost response is not: explicit retry reuses the
    // same revision/key, even if the user has since edited the original input.
    if (error.status) understandingIntents.delete(workId);
    if (current?.id === workId) setUnderstandingMessage(error.status ? error.message : uncertainRequestMessage(intent));
  } finally {
    understandingBusy.delete(workId);
    updateControls();
  }
}

async function cancelUnderstanding(record) {
  const button = $('#understanding-record [data-understanding-action="cancel"]');
  if (button) button.disabled = true;
  stopUnderstandingPolling();
  try {
    const result = await api(`/api/works/${encodeURIComponent(record.work_id)}/understanding-requests/${encodeURIComponent(record.id)}/cancel`, { method: 'POST', body: {} });
    acceptUnderstanding(result);
  } catch (error) {
    if (current?.id === record.work_id) {
      setUnderstandingMessage(`취소를 확인하지 못했습니다. ${error.message}`, 'cancel');
      if (button?.isConnected) button.disabled = false;
      scheduleUnderstandingPoll();
    }
  }
}

function changed() {
  inputVersion++;
  clearTimeout(timer);
  renderTransfer();
  updateUnderstandingRevision();
  if (composing) { setStatus('unsaved', '글자 입력 중 · 입력을 마치면 저장합니다'); return; }
  $('#page-message').textContent = '';
  if (unsaved()) {
    setStatus('unsaved', '아직 저장되지 않은 내용이 있습니다');
    timer = setTimeout(() => action(() => flushText()), 650);
  } else setStatus(current ? 'saved' : 'empty', current ? `DeepTwin 인스턴스에 저장됨 · 저장본 ${current.revision}` : '내용을 입력하면 이 DeepTwin 인스턴스에 저장됩니다');
  updateControls();
  speechInput?.flushPending();
}

async function bootstrap() {
  $('#retry-load').hidden = true;
  try {
    if (!csrf) await establishBrowserSession();
    const result = await api('/api/bootstrap');
    works = result.works;
    understandingProviderReady = result.capabilities?.understanding_provider_ready === true;
    providerRecords = result.providers || [];
    let id;
    try { id = localStorage.getItem(selectedKey); } catch { /* Optional preference only. */ }
    current = works.find(work => work.id === id) || null;
    savedText = current?.text || '';
    input.value = savedText;
    app.dataset.workId = current?.id || '';
    renderPicker(); renderFiles(); renderTransfer();
    ready = true;
    input.disabled = false;
    app.dataset.ready = 'true';
    setStatus(current ? 'saved' : 'empty', current ? `DeepTwin 인스턴스에 저장됨 · 저장본 ${current.revision}` : '내용을 입력하면 이 DeepTwin 인스턴스에 저장됩니다');
    $('#page-message').textContent = '';
    updateControls();
    void syncConversation(current);
    void loadUnderstandings();
    void loadModelSettings();
    void speechInput.load();
  } catch (error) {
    setStatus('error', '저장한 업무를 불러오지 못했습니다');
    $('#page-message').textContent = error.message;
    $('#retry-load').hidden = false;
  }
}

conversation = createConversationController({ request: api, onChange: renderConversation });
renderConversation(conversation.snapshot());

speechInput = createSpeechInput({
  api, getWork: () => current, canStart: () => ready && !pending && !composing,
  saveWork: async () => {
    let work;
    await action(async () => { work = await flushText({ allowBlank: true }); });
    return work;
  },
  appendText: (text, workId) => {
    if (composing || current?.id !== workId || input.readOnly) return false;
    const cursor = input.selectionEnd;
    const before = input.value.slice(0, cursor), after = input.value.slice(cursor);
    const inserted = `${before && !/\s$/.test(before) ? ' ' : ''}${text}${after && !/^\s/.test(after) ? ' ' : ''}`;
    if (input.value.length + inserted.length > input.maxLength) return false;
    input.setRangeText(inserted, cursor, cursor, 'end');
    input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: inserted }));
    return true;
  },
});
input.addEventListener('input', changed);
input.addEventListener('compositionstart', () => { composing = true; clearTimeout(timer); updateControls(); });
input.addEventListener('compositionend', () => { composing = false; changed(); });
$('#save-work').addEventListener('click', () => action(() => flushText()));
$('#new-work').addEventListener('click', () => {
  speechInput.cancel();
  beginWorkSwitch();
  action(() => chooseWork(''), { freeze: true });
});
picker.addEventListener('change', () => {
  speechInput.cancel();
  const id = picker.value;
  beginWorkSwitch();
  action(() => chooseWork(id), { freeze: true }).finally(renderPicker);
});
filesInput.addEventListener('change', () => {
  const files = [...filesInput.files];
  filesInput.value = '';
  if (files.length) action(() => uploadFiles(files));
});
$('#prepare-design').addEventListener('click', requestUnderstanding);
$('#refresh-model-catalog').addEventListener('click', () => loadModelCatalog(true));
$('#model-connection').addEventListener('change', event => {
  const selected = modelConnections.find(item => modelConnectionKey(item) === event.target.value);
  if (!selected) return;
  modelDraft = { provider: selected.provider, mode: selected.mode, model: '', effort: '', thinking: '' };
  modelDraftChanged(); void loadModelCatalog();
});
$('#model-choice').addEventListener('change', event => {
  modelDraft.model = event.target.value;
  modelDraft.effort = draftModel()?.default_reasoning_effort || '';
  modelDraft.thinking = '';
  modelDraftChanged();
});
$('#model-effort').addEventListener('change', event => { modelDraft.effort = event.target.value; modelDraftChanged(); });
$('#model-thinking').addEventListener('change', event => { modelDraft.thinking = event.target.value; modelDraftChanged(); });
for (const selector of [
  '#usage-model-calls', '#usage-tool-calls', '#usage-wall-seconds',
  '#usage-output-bytes', '#usage-currency', '#usage-api-cap',
]) $(selector).addEventListener('input', renderUsageLimits);
$('#save-model-selection').addEventListener('click', saveSelectedModel);
$('#reload-model-selection').addEventListener('click', loadModelSettings);
$('#understanding-history').addEventListener('change', event => { selectedUnderstanding = event.target.value; renderUnderstanding(); });
$('#refresh-understanding').addEventListener('click', () => { understandingPolls = 0; void loadUnderstandings(); });
$('#open-connections').addEventListener('click', openConnections);
$('#retry-load').addEventListener('click', bootstrap);
$('#chat-draft').addEventListener('input', event => conversation.setDraft(event.target.value));
$('#chat-form').addEventListener('submit', event => {
  event.preventDefault();
  void conversation.send().catch(() => {});
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden) { speechInput.cancel('다른 화면으로 이동해 마이크를 껐습니다. 이미 넣은 글은 남아 있습니다.'); stopConnectionPolling(); stopUnderstandingPolling(); }
  else { scheduleConnectionPoll(); scheduleUnderstandingPoll(); }
});
window.addEventListener('pagehide', () => { speechInput.cancel(); stopConnectionPolling(); stopUnderstandingPolling(); });
window.addEventListener('beforeunload', event => { if (unsaved() || pending) { event.preventDefault(); event.returnValue = ''; } });
bootstrap();
