// T052 (US4): the owner's own version of a run artifact, edited in place — a text
// artifact as text, a CSV artifact as a table of cells — with revision-safe
// autosave. Every save names the revision it was edited from; when another screen
// saved first the server refuses (conflict) and this editor keeps the owner's text,
// says so, and offers to load the newer revision or to keep this text as a new
// draft — it never overwrites silently. No reason or instruction is asked for at
// any step. Freezing for analysis is a separate explicit action on one exact
// revision: by default only the changed lines or cells count as the owner's
// evidence and the rest is shown as unreviewed; "whole" is claimed only when the
// owner ticks that they reviewed the whole artifact, because an assembled full
// preview is not a whole work of theirs. The original is never changed. All text
// reaches the DOM through textContent or form values, never markup.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
export const SAVE_SCHEMA = 'alternative-draft-save-v1';
export const FREEZE_SCHEMA = 'alternative-freeze-v1';
export const EDITABLE_MEDIA = Object.freeze(['text/plain', 'text/markdown', 'application/json', 'text/csv']);
export const AUTOSAVE_MS = 800;
// the three views of one alternative: the original as recorded, the owner's version,
// and what the framework observes between them
export const VIEWS = Object.freeze(['original', 'mine', 'differences']);
export const VIEW_LABELS = Object.freeze({ original: '원본', mine: '내 버전', differences: '차이' });

export const MESSAGES = Object.freeze({
  loading: '내 버전을 준비하는 중…',
  original: '원본을 복사해 편집합니다. 원본은 그대로 남습니다.',
  resumed: '저장된 내 버전을 이어서 편집합니다.',
  unsaved: '저장되지 않은 변경이 있습니다.',
  saving: '저장하는 중…',
  conflict: '다른 화면에서 이 버전을 먼저 저장했습니다. 지금 화면의 내용은 그대로 두었습니다.',
  frozen: '분석용으로 고정했습니다.',
  unchanged: '원본과 같은 내용은 내 버전으로 고정할 수 없습니다.',
  noReason: '이유나 지시를 적지 않아도 됩니다.',
  partial: '바꾼 줄·칸만 내 근거로 기록합니다. 나머지는 검토하지 않은 영역으로 남습니다.',
  whole: '전체를 검토했습니다(선택하면 전체를 내 버전으로 기록합니다).',
});

export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '이 산출물은 이 편집기로 고칠 수 없거나 요청 형식이 맞지 않습니다.',
  unauthenticated: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다.',
  not_found: '산출물이나 초안을 찾지 못했습니다.',
  conflict: MESSAGES.conflict,
  too_large: '이 산출물은 한 화면에서 편집하기에 너무 큽니다.',
  unavailable: '저장소에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.',
});

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

function requireUuid(value, label) {
  if (typeof value !== 'string' || !UUID.test(value)) fail(`${label} is not a canonical UUID`);
  return value;
}

export function draftRoutes(basePath = '/') {
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const runs = `${basePath.slice(0, -1)}/api/v1/runs`;
  const list = (runId, artifactId) =>
    `${runs}/${requireUuid(runId, 'run id')}/artifacts/${requireUuid(artifactId, 'artifact id')}/drafts`;
  const one = (runId, artifactId, draftId) => `${list(runId, artifactId)}/${requireUuid(draftId, 'draft id')}`;
  return Object.freeze({ list, one, freeze: (runId, artifactId, draftId) => `${one(runId, artifactId, draftId)}/freeze`,
    differences: (runId, artifactId, draftId) => `${one(runId, artifactId, draftId)}/differences` });
}

export function isEditable(mediaType) {
  return EDITABLE_MEDIA.includes(mediaType);
}

export function createAlternativeEditor({ root, document, request, basePath = '/', crypto, schedule } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  if (typeof crypto?.randomUUID !== 'function') fail('a crypto with randomUUID is required');
  const later = schedule ?? ((fn, ms) => setTimeout(fn, ms));
  const cancel = schedule ? () => {} : handle => clearTimeout(handle);
  const routes = draftRoutes(basePath);
  let target = null;   // { runId, artifactId, format }
  let draft = null;    // { draftId, revision } of the last revision the server accepted
  let content = null;  // the owner's current text or rows
  let originalContent = null;
  let view = 'mine';
  let pending = null;
  let saving = null;
  let dirty = false;
  let generation = 0;

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', '', { role: 'status', 'aria-live': 'polite' });
  const tabs = element('div', undefined, { role: 'group', 'aria-label': '보기 전환' });
  const tabButtons = {};
  for (const name of VIEWS) {
    tabButtons[name] = element('button', VIEW_LABELS[name], { type: 'button', 'aria-pressed': name === view ? 'true' : 'false' });
    tabButtons[name].addEventListener('click', () => show(name).catch(() => {}));
    tabs.append(tabButtons[name]);
  }
  tabs.hidden = true;
  const surface = element('div', undefined, { class: 'alternative-surface' });
  const actions = element('div', undefined, { class: 'alternative-actions' });
  const result = element('section', undefined, { class: 'alternative-freeze', 'aria-label': '고정 결과' });
  root.replaceChildren(element('h2', '내 버전'), element('p', MESSAGES.noReason), status, tabs, surface, actions, result);

  function say(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  function refusal(error) {
    const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
    say(ERROR_MESSAGES[code], code);
    return code;
  }

  function edited(next) {
    content = next;
    dirty = true;
    say(MESSAGES.unsaved, 'dirty');
    if (pending !== null) cancel(pending);
    pending = later(() => { pending = null; save().catch(() => {}); }, AUTOSAVE_MS);
  }

  function renderText() {
    const area = element('textarea', undefined, { rows: '16', 'aria-label': '내 버전 텍스트', spellcheck: 'false' });
    area.value = content;
    area.addEventListener('input', () => edited(area.value));
    surface.replaceChildren(area);
  }

  function renderTable() {
    const table = element('table', undefined, { class: 'alternative-table', 'aria-label': '내 버전 표' });
    content.forEach((row, rowIndex) => {
      const tr = element('tr');
      row.forEach((cell, columnIndex) => {
        const td = element('td');
        const input = element('input', undefined, { type: 'text',
          'aria-label': `${rowIndex + 1}행 ${columnIndex + 1}열` });
        input.value = cell;
        input.addEventListener('input', () => {
          const next = content.map(item => [...item]);
          next[rowIndex][columnIndex] = input.value;
          edited(next);
        });
        td.append(input);
        tr.append(td);
      });
      table.append(tr);
    });
    const addRow = element('button', '행 추가', { type: 'button' });
    addRow.addEventListener('click', () => {
      const width = Math.max(1, ...content.map(row => row.length));
      edited([...content.map(row => [...row]), Array(width).fill('')]);
      renderTable();
    });
    surface.replaceChildren(table, addRow);
  }

  function renderReadOnly(value) {
    if (target.format === 'text') {
      surface.replaceChildren(element('pre', value, { class: 'alternative-original', 'aria-label': '원본 텍스트' }));
      return;
    }
    const table = element('table', undefined, { class: 'alternative-table', 'aria-label': '원본 표' });
    for (const row of value) {
      const tr = element('tr');
      for (const cell of row) tr.append(element('td', cell));
      table.append(tr);
    }
    surface.replaceChildren(table);
  }

  async function show(next) {
    if (!VIEWS.includes(next)) fail('unknown view');
    if (target === null) fail('no artifact is open');
    view = next;
    for (const name of VIEWS) tabButtons[name].setAttribute('aria-pressed', name === view ? 'true' : 'false');
    actions.hidden = view !== 'mine';
    if (view === 'original') { renderReadOnly(originalContent); return null; }
    if (view === 'mine') { if (target.format === 'text') renderText(); else renderTable(); return null; }
    // the differences are observed on a saved revision: an unsaved edit is saved first
    if (pending !== null) { cancel(pending); pending = null; }
    if (dirty) await save();
    if (draft === null) {
      surface.replaceChildren(element('p', '아직 저장된 내 버전이 없어 차이가 없습니다.'));
      return null;
    }
    const observed = await request(routes.differences(target.runId, target.artifactId, draft.draftId), {});
    const list = element('ul', undefined, { class: 'alternative-differences', 'aria-label': '관측된 차이' });
    for (const item of observed.observations ?? []) list.append(element('li', String(item.description)));
    const notes = (observed.uncertainties ?? []).map(text => element('p', String(text), { class: 'alternative-uncertainty' }));
    surface.replaceChildren(element('p', observed.identical ? '원본과 같습니다.'
      : `수정본 ${observed.revision}에서 관측한 차이 ${observed.observations.length}개 (위치는 제안된 정렬입니다)`),
    list, ...notes);
    return observed;
  }

  function render() {
    tabs.hidden = false;
    view = 'mine';
    for (const name of VIEWS) tabButtons[name].setAttribute('aria-pressed', name === view ? 'true' : 'false');
    actions.hidden = false;
    if (target.format === 'text') renderText(); else renderTable();
    const reviewed = element('input', undefined, { type: 'checkbox', id: 'alternative-reviewed-whole' });
    reviewed.checked = false;
    const freezeButton = element('button', '분석용으로 고정', { type: 'button' });
    freezeButton.addEventListener('click', () => freeze(reviewed.checked === true).catch(() => {}));
    actions.replaceChildren(element('p', MESSAGES.partial), reviewed,
      element('label', MESSAGES.whole, { for: 'alternative-reviewed-whole' }), freezeButton);
  }

  async function open(runId, artifact) {
    requireUuid(runId, 'run id');
    if (!isEditable(artifact?.mediaType)) fail('this artifact is not editable here');
    const mine = ++generation;
    if (pending !== null) cancel(pending);
    pending = null;
    say(MESSAGES.loading, 'loading');
    result.replaceChildren();
    try {
      const listing = await request(routes.list(runId, artifact.artifactId), {});
      if (mine !== generation) return null;
      const format = listing?.original?.format;
      if (format !== 'text' && format !== 'table') fail('the draft listing is malformed', 'unavailable');
      target = { runId, artifactId: artifact.artifactId, format };
      originalContent = format === 'text' ? String(listing.original.text)
        : listing.original.rows.map(row => row.map(String));
      const drafts = Array.isArray(listing.drafts) ? listing.drafts : [];
      const latest = drafts.at(-1);
      if (latest) {
        const read = await request(routes.one(runId, artifact.artifactId, latest.draft_id), {});
        if (mine !== generation) return null;
        draft = { draftId: read.draft_id, revision: read.revision };
        content = format === 'text' ? String(read.text) : read.rows.map(row => row.map(String));
        say(`${MESSAGES.resumed} (수정본 ${read.revision})`, 'resumed');
      } else {
        draft = null;
        content = format === 'text' ? String(listing.original.text)
          : listing.original.rows.map(row => row.map(String));
        say(MESSAGES.original, 'original');
      }
      dirty = false;
      render();
      return { target, draft };
    } catch (error) {
      if (mine === generation) refusal(error);
      throw error;
    }
  }

  async function save({ asNew = false } = {}) {
    if (target === null) fail('no artifact is open');
    if (saving) return saving;
    if (!dirty && !asNew) return draft;
    const body = { schema_version: SAVE_SCHEMA, command_id: crypto.randomUUID(),
      draft_id: asNew || draft === null ? null : draft.draftId,
      expected_revision: asNew || draft === null ? 0 : draft.revision, format: target.format,
      ...(target.format === 'text' ? { text: content } : { rows: content }) };
    const sent = content;
    say(MESSAGES.saving, 'saving');
    saving = (async () => {
      try {
        const saved = await request(routes.list(target.runId, target.artifactId), { method: 'POST', body });
        draft = { draftId: saved.draft_id, revision: saved.revision };
        dirty = content !== sent;  // typing during the save keeps the newer text unsaved
        say(dirty ? MESSAGES.unsaved : `저장됨 (수정본 ${saved.revision})`, dirty ? 'dirty' : 'saved');
        return draft;
      } catch (error) {
        if (refusal(error) === 'conflict') offerRecovery();
        throw error;
      } finally {
        saving = null;
      }
    })();
    return saving;
  }

  function offerRecovery() {
    const reload = element('button', '최신 수정본 불러오기', { type: 'button' });
    reload.addEventListener('click', () => open(target.runId, { artifactId: target.artifactId,
      mediaType: target.format === 'text' ? 'text/plain' : 'text/csv' }).catch(() => {}));
    const keep = element('button', '지금 내용을 새 초안으로 저장', { type: 'button' });
    keep.addEventListener('click', () => save({ asNew: true }).catch(() => {}));
    result.replaceChildren(reload, keep);
  }

  async function freeze(reviewedWhole) {
    if (target === null) fail('no artifact is open');
    if (pending !== null) { cancel(pending); pending = null; }
    if (dirty || draft === null) await save({ asNew: false });
    if (draft === null) { say(MESSAGES.unchanged, 'invalid_input'); return null; }
    try {
      const frozen = await request(routes.freeze(target.runId, target.artifactId, draft.draftId), {
        method: 'POST', body: { schema_version: FREEZE_SCHEMA, command_id: crypto.randomUUID(),
          expected_revision: draft.revision, reviewed_whole: reviewedWhole === true } });
      const scope = frozen.coverage === 'whole' ? '전체를 내 버전으로 기록했습니다.'
        : `바꾼 부분 ${frozen.selectors.length}곳을 내 근거로 기록했습니다. 나머지는 검토하지 않은 영역입니다.`;
      result.replaceChildren(element('p', `${MESSAGES.frozen} (수정본 ${draft.revision})`),
        element('p', scope), element('p', '영향 범위는 따로 조사합니다.'));
      say(MESSAGES.frozen, 'frozen');
      return frozen;
    } catch (error) {
      if (error?.code === 'invalid_input') say(MESSAGES.unchanged, 'invalid_input'); else refusal(error);
      throw error;
    }
  }

  return Object.freeze({ open, save, freeze, show, get view() { return view; },
    get draft() { return draft; }, get dirty() { return dirty; }, get content() { return content; } });
}
