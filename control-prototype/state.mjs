import { ARTIFACTS, RUNS, DESIGNS, REVISED_DESIGN, CASE, ROUNDS, LOGS } from './fixtures.mjs';

export const KEY = 'deeptwin:control-ui:v1';

const AREAS = new Set(['design', 'run', 'growth']);
const MODES = new Set(['workspace', 'conversation', 'graph']);
const FOCUSES = new Set(['transfer', 'approval', 'memory', 'evaluation']);
const OVERLAYS = new Set(['connection', 'logs', 'audit', 'approval', 'artifact']);
const DESIGN_IDS = new Set([...DESIGNS.map(design => design.id), REVISED_DESIGN.id]);
const ROUND_IDS = new Set(ROUNDS.map(round => round.id));
const DIFFERENCE_IDS = new Set(CASE.differences.map(difference => difference.id));
const LOG_IDS = new Set(LOGS.map(log => log.id));
const STATE_FIELDS = [
  'version', 'area', 'mode', 'run', 'targets', 'design', 'focus', 'round', 'pairs', 'sample',
  'difference', 'drafts', 'notes', 'workText', 'designText', 'overlay', 'records', 'redact',
];
const TARGET_FIELDS = ['node', 'attempt', 'artifact', 'scope'];
const MAX_TEXT = 20_000;
const MAX_RAW = 2_000_000;

const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const exactFields = (object, fields) => isObject(object)
  && Object.keys(object).length === fields.length
  && fields.every(field => own(object, field));
const boundedString = value => typeof value === 'string' && value.length <= MAX_TEXT;
const sameJSON = (left, right) => JSON.stringify(left) === JSON.stringify(right);

function attemptFor(runId, attemptId) {
  return own(RUNS, runId)
    ? RUNS[runId].attempts.find(attempt => attempt.id === attemptId) ?? null
    : null;
}

function firstTarget(run) {
  const preferred = run.attempts.find(attempt => attempt.outputs.includes(CASE.original))
    ?? run.attempts.find(attempt => attempt.outputs.length > 0)
    ?? run.attempts[0];
  return {
    node: preferred?.node ?? run.nodes[0]?.id ?? null,
    attempt: preferred?.id ?? null,
    artifact: preferred?.outputs[0] ?? null,
    scope: { kind: 'whole' },
  };
}

function startingSelection() {
  for (const run of Object.values(RUNS)) {
    const attempt = run.attempts.find(item => item.outputs.includes(CASE.original));
    if (attempt) return { run: run.id, attempt };
  }
  const run = Object.values(RUNS)[0];
  return { run: run.id, attempt: run.attempts[0] };
}

export function createState() {
  const starting = startingSelection();
  const target = {
    node: starting.attempt.node,
    attempt: starting.attempt.id,
    artifact: starting.attempt.outputs[0],
    scope: { kind: 'whole' },
  };
  return {
    version: 1,
    area: 'run',
    mode: 'graph',
    run: starting.run,
    targets: { [starting.run]: target },
    design: DESIGNS[0].id,
    focus: 'transfer',
    round: ROUNDS[0].id,
    pairs: {},
    sample: false,
    difference: CASE.differences[0].id,
    drafts: {},
    notes: {},
    workText: '',
    designText: '',
    overlay: null,
    records: [],
    redact: true,
  };
}

export function context(state) {
  return { run: state.run, ...state.targets[state.run] };
}

export function draftKey(state) {
  const selected = context(state);
  const attempt = attemptFor(selected.run, selected.attempt);
  return JSON.stringify([
    selected.run,
    selected.attempt,
    attempt?.inputs ?? [],
    selected.artifact,
    selected.scope,
  ]);
}

export function noteKey(state) {
  const runContext = context(state);
  const selection = state.area === 'design'
    ? state.design
    : state.area === 'growth'
      ? [state.sample, state.difference, state.round]
      : runContext.attempt === null
        ? JSON.stringify([draftKey(state), runContext.node])
        : draftKey(state);
  return JSON.stringify([state.area, selection]);
}

const replaceTarget = (state, run, target) => ({
  ...state,
  run,
  targets: { ...state.targets, [run]: target },
});

function selectedRound(state) {
  return ROUNDS.find(round => round.id === state.round);
}

export function transition(state, action) {
  if (!isObject(action) || typeof action.type !== 'string') return state;
  switch (action.type) {
    case 'area':
      return AREAS.has(action.value) ? { ...state, area: action.value } : state;
    case 'mode':
      return MODES.has(action.value) ? { ...state, mode: action.value } : state;
    case 'run':
      if (!own(RUNS, action.value)) return state;
      return own(state.targets, action.value)
        ? { ...state, run: action.value }
        : replaceTarget(state, action.value, firstTarget(RUNS[action.value]));
    case 'attempt': { const runId = action.run ?? state.run;
      const attempt = attemptFor(runId, action.value);
      if (!attempt) return state;
      return replaceTarget(state, runId, {
        node: attempt.node,
        attempt: attempt.id,
        artifact: attempt.outputs[0] ?? null,
        scope: { kind: 'whole' },
      });
    }
    case 'node': { const run = RUNS[state.run];
      if (!run.nodes.some(node => node.id === action.value)) return state;
      const attempts = run.attempts.filter(attempt => attempt.node === action.value);
      const attempt = attempts.at(-1) ?? null;
      return replaceTarget(state, state.run, {
        node: action.value,
        attempt: attempt?.id ?? null,
        artifact: attempt?.outputs[0] ?? null,
        scope: { kind: 'whole' },
      });
    }
    case 'artifact': { const selected = context(state);
      const attempt = attemptFor(selected.run, selected.attempt);
      if (!attempt || ![...attempt.inputs, ...attempt.outputs].includes(action.value)) return state;
      const { run: ignored, ...target } = selected;
      return replaceTarget(state, state.run, { ...target, artifact: action.value, scope: { kind: 'whole' } });
    }
    case 'scope': { const selected = context(state);
      if (!validScope(action.value, selected.artifact)) return state;
      const { run: ignored, ...target } = selected;
      return replaceTarget(state, state.run, { ...target, scope: { ...action.value } });
    }
    case 'draft':
      if (!context(state).artifact || !boundedString(action.value)) return state;
      return { ...state, drafts: { ...state.drafts, [draftKey(state)]: action.value }, sample: false };
    case 'note':
      return boundedString(action.value)
        ? { ...state, notes: { ...state.notes, [noteKey(state)]: action.value } }
        : state;
    case 'workText':
      return boundedString(action.value) ? { ...state, workText: action.value } : state;
    case 'designText':
      return boundedString(action.value) ? { ...state, designText: action.value } : state;
    case 'design':
      return DESIGN_IDS.has(action.value) ? { ...state, design: action.value } : state;
    case 'focus':
      return FOCUSES.has(action.value) ? { ...state, focus: action.value } : state;
    case 'round':
      return ROUND_IDS.has(action.value) ? { ...state, round: action.value } : state;
    case 'pair': { const round = selectedRound(state);
      if (!round || !['baseline', 'candidate'].includes(action.side)) return state;
      const runId = action.side === 'baseline' ? round.baselineRun : round.candidateRun;
      if (!validPairValue(runId, action.value)) return state;
      return { ...state, pairs: { ...state.pairs, [`${round.id}:${action.side}`]: action.value } };
    }
    case 'sample':
      return typeof action.value === 'boolean' ? { ...state, sample: action.value } : state;
    case 'difference':
      return DIFFERENCE_IDS.has(action.value) ? { ...state, difference: action.value } : state;
    case 'overlay':
      return OVERLAYS.has(action.value) ? { ...state, overlay: action.value } : state;
    case 'close':
      return { ...state, overlay: null };
    case 'record':
      if (!LOG_IDS.has(action.value)) return state;
      return { ...state, records: state.records.includes(action.value)
        ? state.records.filter(id => id !== action.value)
        : [...state.records, action.value] };
    case 'redact':
      return typeof action.value === 'boolean' ? { ...state, redact: action.value } : state;
    default:
      return state;
  }
}

function validScope(scope, artifactId) {
  if (!exactFields(scope, scope?.kind === 'whole' ? ['kind']
    : scope?.kind === 'region' ? ['kind', 'id']
      : scope?.kind === 'text' ? ['kind', 'start', 'end'] : [])) return false;
  const artifact = ARTIFACTS[artifactId];
  if (!artifact) return false;
  if (scope.kind === 'whole') return true;
  if (scope.kind === 'region') return typeof scope.id === 'string'
    && artifact.regions.some(region => region.id === scope.id);
  return artifact.type === 'text'
    && Number.isInteger(scope.start) && Number.isInteger(scope.end)
    && scope.start >= 0 && scope.end > scope.start && scope.end <= artifact.body.length;
}

function validTarget(runId, target) {
  if (!exactFields(target, TARGET_FIELDS)) return false;
  const run = RUNS[runId];
  if (!run || !run.nodes.some(node => node.id === target.node)) return false;
  if (target.attempt === null) return target.artifact === null
    && !run.attempts.some(attempt => attempt.node === target.node)
    && sameJSON(target.scope, { kind: 'whole' });
  const attempt = attemptFor(runId, target.attempt);
  if (!attempt || attempt.node !== target.node) return false;
  const allowed = [...attempt.inputs, ...attempt.outputs];
  if (target.artifact === null) return attempt.outputs.length === 0 && sameJSON(target.scope, { kind: 'whole' });
  return allowed.includes(target.artifact) && validScope(target.scope, target.artifact);
}

function validPairValue(runId, value) {
  if (typeof value !== 'string') return false;
  const run = RUNS[runId];
  if (value.startsWith('@')) return run.nodes.some(node => node.id === value.slice(1));
  return run.attempts.some(attempt => attempt.id === value);
}

function parseJSON(value) {
  try { return JSON.parse(value); } catch { return null; }
}

function validRunContextKey(key, requireArtifact) {
  if (typeof key !== 'string' || key.length > MAX_TEXT) return false;
  const parsed = parseJSON(key);
  if (!Array.isArray(parsed) || parsed.length !== 5 || JSON.stringify(parsed) !== key) return false;
  const [runId, attemptId, inputs, artifactId, scope] = parsed;
  if (!own(RUNS, runId)) return false;
  if (attemptId === null) return !requireArtifact && sameJSON(inputs, []) && artifactId === null
    && sameJSON(scope, { kind: 'whole' });
  const attempt = attemptFor(runId, attemptId);
  if (!attempt || !sameJSON(inputs, attempt.inputs ?? [])) return false;
  if (artifactId === null) return !requireArtifact && attempt.outputs.length === 0
    && sameJSON(scope, { kind: 'whole' });
  return [...attempt.inputs, ...attempt.outputs].includes(artifactId) && validScope(scope, artifactId);
}

const validDraftKey = key => validRunContextKey(key, true);

function validNoteKey(key) {
  if (typeof key !== 'string' || key.length > MAX_TEXT) return false;
  const parsed = parseJSON(key);
  if (!Array.isArray(parsed) || parsed.length !== 2 || JSON.stringify(parsed) !== key) return false;
  const [area, selection] = parsed;
  if (area === 'design') return DESIGN_IDS.has(selection);
  if (area === 'run') {
    if (validRunContextKey(selection, false)) return true;
    const resourceSelection = parseJSON(selection);
    if (!Array.isArray(resourceSelection) || resourceSelection.length !== 2
      || JSON.stringify(resourceSelection) !== selection
      || !validRunContextKey(resourceSelection[0], false)
      || typeof resourceSelection[1] !== 'string') return false;
    const parsedContext = parseJSON(resourceSelection[0]);
    const [runId, attemptId, inputs, artifactId, scope] = parsedContext;
    return attemptId === null && sameJSON(inputs, []) && artifactId === null
      && sameJSON(scope, { kind: 'whole' }) && RUNS[runId].nodes.some(node => node.id === resourceSelection[1])
      && !RUNS[runId].attempts.some(attempt => attempt.node === resourceSelection[1]);
  }
  return area === 'growth' && Array.isArray(selection) && selection.length === 3
    && typeof selection[0] === 'boolean' && DIFFERENCE_IDS.has(selection[1]) && ROUND_IDS.has(selection[2]);
}

function validStringMap(map, validKey) {
  return isObject(map) && Object.entries(map).every(([key, value]) => validKey(key) && boundedString(value));
}

function validPairs(pairs) {
  if (!isObject(pairs)) return false;
  return Object.entries(pairs).every(([key, value]) => {
    const match = /^(.*):(baseline|candidate)$/.exec(key);
    if (!match || !ROUND_IDS.has(match[1])) return false;
    const round = ROUNDS.find(item => item.id === match[1]);
    const runId = match[2] === 'baseline' ? round.baselineRun : round.candidateRun;
    return validPairValue(runId, value);
  });
}

function validState(state) {
  if (!exactFields(state, STATE_FIELDS) || state.version !== 1) return false;
  if (!AREAS.has(state.area) || !MODES.has(state.mode) || !own(RUNS, state.run)) return false;
  if (!DESIGN_IDS.has(state.design) || !FOCUSES.has(state.focus) || !ROUND_IDS.has(state.round)) return false;
  if (typeof state.sample !== 'boolean' || !DIFFERENCE_IDS.has(state.difference)) return false;
  if (!boundedString(state.workText) || !boundedString(state.designText)) return false;
  if (!(state.overlay === null || OVERLAYS.has(state.overlay)) || typeof state.redact !== 'boolean') return false;
  const targetEntries = isObject(state.targets) ? Object.entries(state.targets) : [];
  if (targetEntries.length === 0 || !own(state.targets, state.run)
    || !targetEntries.every(([runId, target]) => own(RUNS, runId) && validTarget(runId, target))) return false;
  if (!validStringMap(state.drafts, validDraftKey) || !validStringMap(state.notes, validNoteKey)) return false;
  if (!validPairs(state.pairs) || !Array.isArray(state.records)
    || new Set(state.records).size !== state.records.length || !state.records.every(id => LOG_IDS.has(id))) return false;
  return validTarget(state.run, state.targets[state.run]);
}

export function load(storage) {
  const fallback = () => ({
    state: createState(),
    blocked: true,
    message: '보관본 읽기 실패 · 이전 값은 덮어쓰지 않음',
  });
  try {
    const raw = storage.getItem(KEY);
    if (raw === null) return { state: createState(), blocked: false, message: '보관본 없음 · 새 작업공간 시작' };
    if (typeof raw !== 'string' || raw.length > MAX_RAW) return fallback();
    const state = JSON.parse(raw);
    return validState(state)
      ? { state, blocked: false, message: '이 탭 보관본 복원 · 파일 첨부는 복원되지 않음' }
      : fallback();
  } catch {
    return fallback();
  }
}

export function save(storage, state, blocked) {
  if (blocked) return { ok: false, message: '자동 보관 중지 · 기존 보관본 유지' };
  try {
    storage.setItem(KEY, JSON.stringify(state));
    return { ok: true, message: '이 탭에만 보관 · 파일 첨부는 메모리에만 있음' };
  } catch {
    return { ok: false, message: '보관 실패 · 현재 입력은 메모리에 남음 · 새로고침 주의' };
  }
}

export function reset(storage) {
  try {
    storage.removeItem(KEY);
    return { ok: true };
  } catch {
    return { ok: false, message: '초기화 실패 · 현재 작성 내용 유지' };
  }
}
