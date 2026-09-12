import test from 'node:test';
import assert from 'node:assert/strict';
import { ARTIFACTS, CASE, DESIGNS, REVISED_DESIGN, ROUNDS, RUNS } from '../fixtures.mjs';
import { createState, transition } from '../state.mjs';
import { e } from '../primitives.mjs';
import { render } from '../workspace.mjs';

const select = (state, type, value, extra = {}) => transition(state, { type, value, ...extra });
const fixedState = () => select(select(createState(), 'area', 'growth'), 'sample', true);
const origin = Object.values(RUNS).find(run => run.attempts.some(attempt => attempt.outputs.includes(CASE.original)));
const sections = (markup, className) => [...markup.matchAll(new RegExp(`<section class="${className}"([^>]*)>([\\s\\S]*?)<\\/section>`, 'g'))];
const closedDetails = (markup, className) => {
  const opening = markup.match(new RegExp(`<details class="${className}"[^>]*>`))?.[0];
  assert.ok(opening, `${className} disclosure exists`);
  assert.doesNotMatch(opening, /\sopen(?:\s|=|>)/, `${className} begins closed`);
};

test('the shared focus is immediately followed by all three selectable contract summaries', () => {
  let state = select(createState(), 'area', 'design');
  for (const focus of ['transfer', 'approval', 'memory', 'evaluation']) {
    state = select(state, 'focus', focus);
    const markup = render(state);
    assert.match(markup, /<nav class="focus-bar"[^>]*>[\s\S]*?<\/nav><section class="design-comparison"/);
    const comparison = sections(markup, 'design-comparison')[0]?.[2];
    assert.ok(comparison);
    assert.equal((comparison.match(/data-design-option=/g) ?? []).length, DESIGNS.length);
    for (const design of DESIGNS) {
      const option = comparison.match(new RegExp(`<div class="design-option" data-design-option="${design.id}">([\\s\\S]*?)<\\/div>`))?.[1];
      assert.ok(option, design.id);
      assert.ok(option.includes(e(design.label)));
      assert.ok(option.includes(e(design.contracts[focus])));
      assert.match(option, new RegExp(`data-action="design" data-value="${design.id}" aria-pressed="${design.id === state.design}"`));
    }
  }
});

test('only the selected candidate graph is visible and the request record does not duplicate it', () => {
  for (const chosen of [...DESIGNS, REVISED_DESIGN]) {
    let state = select(select(createState(), 'area', 'design'), 'design', chosen.id);
    for (const focus of ['transfer', 'approval', 'memory', 'evaluation']) {
      state = select(state, 'focus', focus);
      const before = JSON.stringify(state);
      const markup = render(state);
      const candidates = sections(markup, 'candidate');
      assert.equal(candidates.length, DESIGNS.length);
      assert.equal(candidates.filter(([, attrs]) => !/\shidden(?:\s|=|$)/.test(attrs)).length, chosen.id === REVISED_DESIGN.id ? 0 : 1);
      for (const design of DESIGNS) {
        const [, attrs, content] = candidates.find(([, attributes]) => attributes.includes(`data-design="${design.id}"`));
        assert.equal(/\shidden(?:\s|=|$)/.test(attrs), state.design !== design.id);
        assert.equal((content.match(/data-edge=/g) ?? []).length, design.edges.length);
        assert.equal((content.match(/<g class="node /g) ?? []).length, design.nodes.length);
        assert.ok(content.includes(e(design.contracts[focus])));
        for (const node of design.nodes) {
          const tag = [...content.matchAll(/<g class="node [^>]*>/g)].find(([opening]) => opening.includes(`data-value="${design.id}:candidate:${node.id}"`))?.[0];
          assert.ok(tag, node.id);
          assert.match(tag, new RegExp(`aria-pressed="${design.focus[focus].includes(node.id)}"`));
        }
      }
      const record = sections(markup, 'selected-design')[0]?.[2];
      assert.ok(record.includes(e(chosen.version)));
      assert.ok(record.includes(e(chosen.review)));
      assert.ok(record.includes('data-field="designText"'));
      assert.ok(record.includes('data-action="overlay" data-value="approval"'));
      assert.doesNotMatch(record, /class="graph"/);
      const merged = sections(markup, 'merged-design');
      assert.equal(merged.length, chosen.id === REVISED_DESIGN.id ? 1 : 0);
      if (merged.length) {
        assert.ok(merged[0][2].includes(e(REVISED_DESIGN.review)));
        assert.equal((merged[0][2].match(/data-edge=/g) ?? []).length, REVISED_DESIGN.edges.length);
        assert.ok(merged[0][2].includes(`${REVISED_DESIGN.id}:selected:`));
      }
      assert.equal(state.design, chosen.id);
      assert.equal(JSON.stringify(state), before, 'render and focus changes do not mutate the chosen version');
    }
  }
});

test('the observed difference precedes closed but complete source and investigation views', () => {
  for (const difference of CASE.differences) {
    const markup = render(select(fixedState(), 'difference', difference.id));
    closedDetails(markup, 'source-pair');
    closedDetails(markup, 'investigation-trace');
    const sourceAt = markup.indexOf('<details class="source-pair"');
    const navAt = markup.indexOf('aria-label="관찰된 차이"');
    const summaryAt = markup.indexOf('class="difference-summary"');
    assert.ok(navAt >= 0 && navAt < summaryAt && summaryAt < sourceAt);
    const summary = markup.slice(summaryAt, sourceAt);
    assert.ok(summary.includes(e(difference.original)));
    assert.ok(summary.includes(e(difference.alternative)));
    for (const id of [CASE.original, CASE.alternative]) {
      assert.ok(markup.indexOf(`data-artifact="${id}"`) > sourceAt);
      assert.ok(markup.includes(`href="${ARTIFACTS[id].path}"`));
    }
    const trace = markup.slice(markup.indexOf('<details class="investigation-trace"'), markup.indexOf('<h2>비교 회차</h2>'));
    for (const node of origin.nodes) assert.ok(trace.includes(`data-action="sampleNode" data-value="${node.id}"`));
    assert.equal((trace.match(/data-edge=/g) ?? []).length, origin.edges.length);
    assert.ok(markup.includes(CASE.region));
    assert.ok(markup.includes('자기 버전이 제공되지 않은 나머지 부분은 승인되거나 수정된 것으로 보지 않습니다.'));
  }
});

test('each tentative explanation leads with its claim and next probe while preserving all evidence', () => {
  const markup = render(fixedState());
  for (const difference of CASE.differences) for (const hypothesis of difference.hypotheses) {
    const content = markup.match(new RegExp(`<section data-hypothesis="${hypothesis.id}">([\\s\\S]*?)<\\/section>`))?.[1];
    assert.ok(content);
    closedDetails(content, 'hypothesis-evidence');
    const evidenceAt = content.indexOf('<details class="hypothesis-evidence"');
    const visible = content.slice(0, evidenceAt);
    assert.ok(visible.includes(e(hypothesis.claim)));
    assert.ok(visible.includes('미확정'));
    assert.ok(visible.includes(e(hypothesis.probe)));
    for (const key of ['support', 'counter', 'unknown', 'newEvidence']) {
      assert.ok(content.slice(evidenceAt).includes(e(hypothesis[key])), key);
    }
    assert.doesNotMatch(content, /<textarea|<input/);
  }
});

test('every round puts outside-scope outcomes and approval limits before closed exact paired histories', () => {
  for (const round of ROUNDS) {
    const state = select(fixedState(), 'round', round.id);
    const markup = render(state);
    closedDetails(markup, 'paired-details');
    const pairedAt = markup.indexOf('<details class="paired-details"');
    const tableAt = markup.indexOf('class="round-checks"');
    assert.ok(tableAt >= 0 && tableAt < pairedAt);
    for (const key of ['candidate', 'result', 'limits']) assert.ok(markup.indexOf(e(round[key])) < tableAt, key);
    for (const key of ['finalEvidence', 'approval']) {
      const at = markup.indexOf(e(round[key]));
      assert.ok(at > tableAt && at < pairedAt, key);
    }
    for (const check of round.checks) {
      const row = markup.match(new RegExp(`<tr><td>${e(check.label)}<\\/td>([\\s\\S]*?)<\\/tr>`))?.[1];
      assert.ok(row?.includes(e(check.result)), check.label);
      assert.ok(row.includes(`data-action="evidence" data-value="${check.evidence}"`));
    }
    assert.ok(markup.indexOf('class="paired-runs"') > pairedAt);
    for (const side of ['baseline', 'candidate']) {
      const run = RUNS[round[`${side}Run`]];
      for (const attempt of run.attempts) {
        const selected = transition(state, { type: 'pair', side, value: attempt.id });
        const pair = sections(render(selected), 'pair').find(([, attrs]) => attrs.includes(`data-pair="${side}"`));
        assert.ok(pair[1].includes(`data-run="${run.id}"`));
        assert.ok(pair[2].includes(`data-inspected-attempt="${attempt.id}"`));
        assert.equal((pair[2].match(/data-edge=/g) ?? []).length, run.edges.length);
        for (const id of [...attempt.inputs, ...attempt.outputs]) {
          assert.ok(pair[2].includes(`data-artifact="${id}"`));
          assert.ok(pair[2].includes(`href="${ARTIFACTS[id].path}"`));
        }
        for (const consumer of attempt.consumers) assert.ok(pair[2].includes(`data-action="pairAttempt" data-value="${side}:${consumer.attempt}"`));
        if (!attempt.outputs.length) assert.ok(pair[2].includes('출력 없음'));
      }
    }
  }
});
