// T048: the run panel's run source. The shell cannot compose a run creation
// yet — no production path records a run consent, an environment or a work
// revision (the design/consent line) — so the honest source of runs to
// observe is the public snapshot (GET {base}api/v1/snapshot, session-protected,
// app/api/routes.py): its durable run rows (id, the runtime ledger's durable
// phase, revision). This module lists them in recorded order, lets the owner
// pick one (nothing is auto-selected; a value the list never offered is not a
// choice) and hands the id to the run panel, which reads the server-derived
// receipt. Reads go through the injected request (the session client's
// adapter); exchanges are generation-ordered so a late reply never replaces a
// newer list, and a failed re-read keeps the last honest list beside its
// error. A snapshot outside the contract never becomes the list.

export const SNAPSHOT_VERSION = 'public-snapshot-v1';
// the runtime ledger's durable run phases (app/runtime/ledger.py RUN_PHASES):
// a row's own phase — the derived phase (running, awaiting…) is the receipt's
export const RUN_PHASES = Object.freeze(['created', 'cancelled']);
export const RUN_PHASE_LABELS = Object.freeze({
  created: '기록됨',
  cancelled: '취소됨',
});
const STATUS_MESSAGES = Object.freeze({
  invalid_input: '실행 목록 요청이 거부되었습니다.',
  unauthenticated: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  access_denied: '실행 목록을 볼 권한이 없습니다.',
  not_found: '실행 목록을 찾지 못했습니다.',
  conflict: '실행 목록을 지금 읽을 수 없습니다. 다시 시도해 주세요.',
  too_large: '실행 목록 요청이 허용 크기를 넘었습니다.',
  unavailable: '서버에서 실행 목록을 읽지 못했습니다.',
  capacity: '서버가 바쁩니다. 잠시 후 다시 시도해 주세요.',
  credentials: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  setup_incomplete: '이 인스턴스의 소유자 설정이 끝나지 않았습니다.',
  setup_unavailable: '이 인스턴스의 설정 상태를 확인할 수 없습니다.',
});
const IDLE_STATUS = '실행 목록을 불러오기 전입니다.';
const BUSY_STATUS = '실행 목록을 확인하는 중…';
const EMPTY_STATUS = '기록된 실행이 아직 없습니다.';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
const CODE_BY_STATUS = Object.freeze({
  400: 'invalid_input', 401: 'unauthenticated', 403: 'access_denied', 404: 'not_found',
  409: 'conflict', 413: 'too_large', 429: 'capacity', 503: 'unavailable',
});
// the server's own snapshot item bound (app/api/routes.py MAX_SNAPSHOT_ITEMS): a list
// bound below it would refuse a snapshot the server served
export const MAX_RUNS = 10_000;

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

export function snapshotRoute(basePath = '/') {
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  return `${basePath.slice(0, -1)}/api/v1/snapshot`;
}

export function runList(snapshot) {
  if (typeof snapshot !== 'object' || snapshot === null || Array.isArray(snapshot)) fail('snapshot must be an object', 'unavailable');
  if (snapshot.snapshot_version !== SNAPSHOT_VERSION) fail('not a public snapshot', 'unavailable');
  const state = snapshot.state;
  if (typeof state !== 'object' || state === null || !Array.isArray(state.runs)) fail('snapshot carries no runs', 'unavailable');
  if (state.runs.length > MAX_RUNS) fail('snapshot run list is out of bounds', 'unavailable');
  const seen = new Set();
  const runs = state.runs.map(row => {
    if (typeof row !== 'object' || row === null) fail('run row must be an object', 'unavailable');
    if (Object.keys(row).sort().join(',') !== 'id,phase,revision') fail('run row must carry exactly id, phase, revision', 'unavailable');
    if (typeof row.id !== 'string' || !UUID.test(row.id) || seen.has(row.id)) fail('run id is not a distinct canonical UUID', 'unavailable');
    seen.add(row.id);
    if (!RUN_PHASES.includes(row.phase)) fail('run phase is outside the durable set', 'unavailable');
    if (!Number.isInteger(row.revision) || row.revision < 1) fail('run revision is not positive', 'unavailable');
    return Object.freeze({ runId: row.id, phase: row.phase, phaseLabel: RUN_PHASE_LABELS[row.phase], revision: row.revision });
  });
  return Object.freeze(runs);
}

function partition(error) {
  // own keys only: a code naming a prototype member is not a label
  if (typeof error?.code === 'string' && Object.hasOwn(STATUS_MESSAGES, error.code)) return error.code;
  return CODE_BY_STATUS[error?.status] ?? 'unavailable';
}

export function createRunList({ root, document, request, basePath = '/', onSelect = () => {} } = {}) {
  if (typeof root !== 'object' || root === null || typeof root.replaceChildren !== 'function') fail('a root element is required');
  if (typeof document !== 'object' || document === null || typeof document.createElement !== 'function') fail('a document is required');
  if (typeof request !== 'function') fail('an injected request function is required');
  if (typeof onSelect !== 'function') fail('onSelect must be a function');
  const route = snapshotRoute(basePath);

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', IDLE_STATUS, { role: 'status', 'aria-live': 'polite' });
  const select = element('select', undefined, { 'aria-label': '관제할 실행 선택' });
  select.disabled = true;
  const refresh = element('button', '실행 목록 다시 읽기');
  refresh.type = 'button';
  root.replaceChildren(status, select, refresh);

  let state = Object.freeze({ busy: false, runs: Object.freeze([]), error: null, selected: null });
  let generation = 0;

  function render() {
    // a failed re-read keeps the last honest list (run rows are never deleted) and says
    // so beside the error, so the panel is never left pointing at a run the list disowned
    const errorText = state.error ? STATUS_MESSAGES[state.error.code] ?? STATUS_MESSAGES.unavailable : '';
    status.textContent = state.busy ? BUSY_STATUS
      : state.error ? (state.runs.length ? `${errorText} 마지막으로 읽은 목록 ${state.runs.length}개를 유지합니다.` : errorText)
        : state.runs.length === 0 ? (generation === 0 ? IDLE_STATUS : EMPTY_STATUS)
          : `기록된 실행 ${state.runs.length}개`;
    const empty = element('option', '실행을 선택해 주세요');
    empty.value = '';
    select.replaceChildren(empty, ...state.runs.map(run => {
      const option = element('option', `${run.phaseLabel} · ${run.runId}`);
      option.value = run.runId;
      option.dataset.phase = run.phase;
      return option;
    }));
    select.value = state.selected ?? '';
    select.disabled = state.busy || state.runs.length === 0;
    refresh.disabled = state.busy;
  }

  function publish(changes) {
    state = Object.freeze({ ...state, ...changes });
    render();
  }

  async function refreshList() {
    const mine = ++generation;
    publish({ busy: true, error: null });
    try {
      const runs = runList(await request(route, {}));
      if (mine === generation) {
        const selected = runs.some(run => run.runId === state.selected) ? state.selected : null;
        publish({ busy: false, runs, selected });
      }
      return state.runs;  // a superseded refresh resolves with the list that stands
    } catch (error) {
      if (mine === generation) {
        publish({ busy: false,
          error: Object.freeze({ code: partition(error), message: String(error?.message ?? error) }) });
      }
      throw error;
    }
  }

  select.addEventListener('change', () => {
    const value = select.value;
    if (value === '') {
      publish({ selected: null });
      return;
    }
    if (!state.runs.some(run => run.runId === value)) {
      publish({ selected: null });  // a DOM edit is not a choice
      return;
    }
    publish({ selected: value });
    onSelect(value);
  });
  refresh.addEventListener('click', () => refreshList().catch(() => {}));

  return Object.freeze({
    refresh: refreshList,
    snapshot() { return state; },
  });
}
