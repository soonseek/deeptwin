// T048/T025, UI phase 3 (2026-09-26): the run screen on the supported factory.
// `observe.html` loads this module by a relative path, so it resolves under the deployment
// base path as under `/`. `boot` derives the base path from the document location,
// establishes the supported session client from the owner cookie the browser already holds
// (no login UI here — that is the start screen), and only then mounts the run list and, for
// the run the owner picks (or `#run=<id>`), the run detail (docs/ui/2026-09-26-product-ux-
// redesign.md §5.3): the header with the run's controls, "최종 결과" first, then "과정" — the
// graph and the timeline sharing one selection with the selection panel's tabs (입력 · 산출물 ·
// 전달 · 도구·모델 · 기록). The owner's version (내 버전) and the alternative-file form open in
// place, next to the artifact they answer, never at the page bottom. Without a session it says
// so plainly and mounts nothing that could send a command. Every dependency (document,
// location, fetch, crypto, history) is injected so the boot is testable under node.

import { createAlternativeFileForm } from './alternative-file.mjs';
import { createApprovalScreen } from './approval-screen.mjs';
import { createAlternativeEditor } from './alternatives.mjs';
import { createArtifactIndex, createArtifactViewer } from './artifacts.mjs';
import { createDifferenceView } from './difference-view.mjs';
import { createGraphView } from './graph.mjs';
import { createInquiryPanel } from './inquiry.mjs';
import { createRunDetail } from './run-detail.mjs';
import { createRunList } from './run-list.mjs';
import { createRunPanel } from './run-panel.mjs';
import { basePathFrom, createSupportedSession } from './session.mjs';
import { shortId } from './ui-format.mjs';
import { mountShell } from './ui-shell.mjs';

export const ALTERNATIVE_MOUNT_ID = 'run-alternative';
export const ALTERNATIVE_FILE_MOUNT_ID = 'run-alternative-file';
export const INQUIRY_MOUNT_ID = 'run-inquiry';
// UI phase 4: "차이 살펴보기" opens in place under the artifact the owner answered
export const DIFFERENCE_MOUNT_ID = 'run-difference';
export const GRAPH_MOUNT_ID = 'run-graph';
export const APPROVALS_MOUNT_ID = 'run-approvals';
export const INDEX_MOUNT_ID = 'artifact-index';
export const MOUNT_IDS = Object.freeze({
  session: 'session-status', source: 'run-source', panel: 'run-panel', artifacts: 'run-artifacts',
});
// the run detail's mounts (UI phase 3); a page without them keeps the older stacked surfaces
export const DETAIL_MOUNT_IDS = Object.freeze({
  view: 'run-view', empty: 'run-empty', summary: 'run-summary', banner: 'run-banner', final: 'run-final',
  views: 'run-process-views', timeline: 'run-timeline', selection: 'run-selection', layout: 'run-process-layout',
  parking: 'run-parking',
});

// the codes GET {base}session can actually answer (app/api/web_boundary.py,
// owner_auth.authenticate_request): a session that stands, none (a fresh
// instance without an owner answers the same 401 — the start screen at `./`
// handles both setup and login, so the text names it), a host/origin refusal;
// anything else is reported by the status the page saw
const SESSION_MESSAGES = Object.freeze({
  authenticated: '브라우저 세션이 연결되어 있습니다. 관제할 실행을 선택해 주세요.',
  unauthenticated: '소유자 세션이 없습니다. 이 인스턴스의 시작 화면(./)에서 최초 소유자 설정 또는 로그인을 마친 뒤 이 화면을 다시 열어 주세요.',
  access_denied: '이 화면은 이 배포의 주소에서만 열 수 있습니다.',
});
const OFFLINE_MESSAGE = '서버에 연결하지 못했습니다. 잠시 후 다시 열어 주세요.';
const BOOT_FAILED_MESSAGE = '이 화면을 준비하지 못했습니다. 세션을 확인하지 못했습니다.';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function fail(message) {
  throw new Error(message);
}

function sessionFailureText(error) {
  if (Object.hasOwn(SESSION_MESSAGES, error?.code)) return [error.code, SESSION_MESSAGES[error.code]];
  if (Number.isInteger(error?.status)) return ['unavailable', `세션을 확인하지 못했습니다 (서버 응답 ${error.status}).`];
  return ['unavailable', OFFLINE_MESSAGE];
}

// `#run=<id>` names the run to open (the work page's link, a reload, the records page's link back)
export function runFromHash(hash) {
  const named = new URLSearchParams(typeof hash === 'string' ? hash.replace(/^#/, '') : '').get('run');
  return typeof named === 'string' && UUID.test(named) ? named : null;
}

// `#run=<id>&artifact=<id>` (the records page's artifact index) also names one artifact to preview
export function artifactFromHash(hash) {
  const named = new URLSearchParams(typeof hash === 'string' ? hash.replace(/^#/, '') : '').get('artifact');
  return runFromHash(hash) !== null && typeof named === 'string' && UUID.test(named) ? named : null;
}

function mount(document, id) {
  const element = document.getElementById(id);
  return element !== null && typeof element?.replaceChildren === 'function' ? element : null;
}

export async function boot({ document, location, fetch, crypto, shell = null, history = null, events = null } = {}) {
  if (typeof document !== 'object' || document === null || typeof document.getElementById !== 'function'
      || typeof document.createElement !== 'function') fail('a document is required');
  if (typeof fetch !== 'function') fail('a fetch function is required');
  if (typeof crypto !== 'object' || crypto === null || typeof crypto.randomUUID !== 'function') fail('a crypto with randomUUID is required');
  const roots = {};
  for (const [name, id] of Object.entries(MOUNT_IDS)) {
    const element = document.getElementById(id);
    if (element === null || typeof element.replaceChildren !== 'function') fail(`the page has no mount for ${id}`);
    roots[name] = element;
  }
  const basePath = basePathFrom(location?.pathname);
  const session = createSupportedSession({ fetch, basePath });
  const commandId = () => crypto.randomUUID();
  try {
    await session.establish();
  } catch (error) {
    const [code, text] = sessionFailureText(error);
    roots.session.dataset.state = code;
    roots.session.textContent = text;
    return Object.freeze({ established: false, basePath, session, list: null, panel: null, artifacts: null, commandId });
  }
  roots.session.dataset.state = 'authenticated';
  roots.session.textContent = SESSION_MESSAGES.authenticated;

  const detailRoots = Object.fromEntries(Object.entries(DETAIL_MOUNT_IDS).map(([name, id]) => [name, document.getElementById(id)]));
  const hasDetail = Object.values(detailRoots).every(element => element !== null && typeof element?.replaceChildren === 'function');
  let detail = null;
  let current = null;       // the run on screen
  let shownKey = null;      // the run panel's view (run, phase, cancel attempts) the detail last covered
  let opening = null;       // the run whose own first panel read the open's trace read already covers
  let loading = Promise.resolve(null);

  // the context bar names only what the page knows: the run the owner picked and, once its
  // trace is read, the work it ran for
  const showContext = (runId, work = null) => shell?.setContext?.({ work, extra: [['실행', shortId(runId), runId]] });

  // ---- the owner's version and the alternative file, opened in place ------------------------------
  const parking = detailRoots.parking;
  const surfaces = [];

  function park(surface) {
    if (surface === null || parking === null || typeof parking?.append !== 'function') return;
    parking.append(surface);
    if (detailRoots.layout?.dataset) detailRoots.layout.dataset.editing = 'false';
    for (const element of document.querySelectorAll?.('[data-editing-artifact]') ?? []) element.removeAttribute('data-editing-artifact');
  }

  function placeIn(surface, context) {
    for (const other of surfaces) if (other !== surface) park(other);
    const slot = context?.slot;
    if (slot && typeof slot.append === 'function') {
      slot.append(surface);
      const inSelection = typeof detailRoots.selection?.contains === 'function' && detailRoots.selection.contains(slot);
      if (detailRoots.layout?.dataset) detailRoots.layout.dataset.editing = inSelection ? 'true' : 'false';
      context.anchor?.setAttribute?.('data-editing-artifact', 'true');
    }
  }

  let editing = null;  // the context the owner's version was opened in (its title, slot and step)

  function inPlace(surface, opener) {
    return async (runId, item, context = {}) => {
      placeIn(surface, context);
      editing = { surface, context };
      const opened = await opener(runId, item, { title: context?.title ?? null });
      surface.scrollIntoView?.({ block: 'nearest' });
      return opened;
    };
  }

  const panel = createRunPanel({ root: roots.panel, document, basePath, request: session.request, commandId,
    onView: view => refreshAfter(view) });
  // the owner's in-place editor, the alternative-file form and the observed difference
  // mount only where the page offers their surfaces (T052/T053/T060). UI phase 4: the difference
  // view ("차이 살펴보기") opens in place, right under the editor it came from, with the related
  // run segment from the trace and the inquiry inside it; a page with only the older
  // `run-inquiry` card keeps that card.
  const differenceRoot = mount(document, DIFFERENCE_MOUNT_ID);
  const difference = differenceRoot !== null
    ? createDifferenceView({ root: differenceRoot, document, basePath, request: session.request, crypto,
      // closing the view hands its place back; the editor above it stays where it is
      onClose: hasDetail ? () => parking?.append?.(differenceRoot) : null,
      onSelectStep: target => {
        detail?.select(target, { focus: true, reveal: true });
        document.getElementById('run-process')?.scrollIntoView?.({ block: 'start' });
      } })
    : null;
  if (differenceRoot !== null) surfaces.push(differenceRoot);
  const inquiryRoot = difference === null ? document.getElementById(INQUIRY_MOUNT_ID) : null;
  const inquiry = inquiryRoot !== null && typeof inquiryRoot?.replaceChildren === 'function'
    ? createInquiryPanel({ root: inquiryRoot, document, basePath, request: session.request, crypto })
    : null;
  let onFrozen;
  if (difference !== null) {
    onFrozen = (runId, artifactId, alternativeId, texts = null) => {
      const context = editing?.context ?? {};
      const slot = editing?.surface?.parentNode;
      if (hasDetail && slot && typeof slot.append === 'function' && slot !== parking) slot.append(differenceRoot);
      const shown = difference.show({ runId, artifactId, alternativeId, title: context.title ?? null, texts,
        segment: detail?.segment(context.segment) ?? null });
      differenceRoot.scrollIntoView?.({ block: 'start' });
      return shown;
    };
  } else if (inquiry !== null) {
    onFrozen = (runId, artifactId, alternativeId) => {
      const shown = inquiry.show(runId, artifactId, alternativeId);
      inquiryRoot.scrollIntoView?.({ block: 'start' });
      return shown;
    };
  }
  const alternativeRoot = mount(document, ALTERNATIVE_MOUNT_ID);
  const fileRoot = mount(document, ALTERNATIVE_FILE_MOUNT_ID);
  if (alternativeRoot) surfaces.push(alternativeRoot);
  if (fileRoot) surfaces.push(fileRoot);
  const editor = alternativeRoot !== null
    ? createAlternativeEditor({ root: alternativeRoot, document, basePath, request: session.request, crypto, onFrozen,
      onClose: hasDetail ? () => { park(alternativeRoot); if (differenceRoot) park(differenceRoot); } : undefined })
    : null;
  const fileForm = fileRoot !== null
    ? createAlternativeFileForm({ root: fileRoot, document, basePath, request: session.request, crypto, onFrozen,
      onClose: hasDetail ? () => { park(fileRoot); if (differenceRoot) park(differenceRoot); } : undefined })
    : null;
  const openEditor = editor === null ? undefined
    : hasDetail ? inPlace(alternativeRoot, (runId, item, options) => editor.open(runId, item, options))
      : (runId, item) => editor.open(runId, item);
  const openFile = fileForm === null ? undefined
    : hasDetail ? inPlace(fileRoot, (runId, item, options) => fileForm.open(runId, item, options))
      : (runId, item) => fileForm.open(runId, item);
  const artifacts = createArtifactViewer({ root: roots.artifacts, document, basePath, request: session.request,
    title: hasDetail ? null : '산출물', onEdit: openEditor, onAlternativeFile: openFile });
  // the selected run's own graph, with node states from its recorded outcome (T037/T048)
  const graphRoot = mount(document, GRAPH_MOUNT_ID);
  const graph = graphRoot !== null
    ? createGraphView({ root: graphRoot, document, basePath, request: session.request, title: hasDetail ? null : '작업 그래프',
      foldDetails: hasDetail, direction: hasDetail ? 'vertical' : 'horizontal',
      onSelect: nodeId => detail?.select({ nodeId }, { fromGraph: true, reveal: true }) })
    : null;
  // the owner's approval screen: the selected run's pending gates and execution-bound
  // asks, decided through the owner routes; a decision re-reads the run panel (T066/T087)
  const approvalsRoot = mount(document, APPROVALS_MOUNT_ID);
  const approvals = approvalsRoot !== null
    ? createApprovalScreen({ root: approvalsRoot, document, basePath, request: session.request, commandId,
      onDecided: runId => panel.read(runId) })
    : null;
  if (hasDetail) {
    detail = createRunDetail({ document, request: session.request, basePath, graph, artifacts, commandId,
      roots: { summary: detailRoots.summary, banner: detailRoots.banner, final: detailRoots.final,
        views: detailRoots.views, graphMount: graphRoot, timeline: detailRoots.timeline,
        selection: detailRoots.selection, artifactsMount: roots.artifacts },
      onEdit: openEditor, onAlternativeFile: openFile,
      onOpenApprovals: () => {
        approvalsRoot?.scrollIntoView?.({ block: 'start' });
        approvalsRoot?.querySelector?.('button')?.focus?.();
      } });
  }

  // the same key the run panel announces a changed view by
  function viewKey(view) {
    return `${view.runId}:${view.phase}:${view.cancellation.attempts.length}`;
  }

  // read everything the run screen shows for one run; each refusal stays on its own surface
  function openRun(runId, { preview = null } = {}) {
    current = runId;
    opening = runId;
    shownKey = null;
    if (hasDetail) {
      detailRoots.view.hidden = false;
      detailRoots.empty.hidden = true;
      for (const surface of surfaces) park(surface);
    }
    if (typeof history?.replaceState === 'function' && runFromHash(location?.hash) !== runId) {
      try { history.replaceState(null, '', `#run=${runId}`); } catch { /* a sandboxed history keeps the page usable */ }
    }
    showContext(runId);
    const read = panel.read(runId).catch(() => {});
    const listed = (preview ? artifacts.open(runId, preview) : artifacts.show(runId)).catch(() => null);
    const reads = [read, listed,
      ...(graph === null ? [] : [graph.showRun(runId).catch(() => {})]),
      ...(approvals === null ? [] : [approvals.show(runId).catch(() => {})])];
    if (detail !== null) {
      loading = detail.show(runId, { artifactsLoad: listed }).then(trace => {
        if (trace && trace.run_id === current) showContext(runId, trace.work?.title === 'not_recorded' ? null : trace.work?.title);
        return trace;
      }).catch(() => null);
      reads.push(loading);
    }
    return Promise.all(reads);
  }

  // after a command (resume, recover, cancel, a decision) the server's view changed: the trace,
  // the graph states and the artifact list are read again for the same run, the selection kept
  async function refreshAfter(view) {
    if (detail === null || view.runId !== current) return;
    const key = viewKey(view);
    // the open read the trace, the graph and the artifacts beside this first panel read:
    // reading them again would redraw the graph under the owner's first click
    if (opening === view.runId) {
      opening = null;
      shownKey = key;
      return;
    }
    await loading;
    if (key === shownKey || view.runId !== current) return;
    shownKey = key;
    const listed = artifacts.show(view.runId, { keepFilter: true }).catch(() => null);
    loading = detail.show(view.runId, { artifactsLoad: listed }).catch(() => null);
    await Promise.all([loading, ...(graph === null ? [] : [graph.showRun(view.runId).catch(() => {})])]);
    // the redrawn graph marks the selection the detail kept
    if (graph !== null && view.runId === current && detail.selection.nodeId !== null) {
      graph.select(detail.selection.nodeId, { notify: false });
    }
  }

  // the vault-wide artifact index: any listed artifact opens in the viewer, with its
  // run's panel, graph and approvals beside it (T045)
  const indexRoot = mount(document, INDEX_MOUNT_ID);
  const index = indexRoot !== null
    ? createArtifactIndex({ root: indexRoot, document, basePath, request: session.request,
      onOpen: (runId, artifactId) => openRun(runId, { preview: artifactId }) })
    : null;
  // `#run=<id>&artifact=<id>` previews that artifact once, when its run opens
  let namedPreview = artifactFromHash(location?.hash);
  const list = createRunList({ root: roots.source, document, basePath, request: session.request,
    onSelect: runId => {
      const preview = namedPreview !== null && runFromHash(location?.hash) === runId ? namedPreview : null;
      namedPreview = null;
      return openRun(runId, { preview });
    } });
  try {
    await list.refresh();
    // `#run=<id>` (the work page's link to the run it started; an asset takes no query)
    // selects that run if the list holds it
    const named = runFromHash(location?.hash);
    if (named) list.select(named);
  } catch {
    // the list's own status names the failure; the session stands
  }
  // a link to another run on this same page (`#run=<id>`) changes only the hash
  if (typeof events?.addEventListener === 'function') {
    events.addEventListener('hashchange', () => {
      const named = runFromHash(location?.hash);
      namedPreview = artifactFromHash(location?.hash);
      if (named && named !== current) list.select(named);
      else if (named && namedPreview !== null) {
        const preview = namedPreview;
        namedPreview = null;
        artifacts.open(named, preview).catch(() => {});
      }
    });
  }
  if (index !== null) {
    try {
      await index.refresh();
    } catch {
      // the index's own status names the failure
    }
  }
  return Object.freeze({ established: true, basePath, session, list, panel, artifacts, index, graph, approvals,
    detail, commandId, get loading() { return loading; } });
}

// the page's entry: a boot that fails before or beside the session exchange
// (no crypto, a mount that throws) still reaches the status line, so the
// HTML's initial text never stands for a failure
export async function bootPage(globals) {
  try {
    return await boot(globals);
  } catch {
    const status = globals?.document?.getElementById?.(MOUNT_IDS.session);
    if (status && typeof status === 'object') {
      status.dataset.state = 'unavailable';
      status.textContent = BOOT_FAILED_MESSAGE;
    }
    return null;
  }
}

// in a browser the page boots itself; under node there is no document
if (typeof globalThis.document === 'object' && globalThis.document !== null
    && typeof globalThis.document.getElementById === 'function'
    && globalThis.document.getElementById(MOUNT_IDS.panel) !== null) {
  const shell = mountShell({ document: globalThis.document, page: 'observe' });
  bootPage({ document: globalThis.document, location: globalThis.location, shell, history: globalThis.history, events: globalThis,
    fetch: (...args) => globalThis.fetch(...args), crypto: globalThis.crypto });
}
