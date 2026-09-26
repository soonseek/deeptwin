// T023/T025 (experience.md §5.1 items 4–6): the first work screen on the
// supported factory over `works-v1`. After the owner session is established
// the page states the retention notices (what stays on this instance, when an
// external model transmission happens, nothing sent to the maker), asks
// `어떤 일을 맡기고 싶으세요?`, keeps an unsaved draft in this browser only —
// said so, never claimed as instance storage — and saves the explanation on
// the instance as a work revision. Every save is one command id persisted with
// the text it was minted for: a retry replays it, and an edit made after a lost
// send is saved as the next revision only after that send is settled, so no
// sentence is orphaned. A draft carries the revision it was based on, so a
// revision saved from another screen is a conflict the owner resolves — the
// draft stays until the saved revision is reopened on purpose. A work the
// instance no longer has is forgotten, never the draft. Without a session
// nothing that could send a command is mounted. Every dependency (document,
// location, fetch, crypto, storage) is injected; the page passes the
// platform's own. Originals are stored through the canonical source boundary;
// their contents are read only when the owner asks, per original (source-reading.mjs),
// and the shared conversation (chat.mjs) binds messages to this work. The microphone
// is not part of this screen (T024).
//
// UI phase 5 (docs/ui/2026-09-26-product-ux-redesign.md §5.1): where the page offers the step
// mounts, the modules sit in one stepped surface (work-steps.mjs): ① 설명·자료, ② 업무 이해,
// ③ 환경 제안, ④ 준비·시작 — only the steps the server says were reached, plus the next one with
// its single call to action; a complete step folds to one line. The work's runs are listed
// beside the steps, export and source deletion sit folded in the work menu (optional, US7-3;
// `#work-records` / `#work-deletion` open them), and with several saved works a switcher and
// "새 업무" change the work only when nothing typed or picked here is unsaved.

import { createWorkConversation } from './chat.mjs';
import { basePathFrom, createSupportedSession } from './session.mjs';
import { createSourceReadings } from './source-reading.mjs';
import { createSourceDeletion } from './source-deletion.mjs';
import { createWorkExport } from './work-export.mjs';
import { createWorkModel } from './work-model.mjs';
import { createRunStart } from './run-start.mjs';
import { createDesignWorkspace } from './workspace.mjs';
import { createWorkRuns, savedWorkIds } from './run-summaries.mjs';
import { createWorkSteps, STEPS } from './work-steps.mjs';
import { mountShell } from './ui-shell.mjs';

export const MOUNT_IDS = Object.freeze({ session: 'session-status', notice: 'intake-notice', form: 'work-form',
  save: 'save-status', materials: 'materials', link: 'observe-link' });
// the export panel's mount is optional: a page without it still boots (T073)
export const RECORDS_MOUNT_ID = 'work-records';
export const DELETION_MOUNT_ID = 'work-deletion';
// the work-model panel's mount is optional too (T030)
export const WORK_MODEL_MOUNT_ID = 'work-model';
// the design workspace (T037) mounts only where the page offers it
export const DESIGN_WORKSPACE_MOUNT_ID = 'design-workspace';
// starting a run of this work from a prepared environment (T048), optional too
export const RUN_START_MOUNT_ID = 'work-run';
// the owner's explicit readings of originals and the shared conversation (T023), optional too
export const READINGS_MOUNT_ID = 'source-readings';
export const CONVERSATION_MOUNT_ID = 'work-conversation';
// UI phase 5: the step mounts (each `step-<id>` holds a `step-<id>-body`), the work switcher,
// this work's runs and the work menu's folds — all optional
export const STEP_MOUNT_PREFIX = 'step-';
export const SWITCHER_MOUNT_ID = 'work-switcher';
export const RUNS_MOUNT_ID = 'work-runs';
export const FOLDS = Object.freeze({ 'work-records': 'work-records-fold', 'work-deletion': 'work-deletion-fold' });
export const MAX_SWITCHER_WORKS = 30;
export const MAX_TEXT_CHARS = 20_000;  // app/services/works.py MAX_TEXT_CHARS
export const MAX_TEXT_BYTES = 65_536;  // app/services/works.py MAX_TEXT_BYTES (raw UTF-8)
const CREATE_SCHEMA = 'work-create-command-v1';
const REVISE_SCHEMA = 'work-revise-command-v1';
const PROMPT = '어떤 일을 맡기고 싶으세요?';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const utf8 = new TextEncoder();

export function storageKey(basePath) {
  return `deeptwin:intake:${basePath}`;
}

// the codes GET {base}session can answer (app/api/web_boundary.py)
const SESSION_TEXT = Object.freeze({
  unauthenticated: '소유자 세션이 없습니다. 이 인스턴스의 시작 화면(./)에서 로그인한 뒤 이 화면을 다시 열어 주세요.',
  access_denied: '이 화면은 이 배포의 주소에서만 열 수 있습니다.',
});
// the codes the works routes answer (app/api/works.py); a save failure never loses the draft
const ERROR_TEXT = Object.freeze({
  invalid_input: '입력 형식이 맞지 않습니다. 입력은 이 브라우저에 임시 보관됩니다.',
  unauthenticated: '세션이 끝났습니다. 시작 화면(./)에서 다시 로그인해 주세요. 입력은 이 브라우저에 임시 보관됩니다.',
  access_denied: '세션 확인에 실패했습니다. 이 화면을 다시 열어 주세요. 입력은 이 브라우저에 임시 보관됩니다.',
  not_found: '저장된 업무를 이 인스턴스에서 더는 찾지 못했습니다. 입력은 이 브라우저에 임시 보관되며, 다시 저장하면 새 업무로 저장됩니다.',
  conflict: '다른 화면에서 이 업무가 먼저 수정되었습니다. 현재 입력은 이 브라우저에만 임시 보관됩니다. 저장본을 다시 열면 그 내용으로 바뀝니다.',
  too_large: '설명이 너무 깁니다. 입력은 이 브라우저에 임시 보관됩니다.',
  unavailable: '서버가 요청을 처리하지 못했습니다. 입력은 이 브라우저에 임시 보관됩니다.',
});
const CREATE_CONFLICT_TEXT = '이 저장 명령은 이미 다른 내용으로 처리되었습니다. 현재 입력은 이 브라우저에만 임시 보관됩니다. 다시 저장하면 새 명령으로 보냅니다.';
const OFFLINE_TEXT = '서버에 연결하지 못했습니다. 입력은 이 브라우저에 임시 보관됩니다.';
const BOOT_FAILED_TEXT = '이 화면을 준비하지 못했습니다. 세션을 확인하지 못했습니다.';
// item 4: the notices, short, with the detail beneath — each claims only what this screen holds
const NOTICES = Object.freeze([
  '저장한 설명·원본은 이 인스턴스에, 미저장 설명은 이 브라우저에만 남습니다.',
  '외부 모델 전송은 업무 모델 초안처럼 소유자가 명시적으로 요청한 동작에서만 이뤄집니다.',
  '제작자에게 자동으로 보내는 것은 없습니다.',
]);
const NOTICE_DETAIL = '저장한 설명은 이 인스턴스의 저장소에 수정본 단위로 남고, 이전 수정본은 덮어쓰지 않습니다. '
  + '아직 저장하지 않은 입력은 이 브라우저에만 임시 보관되며 다른 기기나 인스턴스에 있지 않습니다. '
  + '외부 모델·도구로 무엇이 전송되는지는 실행을 시작하기 전에 대상과 범위를 표시합니다. '
  + '저장·입력만으로는 아무것도 전송하지 않으며, 연결된 Claude로 보내는 것은 소유자가 누른 요청뿐입니다.';

function fail(message) {
  throw new Error(message);
}

function sessionFailureText(error) {
  if (Object.hasOwn(SESSION_TEXT, error?.code)) return [error.code, SESSION_TEXT[error.code]];
  if (Number.isInteger(error?.status)) return ['unavailable', `세션을 확인하지 못했습니다 (서버 응답 ${error.status}).`];
  return ['unavailable', '서버에 연결하지 못했습니다. 잠시 후 다시 열어 주세요.'];
}

function textProblem(text, empty = false) {
  if (!text && !empty) return '설명을 입력하거나 자료를 추가해 주세요.';
  if ([...text].length > MAX_TEXT_CHARS) return `설명은 ${MAX_TEXT_CHARS.toLocaleString('en-US')}자 이하여야 합니다.`;
  if (utf8.encode(text).length > MAX_TEXT_BYTES) return `설명은 UTF-8 ${MAX_TEXT_BYTES.toLocaleString('en-US')}바이트 이하여야 합니다.`;
  return null;
}

const isCount = value => Number.isInteger(value) && value >= 1;
const isUuid = value => typeof value === 'string' && UUID.test(value);

function pendingDescriptor(value) {
  if (!value || typeof value !== 'object' || Object.keys(value).sort().join() !== 'operation,payload,schema_version,work_id'
      || value.schema_version !== 'owner-pending-command-v2' || !['create', 'revise', 'upload'].includes(value.operation)
      || (value.operation === 'create' ? value.work_id !== null : !isUuid(value.work_id))) return null;
  const p = value.payload;
  if (!p || !isUuid(p.command_id)) return null;
  let fields;
  if (value.operation === 'create') {
    if (!['work-create-command-v1', 'work-create-command-v2'].includes(p.schema_version)) return null;
    fields = ['schema_version', 'command_id', 'text'];
    if (p.schema_version.endsWith('v2')) {
      fields.push('input_origin');
      if (!['owner_text', 'owner_material'].includes(p.input_origin)) return null;
    }
  } else if (value.operation === 'revise') {
    if (!['work-revise-command-v1', 'work-revise-command-v2'].includes(p.schema_version) || !isCount(p.expected_revision)) return null;
    fields = ['schema_version', 'command_id', 'text', 'expected_revision'];
  } else {
    fields = ['schema_version', 'command_id', 'expected_revision', 'name', 'declared_media_type', 'size', 'sha256'];
    if (p.schema_version !== 'owner-source-upload-v1' || !isCount(p.expected_revision)
        || typeof p.name !== 'string' || !p.name || utf8.encode(p.name).length > 255
        || /[\/\\\p{Cc}\p{Cf}\p{Cs}]/u.test(p.name) || ['.', '..'].includes(p.name)
        || typeof p.declared_media_type !== 'string' || p.declared_media_type.length > 127
        || !/^[a-z0-9][a-z0-9!#$&^_.+\-]*\/[a-z0-9][a-z0-9!#$&^_.+\-]*$/.test(p.declared_media_type)
        || !Number.isSafeInteger(p.size) || p.size < 0 || p.size > 10485760 || !/^[0-9a-f]{64}$/.test(p.sha256)) return null;
  }
  if (Object.keys(p).sort().join() !== fields.sort().join()) return null;
  if (value.operation !== 'upload' && (typeof p.text !== 'string' || textProblem(p.text,
      p.schema_version === 'work-revise-command-v2' || p.input_origin === 'owner_material'))) return null;
  return Object.freeze({ ...value, payload: Object.freeze({ ...p }) });
}

// what the browser store may hold, field by field; anything else is dropped (a tampered or
// corrupt store never steers a request); a work is kept only with its known revision
function validState(value) {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return {};
  const state = {};
  if (isUuid(value.work_id) && isCount(value.revision)) {
    state.work_id = value.work_id;
    state.revision = value.revision;
    if (isCount(value.base_revision)) state.base_revision = value.base_revision;
  }
  if (typeof value.draft_text === 'string' && utf8.encode(value.draft_text).length <= 131072) state.draft_text = value.draft_text;
  const pending = pendingDescriptor(value.pending_command);
  if (pending) state.pending_command = pending;
  else if (isUuid(value.pending_command_id) && typeof value.pending_text === 'string') {
    const operation = state.work_id ? 'revise' : 'create';
    if (!state.work_id || isCount(value.base_revision)) {
      state.pending_command = pendingDescriptor({ schema_version: 'owner-pending-command-v2', operation,
        work_id: state.work_id ?? null, payload: { schema_version: operation === 'create' ? CREATE_SCHEMA : REVISE_SCHEMA,
          command_id: value.pending_command_id, text: value.pending_text,
          ...(state.work_id ? { expected_revision: value.base_revision } : {}) } });
    }
    if (!state.pending_command) state.unresolved_legacy = true;
  }
  if (value.unresolved_legacy === true) state.unresolved_legacy = true;
  return state;
}

function draftStore(storage, key) {
  // a per-browser convenience: every read and write is guarded, a blocked store is a no-op
  function read() {
    try {
      const raw = storage?.getItem?.(key) ?? 'null';
      return raw.length <= 200000 ? validState(JSON.parse(raw)) : {};
    } catch {
      return {};
    }
  }
  function write(state) {
    try {
      if (Object.keys(state).length === 0) storage?.removeItem?.(key);
      else storage?.setItem?.(key, JSON.stringify(state));
    } catch {
      // nothing: the page never depends on the browser store
    }
  }
  return { read, write };
}

// the context bar names the saved work only: its first written line and its revision;
// a draft or an unsaved work names nothing
export function workContext(text, revision) {
  const line = typeof text === 'string' ? text.split('\n').map(item => item.trim()).find(Boolean) ?? '' : '';
  const name = [...line].length > 32 ? `${[...line].slice(0, 31).join('')}…` : line;
  return { work: name || null, extra: isCount(revision) ? [['저장본', `수정본 ${revision}`]] : [] };
}

export async function boot({ document, location, fetch, crypto, storage, shell = null, events = null,
  reload = null } = {}) {
  if (typeof document !== 'object' || document === null || typeof document.getElementById !== 'function'
      || typeof document.createElement !== 'function') fail('a document is required');
  if (typeof fetch !== 'function') fail('a fetch function is required');
  if (typeof location !== 'object' || location === null) fail('a location is required');
  if (typeof crypto !== 'object' || crypto === null || typeof crypto.randomUUID !== 'function') fail('a crypto with randomUUID is required');
  const roots = {};
  for (const [name, id] of Object.entries(MOUNT_IDS)) {
    const element = document.getElementById(id);
    if (element === null || typeof element.replaceChildren !== 'function') fail(`the page has no mount for ${id}`);
    roots[name] = element;
  }
  const basePath = basePathFrom(location.pathname);
  const prefix = basePath.slice(0, -1);
  const session = createSupportedSession({ fetch, basePath });
  const store = draftStore(storage, storageKey(basePath));
  const works = `${prefix}/api/v1/works`;
  roots.form.hidden = true;

  function element(tag, attributes = {}, text) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  function status(text, state) {
    roots.session.textContent = text;
    roots.session.dataset.state = state;
  }

  const notice = NOTICES.map(text => element('p', {}, text));
  const detail = element('details');
  detail.append(element('summary', {}, '자세히'), element('p', {}, NOTICE_DETAIL));
  roots.notice.replaceChildren(...notice, detail);

  status('브라우저 세션을 확인하는 중…', 'checking');
  try {
    await session.establish();
  } catch (error) {
    const [code, text] = sessionFailureText(error);
    status(text, code);
    return Object.freeze({ mode: code === 'unauthenticated' ? 'unauthenticated' : 'unavailable', basePath, session });
  }
  status('브라우저 세션이 연결되어 있습니다.', 'authenticated');

  // the form: the prompt, the explanation, the save
  const form = roots.form;
  form.replaceChildren();
  const label = element('label', { for: 'work-description' }, PROMPT);
  const area = element('textarea', { id: 'work-description', name: 'text', rows: '6', placeholder: '맡길 일을 문장으로 설명하거나 자료를 추가해 주세요.',
    autocapitalize: 'off', spellcheck: 'false' });
  area.dataset.field = 'text';
  const submit = element('button', { type: 'submit' }, '이 인스턴스에 저장');
  const addMaterials = element('button', { type: 'button' }, '자료 추가');
  const toolbar = element('div', { class: 'original-toolbar' });
  toolbar.append(label, addMaterials);
  form.append(toolbar, area, element('p', { class: 'field-note' }, '마이크 입력은 아직 지원하지 않습니다. 글로 적거나 자료를 추가해 주세요.'),
    submit);
  const picker = element('input', { type: 'file', multiple: '', 'aria-label': '원본 자료 선택' });
  picker.hidden = true;
  addMaterials.addEventListener('click', () => picker.click());
  const materialList = element('ul', { class: 'original-list', 'aria-label': '원본 자료 목록' });
  const materialStatus = element('p', { role: 'status', 'aria-live': 'polite' });
  roots.materials.replaceChildren(element('h2', {}, '자료'), picker,
    element('p', {}, '파일당 10 MiB · 업무당 20개, 합계 50 MiB. 설명 없이 자료만 저장할 수 있습니다.'),
    element('p', {}, '원본 저장은 파일 형식 검증이나 내용 이해가 아닙니다. 내용은 자료 읽기에서 자료마다 직접 읽을 때만 읽습니다.'),
    materialStatus, materialList);
  // two separate destinations, each named for what it opens
  const links = element('ul', { class: 'page-links' });
  for (const [href, text] of [['./observe.html', '실행 화면에서 기록된 실행 보기'], ['./records.html', '기록 화면에서 사건 기록 보기']]) {
    const item = element('li');
    item.append(element('a', { href }, text));
    links.append(item);
  }
  roots.link.replaceChildren(links);

  // the stepped surface, where the page offers it (a page without the mounts keeps the list)
  const stepMounts = Object.fromEntries(STEPS.map(step => [step.id, {
    root: document.getElementById(`${STEP_MOUNT_PREFIX}${step.id}`),
    body: document.getElementById(`${STEP_MOUNT_PREFIX}${step.id}-body`) }]));
  const steps = Object.values(stepMounts).every(item => typeof item.root?.replaceChildren === 'function' && item.body)
    ? createWorkSteps({ document, roots: stepMounts }) : null;

  let state = store.read();
  let loadedWork = state.work_id ?? null;  // the work the work-scoped surfaces last read
  const recordsRoot = document.getElementById(RECORDS_MOUNT_ID);
  const exporter = recordsRoot !== null && typeof recordsRoot?.replaceChildren === 'function'
    ? createWorkExport({ root: recordsRoot, document, basePath, request: session.request, crypto,
      workId: () => state.work_id ?? null })
    : null;
  const deletionRoot = document.getElementById(DELETION_MOUNT_ID);
  const deletion = deletionRoot !== null && typeof deletionRoot?.replaceChildren === 'function'
    ? createSourceDeletion({ root: deletionRoot, document, basePath, request: session.request, crypto,
      workId: () => state.work_id ?? null,
      // the readings panel then shows the erased text as deleted (defined below; called only later)
      onDeleted: () => { readings?.load({ announce: false }).catch(() => {}); } })
    : null;
  const selections = [];
  const originals = new Map();
  let savedSources = [];
  let savedRef = null;
  let conversation = null;
  const workModelRoot = document.getElementById(WORK_MODEL_MOUNT_ID);
  const workModel = workModelRoot !== null && typeof workModelRoot?.replaceChildren === 'function'
    ? createWorkModel({ root: workModelRoot, document, basePath, request: session.request, crypto, restore: steps !== null,
      work: () => ({ work_id: state.work_id ?? null, revision: state.revision ?? null, sources: savedSources.length }),
      onChange: () => { conversation?.refreshReferences(); design?.refreshCreation(); refreshSteps(); } })
    : null;
  const readingsRoot = document.getElementById(READINGS_MOUNT_ID);
  const readings = readingsRoot !== null && typeof readingsRoot?.replaceChildren === 'function'
    ? createSourceReadings({ root: readingsRoot, document, basePath, request: session.request, crypto,
      workId: () => state.work_id ?? null, onChange: () => { conversation?.refreshReferences(); refreshSteps(); } })
    : null;
  // what the owner can point a message at: exactly the records this screen shows now
  function conversationReferences() {
    const items = [];
    if (savedRef && savedRef.id === state.work_id) items.push({ label: `업무 설명 수정본 ${savedRef.version}`, ref: savedRef });
    for (const ref of savedSources) items.push({ label: `원본 ${originals.get(ref.id)?.name ?? ref.id}`, ref });
    for (const entry of readings?.listing?.sources ?? []) {
      if (entry.reading) items.push({ label: `읽기 결과 ${entry.name}`, ref: entry.reading.reading_ref });
    }
    const model = workModel?.view;
    if (model?.record_ref) items.push({ label: '현재 작업 모델', ref: model.record_ref });
    return items;
  }
  const conversationRoot = document.getElementById(CONVERSATION_MOUNT_ID);
  conversation = conversationRoot !== null && typeof conversationRoot?.replaceChildren === 'function'
    ? createWorkConversation({ root: conversationRoot, document, basePath, request: session.request, crypto, storage,
      work: () => ({ work_id: state.work_id ?? null, revision: state.revision ?? null }), headingLevel: steps ? 3 : 2,
      references: conversationReferences,
      // a decision made in the conversation is the same one the panel makes: read it, then move the steps
      onDecided: () => workModel?.refresh().then(() => { design?.refreshCreation(); refreshSteps(); }) })
    : null;
  // the saved works of this instance (from their `work.created` events): the switcher's list, and
  // which design requests belong to no saved work
  let knownWorks = null;
  const designRoot = document.getElementById(DESIGN_WORKSPACE_MOUNT_ID);
  const design = designRoot !== null && typeof designRoot?.replaceChildren === 'function'
    ? createDesignWorkspace({ root: designRoot, document, basePath, request: session.request,
      commandId: () => crypto.randomUUID(), workModel: () => workModel?.view ?? null,
      ...(steps ? { workId: () => state.work_id ?? null, knownWorks: () => knownWorks,
        onChange: () => refreshSteps(), onPrepared: () => { runStart?.load().catch(() => {}); } } : {}) })
    : null;
  const runRoot = document.getElementById(RUN_START_MOUNT_ID);
  const runsRoot = document.getElementById(RUNS_MOUNT_ID);
  const workRuns = runsRoot !== null && typeof runsRoot?.replaceChildren === 'function'
    ? createWorkRuns({ root: runsRoot, document, basePath, request: session.request, workId: () => state.work_id ?? null })
    : null;
  const runStart = runRoot !== null && typeof runRoot?.replaceChildren === 'function'
    ? createRunStart({ root: runRoot, document, basePath, request: session.request, heading: steps === null,
      commandId: () => crypto.randomUUID(), workId: () => state.work_id ?? null,
      onLoaded: () => refreshSteps(),
      onStarted: () => { workRuns?.load().then(() => refreshSteps()).catch(() => {}); } })
    : null;

  // ---- the steps: what each one is, from what the modules read from the server ----------------
  function readingCounts() {
    const counts = { complete: 0, partial: 0, unreadable: 0, notRead: 0 };
    for (const entry of readings?.listing?.sources ?? []) {
      const reading = entry?.reading?.state;
      if (reading === 'complete') counts.complete += 1;
      else if (reading === 'partial') counts.partial += 1;
      else if (reading === 'unreadable') counts.unreadable += 1;
      else if (entry?.original_state !== 'deleted') counts.notRead += 1;
    }
    return counts;
  }

  function unsavedHere() {
    if (state.pending_command || state.unresolved_legacy) return true;
    if (selections.some(item => !['stored', 'cancelled'].includes(item.status))) return true;
    return state.work_id ? savedValue !== null && area.value !== savedValue : area.value !== '';
  }

  function facts() {
    const model = workModel?.view ?? null;
    const designFacts = design?.facts?.() ?? {};
    return {
      describe: { saved: Boolean(state.work_id), dirty: unsavedHere(), revision: state.revision ?? null,
        sources: savedSources.length, readings: readingCounts() },
      understand: { state: model?.state ?? null, revision: model?.work_model?.work_revision_ref?.version ?? null,
        goals: model?.work_model?.goals?.length ?? 0, deliverables: model?.work_model?.deliverables?.length ?? 0,
        blocking: model?.blocking_unknown_ids?.length ?? 0 },
      design: { requests: designFacts.requests ?? 0, presented: designFacts.presented ?? null },
      start: { environments: runStart?.view?.environments?.length ?? 0, runs: workRuns?.runs?.length ?? 0 },
    };
  }

  const sideRoot = document.getElementById('work-side');
  function refreshSteps() {
    if (steps === null) return null;
    // the conversation is part of understanding: it opens with the first work model
    if (conversationRoot) conversationRoot.hidden = !(workModel?.view);
    // readings wait for a saved original; the runs and the work menu for a saved work
    if (readingsRoot) readingsRoot.hidden = savedSources.length === 0;
    if (sideRoot) sideRoot.hidden = !state.work_id;
    return steps.update(facts());
  }
  let activeUpload = null;

  function renderMaterials() {
    const rows = [];
    for (const ref of savedSources) {
      const original = originals.get(ref.id);
      const row = element('li');
      row.append(element('span', { class: 'original-name' }, original?.name ?? '저장된 원본'),
        element('span', { class: 'original-state' }, '원본 보관됨'),
        // name the saved file after the original (an empty attribute lets some engines fall back to
        // a generic name instead of the server's Content-Disposition); separators never pass
        element('a', { href: `${works}/${state.work_id}/sources/${ref.id}/content`,
          download: typeof original?.name === 'string' ? original.name.replace(/[\\/\u0000-\u001f]/g, '_') : '' }, '다운로드'));
      rows.push(row);
    }
    for (const selection of selections.filter(item => item.status !== 'stored')) {
      const row = element('li');
      row.append(element('span', { class: 'original-name' }, selection.file.name),
        element('span', { class: 'original-state' }, { queued: '저장 대기', sending: '받는 중', checking: '저장 상태 확인 중',
          cancelled: '전송 취소됨 · 원본은 이 화면에 유지됨', failed: '저장하지 못함 · 다시 시도할 수 있음' }[selection.status]));
      const retry = element('button', { type: 'button' }, selection.status === 'checking' ? '저장 상태 확인' : '다시 시도');
      retry.addEventListener('click', async () => {
        if (busy) return;
        selection.status = 'queued';
        await saveAll();
      });
      const cancel = element('button', { type: 'button' }, selection.status === 'sending' ? '전송 중지' : '취소');
      cancel.addEventListener('click', () => {
        if (activeUpload?.selection === selection) {
          activeUpload.controller.abort();
          selection.status = 'checking';
          materialStatus.textContent = '저장 상태 확인 중 · 전송 중지는 저장 취소를 뜻하지 않습니다.';
        } else if (selection.status !== 'checking') selection.status = 'cancelled';
        renderMaterials();
      });
      if (['failed', 'cancelled', 'checking'].includes(selection.status)) row.append(retry);
      row.append(cancel);
      rows.push(row);
    }
    materialList.replaceChildren(...rows);
  }

  async function loadMaterials(saved) {
    shell?.setContext?.(workContext(saved.text, state.revision ?? saved.revision));
    savedSources = saved.source_refs ?? [];
    if (saved.ref && typeof saved.ref === 'object') savedRef = saved.ref;
    renderMaterials();
    refreshSteps();
    if (deletion !== null) deletion.load().catch(() => {});
    if (workModel !== null) workModel.load().then(refreshSteps).catch(() => {});
    if (readings !== null) readings.load().then(refreshSteps).catch(() => {});
    if (conversation !== null) conversation.load().catch(() => {});
    if (steps !== null && loadedWork !== saved.work_id) {
      // a work saved for the first time here: its own designs, runs and the switcher's list
      loadKnownWorks().then(() => design?.load()).catch(() => {});
      workRuns?.load().then(refreshSteps).catch(() => {});
    }
    loadedWork = saved.work_id;
    for (const ref of savedSources) {
      if (!originals.has(ref.id)) {
        try {
          const result = await session.request(`${works}/${saved.work_id}/sources/${ref.id}`);
          originals.set(ref.id, result.artifact);
        } catch {
          materialStatus.textContent = '저장된 원본의 이름을 확인하지 못했습니다. 다시 열어 주세요.';
        }
      }
    }
    renderMaterials();
  }

  picker.addEventListener('change', () => {
    for (const file of Array.from(picker.files ?? [])) {
      const queued = selections.filter(item => !['stored', 'cancelled'].includes(item.status));
      const total = [...originals.values()].reduce((sum, item) => sum + item.size, 0)
        + queued.reduce((sum, item) => sum + item.file.size, 0);
      if (file.size > 10485760 || savedSources.length + queued.length >= 20 || total + file.size > 52428800) {
        materialStatus.textContent = '자료 한도를 넘었습니다. 파일당 10 MiB, 업무당 20개·50 MiB 이내로 선택해 주세요.';
        continue;
      }
      if (!file.name || utf8.encode(file.name).length > 255 || /[\/\\\p{Cc}\p{Cf}\p{Cs}]/u.test(file.name) || ['.', '..'].includes(file.name)) {
        materialStatus.textContent = '파일 이름을 확인해 주세요. 경로 문자나 제어 문자는 사용할 수 없습니다.';
        continue;
      }
      selections.push({ file, status: 'queued', metadata: null });
    }
    picker.value = '';
    renderMaterials();
  });

  function keep(changes) {
    state = { ...state, ...changes };
    for (const name of Object.keys(state)) if (state[name] === undefined) delete state[name];
    store.write(state);
  }

  function forgetWork() {
    keep({ work_id: undefined, revision: undefined, base_revision: undefined,
      pending_command: undefined });
  }

  function savedText() {
    return `이 인스턴스에 저장됨 · 수정본 ${state.revision}`;
  }

  function saveStatus(text, code, { reopen = false } = {}) {
    // UI phase 6: the line is a polite live region; the same words written again on every
    // keystroke would be read again, so an unchanged line is left alone
    if (!reopen && roots.save.dataset.state === code && roots.save.textContent === text
        && roots.save.children?.length === 1) return;
    roots.save.replaceChildren(element('span', {}, text));
    roots.save.dataset.state = code;
    if (reopen && state.work_id) {
      const button = element('button', { type: 'button' }, '저장본 다시 열기');
      button.addEventListener('click', reopenSaved);
      const rebase = element('button', { type: 'button' }, '현재 입력을 최신 수정본 위에 저장하기로 두기');
      rebase.addEventListener('click', rebaseDraft);
      roots.save.append(button, rebase);
    }
  }

  function draftStatus() {
    if (state.work_id) saveStatus(`이 브라우저에만 임시 보관된 미저장 초안 (인스턴스에 저장되지 않음) · 저장본은 수정본 ${state.revision}`, 'draft');
    else saveStatus('저장되지 않은 변경 — 이 브라우저에만 임시 보관됨 (인스턴스에 저장되지 않음)', 'draft');
  }

  function baseConflictStatus() {
    saveStatus(`다른 화면에서 수정본 ${state.revision}이(가) 저장되었습니다. 현재 입력은 수정본 ${state.base_revision}을(를) 기준으로 한 초안이며 이 브라우저에만 임시 보관됩니다. 저장본을 다시 열면 그 내용으로 바뀝니다.`, 'conflict', { reopen: true });
  }

  function failureText(error) {
    if (error?.code === 'unavailable' && !Number.isInteger(error?.status)) return ['unavailable', OFFLINE_TEXT];
    if (Object.hasOwn(ERROR_TEXT, error?.code)) return [error.code, ERROR_TEXT[error.code]];
    if (Number.isInteger(error?.status)) return ['unavailable', ERROR_TEXT.unavailable];
    return ['unavailable', OFFLINE_TEXT];
  }

  function revisionShape(saved, workId) {
    if (typeof saved?.text !== 'string' || !isCount(saved?.revision) || !isUuid(saved?.work_id)
        || (workId !== undefined && saved.work_id !== workId)) {
      throw Object.assign(new Error('the saved work could not be read'), { code: 'unavailable', status: 200 });
    }
    return saved;
  }

  async function readSaved() {
    return revisionShape(await session.request(`${works}/${state.work_id}`), state.work_id);
  }

  // a command: on a 403 the token no longer matches the cookie (the owner logged in again
  // elsewhere) — re-establish once and retry; a second refusal is reported as such
  async function command(path, body) {
    try {
      return await session.request(path, { method: 'POST', body });
    } catch (error) {
      if (error?.code !== 'access_denied') throw error;
      await session.establish();
      return await session.request(path, { method: 'POST', body });
    }
  }

  let busy = false;
  let savedValue = null;  // the text of the revision last read or saved, in memory only

  async function reopenSaved() {
    if (busy || state.pending_command) return;
    busy = true;
    try {
      const saved = await readSaved();
      area.value = saved.text;
      savedValue = saved.text;
      keep({ revision: saved.revision, base_revision: undefined, draft_text: undefined,
        unresolved_legacy: undefined });
      await loadMaterials(saved);
      saveStatus(savedText(), 'saved');
    } catch (error) {
      const [code, text] = failureText(error);
      saveStatus(text, code);
    } finally {
      busy = false;
    }
  }

  // the owner keeps the draft and takes the latest revision as its base: the next save
  // seals it on top (the other screen's revision stays, immutable)
  async function rebaseDraft() {
    if (busy || state.pending_command) return;
    busy = true;
    try {
      const saved = await readSaved();
      savedValue = saved.text;
      keep({ revision: saved.revision, base_revision: saved.revision, draft_text: area.value,
        unresolved_legacy: undefined });
      await loadMaterials(saved);
      draftStatus();
    } catch (error) {
      const [code, text] = failureText(error);
      saveStatus(text, code);
    } finally {
      busy = false;
    }
  }

  let mode = 'new';
  area.value = state.draft_text ?? '';
  if (state.pending_command) {
    try {
      const pending = state.pending_command;
      const receipt = revisionShape(await session.request(`${works}/commands/${pending.payload.command_id}`), pending.work_id ?? undefined);
      await acceptSaved(receipt, pending);
    } catch {
      // A missing receipt is not rollback. Preserve the exact command even while
      // a cancelled request's publication is still in progress on the instance.
      saveStatus('저장 상태 확인 중 · 같은 명령으로 다시 확인하거나 원본을 다시 선택해 주세요.', 'checking');
    }
  }
  if (state.work_id) {
    try {
      const saved = await readSaved();
      savedValue = saved.text;
      keep({ revision: saved.revision });
      await loadMaterials(saved);
      if (typeof state.draft_text === 'string' && state.draft_text !== saved.text) {
        area.value = state.draft_text;
        if (state.base_revision === undefined) keep({ base_revision: saved.revision });
        if (state.base_revision !== saved.revision) baseConflictStatus();
        else draftStatus();
      } else {
        area.value = saved.text;
        keep({ draft_text: undefined, base_revision: undefined });
        saveStatus(savedText(), 'saved');
      }
      mode = 'open';
    } catch (error) {
      if (error?.code === 'not_found' && !state.pending_command && !state.unresolved_legacy) {
        // the instance no longer has the work: forgotten — never the draft, the only copy
        forgetWork();
        area.value = typeof state.draft_text === 'string' ? state.draft_text : '';
        if (area.value) draftStatus();
        else saveStatus('저장된 업무가 이 인스턴스에 없어 새 업무로 시작합니다.', 'new');
      } else {
        area.value = typeof state.draft_text === 'string' ? state.draft_text : '';
        const [code, text] = failureText(error);
        saveStatus(text, code);
        mode = 'open';
      }
    }
  } else if (typeof state.draft_text === 'string' && state.draft_text) {
    area.value = state.draft_text;
    draftStatus();
  } else {
    saveStatus('아직 저장된 업무가 없습니다.', 'new');
  }
  if (state.pending_command) saveStatus('저장 상태 확인 중 · 같은 명령을 유지합니다. 원본 전송 재시도에는 같은 파일이 필요합니다.', 'checking');
  if (state.unresolved_legacy) saveStatus('이전 저장 명령의 원래 수정본을 확인할 수 없습니다. 초안을 유지했습니다. 저장본을 확인한 뒤 기준을 선택해 주세요.', 'conflict', { reopen: true });
  form.hidden = false;

  area.addEventListener('input', () => {
    keep({ draft_text: area.value, base_revision: state.work_id && state.base_revision === undefined ? state.revision : state.base_revision });
    draftStatus();
    refreshSteps();
  });

  async function acceptSaved(saved, pending) {
    if (pending?.operation === 'upload') {
      const selection = selections.find(item => item.metadata?.command_id === pending.payload.command_id)
        ?? (await pendingFile(pending.payload))?.selection;
      // A reselected File has no command metadata yet. Verify its full identity
      // before consuming it, including when receipt lookup wins the retry race.
      if (selection) {
        selection.metadata = pending.payload;
        selection.status = 'stored';
      }
    }
    const base = state.base_revision;
    keep({ work_id: saved.work_id, revision: Math.max(saved.revision, state.revision ?? 0),
      base_revision: base === undefined || base === pending?.payload.expected_revision || pending?.operation === 'create' ? saved.revision : base,
      pending_command: undefined });
    savedValue = saved.text;
    if (saved.revision < state.revision) {
      const latest = await readSaved();
      savedValue = latest.text;
      keep({ revision: latest.revision });
      await loadMaterials(latest);
    } else await loadMaterials(saved);
    return saved;
  }

  function remember(operation, payload, workId = state.work_id ?? null) {
    const descriptor = pendingDescriptor({ schema_version: 'owner-pending-command-v2', operation, work_id: workId, payload });
    if (!descriptor) throw Object.assign(new Error('invalid pending command'), { code: 'invalid_input' });
    keep({ pending_command: descriptor, draft_text: area.value });
    return descriptor;
  }

  async function fileMetadata(selection, expected, commandId) {
    const bytes = new Uint8Array(await selection.file.arrayBuffer());
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    const declared = selection.file.type;
    return { bytes, metadata: { schema_version: 'owner-source-upload-v1', command_id: commandId,
      expected_revision: expected, name: selection.file.name, size: bytes.length,
      sha256: Array.from(digest, byte => byte.toString(16).padStart(2, '0')).join(''),
      declared_media_type: typeof declared === 'string' && declared.length <= 127
        && /^[a-z0-9][a-z0-9!#$&^_.+\-]*\/[a-z0-9][a-z0-9!#$&^_.+\-]*$/.test(declared) ? declared : 'application/octet-stream' } };
  }

  async function pendingFile(payload) {
    for (const selection of selections.filter(item => item.status !== 'stored')) {
      if (selection.metadata && selection.metadata.command_id !== payload.command_id) continue;
      if (selection.file.name !== payload.name || selection.file.size !== payload.size) continue;
      const result = await fileMetadata(selection, payload.expected_revision, payload.command_id);
      if (Object.keys(payload).every(key => payload[key] === result.metadata[key])) {
        return { selection, ...result };
      }
    }
    return null;
  }

  async function sendPending() {
    const pending = state.pending_command;
    const p = pending.payload;
    if (pending.operation !== 'upload') {
      const path = pending.operation === 'create' ? works : `${works}/${pending.work_id}/revisions`;
      return acceptSaved(revisionShape(await command(path, p), pending.work_id ?? undefined), pending);
    }
    try {
      const receipt = revisionShape(await session.request(`${works}/commands/${p.command_id}`), pending.work_id);
      return acceptSaved(receipt, pending);
    } catch (error) {
      if (error?.code !== 'not_found') throw error;
    }
    const candidate = await pendingFile(p);
    if (!candidate) throw Object.assign(new Error('same original required'), { code: 'reselect' });
    return sendUpload(pending, candidate.selection, candidate.bytes);
  }

  async function sendUpload(pending, selection, bytes) {
    selection.metadata = pending.payload;
    selection.status = 'sending';
    const controller = new AbortController();
    activeUpload = { controller, selection };
    renderMaterials();
    try {
      const saved = revisionShape(await session.uploadSource(`${works}/${pending.work_id}/sources`,
        { metadata: pending.payload, bytes, signal: controller.signal }), pending.work_id);
      return await acceptSaved(saved, pending);
    } catch (error) {
      selection.status = ['conflict', 'invalid_input', 'too_large'].includes(error?.code) ? 'failed' : 'checking';
      throw error;
    } finally {
      activeUpload = null;
      renderMaterials();
    }
  }

  // after a send: text typed meanwhile stays a browser draft on the revision just saved
  function settled() {
    runStart?.load().catch(() => {});
    if (area.value === savedValue) {
      keep({ draft_text: undefined, base_revision: undefined });
      saveStatus(savedText(), 'saved');
    } else {
      keep({ draft_text: area.value, base_revision: state.revision });
      draftStatus();
    }
    refreshSteps();
  }

  function sendFailed(error) {
    const [code, text] = failureText(error);
    if (code === 'conflict' || code === 'invalid_input' || code === 'too_large') {
      // a refused or conflicting command is spent: the server holds it to its content and target
      keep({ pending_command: undefined });
    }
    if (error?.code === 'reselect') {
      saveStatus('저장 상태 확인 중 · 같은 이름과 내용의 원본을 다시 선택해 주세요. 파일 바이트는 브라우저에 저장하지 않습니다.', 'checking');
      return;
    }
    if (code === 'not_found' && state.pending_command?.operation !== 'upload') forgetWork();
    if (code === 'conflict' && !state.work_id) saveStatus(CREATE_CONFLICT_TEXT, code);
    else saveStatus(state.pending_command ? `저장 상태 확인 중 · ${text}` : text, code, { reopen: code === 'conflict' });
  }

  async function saveAll() {
    if (busy) return;
    if (state.unresolved_legacy) return;
    const text = area.value;
    const queued = selections.filter(item => item.status === 'queued');
    const problem = textProblem(text, queued.length > 0 || savedSources.length > 0 || !!state.pending_command);
    if (problem) {
      saveStatus(problem, 'invalid_input');
      return;
    }
    if (state.work_id && !state.pending_command && text === savedValue && !queued.length) {
      // nothing to seal: the instance already holds this sentence
      keep({ draft_text: undefined, base_revision: undefined });
      saveStatus(savedText(), 'saved');
      return;
    }
    busy = true;
    try {
      saveStatus('이 인스턴스에 저장하는 중…', 'sending');
      // a send whose answer was lost is settled first, with the text it was minted for: the
      // server replays it or seals it; only then is a newer draft saved as the next revision
      if (state.pending_command) {
        await sendPending();
        if (state.base_revision !== undefined && state.base_revision < state.revision) {
          baseConflictStatus();
          return;
        }
      }
      if (!state.work_id || text !== savedValue) {
        const material = queued.length > 0 || savedSources.length > 0;
        const schema = state.work_id ? (material ? 'work-revise-command-v2' : REVISE_SCHEMA)
          : (material ? 'work-create-command-v2' : CREATE_SCHEMA);
        const payload = { schema_version: schema, command_id: crypto.randomUUID(), text,
          ...(state.work_id ? { expected_revision: state.base_revision ?? state.revision }
            : material ? { input_origin: 'owner_material' } : {}) };
        remember(state.work_id ? 'revise' : 'create', payload);
        await sendPending();
      }
      for (const selection of queued) {
        if (selection.status !== 'queued') continue;
        const result = await fileMetadata(selection, state.base_revision ?? state.revision, crypto.randomUUID());
        const pending = remember('upload', result.metadata);
        await sendUpload(pending, selection, result.bytes);
      }
      settled();
    } catch (error) {
      sendFailed(error);
    } finally {
      busy = false;
    }
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    await saveAll();
  });

  // ---- the work switcher and "새 업무" (UI phase 5) -------------------------------------------
  const switcherRoot = steps !== null ? document.getElementById(SWITCHER_MOUNT_ID) : null;
  const switcherStatus = element('p', { role: 'status', 'aria-live': 'polite', class: 'work-switcher-status' });
  const names = new Map();  // work id -> its first line, read once

  function refuseSwitch() {
    if (!unsavedHere() && !busy) return false;
    switcherStatus.textContent = '저장하지 않은 입력이나 전송 중인 자료가 있어 업무를 바꾸지 않았습니다. 먼저 저장해 주세요.';
    switcherStatus.dataset.state = 'refused';
    return true;
  }

  function reopenAs(changes) {
    keep({ base_revision: undefined, draft_text: undefined, pending_command: undefined, unresolved_legacy: undefined, ...changes });
    if (typeof reload === 'function') reload();
    else location.reload?.();
  }

  async function renderSwitcher(ids) {
    if (switcherRoot === null || typeof switcherRoot.replaceChildren !== 'function') return;
    const offerSelect = ids.length >= 2 || (ids.length >= 1 && !state.work_id);
    if (!offerSelect && !state.work_id) {
      switcherRoot.replaceChildren();
      switcherRoot.hidden = true;
      return;
    }
    // each listed work's first line and latest revision, read from the work itself
    const listed = ids.slice(-MAX_SWITCHER_WORKS).reverse();
    const works = (await Promise.all(listed.map(async id => {
      try {
        const saved = await session.request(`${prefix}/api/v1/works/${id}`);
        return isCount(saved?.revision) ? { id, revision: saved.revision,
          name: workContext(saved.text, saved.revision).work ?? '설명 없이 자료만 있는 업무' } : null;
      } catch {
        return null;  // a work this instance no longer serves is not offered
      }
    }))).filter(Boolean);
    const parts = [];
    if (offerSelect) {
      const select = element('select', { id: 'work-switch', 'aria-label': '다른 업무 열기' });
      if (!state.work_id) select.append(element('option', { value: '' }, '새 업무 (저장 전)'));
      for (const item of works) {
        const option = element('option', { value: item.id, title: item.id }, `${item.name} · 수정본 ${item.revision}`);
        select.append(option);
      }
      select.value = state.work_id ?? '';
      select.addEventListener('change', () => {
        const chosen = select.value;
        if (!chosen || chosen === state.work_id) return;
        if (refuseSwitch()) {
          select.value = state.work_id ?? '';
          return;
        }
        const target = works.find(item => item.id === chosen);
        if (!target) return;
        reopenAs({ work_id: target.id, revision: target.revision });
      });
      parts.push(element('label', { for: 'work-switch', class: 'work-switch-label' }, '업무'), select);
    }
    if (state.work_id) {
      const fresh = element('button', { type: 'button', class: 'btn btn-secondary work-new' }, '새 업무');
      fresh.addEventListener('click', () => {
        if (refuseSwitch()) return;
        reopenAs({ work_id: undefined, revision: undefined });
      });
      parts.push(fresh);
    }
    switcherRoot.replaceChildren(...parts, switcherStatus);
    switcherRoot.hidden = false;
  }

  async function loadKnownWorks() {
    if (steps === null) return null;
    try {
      const ids = await savedWorkIds({ request: session.request, basePath });
      if (state.work_id && !ids.includes(state.work_id)) ids.push(state.work_id);
      knownWorks = new Set(ids);
      await renderSwitcher(ids);
      return ids;
    } catch {
      knownWorks = null;
      return null;
    }
  }

  // ---- the work menu's folds: `#work-records` / `#work-deletion` open them ---------------------
  function openFold() {
    const named = typeof location?.hash === 'string' ? location.hash.replace(/^#/, '') : '';
    if (!Object.hasOwn(FOLDS, named)) return false;
    const fold = document.getElementById(FOLDS[named]);
    if (!fold) return false;
    fold.open = true;
    document.getElementById(named)?.scrollIntoView?.({ block: 'start' });
    return true;
  }
  if (typeof events?.addEventListener === 'function') events.addEventListener('hashchange', () => openFold());

  if (deletion !== null) deletion.load().catch(() => {});
  const first = [];
  if (workModel !== null) first.push(workModel.load());
  if (runStart !== null) first.push(runStart.load());
  if (readings !== null) first.push(readings.load());
  if (conversation !== null) conversation.load().catch(() => {});
  if (workRuns !== null) first.push(workRuns.load());
  if (design !== null) first.push(steps !== null ? loadKnownWorks().then(() => design.load()) : design.load());
  openFold();
  // the first reads are in: complete steps fold, the next step stands open
  const ready = Promise.allSettled(first).then(() => {
    if (steps !== null) {
      refreshSteps();
      steps.settle(facts());
    }
    openFold();
  });
  return Object.freeze({ mode, basePath, session, exporter, deletion, workModel, design, runStart, readings, conversation,
    steps, workRuns, ready, refreshSteps });
}

// the page's entry: a boot that fails before the exchange still reaches the status line
export async function bootPage(globals) {
  try {
    return await boot(globals);
  } catch {
    const status = globals?.document?.getElementById?.(MOUNT_IDS.session);
    if (status && typeof status === 'object') {
      status.dataset.state = 'unavailable';
      status.textContent = BOOT_FAILED_TEXT;
    }
    return null;
  }
}

if (typeof globalThis.document === 'object' && globalThis.document !== null
    && typeof globalThis.document.getElementById === 'function'
    && globalThis.document.getElementById(MOUNT_IDS.form) !== null) {
  let storage = null;
  try {
    storage = globalThis.localStorage ?? null;
  } catch {
    storage = null;
  }
  const shell = mountShell({ document: globalThis.document, page: 'work' });
  bootPage({ document: globalThis.document, location: globalThis.location, crypto: globalThis.crypto,
    storage, shell, events: globalThis, reload: () => globalThis.location.reload(),
    fetch: (...args) => globalThis.fetch(...args) });
}
