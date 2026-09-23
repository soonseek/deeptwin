// T073 (US7): the owner exports one work from the work screen — never required,
// always reachable. The owner picks categories (hidden reasoning and credentials
// are not selectable at all) and whether raw originals are included, and first
// sees the ACTUAL preview the server computed: every item with its content mode
// and size, and every omission with its closed-set reason. Consent is a separate
// explicit check bound to that exact preview digest (records.mjs exportConsent);
// a work changed after the preview is refused by the server and shown as such.
// The finished bundle is downloaded from the same origin, beside its SHA-256.
// All server text reaches the DOM through textContent or attributes only.

import { EXPORT_CATEGORIES, exportConsent, previewSummary } from './records.mjs';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
export const PREVIEW_SCHEMA = 'work-export-preview-v1';
export const CONFIRM_SCHEMA = 'work-export-confirm-v1';

export const CATEGORY_LABELS = Object.freeze({
  originals: '작업 설명 원문',
  events: '개정 기록',
  artifacts_metadata: '첨부 자료 목록',
  model_final_responses: '모델 최종 응답',
  tool_observations: '도구 관측',
  alternatives: '내 버전',
  evaluation_evidence: '평가 근거',
});

export const REASON_LABELS = Object.freeze({
  not_selected: '선택하지 않음',
  unavailable: '이 서버가 아직 모으지 않음',
  not_recorded: '기록이 없음',
  redacted: '가림 처리됨',
  deleted: '삭제됨',
  access_denied: '접근 불가',
  rights_restricted: '권리 제한',
});

export const MODE_LABELS = Object.freeze({
  raw: '원문 포함', metadata_only: '원문 제외(메타데이터만)', redacted: '가림 처리',
});

export const MESSAGES = Object.freeze({
  optional: '내보내기는 선택 사항입니다. 내보내지 않아도 작업은 끝까지 진행됩니다.',
  unsaved: '먼저 설명을 이 인스턴스에 저장하면 내보낼 수 있습니다.',
  choose: '내보낼 범주를 하나 이상 고르세요.',
  previewing: '실제로 포함될 내용을 확인하는 중…',
  nothing: '선택한 범주에 지금 내보낼 내용이 없습니다.',
  consent: '위 미리보기 그대로 내보내는 것에 동의합니다.',
  needConsent: '미리보기 내용에 동의해야 내보낼 수 있습니다.',
  exporting: '내보내기 묶음을 만드는 중…',
  stale: '미리보기 이후 작업이 바뀌었습니다. 다시 미리보기 하세요.',
});

export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '요청 형식이 맞지 않습니다.',
  unauthenticated: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다.',
  not_found: '작업을 찾지 못했습니다.',
  conflict: MESSAGES.stale,
  too_large: '작업 기록이 너무 많아 이 화면에서 내보낼 수 없습니다.',
  unavailable: '내보내기를 처리하지 못했습니다.',
});

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

export function exportRoutes(basePath = '/') {
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const works = `${basePath.slice(0, -1)}/api/v1/works`;
  const work = id => {
    if (typeof id !== 'string' || !UUID.test(id)) fail('work id is not a canonical UUID');
    return `${works}/${id}/exports`;
  };
  return Object.freeze({
    preview: id => `${work(id)}/preview`,
    confirm: id => work(id),
    download: (id, bundleId) => {
      if (typeof bundleId !== 'string' || !UUID.test(bundleId)) fail('bundle id is not a canonical UUID');
      return `${work(id)}/${bundleId}`;
    },
  });
}

export function sizeText(bytes) {
  if (!Number.isInteger(bytes) || bytes < 0) return '크기 미상';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function createWorkExport({ root, document, basePath = '/', request, crypto, workId } = {}) {
  if (typeof root !== 'object' || root === null || typeof root.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  if (typeof workId !== 'function') fail('a work id source is required');
  if (typeof crypto?.randomUUID !== 'function') fail('a crypto with randomUUID is required');
  const routes = exportRoutes(basePath);

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', MESSAGES.optional, { role: 'status', 'aria-live': 'polite' });
  status.dataset.state = 'idle';
  const choices = element('fieldset', undefined, { class: 'export-categories' });
  choices.append(element('legend', '내보낼 범주'));
  const boxes = new Map();
  for (const category of EXPORT_CATEGORIES) {
    const id = `export-category-${category}`;
    const box = element('input', undefined, { type: 'checkbox', id, value: category });
    box.checked = category === 'originals' || category === 'events';
    const label = element('label', CATEGORY_LABELS[category], { for: id });
    boxes.set(category, box);
    choices.append(box, label);
  }
  const raw = element('input', undefined, { type: 'checkbox', id: 'export-include-raw' });
  raw.checked = false;
  const rawLabel = element('label', '작업 설명 원문을 그대로 포함(선택하지 않으면 원문은 빠집니다)',
    { for: 'export-include-raw' });
  const previewButton = element('button', '포함될 내용 미리보기', { type: 'button' });
  const shown = element('section', undefined, { class: 'export-preview', 'aria-label': '내보내기 미리보기' });
  root.replaceChildren(element('h2', '기록 내보내기'), status, choices, raw, rawLabel, previewButton, shown);

  let current = null;
  let generation = 0;

  function say(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  function refusal(error) {
    const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
    say(ERROR_MESSAGES[code], code);
  }

  function selection() {
    return EXPORT_CATEGORIES.filter(category => boxes.get(category).checked);
  }

  function renderPreview(value) {
    const summary = previewSummary(value);
    const parts = [];
    const items = element('ul', undefined, { class: 'export-items', 'aria-label': '포함될 항목' });
    for (const item of value.items) {
      items.append(element('li', `${item.label} · ${MODE_LABELS[item.content_mode] ?? item.content_mode}`
        + ` · ${sizeText(item.size_bytes)}`, { 'data-category': item.category }));
    }
    parts.push(element('h3', `포함될 항목 ${value.items.length}개`), items);
    const missing = element('ul', undefined, { class: 'export-missing', 'aria-label': '빠지는 범주' });
    for (const entry of summary.missing) {
      missing.append(element('li', `${CATEGORY_LABELS[entry.category] ?? entry.category}: `
        + `${REASON_LABELS[entry.reason] ?? entry.reason}`, { 'data-reason': entry.reason }));
    }
    parts.push(element('h3', '빠지는 범주와 이유'), missing);
    parts.push(element('p', `미리보기 SHA-256 ${summary.previewSha}`, { class: 'export-digest' }));
    if (!value.exportable) {
      parts.push(element('p', MESSAGES.nothing));
      shown.replaceChildren(...parts);
      say(MESSAGES.nothing, 'empty');
      return;
    }
    const agree = element('input', undefined, { type: 'checkbox', id: 'export-consent' });
    agree.checked = false;
    const go = element('button', '이 내용으로 내보내기', { type: 'button' });
    go.addEventListener('click', () => confirm(summary, agree).catch(() => {}));
    parts.push(agree, element('label', MESSAGES.consent, { for: 'export-consent' }), go);
    shown.replaceChildren(...parts);
    say(`포함될 항목 ${value.items.length}개를 확인하세요.`, 'previewed');
  }

  async function preview() {
    const id = workId();
    if (typeof id !== 'string' || !UUID.test(id)) {
      say(MESSAGES.unsaved, 'unsaved');
      return null;
    }
    const categories = selection();
    if (!categories.length) {
      say(MESSAGES.choose, 'invalid_input');
      return null;
    }
    const includeRaw = raw.checked === true && categories.includes('originals');
    const mine = ++generation;
    current = null;
    shown.replaceChildren();
    say(MESSAGES.previewing, 'previewing');
    try {
      const value = await request(routes.preview(id), { method: 'POST', body: {
        schema_version: PREVIEW_SCHEMA, request_id: crypto.randomUUID(), categories,
        include_raw: includeRaw } });
      if (mine !== generation) return null;
      renderPreview(value);
      current = { workId: id, value };
      return value;
    } catch (error) {
      if (mine === generation) refusal(error);
      throw error;
    }
  }

  async function confirm(summary, agree) {
    if (current === null) fail('no preview is shown');
    if (agree.checked !== true) {
      say(MESSAGES.needConsent, 'consent_required');
      return null;
    }
    const bound = exportConsent(summary, { confirmed: true, previewSha: current.value.preview_sha });
    const { workId: id, value } = current;
    const mine = generation;
    say(MESSAGES.exporting, 'exporting');
    try {
      const receipt = await request(routes.confirm(id), { method: 'POST', body: {
        schema_version: CONFIRM_SCHEMA, request_id: bound.request_id, categories: value.categories,
        include_raw: value.include_raw, preview_sha: bound.preview_sha, confirmed: true } });
      if (mine !== generation) return null;
      const link = element('a', '내보낸 묶음 내려받기', { href: routes.download(id, receipt.bundle_id),
        download: `deeptwin-export-${receipt.bundle_id}.zip`, rel: 'noopener' });
      shown.replaceChildren(element('p', `묶음 ${sizeText(receipt.size_bytes)} · 항목 ${receipt.item_count}개`),
        element('p', `묶음 SHA-256 ${receipt.bundle_sha256}`, { class: 'export-digest' }), link);
      current = null;
      say('내보내기 묶음을 만들었습니다. 어디에도 자동으로 전송하지 않았습니다.', 'exported');
      return receipt;
    } catch (error) {
      if (mine === generation) {
        refusal(error);
        if (error?.code === 'conflict') {
          current = null;
          shown.replaceChildren();
        }
      }
      throw error;
    }
  }

  previewButton.addEventListener('click', () => preview().catch(() => {}));
  return Object.freeze({ preview, get current() { return current; } });
}
