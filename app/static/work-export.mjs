// T073 (US7): the owner exports one work from the work screen — never required,
// always reachable. The owner picks categories (hidden reasoning and credentials
// are not selectable at all) and whether raw originals are included, and first
// sees the ACTUAL preview the server computed: every item with its content mode
// and size, and every omission with its closed-set reason. Consent is a separate
// explicit check bound to that exact preview digest (records.mjs exportConsent);
// a work changed after the preview is refused by the server and shown as such.
// The finished bundle is downloaded from the same origin, beside its SHA-256.
// T074: when raw originals are chosen, the server scans them for credential shapes
// and the instance's own secrets. A finding is shown by kind and location only —
// never the matched value — and its raw original stays out unless the owner
// explicitly confirms that exact finding set, which re-previews with the set's
// digest (bound into the preview digest and carried by the confirmation).
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

export const FINDING_LABELS = Object.freeze({
  anthropic_api_key: 'Anthropic API 키 형태',
  provider_api_key: '제공자 API 키 형태(sk-…)',
  aws_access_key_id: 'AWS 액세스 키 ID 형태',
  aws_secret_access_key: 'AWS 비밀 액세스 키 지정',
  private_key_block: '개인 키(PEM) 블록',
  bearer_token: 'Bearer 토큰',
  instance_session_token: '이 인스턴스의 세션 토큰',
  instance_bootstrap_capability: '이 인스턴스의 초기 설정 토큰',
  unscanned_candidates: '검사 한도를 넘은 토큰 후보',
  unscanned_text: '검사 한도를 넘은 원문 부분',
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
  findings: '원문에서 비밀로 보이는 값을 찾았습니다. 값은 표시하지 않으며, 해당 원문은 제외됩니다.',
  confirmFindings: '위에 표시된 비밀 의심 값을 확인했고, 해당 원문을 그대로 포함합니다.',
  needFindings: '비밀 의심 값을 확인한다는 표시가 있어야 원문을 포함할 수 있습니다.',
  findingsConfirmed: '확인한 비밀 의심 값이 들어 있는 원문이 그대로 포함됩니다.',
  truncated: '찾은 값이 많아 일부만 표시했습니다.',
});

const HEX64 = /^[0-9a-f]{64}$/;

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

  function findingText(finding) {
    const revision = /revision-(\d+)\./.exec(String(finding.relative_path))?.[1] ?? '?';
    return `${FINDING_LABELS[finding.kind] ?? finding.kind} · 작업 설명 ${revision}판 `
      + `${Number(finding.line)}행 ${Number(finding.column)}열`;
  }

  function renderFindings(value, parts) {
    const scan = value.secret_scan;
    if (!scan || !Array.isArray(scan.findings) || !scan.findings.length) return;
    const list = element('ul', undefined, { class: 'export-findings', 'aria-label': '비밀 의심 값' });
    for (const finding of scan.findings) {
      list.append(element('li', findingText(finding), { 'data-kind': String(finding.kind) }));
    }
    parts.push(element('h3', `비밀 의심 값 ${scan.findings.length}개`), list);
    if (scan.truncated) parts.push(element('p', MESSAGES.truncated));
    if (scan.confirmed === true) {
      parts.push(element('p', MESSAGES.findingsConfirmed, { class: 'export-findings-state',
        'data-state': 'confirmed' }));
      return;
    }
    parts.push(element('p', MESSAGES.findings, { class: 'export-findings-state', 'data-state': 'withheld' }));
    if (typeof scan.findings_sha !== 'string' || !HEX64.test(scan.findings_sha)) return;
    const acknowledge = element('input', undefined, { type: 'checkbox', id: 'export-confirm-findings' });
    acknowledge.checked = false;
    const again = element('button', '확인한 값과 함께 원문 포함해 다시 미리보기', { type: 'button' });
    again.addEventListener('click', () => {
      if (acknowledge.checked !== true) {
        say(MESSAGES.needFindings, 'findings_required');
        return;
      }
      preview({ acknowledged: scan.findings_sha, selection: value }).catch(() => {});
    });
    parts.push(acknowledge, element('label', MESSAGES.confirmFindings, { for: 'export-confirm-findings' }), again);
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
    renderFindings(value, parts);
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

  // `acknowledged` re-previews the SAME selection the owner saw, with the exact finding set confirmed
  async function preview({ acknowledged = null, selection: shownSelection = null } = {}) {
    const id = workId();
    if (typeof id !== 'string' || !UUID.test(id)) {
      say(MESSAGES.unsaved, 'unsaved');
      return null;
    }
    if (acknowledged !== null && (typeof acknowledged !== 'string' || !HEX64.test(acknowledged)
        || shownSelection?.include_raw !== true)) fail('a finding confirmation needs the shown raw preview');
    const categories = acknowledged !== null ? [...shownSelection.categories] : selection();
    if (!categories.length) {
      say(MESSAGES.choose, 'invalid_input');
      return null;
    }
    const includeRaw = acknowledged !== null
      || (raw.checked === true && categories.includes('originals'));
    const mine = ++generation;
    current = null;
    shown.replaceChildren();
    say(MESSAGES.previewing, 'previewing');
    try {
      const body = { schema_version: PREVIEW_SCHEMA, request_id: crypto.randomUUID(), categories,
        include_raw: includeRaw };
      if (acknowledged !== null) body.acknowledged_findings_sha = acknowledged;
      const value = await request(routes.preview(id), { method: 'POST', body });
      if (mine !== generation) return null;
      renderPreview(value);
      current = { workId: id, value, acknowledged };
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
    const { workId: id, value, acknowledged } = current;
    const mine = generation;
    say(MESSAGES.exporting, 'exporting');
    try {
      const body = { schema_version: CONFIRM_SCHEMA, request_id: bound.request_id, categories: value.categories,
        include_raw: value.include_raw, preview_sha: bound.preview_sha, confirmed: true };
      if (acknowledged !== null) body.acknowledged_findings_sha = acknowledged;
      const receipt = await request(routes.confirm(id), { method: 'POST', body });
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
