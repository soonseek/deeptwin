// Settings: the preview shell's connection/usage payloads (below) and, for the supported
// server, the settings page's own sub-navigation (T073, UX-AC08; settings.html, booted by
// settings-page.mjs). The page holds every operations section — account and session, model
// connections (the Claude API key and the credential gateway's API credentials with their
// transport qualification), run budgets, backup and retention, update guidance, extensions
// and browser grants — one panel at a time behind this list. Each entry is a plain in-page
// link with no prerequisite and no order; none is a required final step (export is offered,
// never required). With a session an entry may add one line of the server's own state
// (backup worker, retention eligibility). All server text reaches the DOM through
// textContent only.

import { completionGate } from './records.mjs';

export const SETTINGS_MOUNT_ID = 'settings-hub';
export const SETTINGS_STATUS_ID = 'session-status';
// the one page outside the app shell that still carries a static header link to settings;
// every page inside the shell reaches it from the shell's navigation (ui-shell.mjs)
export const SETTINGS_LINKED_PAGES = Object.freeze(['start.html']);

export const SETTINGS_ENTRIES = Object.freeze([
  Object.freeze({ id: 'account', label: '계정과 세션', href: '#settings-account', panel: 'settings-account' }),
  Object.freeze({ id: 'models', label: '모델 연결', href: '#settings-models', panel: 'settings-models' }),
  Object.freeze({ id: 'budgets', label: '실행 한도', href: '#settings-budgets', panel: 'settings-budgets' }),
  Object.freeze({ id: 'backup', label: '백업·보존', href: '#settings-backup', panel: 'settings-backup' }),
  Object.freeze({ id: 'update', label: '업데이트·복구', href: '#settings-update', panel: 'settings-update' }),
  Object.freeze({ id: 'extensions', label: '확장', href: '#settings-extensions', panel: 'settings-extensions' }),
  Object.freeze({ id: 'grants', label: '브라우저 권한', href: '#settings-grants', panel: 'settings-grants' }),
]);

export const HUB_MESSAGES = Object.freeze({
  noFinalStep: '내보내기와 백업은 선택 사항입니다. 어떤 작업도 마지막에 내보내기를 거치지 않아도 끝납니다.',
  unauthenticated: '소유자 세션이 없습니다. 시작 화면(./)에서 로그인하면 각 항목의 현재 상태도 보입니다. 아래 항목은 언제든 열 수 있습니다.',
  authenticated: '브라우저 세션이 연결되어 있습니다.',
  failed: '설정 상태를 불러오지 못했습니다.',
});

const WORKER_LINES = Object.freeze({
  ready: '백업 워커 연결됨', not_configured: '백업 워커 없음(백업을 만들 수 없음)',
  key_unavailable: '백업 키 볼륨 없음', unreachable: '백업 워커에 연결하지 못함',
});

// every entry is available everywhere and none is required: the list never sequences them
export function settingsHub() {
  const gate = completionGate({ exported: false });
  return Object.freeze(SETTINGS_ENTRIES.map(entry => Object.freeze({
    ...entry, available: 'everywhere', required: false, exportRequired: gate.exportRequired,
  })));
}

export function hubStateLines({ backups, retention } = {}) {
  const lines = {};
  if (backups && typeof backups === 'object') {
    const made = Array.isArray(backups.backups) ? backups.backups.length : 0;
    lines.backup = `${WORKER_LINES[backups.worker] ?? WORKER_LINES.unreachable} · 만든 백업 ${made}개`;
  }
  if (retention && typeof retention === 'object' && Array.isArray(retention.items)) {
    const eligible = retention.items.filter(item => item?.eligible === true).length;
    lines.retention = `자동 삭제 없음 · 지금 정리할 수 있는 항목 ${eligible}개`;
  }
  return lines;
}

// which state lines each entry shows: backup and retention share the one 백업·보존 panel
const ENTRY_LINES = Object.freeze({ backup: ['backup', 'retention'] });

export function renderSettingsHub({ root, document, lines = {}, current = null }) {
  if (typeof root?.replaceChildren !== 'function') throw new TypeError('a hub mount is required');
  const element = (tag, text, attributes = {}) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  };
  const list = element('ul', undefined, { class: 'settings-entries' });
  for (const entry of settingsHub()) {
    const row = element('li', undefined, { 'data-entry': entry.id, 'data-required': 'false' });
    const link = element('a', entry.label, { href: entry.href, 'data-panel': entry.panel });
    if (entry.panel === current) link.setAttribute('aria-current', 'true');
    row.append(link);
    for (const key of ENTRY_LINES[entry.id] ?? []) {
      if (typeof lines[key] === 'string') row.append(element('p', lines[key], { class: 'settings-state' }));
    }
    list.append(row);
  }
  root.replaceChildren(list, element('p', HUB_MESSAGES.noFinalStep, { class: 'settings-no-final-step' }));
  return list;
}

const CONNECTIONS = new Map([
  ['codex:subscription', { provider: 'codex', mode: 'subscription' }],
  ['claude:api', { provider: 'claude', mode: 'api' }],
  ['codex:api', { provider: 'codex', mode: 'api' }],
]);
const CONNECTION_ORDER = [...CONNECTIONS.keys()];
const SHORT = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,299}$/;
const SELECTION_KEYS = new Set(['provider', 'mode', 'model', 'effort', 'catalog_id']);
const OPTIONAL_SELECTION_KEYS = new Set(['thinking']);
const USAGE_KEYS = new Set([
  'provider_mode', 'max_model_calls', 'max_tool_calls', 'max_wall_seconds',
  'max_output_bytes',
]);
const OPTIONAL_USAGE_KEYS = new Set(['currency', 'max_api_microunits']);
const MIXED_USAGE_KEYS = new Set(['aggregate', 'api_lanes']);
const AGGREGATE_USAGE_KEYS = new Set([
  'max_model_calls', 'max_tool_calls', 'max_wall_seconds', 'max_output_bytes',
]);
const API_LANE_KEYS = new Set([
  'provider', 'mode', 'binding_id', 'currency', 'max_api_microunits',
]);

function exactKeys(value, required, optional = new Set()) {
  if (!value || Object.getPrototypeOf(value) !== Object.prototype) return false;
  const keys = new Set(Object.keys(value));
  return [...required].every(key => keys.has(key))
    && [...keys].every(key => required.has(key) || optional.has(key));
}

function connection(provider, mode) {
  if (typeof provider !== 'string' || typeof mode !== 'string') throw new TypeError('연결 경로를 확인해 주세요.');
  const result = CONNECTIONS.get(`${provider}:${mode}`);
  if (!result) throw new RangeError('지원하지 않는 모델 연결 경로입니다.');
  return result;
}

export function connectionOptions(providers) {
  if (!Array.isArray(providers) || providers.length > 20) throw new TypeError('제공자 목록을 확인하지 못했습니다.');
  const discovered = new Map();
  for (const provider of providers) {
    if (!provider || typeof provider !== 'object' || typeof provider.id !== 'string' || !Array.isArray(provider.modes)) {
      throw new TypeError('제공자 연결 정보가 올바르지 않습니다.');
    }
    for (const mode of provider.modes) {
      if (!mode || typeof mode !== 'object') throw new TypeError('제공자 연결 방식이 올바르지 않습니다.');
      const key = `${provider.id}:${mode.id}`;
      if (!CONNECTIONS.has(key)) continue;
      if (discovered.has(key)) throw new TypeError('제공자 연결 방식이 중복되었습니다.');
      if (!['api', 'subscription'].includes(mode.billing)
          || !['api_key', 'chatgpt'].includes(mode.auth_mode)
          || typeof mode.label !== 'string' || !mode.label || mode.label.length > 100) {
        throw new TypeError('제공자 연결 방식의 출처 정보가 올바르지 않습니다.');
      }
      if ((mode.id === 'subscription') !== (mode.billing === 'subscription')
          || (mode.id === 'subscription') !== (mode.auth_mode === 'chatgpt')) {
        throw new TypeError('인증 방식과 과금 경로가 일치하지 않습니다.');
      }
      discovered.set(key, {
        provider: provider.id,
        mode: mode.id,
        label: `${provider.id === 'codex' ? 'Codex' : 'Claude'} · ${mode.label}`,
        billing: mode.billing,
        auth_mode: mode.auth_mode,
        is_default: provider.default_mode === mode.id,
      });
    }
  }
  return CONNECTION_ORDER.flatMap(key => discovered.has(key) ? [discovered.get(key)] : []);
}

export function catalogURL(provider, mode, { refresh = false } = {}) {
  connection(provider, mode);
  if (typeof refresh !== 'boolean') throw new TypeError('모델 목록 동작을 확인해 주세요.');
  return `/api/model-catalogs/${provider}${refresh ? '/refresh' : ''}?mode=${mode}`;
}

export function modelSelectionPayload(value) {
  if (!exactKeys(value, SELECTION_KEYS, OPTIONAL_SELECTION_KEYS)) throw new TypeError('모델 선택 항목을 확인해 주세요.');
  connection(value.provider, value.mode);
  for (const key of ['model', 'catalog_id']) {
    if (typeof value[key] !== 'string' || !SHORT.test(value[key])) throw new TypeError('모델 또는 목록 식별자를 확인해 주세요.');
  }
  for (const key of ['effort', 'thinking']) {
    if (value[key] !== undefined && value[key] !== null
        && (typeof value[key] !== 'string' || !SHORT.test(value[key]))) {
      throw new TypeError('모델 실행 설정을 확인해 주세요.');
    }
  }
  const result = {
    provider: value.provider,
    mode: value.mode,
    model: value.model,
    effort: value.effort,
    catalog_id: value.catalog_id,
  };
  if (Object.hasOwn(value, 'thinking')) result.thinking = value.thinking;
  return result;
}

function positiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0;
}

export function usagePolicyPayload(value) {
  if (!exactKeys(value, USAGE_KEYS, OPTIONAL_USAGE_KEYS)) throw new TypeError('실행 한도 항목을 확인해 주세요.');
  if (!['subscription', 'api'].includes(value.provider_mode)
      || !['max_model_calls', 'max_tool_calls', 'max_wall_seconds', 'max_output_bytes']
        .every(key => positiveInteger(value[key]))) {
    throw new TypeError('모든 실행 한도는 유한한 양의 정수여야 합니다.');
  }
  const result = {
    provider_mode: value.provider_mode,
    max_model_calls: value.max_model_calls,
    max_tool_calls: value.max_tool_calls,
    max_wall_seconds: value.max_wall_seconds,
    max_output_bytes: value.max_output_bytes,
    currency: value.currency ?? null,
    max_api_microunits: value.max_api_microunits ?? null,
  };
  if (result.provider_mode === 'api') {
    if (typeof result.currency !== 'string' || !/^[A-Z]{3}$/.test(result.currency)
        || !positiveInteger(result.max_api_microunits)) {
      throw new TypeError('API 사용에는 통화와 양수 비용 한도가 필요합니다.');
    }
  } else if (result.currency !== null || result.max_api_microunits !== null) {
    throw new TypeError('구독 한도는 API 청구액으로 표시할 수 없습니다.');
  }
  return result;
}

export function mixedUsagePolicyPayload(value) {
  if (!exactKeys(value, MIXED_USAGE_KEYS)
      || !exactKeys(value.aggregate, AGGREGATE_USAGE_KEYS)
      || ![...AGGREGATE_USAGE_KEYS].every(key => positiveInteger(value.aggregate[key]))
      || !Array.isArray(value.api_lanes) || value.api_lanes.length > 20) {
    throw new TypeError('전체 실행 한도와 API 연결별 한도를 확인해 주세요.');
  }
  const seen = new Set();
  const apiLanes = value.api_lanes.map(lane => {
    if (!exactKeys(lane, API_LANE_KEYS)) throw new TypeError('API 연결별 비용 한도를 확인해 주세요.');
    connection(lane.provider, lane.mode);
    const identity = `${lane.provider}:${lane.mode}:${lane.binding_id}`;
    if (lane.mode !== 'api' || !SHORT.test(lane.binding_id)
        || typeof lane.currency !== 'string' || !/^[A-Z]{3}$/.test(lane.currency)
        || !positiveInteger(lane.max_api_microunits) || seen.has(identity)) {
      throw new TypeError('API 연결별 비용 한도를 확인해 주세요.');
    }
    seen.add(identity);
    return {
      provider: lane.provider, mode: lane.mode, binding_id: lane.binding_id,
      currency: lane.currency, max_api_microunits: lane.max_api_microunits,
    };
  });
  apiLanes.sort((a, b) => `${a.provider}:${a.mode}:${a.binding_id}`.localeCompare(`${b.provider}:${b.mode}:${b.binding_id}`));
  return { aggregate: { ...value.aggregate }, api_lanes: apiLanes };
}
