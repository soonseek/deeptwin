// T073 (US7) / T070: the records page's backup section — create a backup through the
// isolated backup-crypto worker and stage a restore, never required, always reachable.
// - The state is the server's: no worker attached, worker ready, the worker's
//   backup-key volume lost (then nothing can be made or restored with it), or the
//   worker unreachable. Nothing is claimed that the server did not say.
// - Create: the owner first sees the ACTUAL preview (records.mjs backupPreviewSummary):
//   each included history category with its row count, stored originals by count and
//   size, and every excluded category with its closed reason. Consent is a separate
//   explicit check bound to that preview's digest (backupConsent); a vault changed
//   since the preview is refused by the server and shown as stale. The encrypted
//   bundle and its external receipt download separately; this deployment-key backup is
//   stated as not recoverable after the loss of this host's backup-key volume.
// - Restore: the owner picks the external receipt and the encrypted bundle; the server
//   checks one against the other, the worker decrypts, and the result is staged as
//   `restored_review` beside the active vault, which is not changed. The review lists
//   what is still required — a new owner bootstrap, re-created connections and
//   service clients, and an explicit reactivation of an exact environment — and that
//   dispatch stays blocked until then.
// - Portable recovery: a receipt whose key mode is `portable_recovery` needs the age
//   identity the owner kept elsewhere. It is typed into a masked input, read once and the
//   input is cleared at once, sent as the first line of one upload to the portable route
//   and the sent buffer is zeroed. It is never put in an attribute, a label, a status,
//   localStorage or sessionStorage, and the server uses it for one decrypt only.
// - Interrupted upload (T074): while the bundle is being sent, `업로드 중단` aborts it.
//   The server sees the upload end before its body is complete, drops the partial body
//   and marks that restore `failed` (nothing staged, cleanable at once); the screen reads
//   the restore back instead of assuming so, and a fresh restore starts over.
// All server text reaches the DOM through textContent or attributes only.

import { backupConsent, backupPreviewSummary, restoreReview } from './records.mjs';

const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
// a native age X25519 identity (Bech32, upper case); the worker checks it exactly
const AGE_IDENTITY = /^AGE-SECRET-KEY-1[023456789ACDEFGHJKLMNPQRSTUVWXYZ]{20,120}$/;
export const PREVIEW_SCHEMA = 'backup-preview-request-v1';
export const RESTORE_SCHEMA = 'backup-restore-v1';

export const INCLUDED_LABELS = Object.freeze({
  records_and_lineage: '기록과 계보', work_history: '작업 이력', run_history: '실행 이력',
  event_log: '사건 기록', conversations: '대화·음성·이해 기록', approvals_and_permissions: '승인과 권한 기록',
  other_history: '기타 이력', originals: '저장한 원본',
});

export const EXCLUDED_LABELS = Object.freeze({
  owner_authenticators_sessions_and_bootstrap_verifiers: '소유자 인증 수단·세션·초기 설정 검증값',
  unconsumed_human_capabilities: '쓰지 않은 사람 확인 토큰',
  service_client_credentials: '서비스 클라이언트 자격증명',
  provider_credential_handles: '제공자 자격증명 핸들',
  provider_account_state: '제공자 계정 상태',
  pending_challenges: '대기 중인 확인 요청',
  unconsumed_capabilities: '쓰지 않은 권한 부여',
  deployment_receipt_private_state: '배포 영수증 비공개 상태',
  provider_credential_root: '제공자 자격증명 저장소',
  credential_command_ledger: '자격증명 명령 기록부',
  session_root: '세션 루트',
  backup_key_volume: '백업 키 볼륨',
  codex_auth_volume_and_tokens: 'Codex 인증 볼륨과 토큰',
  raw_audio: '원시 음성',
  regenerable_caches: '다시 만들 수 있는 캐시',
  deleted_originals: '지운 원본',
});

export const REASON_LABELS = Object.freeze({
  authenticator_never_restored: '인증 수단은 복원하지 않습니다(새 소유자가 다시 설정)',
  unconsumed_capability: '쓰지 않은 일회용 권한은 복원하지 않습니다',
  credential_never_restored: '자격증명은 복원하지 않습니다(다시 연결)',
  recreated_after_restore: '복원 후 다시 만듭니다',
  deployment_private_state: '배포의 비공개 상태입니다',
  separate_private_root: '별도 비공개 저장소라 백업하지 않습니다',
  not_retained: '보관하지 않습니다',
  regenerable: '다시 만들 수 있습니다',
  deleted_by_owner: '소유자가 지웠습니다(삭제 표시만 남음)',
});

export const REQUIREMENT_LABELS = Object.freeze({
  new_owner_bootstrap: '새 소유자 초기 설정(복원본에는 인증 수단이 없습니다)',
  recreate_connections_and_service_clients: '제공자 연결과 서비스 클라이언트를 다시 만들기',
  review_and_activate_exact_environment: '정확한 환경을 검토하고 명시적으로 다시 활성화하기',
});

export const MESSAGES = Object.freeze({
  notConfigured: '이 서버에는 백업 워커가 아직 연결되어 있지 않습니다. 그래서 이 화면에서 백업을 만들거나 복원하지 않으며, 백업이 있다고 표시하지도 않습니다.',
  notConfiguredHow: '백업은 배포 관리자가 격리된 백업 워커와 별도 backup-key 볼륨을 연결해야 만들 수 있습니다. 같은 배포용 키로 만든 백업은 그 볼륨을 잃으면 복구할 수 없고, 다른 곳에서 복원하려면 따로 보관한 복구 키가 필요합니다.',
  ready: '격리된 백업 워커가 연결되어 있습니다. 백업 키는 네트워크가 없는 워커에만 있고, 이 서버는 키를 읽지 않습니다.',
  keyLost: '백업 워커의 backup-key 볼륨이 없거나 손상되었습니다. 새 백업을 만들 수 없고, 이 배포용 키로 만든 백업은 복원할 수 없습니다. 키를 다시 만들어도 이전 백업은 열리지 않습니다.',
  unreachable: '백업 워커에 연결하지 못했습니다. 지금은 백업을 만들거나 복원할 수 없습니다.',
  notRecoverable: '이 배포용 키로 만든 백업은 이 호스트의 backup-key 볼륨을 잃으면 복구할 수 없습니다.',
  optional: '백업은 선택 사항입니다. 만들지 않아도 작업은 끝까지 진행됩니다.',
  previewing: '백업에 실제로 포함될 내용을 세는 중…',
  consent: '위 미리보기 그대로 백업을 만드는 것에 동의합니다.',
  needConsent: '미리보기 내용에 동의해야 백업을 만들 수 있습니다.',
  creating: '백업을 만들고 복원 확인까지 하는 중…',
  created: '백업을 만들고 복원 확인을 마쳤습니다. 어디에도 자동으로 보내지 않았습니다.',
  stale: '미리보기 이후 기록이 바뀌었습니다. 다시 미리보기 하세요.',
  pickFiles: '외부 영수증(.receipt.json)과 암호화된 백업(.age)을 모두 고르세요.',
  restoring: '영수증과 백업을 대조하고 스테이징 영역에 복원하는 중…',
  interrupted: '업로드를 중단했습니다. 이 복원은 실패로 기록되었고 스테이징 영역에 아무것도 남지 않았으며 활성 인스턴스는 바뀌지 않았습니다. 정리 화면에서 지울 수 있고, 새 복원을 다시 시작할 수 있습니다.',
  interruptedUnknown: '업로드를 중단했습니다. 서버가 이 복원을 아직 실패로 기록하지 않았습니다. 새 복원을 다시 시작할 수 있습니다.',
  staged: '복원본을 스테이징 영역에 만들었습니다. 활성 인스턴스는 바뀌지 않았습니다.',
  review: '복원본은 검토 대기(restored_review) 상태이고 실행은 막혀 있습니다. 아래 단계가 모두 필요합니다.',
  reactivation: '환경은 자동으로 다시 켜지지 않습니다. 검토한 뒤 정확한 환경을 명시적으로 다시 활성화해야 합니다.',
  inFlight: '백업 당시 진행 중이던 원격 요청이 살아 있는지는 확인 전까지 알 수 없습니다.',
  badReceipt: '영수증 파일을 읽지 못했습니다.',
  identityLabel: '따로 보관한 복구 키(휴대용 복구 백업에만 필요, 한 번만 쓰고 저장하지 않습니다)',
  needIdentity: '이 백업은 휴대용 복구 백업입니다. 따로 보관한 복구 키(AGE-SECRET-KEY-1…)를 입력하세요. 입력한 키는 한 번만 쓰고 저장하지 않습니다.',
  identityNotUsed: '이 배포용 키 백업에는 복구 키가 필요 없어 입력한 키를 쓰지 않고 지웠습니다.',
  portableStaged: '따로 보관한 복구 키로 복호화해 스테이징 영역에 만들었습니다. 키는 한 번만 쓰였고 어디에도 저장하지 않았습니다.',
  deleted: '소유자가 정리함 · 암호화된 파일은 지웠고 영수증과 삭제 표시가 남아 있습니다',
});

export const ERROR_MESSAGES = Object.freeze({
  backup_worker_unavailable: MESSAGES.unreachable,
  backup_key_unavailable: MESSAGES.keyLost,
  backup_failed: '백업을 만들지 못했습니다. 아무 파일도 남기지 않았습니다.',
  restore_failed: '복원하지 못했습니다. 스테이징 영역에 아무것도 남기지 않았습니다.',
  conflict: MESSAGES.stale,
  invalid_input: '요청 형식이 맞지 않습니다.',
  unauthenticated: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  too_large: '이 화면에서 받을 수 있는 백업 크기를 넘었습니다.',
  unavailable: '백업 요청을 처리하지 못했습니다.',
});

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

export function backupRoutes(basePath = '/') {
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const root = `${basePath.slice(0, -1)}/api/v1/backups`;
  const id = value => {
    if (typeof value !== 'string' || !UUID.test(value)) fail('id is not a canonical UUID');
    return value;
  };
  return Object.freeze({
    state: root, preview: `${root}/preview`, create: root, restores: `${root}/restores`,
    ciphertext: backupId => `${root}/${id(backupId)}/ciphertext`,
    receipt: backupId => `${root}/${id(backupId)}/receipt`,
    restore: restoreId => `${root}/restores/${id(restoreId)}`,
    bundle: restoreId => `${root}/restores/${id(restoreId)}/bundle`,
    portableBundle: restoreId => `${root}/restores/${id(restoreId)}/portable-bundle`,
  });
}

export function sizeText(bytes) {
  if (!Number.isInteger(bytes) || bytes < 0) return '크기 미상';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function includedText(entry) {
  const label = INCLUDED_LABELS[entry.category] ?? entry.category;
  return entry.category === 'originals' ? `${label} ${entry.count}개 · ${sizeText(entry.bytes)}`
    : `${label} ${entry.rows}행`;
}

export function excludedText(entry) {
  const rows = Number.isInteger(entry.rows) && entry.rows > 0 ? ` · 지금 ${entry.rows}행` : '';
  return `${EXCLUDED_LABELS[entry.category] ?? entry.category}: ${REASON_LABELS[entry.reason] ?? entry.reason}${rows}`;
}

export function createBackupPanel({ root, document, basePath = '/', request, upload, crypto } = {}) {
  if (typeof root !== 'object' || root === null || typeof root.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function' || typeof upload !== 'function') fail('request and upload adapters are required');
  if (typeof crypto?.randomUUID !== 'function') fail('a crypto with randomUUID is required');
  const routes = backupRoutes(basePath);

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', MESSAGES.optional, { role: 'status', 'aria-live': 'polite' });
  status.dataset.state = 'idle';
  const worker = element('p', undefined, { class: 'backup-worker' });
  const note = element('p', undefined, { class: 'backup-note' });
  const createArea = element('section', undefined, { class: 'backup-create', 'aria-label': '백업 만들기' });
  const previewButton = element('button', '백업에 포함될 내용 미리보기', { type: 'button' });
  const shown = element('div', undefined, { class: 'backup-preview' });
  createArea.append(element('h3', '백업 만들기'), previewButton, shown);
  const list = element('ul', undefined, { class: 'backup-list', 'aria-label': '만든 백업' });
  const restoreArea = element('section', undefined, { class: 'backup-restore', 'aria-label': '복원' });
  const receiptInput = element('input', undefined, { type: 'file', id: 'restore-receipt', accept: '.json,application/json' });
  const bundleInput = element('input', undefined, { type: 'file', id: 'restore-bundle', accept: '.age,application/octet-stream' });
  const identityInput = element('input', undefined, { type: 'password', id: 'restore-recovery-identity',
    autocomplete: 'off', spellcheck: 'false', autocapitalize: 'off', 'data-lpignore': 'true' });
  const restoreButton = element('button', '스테이징 영역에 복원', { type: 'button' });
  const abortButton = element('button', '업로드 중단', { type: 'button', class: 'restore-abort' });
  abortButton.hidden = true;
  let inFlight = null;  // the AbortController of the bundle upload now being sent
  const review = element('div', undefined, { class: 'restore-review' });
  restoreArea.append(element('h3', '복원(검토 대기 상태로)'),
    element('label', '외부 영수증(.receipt.json)', { for: 'restore-receipt' }), receiptInput,
    element('label', '암호화된 백업(.age)', { for: 'restore-bundle' }), bundleInput,
    element('label', MESSAGES.identityLabel, { for: 'restore-recovery-identity' }), identityInput,
    restoreButton, abortButton, review);
  restoreArea.hidden = true;  // shown only when the server says the worker is ready
  root.replaceChildren(element('h2', '백업'), status, worker, note, createArea,
    element('h3', '만든 백업'), list, restoreArea);

  let state = null;
  let current = null;
  let generation = 0;

  function say(text, code) {
    status.textContent = text;
    status.dataset.state = code;
  }

  function refusal(error) {
    const code = [error?.reason, error?.code].find(value => Object.hasOwn(ERROR_MESSAGES, value)) ?? 'unavailable';
    say(ERROR_MESSAGES[code], code);
    return code;
  }

  function downloads(backupId) {
    return [
      element('a', '암호화된 백업 내려받기', { href: routes.ciphertext(backupId), download: `deeptwin-backup-${backupId}.age`, rel: 'noopener' }),
      element('a', '외부 영수증 내려받기', { href: routes.receipt(backupId), download: `deeptwin-backup-${backupId}.receipt.json`, rel: 'noopener' }),
    ];
  }

  function renderState(value) {
    state = value;
    const ready = value.worker === 'ready';
    worker.dataset.state = value.worker;
    worker.textContent = { ready: MESSAGES.ready, not_configured: MESSAGES.notConfigured,
      key_unavailable: MESSAGES.keyLost, unreachable: MESSAGES.unreachable }[value.worker] ?? MESSAGES.unreachable;
    note.textContent = value.worker === 'not_configured' ? MESSAGES.notConfiguredHow : MESSAGES.notRecoverable;
    restoreArea.hidden = !ready;
    const items = (value.backups ?? []).map(item => {
      const removed = item.ciphertext_state === 'deleted';
      const row = element('li', `${item.completed_at} · ${sizeText(item.ciphertext_size)} · SHA-256 ${item.ciphertext_sha256}`
        + (removed ? ` · ${MESSAGES.deleted}` : ''),
      { 'data-backup-id': item.backup_id, 'data-ciphertext-state': item.ciphertext_state ?? 'stored' });
      row.append(...(removed ? downloads(item.backup_id).slice(1) : downloads(item.backup_id)));
      return row;
    });
    list.replaceChildren(...(items.length ? items : [element('li', '아직 만든 백업이 없습니다.')]));
    for (const view of value.restores ?? []) {
      if (view.state === 'restored_review') renderReview(view);
    }
  }

  async function load() {
    try {
      const value = await request(routes.state);
      renderState(value);
      return value;
    } catch (error) {
      refusal(error);
      throw error;
    }
  }

  function renderPreview(value) {
    const summary = backupPreviewSummary(value);
    const included = element('ul', undefined, { class: 'backup-included', 'aria-label': '포함될 내용' });
    for (const entry of summary.included) included.append(element('li', includedText(entry), { 'data-category': entry.category }));
    const excluded = element('ul', undefined, { class: 'backup-excluded', 'aria-label': '빠지는 범주' });
    for (const entry of summary.excluded) {
      excluded.append(element('li', excludedText(entry), { 'data-category': entry.category, 'data-reason': entry.reason }));
    }
    const parts = [element('h4', `포함될 내용 · 기록 ${summary.records}개`), included,
      element('h4', '빠지는 범주와 이유'), excluded,
      element('p', summary.recoverable ? '따로 보관한 복구 키로 다른 곳에서도 복원할 수 있습니다.' : MESSAGES.notRecoverable),
      element('p', `미리보기 SHA-256 ${summary.previewSha}`, { class: 'backup-digest' })];
    if (state?.worker === 'ready') {
      const agree = element('input', undefined, { type: 'checkbox', id: 'backup-consent' });
      agree.checked = false;
      const go = element('button', '이 내용으로 백업 만들기', { type: 'button' });
      go.addEventListener('click', () => confirm(summary, agree).catch(() => {}));
      parts.push(agree, element('label', MESSAGES.consent, { for: 'backup-consent' }), go);
    } else {
      parts.push(element('p', worker.textContent, { class: 'backup-unavailable' }));
    }
    shown.replaceChildren(...parts);
    return summary;
  }

  async function preview() {
    const mine = ++generation;
    current = null;
    shown.replaceChildren();
    say(MESSAGES.previewing, 'previewing');
    try {
      const value = await request(routes.preview, { method: 'POST',
        body: { schema_version: PREVIEW_SCHEMA, request_id: crypto.randomUUID() } });
      if (mine !== generation) return null;
      const summary = renderPreview(value);
      current = { value, summary };
      say(`포함될 내용을 확인하세요. 기록 ${summary.records}개`, 'previewed');
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
    const body = backupConsent(summary, { confirmed: true, previewSha: current.value.preview_sha });
    const mine = generation;
    say(MESSAGES.creating, 'creating');
    try {
      const made = await request(routes.create, { method: 'POST', body });
      if (mine !== generation) return null;
      const receipt = made.receipt;
      shown.replaceChildren(
        element('p', `백업 ${sizeText(receipt.ciphertext_size)} · 복원 확인: ${(receipt.restore_verification_ref?.scope ?? []).length}가지 검사 통과`),
        element('p', `백업 SHA-256 ${receipt.ciphertext_sha256}`, { class: 'backup-receipt-digest' }),
        element('p', MESSAGES.notRecoverable), ...downloads(made.backup_id));
      current = null;
      say(MESSAGES.created, 'created');
      await load().catch(() => {});
      status.dataset.state = 'created';
      status.textContent = MESSAGES.created;
      return made;
    } catch (error) {
      if (mine === generation) {
        const code = refusal(error);
        if (code === 'conflict') {
          current = null;
          shown.replaceChildren();
        }
      }
      throw error;
    }
  }

  function renderReview(view) {
    const checked = restoreReview(view);
    const steps = element('ol', undefined, { class: 'restore-requirements', 'aria-label': '복원 후 필요한 단계' });
    for (const step of checked.requires) {
      steps.append(element('li', `${REQUIREMENT_LABELS[step]} · 필요`, { 'data-step': step, 'data-required': 'true' }));
    }
    const missing = element('ul', undefined, { class: 'restore-not-restored', 'aria-label': '복원하지 않은 범주' });
    for (const category of checked.notRestored) missing.append(element('li', EXCLUDED_LABELS[category] ?? category));
    review.dataset.state = 'restored_review';
    review.replaceChildren(element('p', MESSAGES.review, { class: 'restore-state' }), steps,
      element('p', MESSAGES.reactivation, { class: 'restore-reactivation', 'data-required': 'true' }),
      element('p', MESSAGES.inFlight), element('h4', '복원하지 않은 범주'), missing,
      element('p', `복원 ${checked.restoreId} · 백업 ${checked.backupId}`, { class: 'restore-ids' }));
    return checked;
  }

  // the owner stopped the upload: the server marks that restore failed (nothing staged);
  // the screen reads it back rather than assuming, and a fresh restore starts over
  async function interrupted(restoreId) {
    let view = null;
    for (let attempt = 0; attempt < 10; attempt += 1) {
      try {
        view = await request(routes.restore(restoreId), { method: 'GET' });
      } catch {
        view = null;
      }
      if (view?.state === 'failed') break;
      await new Promise(resolve => setTimeout(resolve, 200));
    }
    review.dataset.state = view?.state === 'failed' ? 'interrupted' : 'interrupted_unconfirmed';
    review.replaceChildren(element('p', typeof view?.failure === 'string' ? view.failure : '', { class: 'restore-failure' }),
      element('p', `복원 ${restoreId}`, { class: 'restore-ids' }));
    say(view?.state === 'failed' ? MESSAGES.interrupted : MESSAGES.interruptedUnknown, 'interrupted');
    return view;
  }

  async function restore() {
    // the kept identity is read once and the masked input cleared before anything else
    let identity = typeof identityInput.value === 'string' ? identityInput.value.trim() : '';
    identityInput.value = '';
    const receiptFile = receiptInput.files?.[0];
    const bundleFile = bundleInput.files?.[0];
    if (!receiptFile || !bundleFile) {
      identity = '';
      say(MESSAGES.pickFiles, 'invalid_input');
      return null;
    }
    let receipt;
    try {
      receipt = JSON.parse(await receiptFile.text());
    } catch {
      identity = '';
      say(MESSAGES.badReceipt, 'invalid_input');
      return null;
    }
    const portable = receipt?.key_mode === 'portable_recovery';
    if (portable && !AGE_IDENTITY.test(identity)) {
      identity = '';
      say(MESSAGES.needIdentity, 'identity_required');
      return null;
    }
    const unused = !portable && identity !== '';
    if (!portable) identity = '';
    const bytes = new Uint8Array(await bundleFile.arrayBuffer());
    let framed = null;
    if (portable) {
      const line = new TextEncoder().encode(`${identity}\n`);
      identity = '';
      framed = new Uint8Array(line.byteLength + bytes.byteLength);
      framed.set(line, 0);
      framed.set(bytes, line.byteLength);
      line.fill(0);
    }
    say(MESSAGES.restoring, 'restoring');
    review.replaceChildren();
    try {
      const begun = await request(routes.restores, { method: 'POST',
        body: { schema_version: RESTORE_SCHEMA, request_id: crypto.randomUUID(), receipt } });
      let view;
      const controller = typeof AbortController === 'function' ? new AbortController() : null;
      inFlight = controller;
      abortButton.hidden = controller === null;
      try {
        const options = controller === null ? undefined : { signal: controller.signal };
        view = portable ? await upload(routes.portableBundle(begun.restore_id), framed, options)
          : await upload(routes.bundle(begun.restore_id), bytes, options);
      } catch (error) {
        if (error?.code === 'aborted') return await interrupted(begun.restore_id);
        throw error;
      } finally {
        inFlight = null;
        abortButton.hidden = true;
        if (framed !== null) framed.fill(0);  // the sent identity does not linger in this buffer
        framed = null;
      }
      if (view.state !== 'restored_review') {
        const code = Object.hasOwn(ERROR_MESSAGES, view.failure_code) ? view.failure_code : 'restore_failed';
        review.dataset.state = 'failed';
        review.replaceChildren(element('p', typeof view.failure === 'string' ? view.failure : '', { class: 'restore-failure' }));
        say(ERROR_MESSAGES[code], code);
        return view;
      }
      renderReview(view);
      say(`${MESSAGES.staged}${portable ? ` ${MESSAGES.portableStaged}` : ''}${unused ? ` ${MESSAGES.identityNotUsed}` : ''}`,
        'restored_review');
      return view;
    } catch (error) {
      refusal(error);
      throw error;
    } finally {
      if (framed !== null) framed.fill(0);
      framed = null;
    }
  }

  previewButton.addEventListener('click', () => preview().catch(() => {}));
  restoreButton.addEventListener('click', () => restore().catch(() => {}));
  abortButton.addEventListener('click', () => { if (inFlight !== null) inFlight.abort(); });
  return Object.freeze({ load, preview, restore, get state() { return state; } });
}
