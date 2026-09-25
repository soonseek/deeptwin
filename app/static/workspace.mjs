// T037 (UX-AC01, FR-005/FR-008/FR-009): the owner's design workspace over one persisted
// design request (`design-workspace-v1`). It shows the honest selection pool — what is
// presented, every exclusion with its reason and the real count, never padded — and a
// large side-by-side comparison of two pooled candidates: both graphs drawn in full,
// what differs between them (`compareGraphs`), and one node in focus on both sides
// (`focusDifference`) with its model and tool bindings. Commands are owner acts:
// select / edit (with an instruction) / merge (two or more) persist a new design
// version that requires re-review and inherits no verdict; review runs only when the
// instance configured a critic model turn; prepare attempts approval and preparation
// and shows the server's exact refusal. A verdict is always shown as the recorded
// conclusion of the critic it names, with that critic's qualification state; nothing
// here presents a recorded verdict as a live one. All text goes through textContent.

import { compareGraphs, createGraphView, differenceSummary, focusDifference, unionNodeIds } from './graph.mjs';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
const MAX_INSTRUCTION_BYTES = 4096;
const utf8 = new TextEncoder();

export const VERDICT_LABELS = Object.freeze({
  passed: '통과', rejected: '필수 결함으로 탈락', insufficient_evidence: '근거 부족',
});
export const ACTION_LABELS = Object.freeze({ select: '선택', edit: '수정', merge: '합치기' });
export const REVIEW_REASONS = Object.freeze({
  critic_model_not_configured: '이 인스턴스에 평가 모델이 설정되지 않아 재검토를 실행할 수 없습니다.',
  derived_graph_not_generated: '수정·합치기 지시를 반영한 그래프를 만드는 생성 단계가 아직 없어 재검토할 그래프가 없습니다.',
  criticism_did_not_complete: '재검토가 끝나지 않았습니다. 기록된 평가는 없습니다.',
});
export const QUALIFICATION_LABELS = Object.freeze({
  qualified: '자격 있음', scoped_pass: '범위 한정 통과(자격 아님)', unqualified: '자격 없음', unknown: '자격 기록 없음',
});
const ERROR_TEXT = Object.freeze({
  invalid_input: '요청 형식이 맞지 않습니다.',
  unauthenticated: '세션이 끝났습니다. 시작 화면(./)에서 다시 로그인해 주세요.',
  access_denied: '세션 확인에 실패했습니다. 이 화면을 다시 열어 주세요.',
  not_found: '이 설계 요청을 이 인스턴스에서 찾지 못했습니다.',
  conflict: '같은 명령이 이미 다른 내용으로 처리되었습니다.',
  unavailable: '서버가 요청을 처리하지 못했습니다.',
});

function fail(message) {
  throw Object.assign(new Error(message), { code: 'invalid_input' });
}

// an exclusion's reason as the owner reads it, the recorded code kept beside it
export function exclusionText(reason) {
  if (reason === 'structural_duplicate') return '이미 제시된 후보와 구조가 같습니다';
  if (reason === 'pool_full') return '기본 3안이 이미 찼습니다';
  if (reason === 'unreviewed') return '아직 평가되지 않았습니다';
  const [status, detail = ''] = reason.split(/:(.*)/s);
  if (Object.hasOwn(VERDICT_LABELS, status)) return `${VERDICT_LABELS[status]} (${detail})`;
  return reason;
}

export function poolSummary(pool) {
  const shown = `통과한 구조적으로 다른 후보 ${pool.presented_count}개를 제시합니다 (기본 ${pool.pool_size}안)`;
  const short = pool.presented_count < pool.pool_size ? ` — ${pool.pool_size}개를 채우지 못했습니다. 채워 넣지 않고 실제 수를 보여 줍니다.` : '';
  return `${shown}${short} 전체 후보 ${pool.candidate_count}개 · 통과 ${pool.passed_count}개.`;
}

// the verdict as what one named critic recorded, never as a live score
export function verdictText(verdict) {
  if (!verdict) return '평가 없음 — 재검토가 필요합니다';
  const critic = verdict.model_ids.length ? verdict.model_ids.join(', ') : '기록된 평가자 없음';
  const reasons = verdict.reasons.length ? ` · 이유 ${verdict.reasons.join(', ')}` : '';
  return `기록된 평가: ${VERDICT_LABELS[verdict.status] ?? verdict.status}${reasons} · 평가자 ${critic} (호출 ${verdict.call_count}회)`;
}

export function qualificationText(preparation) {
  const q = preparation.critic_qualification;
  return `평가자 구성의 자격: ${QUALIFICATION_LABELS[q.status] ?? q.status} (${q.status}: ${q.reason})`;
}

export function createDesignWorkspace({ root, document, request, basePath = '/', commandId } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  if (typeof commandId !== 'function') fail('a command id source is required');
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const api = `${basePath.slice(0, -1)}/api/v1/design-requests`;

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  function button(text, onClick, attributes = {}) {
    const node = element('button', text, { type: 'button', ...attributes });
    node.addEventListener('click', onClick);
    return node;
  }

  const status = element('p', '', { role: 'status', 'aria-live': 'polite' });
  const picker = element('select', undefined, { 'aria-label': '설계 요청 선택' });
  const summary = element('section', undefined, { class: 'design-pool', 'aria-label': '선택 후보' });
  const compare = element('section', undefined, { class: 'design-compare', 'aria-label': '후보 비교' });
  const derived = element('section', undefined, { class: 'design-derivations', 'aria-label': '새 설계 버전' });
  root.replaceChildren(element('h2', '설계 후보 비교'), status, picker, summary, compare, derived);
  picker.hidden = true;
  picker.addEventListener('change', () => show(picker.value).catch(() => {}));
  let view = null;
  let requestId = null;
  const pair = { left: null, right: null, focus: null };
  const merging = new Set();

  function say(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  function refusal(error) {
    if (error?.reason) return error.reason;
    return ERROR_TEXT[error?.code] ?? ERROR_TEXT.unavailable;
  }

  async function command(kind, body) {
    return request(`${api}/${requestId}/${kind}`, { method: 'POST', body: { command_id: commandId(), ...body } });
  }

  function candidate(id) {
    return view.candidates.find(item => item.candidate_id === id)
      ?? view.derivations.map(item => item.reviewed_candidate).find(item => item?.candidate_id === id) ?? null;
  }

  // --- the pool: presented, exclusions, qualification -----------------------------------
  function renderSummary() {
    const excluded = element('ul', undefined, { class: 'design-exclusions', 'aria-label': '제시하지 않은 후보' });
    for (const item of view.pool.excluded) {
      excluded.append(element('li', `${item.candidate_id.slice(0, 8)} · ${exclusionText(item.reason)}`, { 'data-reason': item.reason }));
    }
    const cards = element('ol', undefined, { class: 'design-candidates', 'aria-label': '제시된 후보' });
    view.pool.presented_candidate_ids.forEach((id, index) => cards.append(candidateCard(candidate(id), index)));
    const merge = button('선택한 후보 합치기', () => derive('merge', [...merging]), { 'data-command': 'merge' });
    merge.disabled = merging.size < 2;
    const mergeNote = element('p', merging.size < 2 ? '합치려면 후보를 두 개 이상 고르세요.' : `${merging.size}개를 합칩니다.`);
    summary.replaceChildren(
      element('h3', '제시된 후보'), element('p', poolSummary(view.pool), { class: 'design-pool-count' }),
      element('p', `${qualificationText(view.preparation)}. 아래 평가는 기록된 결론이며 실시간 평가가 아닙니다.`,
        { class: 'design-qualification' }),
      cards, merge, mergeNote,
      ...(view.pool.excluded.length ? [element('h4', '제시하지 않은 후보와 이유'), excluded] : []));
  }

  function candidateCard(item, index) {
    const card = element('li', undefined, { class: 'design-candidate', 'data-candidate': item.candidate_id });
    const name = `후보 ${index + 1}`;
    const agents = item.graph.nodes.filter(node => node.kind === 'agent').length;
    card.append(element('h4', `${name} · ${item.candidate_id.slice(0, 8)}`),
      element('p', `노드 ${item.graph.nodes.length}개 · 에이전트 ${agents}개 · 모델 연결 ${item.graph.model_bindings.length}개 · 도구 연결 ${item.graph.tool_bindings.length}개`),
      element('p', verdictText(item.verdict), { class: 'design-verdict', 'data-verdict': item.verdict?.status ?? 'none' }));
    const pick = element('input', undefined, { type: 'checkbox', 'aria-label': `${name} 합치기에 포함` });
    pick.checked = merging.has(item.candidate_id);
    pick.addEventListener('change', () => {
      if (pick.checked) merging.add(item.candidate_id); else merging.delete(item.candidate_id);
      renderSummary();
    });
    const instruction = element('textarea', undefined, { rows: '2', 'aria-label': `${name} 수정 지시` });
    const outcome = element('p', '', { role: 'status', class: 'design-command-status' });
    const prepare = button('이 설계로 준비', () => prepareCandidate(item.candidate_id, outcome), { 'data-command': 'prepare' });
    const prepareNote = view.preparation.approvable ? [] : [element('p', `지금은 승인할 수 없습니다: ${view.preparation.reason}`,
      { class: 'design-not-approvable' })];
    card.append(
      element('label', '합치기에 포함'), pick,
      button('이 설계 선택', () => derive('select', [item.candidate_id], null, outcome), { 'data-command': 'select' }),
      instruction,
      button('지시대로 수정', () => {
        const text = instruction.value.trim();
        if (!text || utf8.encode(text).length > MAX_INSTRUCTION_BYTES) {
          outcome.textContent = '수정 지시를 한 문장 이상, 4096바이트 이하로 적어 주세요.';
          return undefined;
        }
        return derive('edit', [item.candidate_id], text, outcome);
      }, { 'data-command': 'edit' }),
      button('왼쪽에 비교', () => { pair.left = item.candidate_id; renderCompare(); }),
      button('오른쪽에 비교', () => { pair.right = item.candidate_id; renderCompare(); }),
      prepare, ...prepareNote, outcome);
    return card;
  }

  // --- the comparison: both graphs, what differs, one node in focus -------------------------
  function renderCompare() {
    const left = candidate(pair.left);
    const right = candidate(pair.right);
    if (!left || !right) {
      compare.replaceChildren(element('h3', '후보 비교'), element('p', '비교하려면 제시된 후보가 두 개 이상 있어야 합니다.'));
      return;
    }
    const difference = compareGraphs(left.graph, right.graph);
    const lines = differenceSummary(difference);
    const sides = element('div', undefined, { class: 'design-compare-sides' });
    for (const [label, item] of [['왼쪽', left], ['오른쪽', right]]) {
      const side = element('section', undefined, { class: 'design-compare-side', 'aria-label': `${label} 후보` });
      const graphRoot = element('div');
      side.append(element('h4', `${label}: ${item.candidate_id.slice(0, 8)}`), element('p', verdictText(item.verdict)), graphRoot);
      createGraphView({ root: graphRoot, document, title: null }).show(item.graph);
      sides.append(side);
    }
    const focusPicker = element('select', undefined, { 'aria-label': '같은 노드 비교' });
    for (const id of unionNodeIds(left.graph, right.graph)) {
      const option = element('option', id, { value: id });
      if (id === pair.focus) option.setAttribute('selected', '');
      focusPicker.append(option);
    }
    pair.focus = pair.focus && unionNodeIds(left.graph, right.graph).includes(pair.focus) ? pair.focus
      : unionNodeIds(left.graph, right.graph)[0];
    focusPicker.value = pair.focus;
    const focus = element('div', undefined, { class: 'design-focus', 'aria-label': '같은 노드의 차이' });
    const drawFocus = () => {
      const detail = focusDifference(left.graph, right.graph, pair.focus);
      const state = { same: '같음', changed: `다름 (${detail.fields.join(', ')})`, added: '오른쪽에만 있음', removed: '왼쪽에만 있음' }[detail.state] ?? detail.state;
      const column = (label, rows) => {
        const list = element('dl', undefined, { 'aria-label': `${label} 노드` });
        if (!rows.length) list.append(element('dt', label), element('dd', '이 후보에는 이 노드가 없습니다'));
        for (const [name, value] of rows) list.append(element('dt', name), element('dd', String(value)));
        return list;
      };
      focus.replaceChildren(element('p', `${pair.focus}: ${state}`, { 'data-focus-state': detail.state }),
        column('왼쪽', detail.left), column('오른쪽', detail.right));
    };
    focusPicker.addEventListener('change', () => { pair.focus = focusPicker.value; drawFocus(); });
    drawFocus();
    const list = element('ul', undefined, { class: 'design-differences', 'aria-label': '두 후보의 차이' });
    for (const line of lines.length ? lines : ['구조 차이가 없습니다']) list.append(element('li', line));
    compare.replaceChildren(element('h3', '후보 비교'), list, sides, element('h4', '같은 노드 비교'), focusPicker, focus);
  }

  // --- derived versions ---------------------------------------------------------------------
  function renderDerivations() {
    const items = element('ol', undefined, { 'aria-label': '새 설계 버전 목록' });
    for (const item of view.derivations) {
      const row = element('li', undefined, { class: 'design-derivation', 'data-derivation': item.derivation_id });
      const parents = item.parent_candidate_ids.map(id => id.slice(0, 8)).join(' + ');
      row.append(element('p', `${ACTION_LABELS[item.action] ?? item.action} · 원본 ${parents}${item.instruction ? ` · 지시 "${item.instruction}"` : ''}`));
      const outcome = element('p', '', { role: 'status', class: 'design-command-status' });
      if (item.re_review_required) {
        row.append(element('p', '재검토 필요 · 원본의 평가·승인은 이어지지 않습니다', { class: 'design-re-review' }));
        const review = button('재검토', () => reviewDerivation(item.derivation_id, outcome), { 'data-command': 'review' });
        const reason = !view.review.available ? view.review.reason
          : item.action !== 'select' ? 'derived_graph_not_generated' : null;
        review.disabled = reason !== null;
        row.append(review);
        if (reason !== null) row.append(element('p', REVIEW_REASONS[reason] ?? reason, { class: 'design-review-unavailable' }));
        row.append(element('p', '재검토 전에는 준비할 수 없습니다.'));
      } else {
        const reviewed = item.reviewed_candidate;
        row.append(element('p', verdictText(reviewed.verdict), { class: 'design-verdict' }),
          button('이 설계로 준비', () => prepareCandidate(reviewed.candidate_id, outcome), { 'data-command': 'prepare' }));
      }
      row.append(outcome);
      items.append(row);
    }
    derived.replaceChildren(element('h3', '새 설계 버전'),
      view.derivations.length ? items : element('p', '아직 선택·수정·합치기로 만든 새 버전이 없습니다.'));
  }

  function render() {
    const presented = view.pool.presented_candidate_ids;
    if (!presented.includes(pair.left)) pair.left = presented[0] ?? null;
    if (!presented.includes(pair.right) || pair.right === pair.left) pair.right = presented.find(id => id !== pair.left) ?? null;
    for (const id of [...merging]) if (!presented.includes(id)) merging.delete(id);
    renderSummary();
    renderCompare();
    renderDerivations();
  }

  async function show(id) {
    if (typeof id !== 'string' || !UUID.test(id)) fail('design request id is not a canonical UUID');
    say('설계 후보를 읽는 중…', 'loading');
    try {
      view = await request(`${api}/${id}`, {});
      requestId = id;
      render();
      say(`설계 요청 ${id.slice(0, 8)}의 후보를 보여 줍니다.`, 'shown');
      return view;
    } catch (error) {
      say(ERROR_TEXT[error?.code] ?? ERROR_TEXT.unavailable, error?.code ?? 'unavailable');
      throw error;
    }
  }

  async function derive(action, parents, instruction = null, outcome = null) {
    const target = outcome ?? status;
    try {
      const value = await command('derivations', { schema_version: 'design-derivation-command-v1', action,
        parent_candidate_ids: parents, instruction });
      if (action === 'merge') merging.clear();
      await show(requestId);
      say(`새 설계 버전을 만들었습니다 (${ACTION_LABELS[action]}). 재검토가 필요하며 원본의 평가는 이어지지 않습니다.`, 'derived');
      return value;
    } catch (error) {
      target.textContent = `만들지 못했습니다: ${refusal(error)}`;
      return null;
    }
  }

  async function reviewDerivation(derivationId, outcome) {
    try {
      const value = await command('reviews', { schema_version: 'design-review-command-v1', derivation_id: derivationId });
      await show(requestId);
      say('재검토를 기록했습니다.', 'reviewed');
      return value;
    } catch (error) {
      outcome.textContent = `재검토하지 않았습니다: ${REVIEW_REASONS[error?.reason] ?? refusal(error)}`;
      return null;
    }
  }

  async function prepareCandidate(candidateId, outcome) {
    try {
      const value = await command('preparations', { schema_version: 'design-prepare-command-v1', candidate_id: candidateId });
      outcome.textContent = `환경 버전 ${value.environment_version.version}을 준비했습니다. 준비는 활성화가 아니며 작업을 시작하지 않습니다.`;
      outcome.dataset.state = 'prepared';
      return value;
    } catch (error) {
      outcome.textContent = `준비하지 않았습니다: ${refusal(error)}`;
      outcome.dataset.state = error?.code ?? 'unavailable';
      return null;
    }
  }

  // the requests this instance serves; the first is shown
  async function load() {
    say('설계 요청을 확인하는 중…', 'loading');
    let listed;
    try {
      listed = await request(api, {});
    } catch (error) {
      say(ERROR_TEXT[error?.code] ?? ERROR_TEXT.unavailable, error?.code ?? 'unavailable');
      return null;
    }
    picker.replaceChildren(...listed.requests.map(item => element('option', `설계 요청 ${item.request_id.slice(0, 8)}`,
      { value: item.request_id })));
    picker.hidden = listed.requests.length < 2;
    if (!listed.requests.length) {
      summary.replaceChildren();
      compare.replaceChildren();
      derived.replaceChildren();
      say('이 인스턴스에 비교할 설계 요청이 없습니다.', 'empty');
      return null;
    }
    return show(listed.requests[0].request_id);
  }

  return Object.freeze({ load, show, derive, review: reviewDerivation, prepare: prepareCandidate });
}
