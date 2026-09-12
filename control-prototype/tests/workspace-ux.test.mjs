import test from 'node:test';
import assert from 'node:assert/strict';
import { ARTIFACTS } from '../fixtures.mjs';
import { context, createState, transition } from '../state.mjs';
import { artifact } from '../primitives.mjs';
import { render, overlay } from '../workspace.mjs';

test('run exposes an addressable result work area and explicit original/alternative regions', () => {
  const html = render(createState());
  assert.match(html, /id="selection-workspace"[^>]*tabindex="-1"/);
  assert.match(html, /id="run-graph-target"[^>]*tabindex="-1"/);
  assert.match(html, /class="run-layout"/);
  assert.match(html, /class="original-region"><h3>선택한 원본/);
  assert.match(html, /class="user-version-region"><h3>같은 조건에서 내가 만든 버전/);
  assert.ok(html.indexOf('class="original-region"') < html.indexOf('class="user-version-region"'));
  for (const action of ['inspect', 'graphBack', 'compose']) assert.ok(html.includes(`data-action="${action}"`));
  assert.match(html, /<details class="inspector-details">/);
});

test('the exact selected output is visibly pressed without altering its reference', () => {
  const state = createState();
  const selected = context(state).artifact;
  const tag = [...render(state).matchAll(/<button[^>]*data-action="artifact"[^>]*>/g)]
    .find(match => match[0].includes(`data-value="${selected}"`))?.[0];
  assert.match(tag, /aria-pressed="true"/);
});

test('fresh improvement retains the original and literal alternative as separate regions', () => {
  const state = transition(transition(createState(), { type: 'draft', value: '\n내 버전 <원문>' }), { type: 'area', value: 'growth' });
  const html = render(state);
  assert.match(html, new RegExp(`data-artifact="${context(state).artifact}"`));
  assert.match(html, /class="user-version-content">\n내 버전 &lt;원문&gt;/);
  assert.match(html, /class="artifact-pair current-pair"/);
  assert.doesNotMatch(html, /data-hypothesis=/);
});

test('conversation is a context-linked work layout rather than an entire duplicate graph', () => {
  const state = transition(createState(), { type: 'mode', value: 'conversation' });
  const html = render(state);
  assert.match(html, /class="mode-layout"/);
  assert.equal((html.match(/id="draft-input"/g) ?? []).length, 1);
  assert.equal((html.match(/id="note-input"/g) ?? []).length, 1);
  assert.match(html, /<details class="run-context">/);
});

test('audit identifies the current context before preserving full synthetic audit groups', () => {
  const state = createState();
  const html = overlay(state, 'audit');
  assert.match(html, /class="audit-context"/);
  assert.ok(html.includes(context(state).artifact));
  assert.match(html, /<details class="audit-group">/);
  assert.match(html, /직접적인 연결 근거/);
});

test('synthetic whole scope is not offered twice', () => {
  const file = Object.values(ARTIFACTS).find(item => item.regions.length === 1 && item.regions[0].id === 'whole');
  assert.ok(file);
  const html = artifact(file.id, { selectable: true });
  assert.equal((html.match(/data-action="scope" data-value="whole"/g) ?? []).length, 1);
});

test('selected input says it was received, preserving its producer and recipient', () => {
  const state = transition(createState(), { type: 'artifact', value: 'slots-j1-origin' });
  assert.equal(context(state).artifact, 'slots-j1-origin');
  const html = render(state);
  assert.match(html, /class="artifact-provenance" data-role="input"/);
  assert.match(html, /이용 시간 구성 → 안내문 작성/);
  assert.match(html, /이 수행이 받은 입력/);
});

test('artifact headings use concise task names while retaining exact fixture metadata', () => {
  const file = ARTIFACTS[context(createState()).artifact];
  const html = artifact(file.id);
  const heading = html.match(/<strong>(.*?)<\/strong>/)?.[1];
  assert.ok(heading && !heading.includes('synthetic UI fixture'));
  assert.ok(html.includes(file.id));
  assert.ok(html.includes('title="' + file.label + '"'));
});
