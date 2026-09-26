// T073 (US7): the records page's retention section — what this instance keeps, for how
// long, what the owner may clean up and what is never deleted and why, all from the
// server's own state (GET {base}api/v1/retention). Nothing is ever deleted
// automatically.
// - Per category: what is kept and for how long, that nothing is deleted automatically,
//   where (if anywhere) the owner may clean it up, and the counts the server holds.
//   Core records and deletion tombstones are never offered; originals are deleted on the
//   work screen with their own preview; the newest backup is always kept.
// - Cleanup: the owner ticks eligible items (older backups, failed/abandoned/staged
//   restores), sees the server-computed preview (exact items, bytes, what goes, what
//   stays, what a cleanup cannot reach, its digest), and consents to exactly that
//   preview with a separate unchecked box (records.mjs cleanupConsent). A scope that
//   changed since the preview is refused by the server and shown as stale. Each removed
//   item leaves its tombstone; the cleanup receipt is listed.
// All server text reaches the DOM through textContent or attributes only.

import { cleanupConsent, cleanupPreviewSummary, retentionState } from './records.mjs';

const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
export const PREVIEW_SCHEMA = 'retention-cleanup-preview-v1';

export const CATEGORY_LABELS = Object.freeze({
  core_records: '핵심 기록(기록·계보·사건 기록)', deletion_tombstones: '삭제 표시(tombstone)',
  originals: '저장한 원본', backups: '암호화된 백업', staged_restores: '스테이징된 복원본',
  regenerable_caches: '다시 만들 수 있는 캐시', raw_audio: '원시 음성',
});

export const KEPT_LABELS = Object.freeze({
  forever: '기한 없이 보존', until_owner_deletes: '소유자가 지울 때까지 보존',
  until_owner_cleanup: '소유자가 정리할 때까지 보존', not_stored: '저장하지 않음',
});

export const CLEANUP_LABELS = Object.freeze({
  not_offered: '정리 대상이 아닙니다', work_screen: '업무 화면의 "원본 삭제"에서 미리보기와 동의를 거쳐 지웁니다',
  this_screen: '아래에서 미리보기와 동의를 거쳐 정리할 수 있습니다', nothing_stored: '저장된 것이 없어 정리할 것이 없습니다',
});

export const REASON_LABELS = Object.freeze({
  append_only_history: '기록은 덧붙이기만 하는 이력이라 지우지 않습니다(다른 기록의 근거가 됩니다)',
  record_of_a_deletion: '무엇을 지웠는지의 기록이라 지우지 않습니다',
  source_deletion_with_its_own_preview: '원본마다 따로 미리보기와 동의를 거칩니다',
  newest_backup_kept: '가장 최근 백업은 항상 남깁니다',
  staged_copy_never_activated_here: '복원본은 이 화면에서 활성화되지 않고, 소유자가 버릴 수 있습니다',
  no_cache_is_stored: '이 서버는 캐시를 디스크에 저장하지 않습니다',
  ephemeral_only: '음성은 처리 중에만 잠시 있고 저장하지 않습니다',
  older_backup: '더 최근 백업이 있습니다', failed_restore: '실패한 복원의 남은 자리입니다',
  staged_copy_not_activated: '검토 대기 중인 복원본(복호화된 사본)입니다',
  stale_awaiting_bundle: '백업 파일을 받지 못한 채 오래된 복원입니다',
  awaiting_bundle_recently_begun: '방금 시작한 복원이라 아직 정리하지 않습니다',
});

export const REMOVES_LABELS = Object.freeze({
  encrypted_backup_file: '암호화된 백업 파일', staged_restore_copy: '스테이징된 복원본과 남은 파일',
});

export const KEEPS_LABELS = Object.freeze({
  external_receipt: '외부 영수증', consent_record: '동의 기록', tombstone: '삭제 표시',
  restore_status: '복원 상태 기록',
});

export const NOT_REACHED_LABELS = Object.freeze({
  copies_already_downloaded: '이미 내려받은 사본', copies_outside_this_instance: '이 인스턴스 밖의 사본',
});

export const NEVER_LABELS = Object.freeze({
  core_records: '핵심 기록', deletion_tombstones: '삭제 표시', originals: '저장한 원본(업무 화면에서만 삭제)',
  newest_backup: '가장 최근 백업',
});

export const MESSAGES = Object.freeze({
  automatic: '자동 삭제는 없습니다. 기록과 원본은 명시적으로 지우기 전까지 보존되고, 백업도 자동으로 지우지 않습니다.',
  loading: '보존 상태를 불러오는 중…',
  none: '지금 정리할 수 있는 항목이 없습니다.',
  pick: '정리할 항목을 하나 이상 고르세요.',
  previewing: '정리될 내용을 서버에서 계산하는 중…',
  consent: '위 미리보기 그대로 정리하는 것에 동의합니다. 되돌릴 수 없습니다.',
  needConsent: '미리보기 내용에 동의해야 정리할 수 있습니다.',
  cleaning: '삭제 표시를 먼저 남기고 정리하는 중…',
  cleaned: '정리했습니다. 지운 자리에는 삭제 표시가 남고, 핵심 기록은 그대로 읽힙니다.',
  stale: '미리보기 이후 정리 대상이 바뀌었습니다. 다시 미리보기 하세요.',
  optional: '정리는 선택 사항입니다. 하지 않아도 작업은 끝까지 진행됩니다.',
});

export const ERROR_MESSAGES = Object.freeze({
  conflict: MESSAGES.stale,
  not_found: MESSAGES.stale,
  invalid_input: '요청 형식이 맞지 않습니다.',
  unauthenticated: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  unavailable: '보존 요청을 처리하지 못했습니다.',
});

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

export function retentionRoutes(basePath = '/') {
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const root = `${basePath.slice(0, -1)}/api/v1/retention`;
  return Object.freeze({ state: root, preview: `${root}/cleanup/preview`, cleanup: `${root}/cleanup` });
}

export function sizeText(bytes) {
  if (!Number.isInteger(bytes) || bytes < 0) return '크기 미상';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function categoryText(entry) {
  const parts = [CATEGORY_LABELS[entry.category] ?? entry.category, KEPT_LABELS[entry.kept] ?? entry.kept,
    '자동 삭제 없음'];
  if (Number.isInteger(entry.count) && entry.kept !== 'not_stored') {
    parts.push(Number.isInteger(entry.bytes) ? `${entry.count}개 · ${sizeText(entry.bytes)}` : `${entry.count}개`);
  }
  if (Number.isInteger(entry.events)) parts.push(`사건 ${entry.events}개`);
  if (Number.isInteger(entry.deleted_count) && entry.deleted_count > 0) parts.push(`지운 것 ${entry.deleted_count}개`);
  if (Number.isInteger(entry.eligible_count)) parts.push(`정리 가능 ${entry.eligible_count}개`);
  parts.push(CLEANUP_LABELS[entry.owner_cleanup] ?? entry.owner_cleanup);
  parts.push(REASON_LABELS[entry.reason] ?? entry.reason);
  return parts.join(' · ');
}

export function itemText(item) {
  const label = item.category === 'backups' ? '백업' : `복원(${item.state})`;
  return `${label} · ${item.created_at ?? '시각 미상'} · ${sizeText(item.bytes)} · ${REASON_LABELS[item.reason] ?? item.reason}`;
}

export function createRetentionPanel({ root, document, basePath = '/', request, crypto, onCleaned } = {}) {
  if (typeof root !== 'object' || root === null || typeof root.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  if (typeof crypto?.randomUUID !== 'function') fail('a crypto with randomUUID is required');
  const routes = retentionRoutes(basePath);

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', MESSAGES.loading, { role: 'status', 'aria-live': 'polite' });
  status.dataset.state = 'loading';
  const automatic = element('p', MESSAGES.automatic, { class: 'retention-automatic' });
  const categories = element('ul', undefined, { class: 'retention-categories', 'aria-label': '범주별 보존' });
  const list = element('ul', undefined, { class: 'retention-items', 'aria-label': '정리할 수 있는 항목' });
  const previewButton = element('button', '선택한 항목 정리 미리보기', { type: 'button' });
  const shown = element('div', undefined, { class: 'retention-preview' });
  const history = element('ul', undefined, { class: 'retention-cleanups', 'aria-label': '지난 정리' });
  root.replaceChildren(element('h2', '보존과 삭제'), automatic, status, element('p', MESSAGES.optional),
    element('h3', '범주별로 남기는 것'), categories, element('h3', '소유자가 정리할 수 있는 항목'), list,
    previewButton, shown, element('h3', '지난 정리'), history);

  let checks = [];
  let current = null;
  let generation = 0;

  function say(text, code) {
    status.textContent = text;
    status.dataset.state = code;
  }

  function refusal(error) {
    const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
    say(ERROR_MESSAGES[code], code);
    return code;
  }

  function render(value) {
    const state = retentionState(value);
    categories.replaceChildren(...state.categories.map(entry => element('li', categoryText(entry), {
      'data-category': entry.category, 'data-kept': entry.kept, 'data-owner-cleanup': entry.owner_cleanup,
      'data-automatic-deletion': entry.automatic_deletion })));
    checks = [];
    const rows = state.items.map((item, index) => {
      const row = element('li', undefined, { 'data-item-id': item.item_id, 'data-eligible': String(item.eligible) });
      const id = `retention-item-${index}`;
      const box = element('input', undefined, { type: 'checkbox', id, value: item.item_id, class: 'retention-item' });
      box.checked = false;
      box.disabled = !item.eligible;
      if (item.eligible) checks.push(box);
      row.append(box, element('label', itemText(item), { for: id }));
      return row;
    });
    list.replaceChildren(...(rows.length ? rows : [element('li', MESSAGES.none)]));
    previewButton.disabled = checks.length === 0;
    history.replaceChildren(...(state.cleanups.length ? state.cleanups.map(entry => element('li',
      `${entry.cleaned_at} · ${entry.item_count}개 · ${sizeText(entry.byte_count)} · 미리보기 SHA-256 ${entry.preview_sha256}`,
      { 'data-request-id': entry.request_id })) : [element('li', '아직 정리한 적이 없습니다.')]));
    return state;
  }

  async function load() {
    try {
      const value = await request(routes.state);
      const state = render(value);
      say(checks.length ? `정리할 수 있는 항목 ${checks.length}개` : MESSAGES.none, 'listed');
      return state;
    } catch (error) {
      refusal(error);
      throw error;
    }
  }

  function renderPreview(value) {
    const summary = cleanupPreviewSummary(value);
    const items = element('ul', undefined, { class: 'retention-preview-items', 'aria-label': '정리될 항목' });
    for (const item of summary.items) {
      const keeps = (item.keeps ?? []).map(name => KEEPS_LABELS[name] ?? name).join(', ');
      items.append(element('li', `${item.item_id} · ${sizeText(item.bytes)} · 지움: ${REMOVES_LABELS[item.removes] ?? item.removes} · 남김: ${keeps}`,
        { 'data-item-id': item.item_id }));
    }
    const agree = element('input', undefined, { type: 'checkbox', id: 'retention-consent' });
    agree.checked = false;
    const go = element('button', '이 내용대로 정리', { type: 'button' });
    go.addEventListener('click', () => confirm(summary, agree).catch(() => {}));
    shown.replaceChildren(
      element('h4', `정리될 항목 ${summary.items.length}개 · ${sizeText(summary.byteCount)}`), items,
      element('p', `닿지 않는 것: ${summary.notReached.map(name => NOT_REACHED_LABELS[name] ?? name).join(', ')}`),
      element('p', `어떤 경우에도 지우지 않는 것: ${summary.neverDeleted.map(name => NEVER_LABELS[name] ?? name).join(', ')}`),
      element('p', `미리보기 SHA-256 ${summary.previewSha}`, { class: 'retention-digest' }),
      agree, element('label', MESSAGES.consent, { for: 'retention-consent' }), go);
    return summary;
  }

  async function preview() {
    const itemIds = checks.filter(box => box.checked === true).map(box => box.getAttribute('value'));
    if (!itemIds.length) {
      say(MESSAGES.pick, 'invalid_input');
      return null;
    }
    const mine = ++generation;
    current = null;
    shown.replaceChildren();
    say(MESSAGES.previewing, 'previewing');
    try {
      const value = await request(routes.preview, { method: 'POST', body: {
        schema_version: PREVIEW_SCHEMA, request_id: crypto.randomUUID(), item_ids: itemIds,
        reason_code: 'user_requested' } });
      if (mine !== generation) return null;
      const summary = renderPreview(value);
      current = { value, summary };
      say(`정리될 내용을 확인하세요. ${summary.items.length}개 · ${sizeText(summary.byteCount)}`, 'previewed');
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
    const body = cleanupConsent(summary, { confirmed: true, previewSha: current.value.preview_sha256 });
    const mine = generation;
    say(MESSAGES.cleaning, 'cleaning');
    try {
      const receipt = await request(routes.cleanup, { method: 'POST', body });
      if (mine !== generation) return null;
      current = null;
      shown.replaceChildren(element('p', `정리 ${receipt.removed.length}개 · ${sizeText(receipt.byte_count)} · 미리보기 SHA-256 ${receipt.preview_sha256}`,
        { class: 'retention-receipt' }));
      await load().catch(() => {});
      if (typeof onCleaned === 'function') await Promise.resolve(onCleaned(receipt)).catch(() => {});
      say(MESSAGES.cleaned, 'cleaned');
      return receipt;
    } catch (error) {
      if (mine === generation) {
        refusal(error);
        current = null;
        shown.replaceChildren();
        await load().catch(() => {});
        say(ERROR_MESSAGES[Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable'],
          error?.code ?? 'unavailable');
      }
      throw error;
    }
  }

  previewButton.addEventListener('click', () => preview().catch(() => {}));
  return Object.freeze({ load, preview });
}
