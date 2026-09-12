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
