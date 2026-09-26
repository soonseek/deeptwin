// T048 (DOM half): the run panel. It renders the run observer's state
// (runtime.mjs) into a DOM the caller owns and sends the owner's commands
// through the injected request — the supported session client's adapter
// (session.mjs) in the shell, a fake in tests. One status line (role=status,
// polite), one accessible text row per node (accessibleRows: the state is
// spelled out, never colour alone — experience.md §9/§12), the closed error
// text keyed by the server's code (role=alert), and three commands. The panel
// never decides a phase: the server derives it from the durable head, the
// controls are gated by that view, and a refused command is shown as the
// server's code with the last honest view kept. Each command carries one
// fresh command id from the injected source (crypto.randomUUID in the shell),
// so a repeated click is a new command, never a replay of the last one.

import { ERROR_CODES, accessibleRows, createRunObserver, runRoutes } from './runtime.mjs';
import { RUN_CONTROL_LABELS, shortId } from './ui-format.mjs';
import { TECHNICAL_SUMMARY } from './ui-parts.mjs';

// the owner's words for the three commands (ui-format.mjs): "cancel" stops sending new work;
// calls already sent end on their own and are shown row by row
export const CONTROL_LABELS = RUN_CONTROL_LABELS;

// one actionable sentence per closed error code (runtime.mjs ERROR_CODES)
// the text never claims what the view cannot know: a 503 may have run a node and
// recorded a stop; a 400 was sent; an absent or rotated token needs the session
// re-established, not a login
export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '요청 형식이 맞지 않습니다.',
  unauthenticated: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다. 화면을 새로고침한 뒤 다시 시도해 주세요.',
  not_found: '해당 실행을 찾지 못했습니다.',
  conflict: '지금 상태에서는 이 명령을 적용할 수 없습니다. 아래는 다시 읽은 최신 상태입니다.',
  too_large: '요청이 허용 크기를 넘었습니다.',
  unavailable: '서버가 요청을 처리하지 못했습니다. 아래는 다시 읽은 최신 상태입니다.',
});

// the receipt carries no liveness: a `running` head may be a failed execution with
// nothing live, so the panel says unfinished, never that work is in progress
const PHASE_STATUS = Object.freeze({ running: '미완료' });
const IDLE_STATUS = '실행을 선택하면 상태를 보여 줍니다.';
const BUSY_STATUS = '실행 상태를 확인하는 중…';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

// the commands the server would admit for this view (app/services/runs.py);
// nothing while an exchange is in flight. The server still has the last word.
// resume runs the head again: on `created` and on `running` (an approved gate
// — the server's observe drops it from awaiting — or a failed execution); on a
// waiting gate it is a no-op, so it is not offered there. recover admits one
// more billed attempt of a terminally failed execution: only on `running`, and
// only by the owner's explicit choice. cancel closes any run not yet complete
// or cancelled (a rejected run included).
export function controlsFor(state) {
  if (typeof state !== 'object' || state === null || typeof state.busy !== 'boolean') fail('state must be an observer state');
  const view = state.view;
  if (state.busy || view === null || view === undefined) return Object.freeze({ resume: false, cancel: false, recover: false });
  const open = !view.complete && view.phase !== 'cancelled';
  return Object.freeze({
    resume: view.phase === 'running' || view.phase === 'created',
    cancel: open,
    recover: view.phase === 'running',
  });
}

// UI phase 3: the per-node text rows are no longer the screen's primary element (the run detail's
// graph and timeline are); they stay one disclosure away as the plain-text equivalent, and
// `onView(view)` tells the page when the server's view of the run changed (after a command).
export function createRunPanel({ root, document, request, basePath = '/', commandId, onView = null } = {}) {
  if (typeof root !== 'object' || root === null || typeof root.replaceChildren !== 'function'
      || typeof root.setAttribute !== 'function') fail('a root element is required');
  if (typeof document !== 'object' || document === null || typeof document.createElement !== 'function') {
    fail('a document is required');
  }
  if (typeof commandId !== 'function') fail('a command id source is required');
  runRoutes(basePath); // refuse a bad base before anything is built
  if (typeof request !== 'function') fail('an injected request function is required');

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', IDLE_STATUS, { role: 'status', 'aria-live': 'polite' });
  const rows = element('ol', undefined, { 'aria-label': '실행 상태: 노드별 수행과 지난 시도' });
  const rowsFold = element('details', undefined, { class: 'run-rows' });
  rowsFold.append(element('summary', '노드별 상태를 글로 보기'), rows);
  const alert = element('p', '', { role: 'alert' });
  alert.hidden = true;
  const buttons = {};
  const actions = element('div', undefined, { 'aria-label': '실행 명령' });
  for (const name of Object.keys(CONTROL_LABELS)) {
    const button = element('button', CONTROL_LABELS[name]);
    button.type = 'button';
    button.disabled = true;
    button.dataset.command = name;
    buttons[name] = button;
    actions.append(button);
  }
  // the full run id stays one fold away from the short one in the status line
  const techValue = element('dd');
  const techList = element('dl', undefined, { class: 'kv-list tech-list' });
  techList.append(element('dt', '실행 ID'), techValue);
  const tech = element('details', undefined, { class: 'tech-details' });
  tech.append(element('summary', TECHNICAL_SUMMARY), techList);
  tech.hidden = true;
  root.replaceChildren(status, alert, actions, tech, rowsFold);
  root.dataset.phase = '';
  root.dataset.runId = '';
  root.setAttribute('aria-busy', 'false');

  // a refused command is kept on screen beside the run read again after it (the
  // refusal may have changed the run: a 503 can run a node and record a stop) until
  // the owner's next command or read; the screen and the snapshot always agree
  let retained = null;
  let shown = Object.freeze({ busy: false, view: null, error: null });

  let announced = null;

  function draw(state) {
    shown = state;
    const view = state.view;
    const key = view ? `${view.runId}:${view.phase}:${view.cancellation.attempts.length}` : null;
    if (key !== announced && !state.busy) {
      announced = key;
      if (view && typeof onView === 'function') Promise.resolve().then(() => onView(view)).catch(() => {});
    }
    root.setAttribute('aria-busy', String(state.busy));
    root.dataset.phase = view ? view.phase : '';
    root.dataset.runId = view ? view.runId : '';
    const phaseText = view ? PHASE_STATUS[view.phase] ?? view.phaseLabel : '';
    status.textContent = state.busy ? BUSY_STATUS : view ? `${phaseText} · 실행 ${shortId(view.runId)}` : IDLE_STATUS;
    tech.hidden = !view;
    rowsFold.hidden = !view;
    techValue.textContent = view ? view.runId : '';
    rows.replaceChildren(...(view ? accessibleRows(view).map(text => element('li', text)) : []));
    if (state.error) {
      alert.hidden = false;
      alert.dataset.code = state.error.code;
      alert.textContent = ERROR_MESSAGES[ERROR_CODES.includes(state.error.code) ? state.error.code : 'unavailable'];
    } else {
      alert.hidden = true;
      alert.dataset.code = '';
      alert.textContent = '';
    }
    const controls = controlsFor(state);
    for (const name of Object.keys(buttons)) buttons[name].disabled = !controls[name];
  }

  function render(state) {
    draw(retained !== null && state.error === null ? Object.freeze({ ...state, error: retained }) : state);
  }

  const observer = createRunObserver({ request, basePath, onChange: render });

  function fresh(exchange) {
    retained = null;
    return exchange();
  }

  function command(name) {
    return async () => {
      const state = observer.snapshot();
      if (!controlsFor(state)[name]) return; // a disabled control sends nothing, whatever fired it
      retained = null;
      const runId = state.view.runId;
      const id = commandId();
      if (typeof id !== 'string' || !UUID.test(id)) {
        retained = Object.freeze({ code: 'invalid_input', message: 'command id is not a UUID', target: null });
        render(state);
        return;
      }
      try {
        await observer[name](runId, id);
      } catch {
        const refused = observer.snapshot();
        if (refused.error === null || refused.view === null || refused.view.runId !== runId) return;
        retained = refused.error;
        try {
          await observer.read(runId);
        } catch {
          // the read's own refusal is on screen; the retained one yields to it
        }
      }
    };
  }
  for (const name of Object.keys(buttons)) buttons[name].addEventListener('click', command(name));

  return Object.freeze({
    observer,
    read(runId) { return fresh(() => observer.read(runId)); },
    start(fields) { return fresh(() => observer.start(fields)); },
    snapshot() { return shown; },
  });
}
