// T045: what a run produced, shown to the owner. It lists the run's artifacts
// (GET {base}api/v1/runs/{run}/artifacts) and, for the one the owner picks,
// the server's derived preview (…/{artifact}/preview): text and JSON as text,
// CSV as a table of text cells, an image as the original bytes the browser
// decodes (…/content, same origin), and — for PDF, DOCX or anything else the
// server does not preview in-process — the plain disclosure that the codec
// worker is needed, with the original always downloadable. Every piece of
// artifact content reaches the DOM through textContent or an attribute,
// never as markup; the preview's coverage (what was shown, what was left
// out) and fidelity note are shown beside it, so a truncated preview never
// reads as the whole artifact. The request is the supported session client's
// adapter (session.mjs) in the shell, a fake in tests.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
export const PREVIEW_KINDS = Object.freeze(['text', 'json', 'table', 'image', 'codec_required', 'unsupported']);
export const MAX_ARTIFACTS = 256;

export const MESSAGES = Object.freeze({
  idle: '실행을 선택하면 산출물을 보여 줍니다.',
  loading: '산출물을 불러오는 중…',
  empty: '이 실행이 남긴 산출물 파일이 없습니다.',
  previewing: '미리보기를 준비하는 중…',
  codec_required: '이 형식(PDF·DOCX 등)은 격리된 문서 변환 워커가 연결되어야 미리볼 수 있습니다. 원본은 내려받을 수 있습니다.',
  unsupported: '이 형식은 미리보기를 지원하지 않습니다. 원본은 내려받을 수 있습니다.',
  truncated: '미리보기가 잘렸습니다. 전체는 원본에 있습니다.',
});

export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '요청 형식이 맞지 않습니다.',
  unauthenticated: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다.',
  not_found: '해당 실행 또는 산출물을 찾지 못했습니다.',
  unavailable: '산출물을 읽지 못했습니다. 저장된 원본을 확인할 수 없거나 서버가 응답하지 못했습니다.',
});

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

function requireUuid(value, label) {
  if (typeof value !== 'string' || !UUID.test(value)) fail(`${label} is not a canonical UUID`);
  return value;
}

export function artifactRoutes(basePath = '/') {
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const runs = `${basePath.slice(0, -1)}/api/v1/runs`;
  const one = (runId, artifactId) =>
    `${runs}/${requireUuid(runId, 'run id')}/artifacts/${requireUuid(artifactId, 'artifact id')}`;
  return Object.freeze({
    list: runId => `${runs}/${requireUuid(runId, 'run id')}/artifacts`,
    read: one,
    content: (runId, artifactId) => `${one(runId, artifactId)}/content`,
    preview: (runId, artifactId) => `${one(runId, artifactId)}/preview`,
  });
}

// a human size, spelled out (never colour or an icon alone)
export function sizeText(bytes) {
  if (!Number.isSafeInteger(bytes) || bytes < 0) fail('size must be a byte count');
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function artifactList(payload) {
  if (typeof payload !== 'object' || payload === null || !Array.isArray(payload.artifacts)
      || payload.artifacts.length > MAX_ARTIFACTS) fail('the artifact list is malformed', 'unavailable');
  return payload.artifacts.map(item => {
    if (typeof item !== 'object' || item === null) fail('an artifact is malformed', 'unavailable');
    requireUuid(item.artifact_id, 'artifact id');
    for (const name of ['role', 'declared_media_type', 'sha256', 'availability']) {
      if (typeof item[name] !== 'string') fail(`artifact ${name} is malformed`, 'unavailable');
    }
    if (!Number.isSafeInteger(item.size) || !Number.isSafeInteger(item.ordinal)) fail('artifact size is malformed', 'unavailable');
    return Object.freeze({
      artifactId: item.artifact_id, role: item.role, nodeId: typeof item.node_id === 'string' ? item.node_id : null,
      ordinal: item.ordinal, mediaType: item.declared_media_type, size: item.size,
      sha256: item.sha256, available: item.availability === 'available',
    });
  });
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
  const shown = coverage.covered.reduce((sum, [start, end]) => sum + (end - start), 0);
  return Object.freeze({
    kind: preview.kind, body: preview.body ?? {}, fidelity: String(preview.fidelity ?? ''),
    derived: preview.derived === true, sha256: preview.sha256 ?? null,
    originalBytes: coverage.original_bytes, shownBytes: shown,
    truncated: coverage.omissions.length > 0 || preview.body?.truncated === true,
  });
}

// `onEdit(runId, item)`, when given, offers the owner's in-place editor (alternatives.mjs)
// for the formats it edits; the viewer itself never changes an artifact
const EDITABLE = new Set(['text/plain', 'text/markdown', 'application/json', 'text/csv']);

export function createArtifactViewer({ root, document, request, basePath = '/', onEdit, onAlternativeFile } = {}) {
  if (typeof root !== 'object' || root === null || typeof root.replaceChildren !== 'function') fail('a root element is required');
  if (typeof document !== 'object' || document === null || typeof document.createElement !== 'function') fail('a document is required');
  if (typeof request !== 'function') fail('an injected request function is required');
  const routes = artifactRoutes(basePath);
  let runId = null;
  let generation = 0;

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', MESSAGES.idle, { role: 'status', 'aria-live': 'polite' });
  const list = element('ul', undefined, { class: 'artifact-list' });
  const viewer = element('section', undefined, { class: 'artifact-viewer', 'aria-label': '산출물 미리보기' });
  root.replaceChildren(element('h2', '산출물'), status, list, viewer);

  function refusal(error) {
    const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
    status.dataset.state = code;
    status.textContent = ERROR_MESSAGES[code];
  }

  function row(item) {
    const entry = element('li', undefined, { 'data-artifact-id': item.artifactId });
    const label = `${item.role} · ${item.nodeId ?? '노드 미상'} · ${item.mediaType} (선언) · ${sizeText(item.size)}`
      + (item.available ? '' : ' · 원본 없음');
    entry.append(element('span', label));
    entry.append(element('code', item.sha256.slice(0, 12), { title: `SHA-256 ${item.sha256}` }));
    const show = element('button', '미리보기', { type: 'button' });
    show.addEventListener('click', () => preview(item.artifactId).catch(() => {}));
    const download = element('a', '원본 내려받기', { href: routes.content(runId, item.artifactId),
      download: `${item.role}-${item.ordinal}`, rel: 'noopener' });
    entry.append(show, download);
    if (typeof onAlternativeFile === 'function') {
      // any format may be answered with the owner's own file (alternative-file.mjs)
      const answer = element('button', '대안 파일 올리기', { type: 'button' });
      answer.addEventListener('click', () => Promise.resolve(onAlternativeFile(runId, item)).catch(() => {}));
      entry.append(answer);
    }
    if (typeof onEdit === 'function' && EDITABLE.has(item.mediaType)) {
      const edit = element('button', '내 버전 편집', { type: 'button' });
      edit.addEventListener('click', () => Promise.resolve(onEdit(runId, item)).catch(() => {}));
      entry.append(edit);
    }
    return entry;
  }

  function coverageText(view) {
    if (view.kind === 'codec_required' || view.kind === 'unsupported') return '';
    const base = `원본 ${sizeText(view.originalBytes)} 중 ${sizeText(view.shownBytes)} 표시`;
    return view.truncated ? `${base} — ${MESSAGES.truncated}` : base;
  }

  function render(view, artifactId) {
    const parts = [];
    if (view.kind === 'text' || view.kind === 'json') {
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
    } else {
      parts.push(element('p', MESSAGES[view.kind]));
    }
    const facts = element('p', coverageText(view), { class: 'artifact-coverage' });
    const fidelity = element('p', view.fidelity, { class: 'artifact-fidelity' });
    viewer.replaceChildren(...parts, facts, fidelity);
    viewer.dataset.kind = view.kind;
  }

  async function show(nextRunId) {
    runId = requireUuid(nextRunId, 'run id');
    const mine = ++generation;
    status.dataset.state = 'loading';
    status.textContent = MESSAGES.loading;
    list.replaceChildren();
    viewer.replaceChildren();
    try {
      const items = artifactList(await request(routes.list(runId), {}));
      if (mine !== generation) return null;
      list.replaceChildren(...items.map(row));
      status.dataset.state = items.length ? 'listed' : 'empty';
      status.textContent = items.length ? `산출물 ${items.length}개` : MESSAGES.empty;
      return items;
    } catch (error) {
      if (mine === generation) refusal(error);
      throw error;
    }
  }

  async function preview(artifactId) {
    if (runId === null) fail('no run is shown');
    requireUuid(artifactId, 'artifact id');
    const mine = generation;
    viewer.replaceChildren(element('p', MESSAGES.previewing));
    try {
      const view = previewView(await request(routes.preview(runId, artifactId), {}));
      if (mine !== generation) return null;
      render(view, artifactId);
      return view;
    } catch (error) {
      if (mine === generation) {
        refusal(error);
        viewer.replaceChildren();
      }
      throw error;
    }
  }

  return Object.freeze({ show, preview, get runId() { return runId; } });
}
