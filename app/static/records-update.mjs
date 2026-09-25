// T072 (US7): the records page's update section — the web-release update guidance, read
// only, from the server's own state (GET {base}api/v1/platform/update): the release this
// instance records as current, the pending update request and its lifecycle state, the
// backup the migration gate requires (and whether it still holds everything written),
// the last refusal and what the deployment operator must do next.
// The owner cannot start, back up, migrate, cancel or hand over a receipt from here: those
// are the stopped-control-plane operator tools, and no browser upload ever becomes update
// or recovery authority. This panel has no buttons, forms or file inputs.
// All server text reaches the DOM through textContent or attributes only.

const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
export const GUIDANCE_SCHEMA = 'deeptwin-update-guidance-v1';

export const STATE_LABELS = Object.freeze({
  prepared: '준비됨 — 검증된 백업을 기다리는 중',
  backup_verified: '백업 확인됨 — 배포 관리자의 이미지 교체와 서명된 영수증을 기다리는 중',
  migrating: '이전(migration) 중 — 운영자 도구가 같은 영수증으로 마쳐야 합니다',
  completed: '완료됨',
  cancelled: '취소됨 — 이 요청의 영수증은 더 이상 받지 않습니다',
  failed: '실패함 — 이전을 되돌렸고 자료는 백업 시점 그대로입니다',
});

export const BACKUP_LABELS = Object.freeze({
  not_required: '지금 필요한 백업이 없습니다.',
  absent: '이전 전에 검증된 백업이 필요합니다. 아직 없습니다.',
  verified: '검증된 백업이 지금의 자료 전체를 담고 있습니다.',
  stale: '백업 뒤에 새 자료가 기록되어, 이 백업으로는 이전할 수 없습니다. 백업을 다시 만들어야 합니다.',
  kept: '이 요청을 위해 만든 백업이 남아 있습니다.',
});

export const STEP_LABELS = Object.freeze({
  stop_control_plane: '서비스(control plane)를 멈춥니다.',
  take_verified_backup: '운영자 도구로 백업을 만들고 복원 확인까지 마칩니다(updates backup).',
  take_verified_backup_again: '백업 뒤에 기록된 자료까지 담도록 백업을 다시 만듭니다(updates backup).',
  apply_image_lock_and_sign_receipt: '배포 관리자가 이미지 잠금 목록의 정확한 이미지로 교체하고 이 요청에 대한 영수증에 서명합니다.',
  migrate_with_receipt: '운영자 도구에 그 영수증을 넘겨 이전합니다(updates migrate).',
  rerun_migrate_with_same_receipt: '같은 영수증으로 운영자 도구의 이전을 다시 실행해 마칩니다(updates migrate).',
  start_new_release: '새 릴리스로 서비스를 시작합니다.',
  keep_current_release: '지금 릴리스를 그대로 씁니다. 저장한 자료는 바뀌지 않았습니다.',
  prepare_new_request: '다시 업데이트하려면 새 요청을 준비합니다(updates prepare).',
});

export const REFUSAL_LABELS = Object.freeze({
  backup_required: '검증된 백업이 없어 이전을 거절했습니다.',
  backup_stale: '백업 뒤에 새 자료가 있어 이전을 거절했습니다.',
  backup_missing: '게이트 백업 파일이 없거나 바뀌어 이전을 거절했습니다.',
  component_unavailable: '필요한 구성 요소가 응답하지 않아 아무것도 바꾸지 않았습니다.',
  component_version_mismatch: '구성 요소의 버전이 맞지 않아 아무것도 바꾸지 않았습니다.',
  epoch_changed: '요청 뒤에 소유자 복구로 권한 세대가 바뀌어 이 요청으로는 이전할 수 없습니다.',
  receipt_mismatch: '이 요청과 맞지 않는 영수증을 거절했습니다.',
  receipt_expired: '기한이 지난 영수증을 거절했습니다.',
  backup_failed: '백업을 만들지 못했습니다.',
  backup_unverified: '백업을 다시 열어 확인하지 못했습니다.',
  backup_state_mismatch: '백업이 지금의 자료와 맞지 않았습니다.',
  migration_failed: '이전 단계가 실패해 되돌렸습니다.',
  schema_changed: '요청 뒤에 저장소 형식이 바뀌었습니다.',
});

export const MESSAGES = Object.freeze({
  loading: '업데이트 상태를 불러오는 중…',
  failed: '업데이트 상태를 불러오지 못했습니다.',
  readOnly: '이 화면은 읽기만 합니다. 업데이트와 복구는 서비스를 멈춘 상태에서 배포 운영자 도구로만 하며, 브라우저에서 올린 파일은 업데이트나 복구의 근거가 되지 않습니다.',
  noRelease: '기록된 릴리스가 없습니다(아직 운영자 도구로 업데이트한 적이 없습니다).',
  noRequest: '진행 중인 업데이트 요청이 없습니다.',
});

function fail(message) {
  throw new Error(message);
}

function short(digest) {
  return typeof digest === 'string' ? digest.slice(0, 12) : '';
}

// the pure view of one guidance state: the lines the panel shows, in order
export function updateGuidanceView(state) {
  if (typeof state !== 'object' || state === null || state.schema_version !== GUIDANCE_SCHEMA
      || state.product_authority !== 'read_only' || !Array.isArray(state.next_steps)) {
    fail('the update guidance is malformed');
  }
  const release = state.current_release === null ? MESSAGES.noRelease
    : `현재 릴리스 ${state.current_release.release_id} · 매니페스트 SHA-256 ${short(state.current_release.release_manifest_sha256)}… · ${state.current_release.installed_at}`;
  let request = MESSAGES.noRequest;
  let requestState = 'none';
  if (state.request !== null) {
    const r = state.request;
    requestState = r.state;
    request = `업데이트 요청 → ${r.target_release_id} · ${STATE_LABELS[r.state] ?? r.state}`
      + ` · 매니페스트 ${short(r.target_release_manifest_sha256)}… · 이미지 잠금 ${short(r.target_image_lock_set_sha256)}…`
      + ` · 권한 세대 ${r.recovery_epoch} · 만료 ${r.expires_at}`;
  }
  const backupState = state.backup?.state ?? 'not_required';
  let backup = BACKUP_LABELS[backupState] ?? backupState;
  if (typeof state.backup?.backup_id === 'string') backup += ` (백업 ${state.backup.backup_id})`;
  let refusal = null;
  if (state.last_refusal !== null && state.last_refusal !== undefined) {
    refusal = `최근 거절: ${REFUSAL_LABELS[state.last_refusal.code] ?? state.last_refusal.code}`
      + (state.last_refusal.component ? ` (${state.last_refusal.component})` : '');
  }
  const steps = state.next_steps.map(code => ({ code, text: STEP_LABELS[code] ?? code }));
  return { release, request, requestState, backup, backupState, refusal, steps };
}

export function createUpdatePanel({ root, document, request, basePath = '/' }) {
  if (typeof request !== 'function') fail('a request adapter is required');
  if (!BASE_PATH.test(basePath)) fail('the base path is malformed');
  const path = `${basePath}api/v1/platform/update`;

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', MESSAGES.loading, { role: 'status', 'aria-live': 'polite' });
  root.replaceChildren(element('h2', '업데이트와 복구'), element('p', MESSAGES.readOnly, { class: 'update-read-only' }),
    status);

  async function load() {
    status.dataset.state = 'loading';
    try {
      const view = updateGuidanceView(await request(path));
      const list = element('ol', undefined, { class: 'update-steps', 'aria-label': '운영자가 할 일' });
      for (const step of view.steps) list.append(element('li', step.text, { 'data-step': step.code }));
      const nodes = [element('h2', '업데이트와 복구'), element('p', MESSAGES.readOnly, { class: 'update-read-only' }),
        element('p', view.release, { class: 'update-release' }),
        element('p', view.request, { class: 'update-request', 'data-state': view.requestState }),
        element('p', view.backup, { class: 'update-backup', 'data-state': view.backupState })];
      if (view.refusal !== null) nodes.push(element('p', view.refusal, { class: 'update-refusal' }));
      if (view.steps.length) nodes.push(element('h3', '운영자가 할 일'), list);
      status.textContent = '업데이트 상태를 불러왔습니다.';
      status.dataset.state = 'listed';
      nodes.push(status);
      root.replaceChildren(...nodes);
      return view;
    } catch (error) {
      status.textContent = MESSAGES.failed;
      status.dataset.state = error?.code ?? 'unavailable';
      throw error;
    }
  }

  return Object.freeze({ load });
}
