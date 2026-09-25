// T087 -> T090: the owner's provider-transport qualification section over a fake
// document, fetch and session adapter. The read shows the manifest digest, what a
// qualification requires, the prerequisite (naming the run that meets it), the sealed
// qualification and the gateway's adopted revision; the act names the run the read
// offered (or null), shows the server's exact refusal text for each code, retries an
// unread answer under the same command id and otherwise starts a new one.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  TRANSPORT_QUALIFICATION_ERRORS, TRANSPORT_QUALIFICATION_MESSAGES, createTransportQualificationPanel,
} from '../static/account.mjs';

class FakeElement {
  constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.attributes = new Map(); this.dataset = {}; this.listeners = new Map(); this._text = ''; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(_value) { throw new Error('markup is never written'); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }
  findAll(predicate, found = []) { for (const child of this.children) { if (predicate(child)) found.push(child); child.findAll(predicate, found); } return found; }
}

const document = { createElement: tag => new FakeElement(tag) };
const BASE = `/${'2'.repeat(32)}/`;
const PATH = `${BASE}api/v1/extensions/provider-transport-qualification`;
const CSRF = 'c'.repeat(43);
const DIGEST = 'd'.repeat(64);
const RUN = '11111111-1111-4111-8111-111111111111';
const REF = { kind: 'validation_report', id: '22222222-2222-4222-8222-222222222222', version: 1, sha256: 'e'.repeat(64) };

function state(overrides = {}) {
  return {
    schema_version: 'provider-transport-qualification-state-v1', provider: 'claude',
    manifest_schema: 'provider-transport-manifest-v1', manifest_sha256: DIGEST, api_origin: 'https://api.anthropic.com',
    requirements: {}, prerequisite: 'verified_installation_missing', eligible_conformance: null,
    qualification: null, gateway: { state: 'not_adopted', revision: null, manifest_sha256: null },
    state: 'unqualified', reason: 'not_qualified', ...overrides,
  };
}

function panelWith(responses) {
  const root = new FakeElement('div');
  const sent = [];
  let counter = 0;
  const fetch = async (path, options) => {
    sent.push([path, options.method, options.body === undefined ? undefined : JSON.parse(options.body), options.headers]);
    const next = responses.shift();
    if (next instanceof Error) throw next;
    const [status, body] = next;
    return { ok: status < 400, status, json: async () => body };
  };
  const randomUUID = () => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`;
  const panel = createTransportQualificationPanel({ root, document, fetch, basePath: BASE, session: { csrfToken: () => CSRF }, randomUUID });
  const line = root.findAll(el => el.getAttribute('data-transport-line') !== null)[0];
  const facts = root.findAll(el => el.getAttribute('aria-label') === '전송 매니페스트 검증 상태')[0];
  return { root, sent, panel, line, facts };
}

test('the unqualified read names the digest, the requirement and the missing prerequisite', async () => {
  const { panel, facts, sent, root } = panelWith([[200, state()]]);
  assert.deepEqual(await panel.load(), { state: 'unqualified', reason: 'not_qualified',
    prerequisite: 'verified_installation_missing', gateway: { state: 'not_adopted', revision: null, manifest_sha256: null } });
  assert.deepEqual(sent.map(([path, method]) => [path, method]), [[PATH, 'GET']]);
  const text = facts.textContent;
  assert.ok(text.includes(TRANSPORT_QUALIFICATION_MESSAGES.manifest(DIGEST)));
  assert.ok(text.includes(TRANSPORT_QUALIFICATION_MESSAGES.requirement));
  assert.ok(text.includes(TRANSPORT_QUALIFICATION_MESSAGES.prerequisite.verified_installation_missing));
  assert.ok(text.includes(TRANSPORT_QUALIFICATION_MESSAGES.unsealed));
  assert.ok(text.includes(TRANSPORT_QUALIFICATION_MESSAGES.gateway.not_adopted()));
  assert.ok(text.includes(TRANSPORT_QUALIFICATION_MESSAGES.state.not_qualified));
  assert.equal(facts.dataset.state, 'unqualified');
  assert.ok(root.textContent.includes(TRANSPORT_QUALIFICATION_MESSAGES.intro));
  assert.equal(root.findAll(el => el.getAttribute('role') === 'status').length, 0);
});

test('each refusal shows the exact server text, the act names null without a run and nothing is retried', async () => {
  for (const code of Object.keys(TRANSPORT_QUALIFICATION_ERRORS)) {
    const { panel, sent, line } = panelWith([[200, state()], [code === 'unavailable' ? 503 : 409, { code }], [200, state()]]);
    await panel.load();
    await assert.rejects(panel.qualify());
    assert.equal(line.textContent, TRANSPORT_QUALIFICATION_ERRORS[code]);
    assert.equal(line.dataset.state, code);
    const [path, method, body, headers] = sent[1];
    assert.deepEqual([path, method], [PATH, 'POST']);
    assert.deepEqual(body, { command_id: '00000000-0000-4000-8000-000000000001', manifest_sha256: DIGEST,
      conformance_command_id: null });
    assert.equal(headers['X-DeepTwin-CSRF'], CSRF);
    assert.equal(sent[2][1], 'GET');  // the state is re-read after every act
  }
  // an unknown code is shown as unavailable, never echoed
  const { panel, line } = panelWith([[200, state()], [409, { code: 'something_else' }], [200, state()]]);
  await panel.load();
  await assert.rejects(panel.qualify());
  assert.equal(line.textContent, TRANSPORT_QUALIFICATION_ERRORS.unavailable);
});

test('a met prerequisite names its run; the act publishes and the gateway adoption is shown', async () => {
  const met = state({ prerequisite: 'met', eligible_conformance: { command_id: RUN, verified_installation_ref: REF, result_ref: REF } });
  const adopted = state({ prerequisite: 'met', eligible_conformance: met.eligible_conformance,
    qualification: { revision: 1790000000000, qualification_ref: REF, conformance_command_id: RUN },
    gateway: { state: 'adopted', revision: 1790000000000, manifest_sha256: DIGEST }, state: 'qualified', reason: null });
  const answer = { command_id: '00000000-0000-4000-8000-000000000001', published: true,
    qualification: { revision: 1790000000000, manifest_sha256: DIGEST, qualification_ref: REF, conformance_command_id: RUN } };
  const { panel, sent, line, facts } = panelWith([[200, met], [200, answer], [200, adopted]]);
  await panel.load();
  assert.ok(facts.textContent.includes(TRANSPORT_QUALIFICATION_MESSAGES.prerequisite.met(RUN)));
  assert.deepEqual(await panel.qualify(), { revision: 1790000000000, published: true });
  assert.equal(sent[1][2].conformance_command_id, RUN);
  assert.equal(line.textContent, TRANSPORT_QUALIFICATION_MESSAGES.published(1790000000000));
  assert.equal(facts.dataset.state, 'qualified');
  assert.ok(facts.textContent.includes(TRANSPORT_QUALIFICATION_MESSAGES.gateway.adopted(1790000000000)));
  assert.ok(facts.textContent.includes(TRANSPORT_QUALIFICATION_MESSAGES.sealed(1790000000000, RUN)));
  assert.ok(facts.textContent.includes(TRANSPORT_QUALIFICATION_MESSAGES.state.qualified));
});

test('an unpublished qualification says so; an unread answer is retried under the same command id', async () => {
  const met = state({ prerequisite: 'met', eligible_conformance: { command_id: RUN, verified_installation_ref: REF, result_ref: REF } });
  const sealed = { ...met, qualification: { revision: 7, qualification_ref: REF, conformance_command_id: RUN }, reason: 'not_published' };
  const unpublished = { command_id: '00000000-0000-4000-8000-000000000001', published: false,
    qualification: { revision: 7, manifest_sha256: DIGEST, qualification_ref: REF, conformance_command_id: RUN } };
  const { panel, sent, line, facts } = panelWith([[200, met], new TypeError('network'), [200, met],
    [200, unpublished], [200, sealed], [200, { ...unpublished, command_id: '00000000-0000-4000-8000-000000000002' }], [200, sealed]]);
  await panel.load();
  await assert.rejects(panel.qualify());
  assert.equal(line.textContent, TRANSPORT_QUALIFICATION_ERRORS.unavailable);
  await panel.qualify();
  assert.equal(sent[1][2].command_id, sent[3][2].command_id);  // the same command, only looked up
  assert.equal(line.textContent, TRANSPORT_QUALIFICATION_MESSAGES.unpublished(7));
  assert.ok(facts.textContent.includes(TRANSPORT_QUALIFICATION_MESSAGES.state.not_published));
  await panel.qualify();
  assert.equal(sent[5][2].command_id, '00000000-0000-4000-8000-000000000002');  // a settled act starts over
});

test('a malformed or refused read clears the facts and says so', async () => {
  const { panel, facts, line } = panelWith([[200, { ...state(), state: 'qualified' }], [503, { code: 'unavailable' }]]);
  await assert.rejects(panel.load());
  assert.equal(facts.children.length, 0);
  assert.equal(line.textContent, TRANSPORT_QUALIFICATION_ERRORS.unavailable);
  assert.equal(panel.state, null);
  await assert.rejects(panel.load());
  assert.equal(line.dataset.state, 'unavailable');
});
