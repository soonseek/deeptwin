// T066 (US6, UX-AC06): the owner's operating versions. What runs now and what ran
// before; each candidate with the gates its validation actually recorded (failed and
// invalid gates keep their reasons); approve / reject / defer as the owner's own
// decision — approve is offered only for a passed sealed-offline candidate — and
// applying an approved candidate as a separate explicit act on the exact revision
// shown; a rollback that requires a stated reason and never claims to undo what
// already happened outside. Growth experiments show the stop reason the loop
// recorded, never a reconstructed one. All text reaches the DOM through textContent.

// The isolation boundaries a comparison plan needs (G-14) are listed with what each
// means and are approved or rejected here as the owner's own recorded decision over
// the exact boundary shown (its digest travels with the command).

import { renderBoundaries, renderRounds } from './experiments.mjs';

const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;

export const STOP_REASONS = Object.freeze({
  plateau_reached: '하한 도달 뒤 세 번 연속 의미 있는 개선이 없어 멈춤',
  budget_exhausted: '하한 도달 뒤 탐색 예산을 모두 씀(수렴이 아님)',
  below_floor_exhausted: '하한에 한 번도 닿지 못한 채 예산을 모두 씀(품질 미달, 승격 아님)',
  evidence_blocked: '필요한 증거가 없어 다음 비교를 할 수 없음',
  safety_stop: '안전 경계 위반으로 멈춤(최고 점수도 승격 근거가 아님)',
  human_stop: '사용자가 멈춤(운영 적용 동의가 아님)',
  lineage_changed: '비교 조건이 바뀌어 새 계보로 다시 해야 함',
});

export const GATE_LABELS = Object.freeze({
  reconstruction: '재구성', heldout_transfer: '미관측 전이', boundary_exclusion: '경계 제외',
  regression: '회귀', leakage: '누출', side_effects: '부수 효과',
});

export const MESSAGES = Object.freeze({
  noState: '운영 버전이 아직 채택되지 않았습니다. 설계 승인으로 준비된 환경을 채택하면 여기에서 버전을 관리합니다.',
  noCandidates: '검증을 마친 후보가 없습니다.',
  noExperiments: '기록된 성장 실험이 없습니다.',
  notApprovable: '봉인 검증을 통과하지 못한 후보는 승인할 수 없습니다. 거절하거나 보류할 수 있습니다.',
  rollbackReason: '되돌리는 이유를 적어 주세요.',
  rollbackNote: '되돌리면 이전 버전의 번들로 돌아갈 뿐, 이미 보낸 것·게시한 것은 되돌리지 않습니다.',
  unreadable: '이 후보의 기록을 정확히 다시 읽지 못해 결정 대상으로 보이지 않습니다.',
});

export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '요청 형식이 맞지 않습니다.',
  unauthenticated: '세션이 없습니다. 시작 화면(./)에서 로그인해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다.',
  not_found: '해당 후보를 찾지 못했습니다.',
  conflict: '운영 버전이 그사이 바뀌었거나 이 승인은 이미 적용되었습니다. 다시 확인해 주세요.',
  unavailable: '처리하지 못했습니다.',
});

export const BOUNDARY_ERRORS = Object.freeze({
  ...ERROR_MESSAGES,
  not_found: '해당 비교 계획이나 경계를 찾지 못했습니다.',
  conflict: '이 경계의 내용이 화면에 보인 것과 다르거나, 같은 명령이 다른 결정으로 이미 기록되었습니다. 다시 확인해 주세요.',
});

function fail(message) {
  throw new Error(message);
}

// the budget the loop recorded as actually consumed, invalid rounds included
export const budgetText = budget => {
  const entries = budget && typeof budget === 'object' ? Object.entries(budget) : [];
  return entries.length ? entries.map(([name, amount]) => `${name} ${amount}`).join(', ') : '기록 없음';
};

const short = ref =>(ref && typeof ref.id === 'string' ? `${ref.kind} ${ref.id.slice(0, 8)} (${ref.sha256.slice(0, 12)})` : '없음');

export function createVersionsPanel({ root, document, request, basePath = '/', crypto } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  if (typeof crypto?.randomUUID !== 'function') fail('a crypto with randomUUID is required');
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const path = `${basePath.slice(0, -1)}/api/v1/versions`;
  let view = null;
  const approvals = new Map();  // validation report sha → approval ref the owner just recorded

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', '', { role: 'status', 'aria-live': 'polite' });
  const current = element('section', undefined, { 'aria-label': '운영 버전' });
  const candidates = element('section', undefined, { 'aria-label': '후보' });
  const experiments = element('section', undefined, { 'aria-label': '성장 실험' });
  const boundaries = element('section', undefined, { 'aria-label': '도구 효과 경계' });
  const rounds = element('section', undefined, { 'aria-label': '비교 라운드' });
  root.replaceChildren(element('h2', '버전'), status, current, candidates, experiments, boundaries, rounds);
  let plans = [];

  function say(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  function refusal(error) {
    const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
    say(ERROR_MESSAGES[code], code);
  }

  async function command(name, body) {
    try {
      const next = await request(`${path}/${name}`, { method: 'POST', body });
      return next;
    } catch (error) {
      refusal(error);
      throw error;
    }
  }

  function renderCurrent() {
    if (view.state === null) {
      current.replaceChildren(element('h3', '운영 버전'), element('p', MESSAGES.noState));
      return;
    }
    const state = view.state;
    const history = element('ol', undefined, { 'aria-label': '이전 버전' });
    for (const item of state.history) {
      history.append(element('li', `${short(item.environment_ref)} · ${item.lifecycle === 'retired' ? '이전 운영' : '되돌림으로 내림'}`));
    }
    const parts = [element('h3', '운영 버전'), element('p', `지금 운영: ${short(state.current_environment_ref)} · 수정본 ${state.revision}`),
      element('h4', '이력'), state.history.length ? history : element('p', '이전 버전이 없습니다.')];
    if (state.history.some(item => item.lifecycle === 'retired')) {
      const reason = element('textarea', undefined, { id: 'versions-rollback-reason', rows: '2' });
      const go = element('button', '이전 버전으로 되돌리기', { type: 'button' });
      go.addEventListener('click', () => rollback(reason).catch(() => {}));
      parts.push(element('label', MESSAGES.rollbackReason, { for: 'versions-rollback-reason' }), reason,
        element('p', MESSAGES.rollbackNote), go);
    }
    current.replaceChildren(...parts);
  }

  function renderCandidates() {
    const parts = [element('h3', '후보')];
    if (!view.candidates.length) parts.push(element('p', MESSAGES.noCandidates));
    for (const item of view.candidates) {
      const entry = element('article', undefined, { 'aria-label': '후보' });
      if (!item.readable) {
        entry.append(element('p', MESSAGES.unreadable));
        parts.push(entry);
        continue;
      }
      entry.append(element('h4', `${short(item.candidate_bundle_ref)} · 검증 ${item.status} (${item.mode})`));
      const gates = element('ul', undefined, { 'aria-label': '검증 게이트' });
      for (const [name, gate] of Object.entries(item.gates)) {
        const reasons = gate.reasons.length ? ` · ${gate.reasons.join(', ')}` : '';
        gates.append(element('li', `${GATE_LABELS[name] ?? name}: ${gate.status} · 비교 라운드 ${gate.rounds}개${reasons}`));
      }
      entry.append(gates);
      if (!item.approvable) entry.append(element('p', MESSAGES.notApprovable));
      const decisions = [['reject', '거절'], ['defer', '보류']];
      if (item.approvable) decisions.unshift(['approve', '승인']);
      for (const [decision, label] of decisions) {
        const button = element('button', label, { type: 'button' });
        button.addEventListener('click', () => decide(item, decision).catch(() => {}));
        entry.append(button);
      }
      const approval = approvals.get(item.validation_report_ref.sha256);
      if (approval && view.state !== null) {
        const apply = element('button', '승인한 이 버전 적용', { type: 'button' });
        apply.addEventListener('click', () => activate(approval).catch(() => {}));
        entry.append(apply);
      }
      parts.push(entry);
    }
    candidates.replaceChildren(...parts);
  }

  function renderExperiments() {
    const parts = [element('h3', '성장 실험')];
    if (!view.experiments.length) parts.push(element('p', MESSAGES.noExperiments));
    for (const item of view.experiments) {
      if (!item.readable) {
        parts.push(element('p', `계보 ${item.lineage_id.slice(0, 8)}: 기록을 정확히 다시 읽지 못했습니다.`));
        continue;
      }
      const stop = item.stop_reason ? (STOP_REASONS[item.stop_reason] ?? item.stop_reason) : '진행 중(멈춤 사유 없음)';
      const best = item.best_observed ? `최고 ${item.best_observed.utility} (${item.best_observed.round_id})` : '유효한 최고 기록 없음';
      parts.push(element('p', `계보 ${item.lineage_id.slice(0, 8)} · ${item.status} · ${stop} · ${best} · `
        + `완료 라운드 ${item.completed_round_ids.length}개 · 연속 비개선 ${item.non_improving_valid_count} · `
        + `소비 ${budgetText(item.consumed_budget)}`));
    }
    experiments.replaceChildren(...parts);
  }

  function render(next) {
    view = next;
    renderCurrent();
    renderCandidates();
    renderExperiments();
    renderRounds({ root: rounds, document, rounds: Array.isArray(view.rounds) ? view.rounds : [] });
  }

  function renderPlans() {
    renderBoundaries({ root: boundaries, document, plans, onDecide: decideBoundary });
  }

  async function loadBoundaries() {
    try {
      const answer = await request(`${path}/tool-effect-boundaries`, {});
      plans = Array.isArray(answer?.plans) ? answer.plans : null;
    } catch {
      plans = null;  // said plainly in the section; the rest of the page still loads
    }
    renderPlans();
    return plans;
  }

  async function load() {
    try {
      const next = await request(path, {});
      render(next);
      await loadBoundaries();
      say('', 'loaded');
      return next;
    } catch (error) {
      refusal(error);
      throw error;
    }
  }

  async function decideBoundary(plan, item, decision) {
    let answer;
    try {
      answer = await request(`${path}/tool-effect-boundaries/decisions`, { method: 'POST', body: {
        command_id: crypto.randomUUID(), plan_record_ref: plan.plan_record, tool_id: item.tool_id,
        version: item.version, boundary_sha256: item.boundary_sha256, decision } });
    } catch (error) {
      const code = Object.hasOwn(BOUNDARY_ERRORS, error?.code) ? error.code : 'unavailable';
      say(BOUNDARY_ERRORS[code], code);
      throw error;
    }
    const updated = answer?.boundary;
    if (updated && Array.isArray(plans)) {
      plans = plans.map(entry => (entry.plan_record?.sha256 !== plan.plan_record.sha256 ? entry : {
        ...entry, boundaries: entry.boundaries.map(value => (value.tool_id === updated.tool_id
          && value.version === updated.version ? updated : value)) }));
    }
    renderPlans();
    say(decision === 'approve' ? '경계 승인을 기록했습니다. 이 경계만 쓰며 실제 서비스로는 보내지 않습니다.'
      : '경계 거절을 기록했습니다. 이 경계가 필요한 항목은 비교하지 않습니다.', 'boundary_decided');
    return answer;
  }

  async function decide(item, decision) {
    const answer = await command('decisions', { command_id: crypto.randomUUID(), decision,
      validation_report_ref: item.validation_report_ref });
    if (decision === 'approve') approvals.set(item.validation_report_ref.sha256, answer.approval_ref);
    say(decision === 'approve' ? '승인을 기록했습니다. 적용은 따로 합니다.' : decision === 'reject' ? '거절을 기록했습니다.'
      : '보류를 기록했습니다.', 'decided');
    renderCandidates();
    return answer;
  }

  async function activate(approvalRef) {
    const next = await command('activate', { approval_ref: approvalRef, expected_revision: view.state.revision });
    render(next);
    say('승인한 버전을 운영 버전으로 적용했습니다.', 'applied');
    return next;
  }

  async function rollback(reasonField) {
    const reason = String(reasonField.value ?? '').trim();
    if (!reason) {
      say(MESSAGES.rollbackReason, 'invalid_input');
      return null;
    }
    const next = await command('rollback', { reason, expected_revision: view.state.revision });
    render(next);
    say('이전 버전으로 되돌렸습니다. 외부로 이미 나간 효과는 되돌리지 않았습니다.', 'rolled_back');
    return next;
  }

  return Object.freeze({ load, decide, decideBoundary, activate, get view() { return view; },
    get plans() { return plans; } });
}
