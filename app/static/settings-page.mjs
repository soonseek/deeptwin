// The settings page's boot (settings.html; docs/ui/2026-09-26-product-ux-redesign.md §5.8).
// It renders the sub-navigation (settings.mjs), shows one panel at a time chosen by the
// address's fragment (an old deep link such as `#records-credentials` opens the panel that
// holds it), and, with the owner's session, mounts the operations sections that used to sit
// on the records page — account and session, the Claude connection, the gateway's API
// credentials with their transport qualification, run budgets, backup, retention and the
// read-only update guidance, and (UI phase 6) the owner's service clients
// (service-clients.mjs). The modules are unchanged; only the page that mounts them moved. Browser grants and extensions boot from their own modules on this page. Backup and
// retention say only what this server actually does: no backup is claimed where no backup
// worker is connected, and nothing is deleted automatically. All server text reaches the
// DOM through textContent only.

import { createAccountPanel, createCredentialsPanel, createTransportQualificationPanel } from './account.mjs';
import { createBudgetPolicies } from './budget-policy.mjs';
import { createClaudeConnection } from './claude-connection.mjs';
import { createBackupPanel } from './records-backup.mjs';
import { createRetentionPanel } from './records-retention.mjs';
import { createUpdatePanel } from './records-update.mjs';
import { SERVICE_CLIENTS_MOUNT_ID, createServiceClientsPanel } from './service-clients.mjs';
import { basePathFrom, createSupportedSession } from './session.mjs';
import { HUB_MESSAGES, SETTINGS_ENTRIES, SETTINGS_MOUNT_ID, SETTINGS_STATUS_ID, hubStateLines, renderSettingsHub } from './settings.mjs';
import { mountShell } from './ui-shell.mjs';

// the mounts keep the ids they had on the records page, so deep links and tests still find them
export const ACCOUNT_MOUNT_ID = 'records-account';
export const CONNECTION_MOUNT_ID = 'records-connection';
export const CREDENTIALS_MOUNT_ID = 'records-credentials';
export const TRANSPORT_MOUNT_ID = 'records-transport-qualification';
// T023: the owner's run budgets (budget-policy.mjs)
export const BUDGETS_MOUNT_ID = 'records-budgets';
export const BACKUP_MOUNT_ID = 'records-backup';
export const RETENTION_MOUNT_ID = 'records-retention';
// T072: the read-only web-release update guidance (records-update.mjs)
export const UPDATE_MOUNT_ID = 'records-update';
export const PANEL_ATTRIBUTE = 'data-settings-panel';

// what the backup and retention sections say before (or without) a session: only what this
// server does, never a backup it has not made
export const MESSAGES = Object.freeze({
  backupState: '이 서버에는 백업 워커가 아직 연결되어 있지 않습니다. 그래서 이 화면에서 백업을 만들거나 복원하지 않으며, 백업이 있다고 표시하지도 않습니다.',
  backupHow: '백업은 배포 관리자가 격리된 백업 워커와 별도 backup-key 볼륨을 연결해야 만들 수 있습니다. 같은 배포용 키로 만든 백업은 그 볼륨을 잃으면 복구할 수 없고, 다른 곳에서 복원하려면 따로 보관한 복구 키가 필요합니다.',
  retentionState: '자동 삭제는 없습니다. 기록과 원본은 명시적으로 지우기 전까지 보존됩니다.',
  retentionHow: '저장한 원본은 업무 화면의 "원본 삭제"에서 미리보기와 동의를 거쳐 지울 수 있습니다. 지운 자리에는 삭제 표시가 남고, 이전 백업과 이미 보낸 사본에는 닿지 않습니다. 오래된 백업과 스테이징된 복원본은 로그인한 뒤 이 화면에서 미리보기와 동의를 거쳐 정리할 수 있습니다. 핵심 기록은 지우지 않습니다.',
});

function fail(message) {
  throw new Error(message);
}

function mount(document, id) {
  const node = document.getElementById(id);
  return node !== null && typeof node?.replaceChildren === 'function' ? node : null;
}

// the panel a fragment names: the panel itself, or the panel holding the named element
export function panelFor(document, hash) {
  const panels = typeof document.querySelectorAll === 'function' ? [...document.querySelectorAll(`[${PANEL_ATTRIBUTE}]`)] : [];
  if (panels.length === 0) return null;
  let id = '';
  try {
    id = typeof hash === 'string' && hash.startsWith('#') ? decodeURIComponent(hash.slice(1)) : '';
  } catch {
    id = '';
  }
  const target = id ? document.getElementById(id) : null;
  const holder = target?.closest?.(`[${PANEL_ATTRIBUTE}]`) ?? null;
  return panels.includes(holder) ? holder : panels[0];
}

// one panel shown at a time; the list marks the shown one
export function showPanel(document, hash) {
  const panel = panelFor(document, hash);
  if (panel === null) return null;
  for (const other of document.querySelectorAll(`[${PANEL_ATTRIBUTE}]`)) other.hidden = other !== panel;
  for (const link of document.querySelectorAll(`#${SETTINGS_MOUNT_ID} a[data-panel]`)) {
    if (link.getAttribute('data-panel') === panel.id) link.setAttribute('aria-current', 'true');
    else link.removeAttribute('aria-current');
  }
  return panel.id;
}

export async function bootSettings({ document, location, fetch, crypto = globalThis.crypto, window = globalThis.window } = {}) {
  if (typeof document?.getElementById !== 'function') fail('a document is required');
  const root = document.getElementById(SETTINGS_MOUNT_ID);
  const status = document.getElementById(SETTINGS_STATUS_ID);
  let current = null;
  const drawHub = (lines = {}) => {
    renderSettingsHub({ root, document, lines, current });
    current = showPanel(document, location?.hash) ?? current;
  };
  current = panelFor(document, location?.hash)?.id ?? SETTINGS_ENTRIES[0].panel;
  drawHub();
  // choosing an entry moves the reading position to its panel, as a page change would
  window?.addEventListener?.('hashchange', () => {
    const shown = showPanel(document, location?.hash);
    if (shown === null) return;
    const panel = document.getElementById(shown);
    if (shown !== current && panel !== null) {
      panel.setAttribute('tabindex', '-1');
      panel.focus?.({ preventScroll: true });
    }
    current = shown;
  });
  const element = (tag, text) => {
    const node = document.createElement(tag);
    node.textContent = text;
    return node;
  };
  const backupRoot = mount(document, BACKUP_MOUNT_ID);
  const retentionRoot = mount(document, RETENTION_MOUNT_ID);
  backupRoot?.replaceChildren(element('h2', '백업'), element('p', MESSAGES.backupState), element('p', MESSAGES.backupHow));
  retentionRoot?.replaceChildren(element('h2', '보존과 삭제'), element('p', MESSAGES.retentionState),
    element('p', MESSAGES.retentionHow));
  const basePath = basePathFrom(location.pathname);
  const session = createSupportedSession({ fetch, basePath });
  try {
    await session.establish();
  } catch (error) {
    if (status) {
      status.dataset.state = error?.code ?? 'unavailable';
      status.textContent = error?.code === 'unauthenticated' ? HUB_MESSAGES.unauthenticated : HUB_MESSAGES.failed;
    }
    return Object.freeze({ established: false, basePath });
  }
  if (status) {
    status.dataset.state = 'authenticated';
    status.textContent = HUB_MESSAGES.authenticated;
  }
  const accountRoot = mount(document, ACCOUNT_MOUNT_ID);
  const account = accountRoot ? createAccountPanel({ root: accountRoot, document, fetch, basePath, session }) : null;
  const connectionRoot = mount(document, CONNECTION_MOUNT_ID);
  const connection = connectionRoot
    ? createClaudeConnection({ root: connectionRoot, document, request: session.request, basePath }) : null;
  if (connection !== null) await connection.load().catch(() => {});
  const credentialsRoot = mount(document, CREDENTIALS_MOUNT_ID);
  const credentials = credentialsRoot
    ? createCredentialsPanel({ root: credentialsRoot, document, fetch, basePath, session }) : null;
  if (credentials !== null) await credentials.load().catch(() => {});
  // the gateway's transport qualification sits under the credentials it gates (T087/T090)
  let transport = null;
  if (credentials !== null && typeof credentialsRoot.append === 'function') {
    const transportRoot = document.createElement('div');
    transportRoot.id = TRANSPORT_MOUNT_ID;
    credentialsRoot.append(transportRoot);
    transport = createTransportQualificationPanel({ root: transportRoot, document, fetch, basePath, session });
    await transport.load().catch(() => {});
  }
  const budgetsRoot = mount(document, BUDGETS_MOUNT_ID);
  const budgets = budgetsRoot && typeof crypto?.randomUUID === 'function'
    ? createBudgetPolicies({ root: budgetsRoot, document, request: session.request, crypto, basePath }) : null;
  if (budgets !== null) await budgets.load().catch(() => {});
  const backup = backupRoot ? createBackupPanel({ root: backupRoot, document, basePath, request: session.request,
    upload: session.uploadBackupBundle, crypto }) : null;
  if (backup !== null) await backup.load().catch(() => {});
  // a cleanup changes what the backup section lists: it re-reads the server's state
  const retention = retentionRoot ? createRetentionPanel({ root: retentionRoot, document, basePath,
    request: session.request, crypto, onCleaned: () => backup?.load() }) : null;
  if (retention !== null) await retention.load().catch(() => {});
  const updateRoot = mount(document, UPDATE_MOUNT_ID);
  const update = updateRoot ? createUpdatePanel({ root: updateRoot, document, basePath, request: session.request }) : null;
  if (update !== null) await update.load().catch(() => {});
  const clientsRoot = mount(document, SERVICE_CLIENTS_MOUNT_ID);
  const serviceClients = clientsRoot && typeof crypto?.randomUUID === 'function'
    ? createServiceClientsPanel({ root: clientsRoot, document, basePath, request: session.request, crypto,
      pageProtocol: location?.protocol ?? '', heading: false }) : null;
  if (serviceClients !== null) await serviceClients.load().catch(() => {});
  const prefix = basePath.slice(0, -1);
  const [backups, retained] = await Promise.all([
    session.request(`${prefix}/api/v1/backups`).catch(() => null),
    session.request(`${prefix}/api/v1/retention`).catch(() => null),
  ]);
  const lines = hubStateLines({ backups, retention: retained });
  drawHub(lines);
  return Object.freeze({ established: true, basePath, lines, account, connection, credentials, transport, budgets,
    backup, retention, update, serviceClients });
}

if (typeof globalThis.document === 'object' && globalThis.document !== null
    && typeof globalThis.document.getElementById === 'function'
    && globalThis.document.getElementById(SETTINGS_MOUNT_ID) !== null) {
  mountShell({ document: globalThis.document, page: 'settings' });
  bootSettings({ document: globalThis.document, location: globalThis.location, crypto: globalThis.crypto,
    window: globalThis.window, fetch: (...args) => globalThis.fetch(...args) }).catch(() => {
    const status = globalThis.document.getElementById(SETTINGS_STATUS_ID);
    if (status) status.textContent = '이 화면을 준비하지 못했습니다.';
  });
}
