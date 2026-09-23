// T066 (US6, UX-AC06): paired comparison rounds as they were recorded. Each round is
// shown under its lineage with every baseline run next to the candidate run it was
// paired with, the round's validity and its stated reasons, and — only on a valid
// round — the measurements and utility it recorded. An invalid or pending round never
// shows a score, and a round whose record does not read back exactly is listed as
// unreadable rather than dropped. The runs are shown by their exact references; this
// view renders no artifact and says so, so no side-by-side artifact reading is implied.
// All text reaches the DOM through textContent.

export const VALIDITY_LABELS = Object.freeze({
  valid: '유효', invalid: '무효', pending: '판정 대기',
});

export const MESSAGES = Object.freeze({
  none: '기록된 비교 라운드가 없습니다.',
  unreadable: '이 라운드 기록을 정확히 다시 읽지 못했습니다. 비교 근거로 쓰지 않습니다.',
  noScore: '유효한 라운드가 아니므로 측정값과 효용을 표시하지 않습니다.',
  noMetrics: '측정값이 기록되지 않았습니다.',
  artifacts: '짝지은 실행의 산출물은 여기에서 펼쳐 보이지 않습니다. 실행 참조로만 표시하며, 산출물을 나란히 읽었다고 간주하지 않습니다.',
});

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
      entry.append(table, element('p', outcomeText(item)));
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
