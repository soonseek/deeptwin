// T048 (experience.md §6.3 `업무 시작`): starting a run from the work page. The section
// reads what a run of this work can use (`GET /api/v1/run-environments/{work}`: the
// owner's prepared environment versions, each bound back to its stored graph, the work
// revision it was designed for, its bindings, grants and critic qualification) and the
// owner's budget policies (`GET /api/v1/budget-policies`). It shows exactly what the run
// will use and what the consent covers, records the owner's consent through the
// run-consents route and starts the run through the runs route — the server verifies
// every input itself — then links to the observation page. Without a prepared environment
// it says exactly why (no approved design: no critic configuration can be qualified here)
// and offers no start: nothing is started, simulated or implied. A qualification outside
// the release designs is labelled a simulation (test-actor). All text uses textContent.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
export const CONSENT_SCHEMA = 'run-consent-command-v1';

const ERROR_TEXT = Object.freeze({
  invalid_input: '요청 형식이 맞지 않습니다.',
  unauthenticated: '세션이 끝났습니다. 시작 화면(./)에서 다시 로그인해 주세요.',
  access_denied: '서버가 이 입력으로는 실행을 허용하지 않았습니다 (동의가 입력과 정확히 맞지 않거나 철회·만료됨).',
  not_found: '이 업무나 실행 입력을 이 인스턴스에서 찾지 못했습니다.',
  conflict: '같은 명령이 이미 다른 내용으로 처리되었거나 이 동의가 이미 쓰였습니다.',
  unavailable: '서버가 요청을 처리하지 못했습니다.',
});
export const ABSENCE_TEXT = Object.freeze({
  unqualifiable: '준비된 실행 환경이 없어 실행을 시작할 수 없습니다. 승인된 설계가 없습니다: 설계를 승인하려면 평가자(critic) 구성과 렌즈의 자격이 필요한데, 이 인스턴스에는 자격을 얻을 수 있는 평가자 구성이 없습니다 (V3 오류 독립성 미검증).',
  not_yet: '준비된 실행 환경이 없어 실행을 시작할 수 없습니다. 이 업무의 설계 후보 중 하나를 "이 설계로 준비"로 먼저 준비해 주세요.',
});

function fail(message) {
  throw Object.assign(new Error(message), { code: 'invalid_input' });
}

const short = value => String(value).slice(0, 8);
const refText = ref => (ref ? `${ref.kind} ${short(ref.id)} v${ref.version}` : '없음');

export function absenceText(view) {
  return view.absence?.critic_qualifiable === false ? ABSENCE_TEXT.unqualifiable : ABSENCE_TEXT.not_yet;
}

export function qualificationLine(entry) {
  const q = entry.critic_qualification;
  const simulated = q.simulated ? ' — 시뮬레이션(테스트 행위자) 자격이며 출시 자격이 아닙니다' : '';
  return `${q.status} (${q.reason})${simulated}`;
}

export function budgetText(policy) {
  const cost = policy.provider_mode === 'api' ? ` · 비용 한도 ${policy.max_api_microunits} ${policy.currency} 마이크로단위` : '';
  return `${policy.profile} · ${policy.provider_mode} · 모델 호출 ${policy.max_model_calls} · 도구 호출 ${policy.max_tool_calls} · 노드 방문 ${policy.max_node_visits} · 반복 ${policy.max_loop_rounds} · 출력 ${policy.max_output_bytes}바이트 · 동시 ${policy.max_concurrency} · ${policy.max_wall_seconds}초 · 후보 ${policy.max_candidates}${cost}`;
}

// exactly what one run will name and use, as [label, value] rows
export function usageRows(entry, policy) {
  const graph = entry.graph;
  return [
    ['환경 버전', `${short(entry.environment_id)} 버전 ${entry.version} · 준비됨 (활성화 아님)`],
    ['그래프', `${refText(entry.graph_ref)} · 노드 ${graph.nodes.length}개: ${graph.nodes.map(node => `${node.node_id}(${node.kind})`).join(', ')}`],
    ['작업 수정본', `수정본 ${entry.work_revision_ref.version}${entry.revision_current ? ' (현재 수정본)' : ' — 설계가 만들어진 수정본이며 이후 더 새 수정본이 있습니다'}`],
    ['모델 연결', graph.model_bindings.length ? graph.model_bindings.map(item => `${item.binding_id} → ${refText(item.model_choice_ref)}`).join(', ') : '없음'],
    ['도구 연결', graph.tool_bindings.length ? graph.tool_bindings.map(item => `${item.binding_id} [${item.capabilities.join(', ')}] 권한 ${refText(item.grant_ref)}`).join(', ') : '없음'],
    ['승인된 권한', `모델 ${refText(entry.approval.model_bindings_ref)} · 도구 권한 ${refText(entry.approval.tool_permissions_ref)} · 관측 계약 ${refText(entry.approval.observation_contract_ref)}`],
    ['확장 연결', entry.extension_binding_revisions.length ? `${entry.extension_binding_revisions.length}개 (준비 당시 기록)` : '없음'],
    ['평가자 자격', qualificationLine(entry)],
    ['예산 정책', policy ? budgetText(policy) : '선택되지 않음'],
    ['동의 범위', '위 그래프·작업 수정본·환경 버전·예산 정책 네 기록에만, 실행 한 번에만 쓰입니다. 외부 쓰기·결제 변경·승격은 포함하지 않습니다.'],
  ];
}

export function createRunStart({ root, document, request, basePath = '/', commandId, workId } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  if (typeof commandId !== 'function') fail('a command id source is required');
  if (typeof workId !== 'function') fail('a work id source is required');
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const api = `${basePath.slice(0, -1)}/api/v1`;

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', '', { role: 'status', 'aria-live': 'polite', class: 'run-start-status' });
  const body = element('div', undefined, { class: 'run-start-body' });
  const refresh = element('button', '실행 준비 다시 읽기', { type: 'button' });
  root.replaceChildren(element('h2', '실행 시작'), status, body, refresh);
  refresh.addEventListener('click', () => { load().catch(() => {}); });
  let view = null;
  let policies = [];
  let busy = false;

  function say(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  function render(selected = 0, policyIndex = 0) {
    const environments = view.environments;
    if (!environments.length) {
      body.replaceChildren(element('p', absenceText(view), { class: 'run-start-absent', 'data-reason': view.absence?.reason ?? '' }));
      say('실행을 시작할 수 없습니다.', 'absent');
      return;
    }
    const picker = element('select', undefined, { 'aria-label': '실행 환경 선택' });
    environments.forEach((entry, index) => {
      const option = element('option', `환경 ${short(entry.environment_id)} 버전 ${entry.version} · 준비됨`, { value: String(index) });
      picker.append(option);
    });
    picker.value = String(selected);
    const budget = element('select', undefined, { 'aria-label': '예산 정책 선택' });
    policies.forEach((policy, index) => budget.append(element('option', budgetText(policy), { value: String(index) })));
    budget.value = String(policyIndex);
    const entry = environments[selected];
    const policy = policies[policyIndex] ?? null;
    const usage = element('dl', undefined, { class: 'run-start-usage', 'aria-label': '이 실행이 쓰는 것' });
    for (const [label, value] of usageRows(entry, policy)) usage.append(element('dt', label), element('dd', value));
    const agree = element('input', undefined, { type: 'checkbox', 'aria-label': '위 내용으로 이 실행 한 번에 동의합니다' });
    const start = element('button', '동의하고 실행 시작', { type: 'button', 'data-command': 'start' });
    const outcome = element('p', '', { role: 'status', class: 'run-start-outcome' });
    const blockers = [];
    if (!view.runs.available) blockers.push('이 인스턴스에 실행기가 설정되지 않아 실행을 시작할 수 없습니다.');
    if (!entry.usable) blockers.push(`이 환경으로는 시작할 수 없습니다 (${entry.unusable_reason}).`);
    if (!policy) blockers.push('예산 정책이 없습니다. 기록·내보내기 화면(./records.html)에서 실행 예산을 먼저 만들어 주세요.');
    const update = () => { start.disabled = busy || blockers.length > 0 || !agree.checked; };
    agree.addEventListener('change', update);
    picker.addEventListener('change', () => render(Number(picker.value), Number(budget.value)));
    budget.addEventListener('change', () => render(Number(picker.value), Number(budget.value)));
    start.addEventListener('click', () => begin(entry, policy, outcome, start));
    update();
    body.replaceChildren(picker, budget, element('h3', '이 실행이 쓰는 것'), usage,
      ...blockers.map(text => element('p', text, { class: 'run-start-blocked' })),
      element('label', '위 내용으로 이 실행 한 번에 동의합니다'), agree, start, outcome);
    say(`준비된 환경 ${environments.length}개`, 'ready');
  }

  async function begin(entry, policy, outcome, start) {
    if (busy || !policy) return null;
    busy = true;
    start.disabled = true;
    const inputs = { graph_ref: entry.graph_ref, work_revision_ref: entry.work_revision_ref,
      environment_ref: entry.environment_ref, budget_policy_ref: policy.budget_policy_ref };
    try {
      outcome.textContent = '동의를 기록하는 중…';
      const consent = await request(`${api}/run-consents`, { method: 'POST',
        body: { schema_version: CONSENT_SCHEMA, command_id: commandId(), ...inputs } });
      outcome.textContent = '실행을 시작하는 중…';
      const run = await request(`${api}/runs`, { method: 'POST',
        body: { command_id: commandId(), ...inputs, consent_ref: consent.ref } });
      outcome.replaceChildren(element('span', `실행 ${short(run.run_id)}을 시작했습니다 · 상태 ${run.phase}. `),
        element('a', '관제 화면에서 보기', { href: `./observe.html?run=${run.run_id}`, 'data-run': run.run_id }));
      outcome.dataset.state = 'started';
      return run;
    } catch (error) {
      outcome.textContent = `시작하지 않았습니다: ${ERROR_TEXT[error?.code] ?? ERROR_TEXT.unavailable}`;
      outcome.dataset.state = error?.code ?? 'unavailable';
      return null;
    } finally {
      busy = false;
      start.disabled = false;
    }
  }

  async function load() {
    const work = workId();
    if (work === null || work === undefined) {
      body.replaceChildren();
      say('업무를 먼저 저장하면 실행 준비를 확인합니다.', 'no_work');
      return null;
    }
    if (typeof work !== 'string' || !UUID.test(work)) fail('work id is not a canonical UUID');
    say('실행 준비를 확인하는 중…', 'loading');
    try {
      view = await request(`${api}/run-environments/${work}`, {});
      policies = (await request(`${api}/budget-policies`, {})).policies ?? [];
    } catch (error) {
      body.replaceChildren();
      say(ERROR_TEXT[error?.code] ?? ERROR_TEXT.unavailable, error?.code ?? 'unavailable');
      return null;
    }
    render();
    return view;
  }

  return Object.freeze({ load });
}
