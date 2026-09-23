// T073 (US7, OPS-D04/AC06): the owner's explicit deletion of stored originals. Nothing
// is deleted automatically and nothing here is a required step. The panel lists the
// saved work's originals with their state. The owner picks some and reads the
// server's actual preview:
// - what would go
// - how many stored records name it (they stay, and the original then reads as deleted)
// - other works' sources holding the same bytes
// - what the deletion cannot reach (earlier backups, copies already exported or sent)
// Consent is a separate unchecked box bound to that preview's digest. A preview made
// stale by any change is refused and cleared. The result says, per original, whether
// the bytes' removal was confirmed or is still pending — never more than that.
// Server text reaches the DOM through textContent only.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
export const PREVIEW_SCHEMA = 'source-deletion-preview-command-v1';
export const CONFIRM_SCHEMA = 'source-deletion-command-v1';

export const REASONS = Object.freeze({ user_requested: '더는 필요하지 않음', rights_request: '권리·개인정보 요청' });

export const NOT_REACHED_LABELS = Object.freeze({
  backups_made_before_this_deletion: '이 삭제 전에 만든 백업',
  copies_already_exported_or_sent: '이미 내보내거나 보낸 사본',
  copies_outside_this_instance: '이 인스턴스 밖의 사본',
});

export const MESSAGES = Object.freeze({
  intro: '삭제는 선택 사항입니다. 자동으로 지워지는 원본은 없습니다. 지울 원본을 고르면 실제로 지워질 내용과 영향을 먼저 보여 드립니다.',
  unsaved: '저장된 업무가 없습니다. 원본을 저장한 뒤에 삭제를 고를 수 있습니다.',
  none: '저장된 원본이 없습니다.',
  choose: '지울 원본을 하나 이상 고르세요.',
  previewing: '실제로 지워질 내용을 확인하는 중…',
  kept: '이 원본을 가리키는 기록은 남고, 원본은 "삭제됨"으로 읽힙니다. 삭제는 되돌릴 수 없습니다.',
  consent: '위 미리보기 그대로 삭제하는 것에 동의합니다.',
  needConsent: '미리보기 내용에 동의해야 삭제할 수 있습니다.',
  deleting: '삭제하는 중…',
  stale: '미리보기 이후 업무나 원본이 바뀌었습니다. 다시 미리보기 하세요.',
});

export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '요청 형식이 맞지 않습니다.',
  unauthenticated: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다.',
  not_found: '선택한 원본을 이 업무에서 찾지 못했습니다.',
  conflict: MESSAGES.stale,
  unavailable: '삭제를 처리하지 못했습니다.',
});

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

export function deletionRoutes(basePath = '/') {
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const works = `${basePath.slice(0, -1)}/api/v1/works`;
  const work = id => {
    if (typeof id !== 'string' || !UUID.test(id)) fail('work id is not a canonical UUID');
    return `${works}/${id}`;
  };
  return Object.freeze({
    work,
    source: (id, sourceId) => {
      if (typeof sourceId !== 'string' || !UUID.test(sourceId)) fail('source id is not a canonical UUID');
      return `${work(id)}/sources/${sourceId}`;
    },
    preview: id => `${work(id)}/deletions/preview`,
    confirm: id => `${work(id)}/deletions`,
  });
}

export function sizeText(bytes) {
  if (!Number.isInteger(bytes) || bytes < 0) return '크기 미상';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function createSourceDeletion({ root, document, basePath = '/', request, crypto, workId } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  if (typeof workId !== 'function') fail('a work id source is required');
  if (typeof crypto?.randomUUID !== 'function') fail('a crypto with randomUUID is required');
  const routes = deletionRoutes(basePath);
  let current = null;  // { workId, view }
  let generation = 0;

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', MESSAGES.intro, { role: 'status', 'aria-live': 'polite' });
  status.dataset.state = 'idle';
  const list = element('ul', undefined, { class: 'deletion-sources', 'aria-label': '저장된 원본' });
  const reason = element('select', undefined, { id: 'deletion-reason', 'aria-label': '삭제 이유' });
  for (const [value, label] of Object.entries(REASONS)) {
    const option = element('option', label, { value });
    reason.append(option);
  }
  reason.value = 'user_requested';
  const previewButton = element('button', '삭제 미리보기', { type: 'button' });
  const shown = element('section', undefined, { class: 'deletion-preview', 'aria-label': '삭제 미리보기' });
  root.replaceChildren(element('h2', '원본 삭제'), status, list,
    element('label', '삭제 이유', { for: 'deletion-reason' }), reason, previewButton, shown);
  const boxes = new Map();

  function say(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  function refusal(error) {
    const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
    say(ERROR_MESSAGES[code], code);
  }

  async function load() {
    const id = workId();
    boxes.clear();
    current = null;
    shown.replaceChildren();
    if (typeof id !== 'string' || !UUID.test(id)) {
      list.replaceChildren();
      say(MESSAGES.unsaved, 'unsaved');
      return [];
    }
    const work = await request(routes.work(id), {});
    const refs = Array.isArray(work?.source_refs) ? work.source_refs : [];
    const rows = [];
    for (const ref of refs) {
      const detail = await request(routes.source(id, ref.id), {});
      const state = detail.original_state === 'deleted' ? 'deleted' : 'stored';
      const row = element('li', undefined, { 'data-state': state });
      const label = `${detail.artifact?.name ?? '이름 없는 원본'} · ${sizeText(detail.artifact?.size)}`
        + (state === 'deleted' ? ' · 삭제됨' : '');
      if (state === 'stored') {
        const box = element('input', undefined, { type: 'checkbox', id: `deletion-${ref.id}`, value: ref.id });
        box.checked = false;
        boxes.set(ref.id, box);
        row.append(box, element('label', label, { for: `deletion-${ref.id}` }));
      } else {
        row.append(element('span', label));
      }
      rows.push(row);
    }
    list.replaceChildren(...rows);
    say(rows.length ? MESSAGES.intro : MESSAGES.none, rows.length ? 'listed' : 'empty');
    return rows;
  }

  async function preview() {
    const id = workId();
    if (typeof id !== 'string' || !UUID.test(id)) { say(MESSAGES.unsaved, 'unsaved'); return null; }
    const chosen = [...boxes].filter(([, box]) => box.checked === true).map(([sourceId]) => sourceId);
    if (!chosen.length) { say(MESSAGES.choose, 'invalid_input'); return null; }
    const mine = ++generation;
    say(MESSAGES.previewing, 'previewing');
    try {
      const view = await request(routes.preview(id), { method: 'POST', body: {
        schema_version: PREVIEW_SCHEMA, request_id: crypto.randomUUID(), source_ids: chosen, reason_code: reason.value } });
      if (mine !== generation) return null;
      current = { workId: id, view };
      render(view);
      say('미리보기를 확인한 뒤 동의하면 삭제합니다.', 'previewed');
      return view;
    } catch (error) {
      if (mine === generation) refusal(error);
      throw error;
    }
  }

  function render(view) {
    const items = element('ul', undefined, { 'aria-label': '지워질 원본' });
    for (const item of view.items) {
      const shared = item.shared_with_other_sources.length
        ? ` · 같은 내용을 가진 다른 원본 ${item.shared_with_other_sources.length}개도 함께 "삭제됨"이 됩니다` : '';
      items.append(element('li', `${item.name} · ${sizeText(item.size)} · 이 원본을 가리키는 수정본 ${item.revisions_naming_it}개${shared}`));
    }
    const reach = element('ul', undefined, { 'aria-label': '이 삭제가 닿지 않는 곳' });
    for (const key of view.not_reached) reach.append(element('li', NOT_REACHED_LABELS[key] ?? key));
    const agree = element('input', undefined, { type: 'checkbox', id: 'deletion-consent' });
    agree.checked = false;
    const go = element('button', '선택한 원본 삭제', { type: 'button' });
    go.addEventListener('click', () => confirm(agree).catch(() => {}));
    shown.replaceChildren(items, element('p', `영향받는 기록 ${view.affected_record_count}개. ${MESSAGES.kept}`),
      element('h3', '이 삭제가 닿지 않는 곳'), reach,
      agree, element('label', MESSAGES.consent, { for: 'deletion-consent' }), go);
  }

  async function confirm(agree) {
    if (current === null) fail('no preview is shown');
    if (agree.checked !== true) { say(MESSAGES.needConsent, 'consent_required'); return null; }
    const { workId: id, view } = current;
    const mine = generation;
    say(MESSAGES.deleting, 'deleting');
    try {
      const result = await request(routes.confirm(id), { method: 'POST', body: {
        schema_version: CONFIRM_SCHEMA, request_id: view.request_id, source_ids: view.items.map(item => item.source_id),
        reason_code: view.reason_code, preview_sha256: view.preview_sha256, confirmed: true } });
      if (mine !== generation) return null;
      current = null;
      const pending = result.deleted.filter(item => item.bytes_removed !== true).length;
      await load();
      say(pending ? `삭제를 기록했습니다. 원본 ${pending}개는 파일 제거 확인이 아직 끝나지 않았습니다.`
        : `원본 ${result.deleted.length}개를 삭제했고 파일 제거를 확인했습니다. 이전 백업과 이미 보낸 사본에는 닿지 않습니다.`,
      pending ? 'cleanup_pending' : 'deleted');
      return result;
    } catch (error) {
      if (mine === generation) {
        refusal(error);
        if (error?.code === 'conflict') { current = null; shown.replaceChildren(); }
      }
      throw error;
    }
  }

  previewButton.addEventListener('click', () => preview().catch(() => {}));
  return Object.freeze({ load, preview, get current() { return current; } });
}
