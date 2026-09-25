// T066 (US6, UX-AC06): paired comparison rounds as they were recorded. Each round is
// shown under its lineage with every baseline run next to the candidate run it was
// paired with, the round's validity and its stated reasons, and — only on a valid
// round — the measurements and utility it recorded. An invalid or pending round never
// shows a score, and a round whose record does not read back exactly is listed as
// unreadable rather than dropped. The runs are shown by their exact references; this
// view renders no artifact and says so, so no side-by-side artifact reading is implied.
// A round whose queue named past external effects (G-14) lists each item's outcome —
// compared, or not comparable with its reason — and the isolation boundary every
// isolated tool call used (a replay bound to the recorded ToolCall, or an isolated sink);
// nothing was sent to a real service again. All text reaches the DOM through textContent.

export const VALIDITY_LABELS = Object.freeze({
  valid: '유효', invalid: '무효', pending: '판정 대기',
});

export const MESSAGES = Object.freeze({
  none: '기록된 비교 라운드가 없습니다.',
  unreadable: '이 라운드 기록을 정확히 다시 읽지 못했습니다. 비교 근거로 쓰지 않습니다.',
  noScore: '유효한 라운드가 아니므로 측정값과 효용을 표시하지 않습니다.',
  noMetrics: '측정값이 기록되지 않았습니다.',
  artifacts: '각 라운드는 항목별로 기준과 후보가 만든 노드 결과를 나란히 보여 줍니다. 결과를 보존하지 않은 라운드는 그렇다고 밝힙니다.',
  noOutputs: '이 라운드는 두 쪽의 산출물을 보존하지 않았습니다. 실행 참조만 있습니다.',
  outputsUnreadable: '이 라운드의 보존된 산출물을 정확히 다시 읽지 못했습니다.',
  effects: '과거 발송·게시는 다시 실행하지 않았습니다. 승인된 기록 재생이나 격리 싱크로만 답했고, 그럴 수 없는 항목은 비교하지 않았습니다.',
  outcomesUnreadable: '이 라운드의 항목별 결과를 정확히 다시 읽지 못했습니다.',
});

export const ITEM_OUTCOMES = Object.freeze({
  compared: '비교함', not_comparable: '비교 불가', invalid: '무효', failed: '실행 실패',
});

const SIDES = Object.freeze({ baseline_effects: '기준', candidate_effects: '후보' });

const short = ref => (ref && typeof ref.id === 'string' && typeof ref.sha256 === 'string'
  ? `${ref.kind} ${ref.id.slice(0, 8)} (${ref.sha256.slice(0, 12)})` : '없음');

function fail(message) {
  throw new Error(message);
}

// rounds grouped by lineage, each lineage in recorded round order
export function roundsByLineage(rounds) {
  if (!Array.isArray(rounds)) fail('rounds must be a list');
  const lineages = new Map();
  const unreadable = [];
  for (const item of rounds) {
    if (item?.readable !== true) {
      unreadable.push(item);
      continue;
    }
    if (!lineages.has(item.lineage_id)) lineages.set(item.lineage_id, []);
    lineages.get(item.lineage_id).push(item);
  }
  for (const list of lineages.values()) list.sort((a, b) => a.round_index - b.round_index);
  return { lineages, unreadable };
}

// the text of one round's outcome; a score appears only on a valid round
export function outcomeText(item) {
  const validity = VALIDITY_LABELS[item.validity] ?? String(item.validity);
  const reasons = item.validity_reasons.length ? ` · 사유: ${item.validity_reasons.join(', ')}` : '';
  if (item.validity !== 'valid') return `${validity}${reasons} · ${MESSAGES.noScore}`;
  const metrics = item.metric_vector === null ? MESSAGES.noMetrics
    : Object.entries(item.metric_vector).map(([name, value]) => `${name} ${value}`).join(', ');
  const utility = item.utility === null ? '효용 미기록' : `효용 ${item.utility}`;
  return `${validity}${reasons} · ${metrics} · ${utility}`;
}

// what each side produced, per item, side by side: every node's result on both sides, the
// nodes whose results differ marked, and those outside the declared change scope named
export function outputsView(element, outputs) {
  if (outputs === undefined || outputs === null) return [element('p', MESSAGES.noOutputs)];
  if (!Array.isArray(outputs)) return [element('p', MESSAGES.outputsUnreadable)];
  const parts = [];
  for (const item of outputs) {
    const changed = new Set(item.changed_nodes);
    const outside = new Set(item.unexplained_nodes);
    const table = element('table', undefined, { 'aria-label': `항목 ${item.item_index} 산출물 비교` });
    const head = element('tr');
    head.append(element('th', '노드', { scope: 'col' }), element('th', '기준 결과', { scope: 'col' }),
      element('th', '후보 결과', { scope: 'col' }));
    table.append(element('caption', `항목 ${item.item_index}: 달라진 노드 ${item.changed_nodes.length}개`
      + (item.unexplained_nodes.length ? ` · 변경 범위 밖 ${item.unexplained_nodes.join(', ')}` : '')), head);
    const byNode = side => new Map(side.map(entry => [entry.node_id, entry]));
    const left = byNode(item.baseline);
    const right = byNode(item.candidate);
    for (const node of [...new Set([...left.keys(), ...right.keys()])].sort()) {
      const text = entry => (entry ? `${entry.result_text}${entry.truncated ? ` … (${entry.result_bytes}바이트 중 일부)` : ''}` : '결과 없음');
      const row = element('tr', undefined, { 'data-changed': changed.has(node) ? 'true' : 'false',
        ...(outside.has(node) ? { 'data-outside-scope': 'true' } : {}) });
      row.append(element('th', `${node}${changed.has(node) ? ' · 다름' : ''}`, { scope: 'row' }),
        element('td', text(left.get(node))), element('td', text(right.get(node))));
      table.append(row);
    }
    parts.push(table);
  }
  return parts;
}

// one isolated tool call and the boundary that answered it
export function effectText(effect) {
  const tool = `${effect.tool_id} ${effect.version} (${effect.effect_class})`;
  if (effect.boundary === 'replay') {
    return `${tool} · 기록 재생: ToolCall 기록 ${String(effect.tool_call_sha256).slice(0, 12)}의 결과 · 실제 서비스로 다시 보내지 않음`;
  }
  if (effect.boundary === 'isolated_sink') {
    return `${tool} · 격리 싱크 ${effect.sink_id}에 보관(입력 sha256 ${String(effect.inputs_digest).slice(0, 12)}) · 실제 서비스로 보내지 않음`;
  }
  return `${tool} · ${String(effect.boundary)}`;
}

// each queue item's outcome in a round whose queue involved tool effects; none otherwise
export function itemOutcomesView(element, outcomes) {
  if (outcomes === undefined || outcomes === null) return [];
  if (!Array.isArray(outcomes)) return [element('p', MESSAGES.outcomesUnreadable)];
  const list = element('ul', undefined, { 'aria-label': '항목별 결과' });
  for (const item of outcomes) {
    const past = item.past_tool_effects.length
      ? ` · 과거 외부 효과 ${item.past_tool_effects.length}건: ${item.past_tool_effects.map(entry =>
        `${entry.tool_id} ${entry.version} (ToolCall 기록 ${entry.tool_call_sha256.slice(0, 12)})`).join(', ')}` : '';
    const reasons = item.reasons.length ? ` · 사유: ${item.reasons.join(', ')}` : '';
    const entry = element('li', `항목 ${item.item_index}: ${ITEM_OUTCOMES[item.outcome] ?? String(item.outcome)}${reasons}${past}`,
      { 'data-item-outcome': String(item.outcome) });
    const calls = element('ul');
    for (const [key, label] of Object.entries(SIDES)) {
      for (const effect of item[key]) {
        calls.append(element('li', `${label}: ${effectText(effect)}`, { 'data-boundary': String(effect.boundary) }));
      }
    }
    if (item.outcome === 'compared' && !item.baseline_effects.length && !item.candidate_effects.length) {
      calls.append(element('li', '도구 호출 없음'));
    }
    entry.append(calls);
    list.append(entry);
  }
  return [element('p', MESSAGES.effects), list];
}

export function renderRounds({ root, document, rounds }) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  const element = (tag, text, attributes = {}) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  };
  const { lineages, unreadable } = roundsByLineage(rounds);
  const parts = [element('h3', '비교 라운드')];
  if (!lineages.size && !unreadable.length) parts.push(element('p', MESSAGES.none));
  else parts.push(element('p', MESSAGES.artifacts));
  for (const [lineage, list] of lineages) {
    const group = element('section', undefined, { 'aria-label': `계보 ${lineage.slice(0, 8)}` });
    group.append(element('h4', `계보 ${lineage.slice(0, 8)} · 기준 환경 ${short(list[0].baseline_environment_ref)}`));
    for (const item of list) {
      const entry = element('article', undefined, { 'aria-label': `라운드 ${item.round_index}`, 'data-validity': item.validity });
      entry.append(element('h5', `라운드 ${item.round_index} (${item.round_id}) · 후보 ${short(item.candidate_ref)}`));
      const table = element('table');
      const head = element('tr');
      head.append(element('th', '기준 실행', { scope: 'col' }), element('th', '후보 실행', { scope: 'col' }));
      table.append(element('caption', `짝지은 실행 ${item.pairs.length}쌍`), head);
      for (const pair of item.pairs) {
        const row = element('tr');
        row.append(element('td', short(pair.baseline_run_ref)), element('td', short(pair.candidate_run_ref)));
        table.append(row);
      }
      entry.append(table, element('p', outcomeText(item)), ...itemOutcomesView(element, item.item_outcomes),
        ...outputsView(element, item.outputs));
      entry.append(element('p', item.evidence_refs.length
        ? `근거 ${item.evidence_refs.length}건: ${item.evidence_refs.map(short).join(', ')}` : '근거 참조 없음'));
      group.append(entry);
    }
    parts.push(group);
  }
  for (const item of unreadable) {
    parts.push(element('p', `${short(item?.round_record)}: ${MESSAGES.unreadable}`, { 'data-validity': 'unreadable' }));
  }
  root.replaceChildren(...parts);
  return { lineages: lineages.size, unreadable: unreadable.length };
}

// G-14 approvals (2026-09-25): the isolation boundary each persisted comparison plan's
// tool effect policy names per tool, what it means, and the owner's standing decision.
// A boundary is used only after the owner approves it here; neither boundary sends
// anything to a real service.
export const BOUNDARY_MESSAGES = Object.freeze({
  intro: '과거에 발송·게시한 업무를 다시 비교할 때, 도구마다 계획이 정한 경계 하나만 쓸 수 있고 소유자가 승인해야만 씁니다. '
    + '어느 경계도 실제 서비스로 보내지 않습니다. 승인하지 않은 경계가 필요한 항목은 비교하지 않습니다.',
  none: '도구 효과 경계를 정한 비교 계획이 없습니다.',
  unreadable: '이 계획의 도구 효과 정책을 정확히 읽지 못했습니다. 과거 외부 효과가 있는 항목은 비교하지 않습니다.',
  noBoundaries: '이 계획의 정책은 경계를 두지 않습니다. 과거 외부 효과가 있는 항목은 비교하지 않습니다.',
  unavailable: '도구 효과 경계를 불러오지 못했습니다.',
});

export const BOUNDARY_MEANINGS = Object.freeze({
  replay: '과거 호출의 기록된 결과를 그대로 돌려줍니다. 실제 서비스로 다시 보내지 않습니다.',
  isolated_sink: '보내려던 내용을 격리된 실행의 보관소 안에만 남깁니다. 실제 서비스로 보내지 않습니다.',
});

export const BOUNDARY_STATES = Object.freeze({
  pending: '결정 대기', approved: '승인됨', rejected: '거절됨', unreadable: '결정 기록을 읽지 못함',
});

const boundaryKind = item => (item.boundary === 'replay' ? '기록 재생'
  : item.boundary === 'isolated_sink' ? `격리 싱크 ${item.sink_id}` : String(item.boundary));

// one boundary: the tool, the boundary kind, what it does, its digest and decision
export function boundaryText(item) {
  const meaning = BOUNDARY_MEANINGS[item.boundary] ?? '알 수 없는 경계입니다. 승인할 수 없습니다.';
  const state = BOUNDARY_STATES[item.state] ?? String(item.state);
  const when = item.state === 'approved' || item.state === 'rejected' ? ` (${item.decided_at_utc})` : '';
  return `${item.tool_id} ${item.version} (${item.effect_class}) · ${boundaryKind(item)} · ${meaning} `
    + `· 경계 sha256 ${String(item.boundary_sha256).slice(0, 12)} · 상태: ${state}${when}`;
}

export function renderBoundaries({ root, document, plans, onDecide }) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  const element = (tag, text, attributes = {}) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  };
  const parts = [element('h3', '도구 효과 경계 승인')];
  if (!Array.isArray(plans)) {
    parts.push(element('p', BOUNDARY_MESSAGES.unavailable, { 'data-state': 'unavailable' }));
    root.replaceChildren(...parts);
    return { plans: 0 };
  }
  parts.push(element('p', BOUNDARY_MESSAGES.intro));
  if (!plans.length) parts.push(element('p', BOUNDARY_MESSAGES.none));
  for (const plan of plans) {
    const lineage = typeof plan.lineage_id === 'string' ? plan.lineage_id.slice(0, 8) : '알 수 없음';
    const group = element('section', undefined, { 'aria-label': `계획 ${lineage}`, 'data-readable': String(plan.readable) });
    group.append(element('h4', `계보 ${lineage} · 비교 계획 ${short(plan.plan_record)}`));
    if (!plan.readable) {
      group.append(element('p', `${BOUNDARY_MESSAGES.unreadable} (${plan.reason})`));
      parts.push(group);
      continue;
    }
    if (!plan.boundaries.length) group.append(element('p', BOUNDARY_MESSAGES.noBoundaries));
    const list = element('ul', undefined, { 'aria-label': '필요한 경계' });
    for (const item of plan.boundaries) {
      const entry = element('li', undefined, { 'data-boundary': String(item.boundary), 'data-state': String(item.state),
        'data-tool': `${item.tool_id} ${item.version}` });
      entry.append(element('span', boundaryText(item)));
      const known = Object.hasOwn(BOUNDARY_MEANINGS, item.boundary) && item.state !== 'unreadable';
      for (const [decision, label, skip] of [['approve', '승인', 'approved'], ['reject', '거절', 'rejected']]) {
        if (!known || item.state === skip || typeof onDecide !== 'function') continue;
        const button = element('button', `경계 ${label}`, { type: 'button',
          'aria-label': `경계 ${label}: ${item.tool_id} ${item.version} (${boundaryKind(item)})` });
        button.addEventListener('click', () => Promise.resolve(onDecide(plan, item, decision)).catch(() => {}));
        entry.append(button);
      }
      list.append(entry);
    }
    if (plan.boundaries.length) group.append(list);
    parts.push(group);
  }
  root.replaceChildren(...parts);
  return { plans: plans.length };
}
