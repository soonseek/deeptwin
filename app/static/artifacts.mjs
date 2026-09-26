// T045: what a run produced, shown to the owner. It lists the run's artifacts
// (GET {base}api/v1/runs/{run}/artifacts) and, for the one the owner picks,
// the server's derived preview (…/{artifact}/preview): text and JSON as text,
// CSV as a table of text cells, an image as the original bytes the browser
// decodes (…/content, same origin), a PDF page as the PNG the isolated
// document worker rendered (…/pages/{n}/image, with page-by-page navigation
// through …/pages/{n}), a DOCX as the body and table text that worker
// extracted — and, when the worker is not connected, cannot answer or
// refuses the file, the plain disclosure of that, with the original always
// downloadable. Every piece of artifact content reaches the DOM through
// textContent or an attribute, never as markup; the preview's coverage (what
// was shown — bytes, pages or text parts — and what was left out) and its
// fidelity note are shown beside it, so a partial preview never reads as the
// whole artifact. `createArtifactIndex` is the vault-wide index
// (GET {base}api/v1/artifacts): bounded pages across every run, filtered by
// media type, each row opening its artifact in the viewer. The request is
// the supported session client's adapter (session.mjs) in the shell, a fake
// in tests.

import { formatBytes, mediaTypeLabel, shortId } from './ui-format.mjs';
import { technicalDetails } from './ui-parts.mjs';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
export const PREVIEW_KINDS = Object.freeze(['text', 'json', 'table', 'image', 'page_image', 'document_text',
  'codec_required', 'codec_failed', 'unsupported']);
export const MAX_ARTIFACTS = 256;
export const MAX_PAGES = 10000;
export const INDEX_LIMIT = 25;
// the media-type filters the index offers (exact declared types or a `type/*` family)
export const INDEX_FILTERS = Object.freeze([
  ['', '모든 형식'], ['application/pdf', 'PDF'],
  ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'DOCX'],
  ['image/*', '이미지'], ['text/*', '텍스트·CSV'], ['application/json', 'JSON'],
]);

export const MESSAGES = Object.freeze({
  idle: '실행을 선택하면 산출물을 보여 줍니다.',
  loading: '산출물을 불러오는 중…',
  empty: '이 실행이 남긴 산출물 파일이 없습니다.',
  previewing: '미리보기를 준비하는 중…',
  codec_required: '이 형식(PDF·DOCX 등)은 격리된 문서 변환 워커가 연결되어야 미리볼 수 있습니다. 원본은 내려받을 수 있습니다.',
  codec_too_large: '이 파일은 문서 변환 워커가 받는 크기 한도를 넘어 미리보지 않았습니다. 원본은 내려받을 수 있습니다.',
  codec_unavailable: '문서 변환 워커가 응답하지 않아 미리보지 못했습니다. 대신 보여 준 것은 없습니다. 원본은 내려받을 수 있습니다.',
  codec_failed: '문서 변환 워커가 이 파일을 읽지 못했거나 거부했습니다. 대신 보여 준 것은 없습니다. 원본은 내려받을 수 있습니다.',
  unsupported: '이 형식은 미리보기를 지원하지 않습니다. 원본은 내려받을 수 있습니다.',
  truncated: '미리보기가 잘렸습니다. 전체는 원본에 있습니다.',
  index_idle: '보관된 모든 실행의 산출물을 여기서 찾을 수 있습니다.',
  index_loading: '산출물 색인을 불러오는 중…',
  index_empty: '조건에 맞는 산출물이 없습니다.',
  // the listed type is the one the producer declared; the preview reads the bytes themselves
  declared: '형식은 산출물을 만든 쪽이 밝힌 값입니다. 미리보기는 실제 내용을 보고 보여 줄 방법을 고릅니다.',
});

export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '요청 형식이 맞지 않습니다.',
  unauthenticated: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다.',
  not_found: '해당 실행 또는 산출물을 찾지 못했습니다.',
  unavailable: '산출물을 읽지 못했습니다. 저장된 원본을 확인할 수 없거나 서버(또는 문서 변환 워커)가 응답하지 못했습니다.',
  range_not_satisfiable: '그 쪽은 이 문서에 없습니다.',
  too_large: '이 파일은 문서 변환 워커가 받는 크기 한도를 넘습니다. 원본은 내려받을 수 있습니다.',
  unsupported_media: '쪽 미리보기는 PDF에만 있습니다.',
  codec_failed: '문서 변환 워커가 이 쪽을 그리지 못했습니다. 대신 보여 준 것은 없습니다.',
});

// the parts a worker preview discloses as not shown, in the owner's words
const PART_LABELS = Object.freeze({
  annotations_interactive: '주석 상호작용', links: '링크', text_layer: '텍스트 층', forms: '양식',
  attachments: '첨부 파일', comments: '메모', footnotes: '각주', formatting: '서식',
  headers_footers: '머리글·바닥글', images: '이미지', text_boxes: '글상자', tracked_changes: '변경 내용 추적',
  text_beyond_bound: '한도 뒤의 본문', body_paragraphs: '본문 문단', table_cells: '표 셀',
});

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

function requireUuid(value, label) {
  if (typeof value !== 'string' || !UUID.test(value)) fail(`${label} is not a canonical UUID`);
  return value;
}

function requirePage(value) {
  if (!Number.isSafeInteger(value) || value < 1 || value > MAX_PAGES) fail('page is out of bounds');
  return value;
}

export function artifactRoutes(basePath = '/') {
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const api = `${basePath.slice(0, -1)}/api/v1`;
  const runs = `${api}/runs`;
  const one = (runId, artifactId) =>
    `${runs}/${requireUuid(runId, 'run id')}/artifacts/${requireUuid(artifactId, 'artifact id')}`;
  return Object.freeze({
    list: runId => `${runs}/${requireUuid(runId, 'run id')}/artifacts`,
    read: one,
    content: (runId, artifactId) => `${one(runId, artifactId)}/content`,
    preview: (runId, artifactId) => `${one(runId, artifactId)}/preview`,
    page: (runId, artifactId, page) => `${one(runId, artifactId)}/pages/${requirePage(page)}`,
    pageImage: (runId, artifactId, page) => `${one(runId, artifactId)}/pages/${requirePage(page)}/image`,
    index: `${api}/artifacts`,
  });
}

// a human size, spelled out (never colour or an icon alone)
export function sizeText(bytes) {
  if (!Number.isSafeInteger(bytes) || bytes < 0) fail('size must be a byte count');
  return formatBytes(bytes);
}

// the raw facts of one listed artifact, folded under "기술 정보"
function artifactTechnical(document, item) {
  const lines = [['산출물 ID', item.artifactId], ['밝힌 형식', item.mediaType], ['SHA-256', item.sha256]];
  if (item.runId) lines.unshift(['실행 ID', item.runId]);
  return technicalDetails(document, lines);
}

function artifactItem(item) {
  if (typeof item !== 'object' || item === null) fail('an artifact is malformed', 'unavailable');
  requireUuid(item.artifact_id, 'artifact id');
  for (const name of ['role', 'declared_media_type', 'sha256', 'availability']) {
    if (typeof item[name] !== 'string') fail(`artifact ${name} is malformed`, 'unavailable');
  }
  if (!Number.isSafeInteger(item.size) || !Number.isSafeInteger(item.ordinal)) fail('artifact size is malformed', 'unavailable');
  return {
    artifactId: item.artifact_id, role: item.role, nodeId: typeof item.node_id === 'string' ? item.node_id : null,
    ordinal: item.ordinal, mediaType: item.declared_media_type, size: item.size,
    sha256: item.sha256, available: item.availability === 'available',
  };
}

export function artifactList(payload) {
  if (typeof payload !== 'object' || payload === null || !Array.isArray(payload.artifacts)
      || payload.artifacts.length > MAX_ARTIFACTS) fail('the artifact list is malformed', 'unavailable');
  return payload.artifacts.map(item => Object.freeze(artifactItem(item)));
}

export function indexPage(payload) {
  if (typeof payload !== 'object' || payload === null || !Array.isArray(payload.artifacts)
      || payload.artifacts.length > 100 || !Number.isSafeInteger(payload.total)
      || (payload.next_cursor !== null && (typeof payload.next_cursor !== 'string' || !/^\d{1,9}$/.test(payload.next_cursor)))
      || typeof payload.runs !== 'object' || payload.runs === null) {
    fail('the artifact index is malformed', 'unavailable');
  }
  const items = payload.artifacts.map(item => Object.freeze({ ...artifactItem(item), runId: requireUuid(item.run_id, 'run id') }));
  const runs = payload.runs;
  for (const name of ['scanned', 'unreadable', 'omitted']) {
    if (!Number.isSafeInteger(runs[name]) || runs[name] < 0) fail('the index run counts are malformed', 'unavailable');
  }
  return Object.freeze({ items: Object.freeze(items), total: payload.total, nextCursor: payload.next_cursor,
    runs: Object.freeze({ scanned: runs.scanned, unreadable: runs.unreadable, omitted: runs.omitted }) });
}

export function previewView(payload) {
  const preview = payload?.preview;
  if (typeof preview !== 'object' || preview === null || !PREVIEW_KINDS.includes(preview.kind)) {
    fail('the preview is malformed', 'unavailable');
  }
  const coverage = preview.coverage;
  if (typeof coverage !== 'object' || coverage === null || !Array.isArray(coverage.covered)
      || !Array.isArray(coverage.omissions) || !Number.isSafeInteger(coverage.original_bytes)) {
    fail('the preview coverage is malformed', 'unavailable');
  }
  const unit = coverage.unit ?? 'byte';
  if (!['byte', 'page', 'text_layer'].includes(unit)) fail('the preview coverage unit is unknown', 'unavailable');
  const body = preview.body ?? {};
  if (preview.kind === 'page_image') {
    if (unit !== 'page' || !Number.isSafeInteger(body.page) || !Number.isSafeInteger(body.page_count)
        || body.page < 1 || body.page > body.page_count || body.page_count > MAX_PAGES
        || !Number.isSafeInteger(body.width) || !Number.isSafeInteger(body.height)) {
      fail('the page preview is malformed', 'unavailable');
    }
  }
  const shown = unit === 'byte' ? coverage.covered.reduce((sum, [start, end]) => sum + (end - start), 0) : 0;
  return Object.freeze({
    kind: preview.kind, body, fidelity: String(preview.fidelity ?? ''),
    derived: preview.derived === true, sha256: preview.sha256 ?? null, unit,
    originalBytes: coverage.original_bytes, shownBytes: shown,
    covered: coverage.covered, omissions: coverage.omissions,
    notRendered: Array.isArray(coverage.not_rendered) ? coverage.not_rendered : [],
    truncated: unit === 'byte' ? coverage.omissions.length > 0 || body.truncated === true : body.truncated === true,
  });
}

function partsText(names) {
  return names.map(name => PART_LABELS[name] ?? String(name)).join(', ');
}

export function coverageText(view) {
  if (['codec_required', 'codec_failed', 'unsupported'].includes(view.kind)) return '';
  if (view.unit === 'page') {
    return `전체 ${view.body.page_count}쪽 중 ${view.body.page}쪽 표시 (${view.body.width}×${view.body.height} 픽셀)`
      + (view.notRendered.length ? ` — 이미지에 없는 것: ${partsText(view.notRendered)}` : '');
  }
  if (view.unit === 'text_layer') {
    const counts = `본문 문단 ${view.body.paragraphs ?? 0}개, 표 ${view.body.tables ?? 0}개(셀 ${view.body.table_cells ?? 0}개)의 텍스트`;
    const left = view.omissions.length ? ` — 포함하지 않은 것: ${partsText(view.omissions)}` : '';
    return `${counts}${left}` + (view.truncated ? ` — ${MESSAGES.truncated}` : '');
  }
  const base = `원본 ${sizeText(view.originalBytes)} 중 ${sizeText(view.shownBytes)} 표시`;
  return view.truncated ? `${base} — ${MESSAGES.truncated}` : base;
}

function disclosureText(view) {
  if (view.kind === 'codec_required') {
    const reason = view.body?.reason;
    return reason === 'too_large' ? MESSAGES.codec_too_large
      : reason === 'unavailable' ? MESSAGES.codec_unavailable : MESSAGES.codec_required;
  }
  return MESSAGES[view.kind];
}

// `onEdit(runId, item)`, when given, offers the owner's in-place editor (alternatives.mjs)
// for the formats it edits; the viewer itself never changes an artifact
const EDITABLE = new Set(['text/plain', 'text/markdown', 'application/json', 'text/csv']);

function builder(document) {
  return function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  };
}

// `title` null leaves the heading to the page (the run detail's 산출물 tab names it).
// `filter(ids, …)` narrows the loaded list to one selection's artifacts (UI phase 3: selecting a
// node shows THAT node's artifacts); `onEdit(runId, item, context)` and
// `onAlternativeFile(runId, item, context)` get `context.slot`, the place beside the list where
// the page opens the owner's version in place, and `context.anchor`, the artifact's row.
export function createArtifactViewer({ root, document, request, basePath = '/', onEdit, onAlternativeFile,
  title = '산출물' } = {}) {
  if (typeof root !== 'object' || root === null || typeof root.replaceChildren !== 'function') fail('a root element is required');
  if (typeof document !== 'object' || document === null || typeof document.createElement !== 'function') fail('a document is required');
  if (typeof request !== 'function') fail('an injected request function is required');
  const routes = artifactRoutes(basePath);
  const element = builder(document);
  let runId = null;
  let generation = 0;
  let previewGeneration = 0;
  let loaded = [];
  let filtering = null;  // { ids, label, nodeId, editContext } or null for the whole run
  let producerOf = null;  // artifact id -> the node whose visit first recorded it (the run trace)

  const status = element('p', MESSAGES.idle, { role: 'status', 'aria-live': 'polite' });
  const note = element('p', MESSAGES.declared, { class: 'artifact-note' });
  note.hidden = true;
  const list = element('ul', undefined, { class: 'artifact-list' });
  const editorSlot = element('div', undefined, { class: 'editor-slot artifact-editor-slot' });
  const viewer = element('section', undefined, { class: 'artifact-viewer', 'aria-label': '산출물 미리보기' });
  root.replaceChildren(...(title === null ? [] : [element('h2', title)]), status, note, list, editorSlot, viewer);

  function refusal(error) {
    const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
    status.dataset.state = code;
    status.textContent = ERROR_MESSAGES[code];
  }

  function row(item) {
    const entry = element('li', undefined, { 'data-artifact-id': item.artifactId });
    // a filtered list names the selected node: one result forwarded by several steps is
    // listed once by the run, under whichever visit the server met first
    const nodeId = filtering?.nodeId ?? producerOf?.[item.artifactId] ?? item.nodeId;
    const label = `${item.role} · ${nodeId ?? '노드 미상'} · ${mediaTypeLabel(item.mediaType)} · ${sizeText(item.size)}`
      + (item.available ? '' : ' · 원본 없음');
    entry.append(element('span', label, { class: 'artifact-label' }));
    const show = element('button', '미리보기', { type: 'button' });
    show.addEventListener('click', () => preview(item.artifactId).catch(() => {}));
    const download = element('a', '원본 내려받기', { href: routes.content(runId, item.artifactId),
      download: `${item.role}-${item.ordinal}`, rel: 'noopener' });
    entry.append(show, download);
    const context = () => ({ slot: editorSlot, anchor: entry,
      title: filtering?.editContext ? filtering.editContext.title(item.role) : `${item.role} (${item.nodeId ?? '노드 미상'})` });
    if (typeof onAlternativeFile === 'function') {
      // any format may be answered with the owner's own file (alternative-file.mjs)
      const answer = element('button', '대안 파일 올리기', { type: 'button' });
      answer.addEventListener('click', () => Promise.resolve(onAlternativeFile(runId, item, context())).catch(() => {}));
      entry.append(answer);
    }
    if (typeof onEdit === 'function' && EDITABLE.has(item.mediaType)) {
      const edit = element('button', '내 버전 편집', { type: 'button' });
      edit.addEventListener('click', () => Promise.resolve(onEdit(runId, item, context())).catch(() => {}));
      entry.append(edit);
    }
    entry.append(artifactTechnical(document, item));
    return entry;
  }

  function renderList() {
    const items = filtering === null ? loaded : loaded.filter(item => filtering.ids.includes(item.artifactId));
    list.replaceChildren(...items.map(row));
    note.hidden = items.length === 0;
    if (filtering === null) {
      status.dataset.state = items.length ? 'listed' : 'empty';
      status.textContent = items.length ? `산출물 ${items.length}개` : MESSAGES.empty;
    } else {
      status.dataset.state = items.length ? 'filtered' : 'filtered-empty';
      status.textContent = items.length ? `${filtering.label ?? '선택한 단계의'} 산출물 ${items.length}개`
        : `${filtering.label ?? '선택한 단계의'} 산출물이 없습니다.`;
    }
    // a preview of an artifact outside the narrowed list is not left beside it
    const previewed = viewer.dataset.artifactId;
    if (previewed && !items.some(item => item.artifactId === previewed)) {
      previewGeneration += 1;
      viewer.replaceChildren();
      viewer.dataset.artifactId = '';
    }
    return items;
  }

  function filter(ids, options = {}) {
    if (ids !== null && (!Array.isArray(ids) || ids.some(id => typeof id !== 'string' || !UUID.test(id)))) {
      fail('filter ids must be artifact ids');
    }
    filtering = ids === null ? null : Object.freeze({ ids: [...ids], label: options.label ?? null,
      nodeId: options.nodeId ?? null, editContext: options.editContext ?? null });
    if (options.producers !== undefined) producerOf = options.producers;
    return runId === null ? [] : renderList();
  }

  function pageNavigation(view, artifactId) {
    const nav = element('nav', undefined, { class: 'artifact-pages', 'aria-label': '쪽 이동' });
    const { page, page_count: count } = view.body;
    const previous = element('button', '이전 쪽', { type: 'button' });
    previous.disabled = page <= 1;
    previous.addEventListener('click', () => showPage(artifactId, page - 1).catch(() => {}));
    const next = element('button', '다음 쪽', { type: 'button' });
    next.disabled = page >= count;
    next.addEventListener('click', () => showPage(artifactId, page + 1).catch(() => {}));
    nav.append(previous, element('span', `${page} / ${count}쪽`, { class: 'artifact-page-number' }), next);
    return nav;
  }

  function render(view, artifactId) {
    const parts = [];
    if (view.kind === 'text' || view.kind === 'json' || view.kind === 'document_text') {
      parts.push(element('pre', String(view.body.text ?? ''), { class: 'artifact-text' }));
    } else if (view.kind === 'table') {
      const table = element('table', undefined, { class: 'artifact-table' });
      for (const cells of Array.isArray(view.body.rows) ? view.body.rows : []) {
        const tr = element('tr');
        for (const cell of Array.isArray(cells) ? cells : []) tr.append(element('td', String(cell)));
        table.append(tr);
      }
      parts.push(table);
    } else if (view.kind === 'image') {
      parts.push(element('img', undefined, { src: routes.content(runId, artifactId), alt: '실행 산출물 이미지',
        class: 'artifact-image' }));
    } else if (view.kind === 'page_image') {
      parts.push(pageNavigation(view, artifactId));
      parts.push(element('img', undefined, { src: routes.pageImage(runId, artifactId, view.body.page),
        alt: `실행 산출물 PDF ${view.body.page}쪽 (문서 변환 워커가 그린 이미지)`, class: 'artifact-image artifact-page',
        width: String(view.body.width), height: String(view.body.height), 'data-page': String(view.body.page) }));
    } else {
      parts.push(element('p', disclosureText(view)));
    }
    const facts = element('p', coverageText(view), { class: 'artifact-coverage' });
    const fidelity = element('p', view.fidelity, { class: 'artifact-fidelity' });
    const digest = view.derived && typeof view.sha256 === 'string'
      ? [element('p', `미리보기 SHA-256 ${view.sha256.slice(0, 12)}`, { class: 'artifact-digest', title: `SHA-256 ${view.sha256}` })]
      : [];
    viewer.replaceChildren(...parts, facts, fidelity, ...digest);
    viewer.dataset.kind = view.kind;
    viewer.dataset.artifactId = artifactId;
  }

  async function show(nextRunId, { keepFilter = false } = {}) {
    runId = requireUuid(nextRunId, 'run id');
    const mine = ++generation;
    previewGeneration += 1;
    if (!keepFilter) filtering = null;
    status.dataset.state = 'loading';
    status.textContent = MESSAGES.loading;
    list.replaceChildren();
    viewer.replaceChildren();
    viewer.dataset.artifactId = '';
    note.hidden = true;
    try {
      const items = artifactList(await request(routes.list(runId), {}));
      if (mine !== generation) return null;
      loaded = items;
      renderList();
      return items;
    } catch (error) {
      if (mine === generation) refusal(error);
      throw error;
    }
  }

  async function load(path, artifactId) {
    const mine = generation;
    const shown = ++previewGeneration;
    viewer.replaceChildren(element('p', MESSAGES.previewing));
    try {
      const view = previewView(await request(path, {}));
      if (mine !== generation || shown !== previewGeneration) return null;
      render(view, artifactId);
      return view;
    } catch (error) {
      if (mine === generation && shown === previewGeneration) {
        refusal(error);
        viewer.replaceChildren();
      }
      throw error;
    }
  }

  async function preview(artifactId) {
    if (runId === null) fail('no run is shown');
    requireUuid(artifactId, 'artifact id');
    return load(routes.preview(runId, artifactId), artifactId);
  }

  async function showPage(artifactId, page) {
    if (runId === null) fail('no run is shown');
    requireUuid(artifactId, 'artifact id');
    return load(routes.page(runId, artifactId, requirePage(page)), artifactId);
  }

  // the index's entry: the run's list, then that artifact's preview
  async function open(nextRunId, artifactId) {
    requireUuid(artifactId, 'artifact id');
    const items = await show(nextRunId);
    if (items === null) return null;
    return preview(artifactId);
  }

  return Object.freeze({ show, preview, showPage, open, filter, editorSlot,
    get runId() { return runId; }, get items() { return loaded; }, get filtered() { return filtering !== null; } });
}

export function createArtifactIndex({ root, document, request, basePath = '/', onOpen } = {}) {
  if (typeof root !== 'object' || root === null || typeof root.replaceChildren !== 'function') fail('a root element is required');
  if (typeof document !== 'object' || document === null || typeof document.createElement !== 'function') fail('a document is required');
  if (typeof request !== 'function') fail('an injected request function is required');
  if (typeof onOpen !== 'function') fail('an open callback is required');
  const routes = artifactRoutes(basePath);
  const element = builder(document);
  let generation = 0;
  let filter = '';
  let items = [];
  let nextCursor = null;

  const status = element('p', MESSAGES.index_idle, { role: 'status', 'aria-live': 'polite' });
  const select = element('select', undefined, { 'aria-label': '산출물 형식 필터' });
  for (const [value, label] of INDEX_FILTERS) {
    const option = element('option', label);
    option.value = value;
    select.append(option);
  }
  const reload = element('button', '색인 다시 읽기', { type: 'button' });
  const list = element('ul', undefined, { class: 'artifact-index-list' });
  const more = element('button', '더 보기', { type: 'button' });
  more.disabled = true;
  const note = element('p', MESSAGES.declared, { class: 'artifact-note' });
  root.replaceChildren(element('h2', '모든 산출물'), status, select, reload, note, list, more);

  function row(item) {
    const entry = element('li', undefined, { 'data-artifact-id': item.artifactId, 'data-run-id': item.runId });
    entry.append(element('span', `${item.role} · ${mediaTypeLabel(item.mediaType)} · ${sizeText(item.size)} · 실행 ${shortId(item.runId)}`
      + (item.available ? '' : ' · 원본 없음'), { class: 'artifact-label' }));
    const open = element('button', '열기', { type: 'button' });
    open.addEventListener('click', () => Promise.resolve(onOpen(item.runId, item.artifactId)).catch(() => {}));
    entry.append(open, artifactTechnical(document, item));
    return entry;
  }

  function statusText(page) {
    const base = items.length ? `산출물 ${page.total}개 중 ${items.length}개 표시` : MESSAGES.index_empty;
    const notes = [];
    if (page.runs.unreadable) notes.push(`읽지 못한 실행 ${page.runs.unreadable}개`);
    if (page.runs.omitted) notes.push(`색인 한도 밖의 실행 ${page.runs.omitted}개`);
    return notes.length ? `${base} (${notes.join(', ')})` : base;
  }

  async function read({ append = false } = {}) {
    const mine = ++generation;
    const query = { limit: String(INDEX_LIMIT) };
    if (filter) query.media_type = filter;
    if (append && nextCursor !== null) query.cursor = nextCursor;
    status.dataset.state = 'loading';
    status.textContent = MESSAGES.index_loading;
    more.disabled = true;
    try {
      const page = indexPage(await request(routes.index, { query }));
      if (mine !== generation) return null;
      items = append ? [...items, ...page.items] : [...page.items];
      nextCursor = page.nextCursor;
      list.replaceChildren(...items.map(row));
      status.dataset.state = items.length ? 'listed' : 'empty';
      status.textContent = statusText(page);
      more.disabled = nextCursor === null;
      return page;
    } catch (error) {
      if (mine === generation) {
        const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
        status.dataset.state = code;
        status.textContent = ERROR_MESSAGES[code];
        more.disabled = nextCursor === null;
      }
      throw error;
    }
  }

  select.addEventListener('change', () => {
    const value = select.value;
    filter = INDEX_FILTERS.some(([known]) => known === value) ? value : '';  // a DOM edit is not a filter
    nextCursor = null;
    read().catch(() => {});
  });
  reload.addEventListener('click', () => { nextCursor = null; read().catch(() => {}); });
  more.addEventListener('click', () => read({ append: true }).catch(() => {}));

  return Object.freeze({
    refresh: () => { nextCursor = null; return read(); },
    more: () => read({ append: true }),
    setFilter(value) {
      if (!INDEX_FILTERS.some(([known]) => known === value)) fail('unknown filter');
      filter = value;
      select.value = value;
      nextCursor = null;
      return read();
    },
    get items() { return items; },
  });
}
