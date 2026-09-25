// Settings > Extensions (app/static/extensions.mjs) over a fake document, fetch and
// session adapter: what the screen shows from each fixed extension route's reply, what it
// marks as not supplied, and the exact bodies of the owner acts those routes carry —
// candidate metadata registration, release-evidence packet verification (bytes as the file
// holds them) and the verified-installation conformance run carrying exactly the head the
// screen read; a 409 is shown as a conflict and never retried with another head, an unread
// answer is resent under the same command id. No bind/disable/rollback/release control
// exists and no host/operator instruction is rendered.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CONFORMANCE_STATES, CREDENTIALS_LINK, ERRORS, INSTALLATION_MEDIA_TYPE, MESSAGES, NOT_SUPPLIED, SUPPLY,
  candidateCommand, candidateFacts, conformanceCommand, createExtensionsPanel, headFrom, packetHeader,
} from '../static/extensions.mjs';

class FakeElement {
  constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.attributes = new Map(); this.dataset = {}; this.listeners = new Map(); this._text = ''; this.value = ''; }
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
const API = `${BASE}api/v1/extensions`;
const CSRF = 'c'.repeat(43);
const RUN = '11111111-1111-4111-8111-111111111111';
const INSTALLATION = '33333333-3333-4333-8333-333333333333';
const CANDIDATE = '44444444-4444-4444-8444-444444444444';
const STAGED = { kind: 'extension_installation', id: INSTALLATION, version: 1, sha256: 'a'.repeat(64) };
const VERIFIED = { kind: 'extension_installation', id: INSTALLATION, version: 2, sha256: 'b'.repeat(64) };

function qualification(overrides = {}) {
  return {
    schema_version: 'provider-transport-qualification-state-v1', provider: 'claude',
    manifest_schema: 'provider-transport-manifest-v1', manifest_sha256: 'd'.repeat(64), api_origin: 'https://api.example.test',
    requirements: {}, prerequisite: 'verified_installation_missing', eligible_conformance: null,
    qualification: null, gateway: { state: 'unavailable', revision: null, manifest_sha256: null },
    state: 'unqualified', reason: 'gateway_unavailable', ...overrides,
  };
}

function conformanceReply(overrides = {}) {
  return {
    schema_version: 'provider-conformance-reply-v2', command_id: RUN, staged_installation_ref: STAGED,
    verified_installation_ref: VERIFIED, intent_ref: { kind: 'provider_conformance_run', id: RUN, version: 1, sha256: 'e'.repeat(64) },
    result_ref: { kind: 'provider_conformance_run', id: RUN, version: 2, sha256: 'f'.repeat(64) }, state: 'matched',
    suite_version: 'private-provider-conformance-v1', suite_sha256: '1'.repeat(64), stage_context_sha256: '2'.repeat(64),
    admission_sha256: '3'.repeat(64), completed_count: 4, matched_count: 4, event_cursor: 'cursor',
    links: { self: `${API}/provider-conformance/${RUN}`, events: `${BASE}api/v1/events` }, ...overrides,
  };
}

function installationReply(overrides = {}) {
  return {
    schema_version: 'provider-installation-reply-v1', command_id: '55555555-5555-4555-8555-555555555555',
    staged_installation_ref: STAGED, verified_installation_ref: VERIFIED, state: 'verified', revision: 2,
    release_review_sha256: '4'.repeat(64), release_source_context_sha256: '5'.repeat(64), verified_at_ms: 1790000000000,
    event_cursor: 'cursor', links: { self: 'x', events: 'y' }, ...overrides,
  };
}

function candidateRead() {
  const ref = kind => ({ document_kind: kind, sha256: '6'.repeat(64), size_bytes: 10 });
  return {
    candidate_ref: { candidate_id: CANDIDATE, manifest_digest: '7'.repeat(64), service_descriptor_digest: '8'.repeat(64) },
    command_id: '66666666-6666-4666-8666-666666666666', event_cursor: 'c', links: {}, registration_digest: '9'.repeat(64),
    state: 'registered_unqualified',
    registration: { registered_by: { id: 'owner-actor' }, registered_at: '2026-09-25T00:00:00.000Z', source_class: 'owner_proposal' },
    manifest: { extension_id: 'synthetic-tool', extension_version: '1.0.0', extension_kind: 'tool', port_contract_version: 'tool-port-v1',
      artifact: { artifact_form: 'oci_extension_service' },
      source: { kind: 'third_party', locator: 'https://example.test/synthetic', provenance_ref: ref('provenance') },
      license: { expression: 'Synthetic', text_ref: ref('license') },
      compatibility: { framework_min: '1.0.0', framework_max: '1.0.0', extension_api_min: '1.0.0', extension_api_max: '1.0.0', schema_versions: ['domain-v1'] },
      requirements: { grant_ids: [], secret_needs: [], filesystem_needs: ['owned_scratch'], network_policy_ref: ref('network_declaration'),
        resource_profile_ref: ref('resource_declaration'), isolation_profile_ref: ref('isolation_declaration') } },
    service_descriptor: { service_identity: 'synthetic-worker', image_repository: 'registry.example.test/tools/synthetic',
      index: { digest: `sha256:${'a'.repeat(64)}` }, platforms: [{ platform: 'linux/amd64', manifest: { digest: 'sha256:m1' } }] },
    documents: [{ document_kind: 'license', content: 'Synthetic license\n' }, { document_kind: 'sbom', content: {} }],
  };
}

function panelWith(responses) {
  const root = new FakeElement('section');
  const sent = [];
  let counter = 0;
  const fetch = async (path, options) => {
    const body = options.body === undefined ? undefined
      : typeof options.body === 'string' ? JSON.parse(options.body) : options.body;
    sent.push([path, options.method, body, options.headers]);
    const next = responses.shift();
    if (next === undefined) throw new Error(`unexpected request ${options.method} ${path}`);
    if (next instanceof Error) throw next;
    const [status, payload] = next;
    return { ok: status < 400, status, json: async () => payload };
  };
  const randomUUID = () => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`;
  const panel = createExtensionsPanel({ root, document, fetch, basePath: BASE, session: { csrfToken: () => CSRF }, randomUUID });
  const line = root.findAll(el => el.getAttribute('data-extensions-line') !== null)[0];
  const view = name => root.findAll(el => el.getAttribute('data-view') === name)[0];
  const field = (name, scope = root) => scope.findAll(el => el.tagName === 'DD' && el.getAttribute('data-field') === name);
  return { root, sent, panel, line, view, field };
}

test('every T078 item is listed with what this server supplies; binding acts have no control', () => {
  const ids = SUPPLY.map(entry => entry.id);
  for (const id of ['source', 'license', 'port', 'qualification', 'binding', 'failure', 'environments', 'slot_key',
    'slot', 'coexistence', 'import', 'bind', 'history', 'release', 'staging']) assert.ok(ids.includes(id), id);
  const unsupplied = SUPPLY.filter(entry => !entry.supplied).map(entry => entry.id);
  assert.deepEqual(unsupplied, ['binding', 'slot_key', 'slot', 'coexistence', 'bind', 'history', 'release', 'environments', 'trust', 'staging']);
  const { root } = panelWith([]);
  const rows = root.findAll(el => el.getAttribute('data-supply') !== null);
  assert.equal(rows.length, SUPPLY.length);
  assert.deepEqual(rows.filter(el => el.getAttribute('data-supplied') === 'false').map(el => el.getAttribute('data-supply')), unsupplied);
  const buttons = root.findAll(el => el.tagName === 'BUTTON').map(el => el.textContent);
  assert.ok(buttons.every(label => !/바인딩|비활성|롤백|해제|제거|bind|disable|rollback|release/i.test(label)), buttons.join('|'));
  const bindingRows = root.findAll(el => el.tagName === 'DD' && el.textContent === NOT_SUPPLIED);
  assert.ok(bindingRows.length >= 8);
  const link = root.findAll(el => el.getAttribute('data-link') === 'transport-qualification')[0];
  assert.equal(link.getAttribute('href'), CREDENTIALS_LINK);
  // staging is a handoff description: no host, container or command-line instruction
  const text = root.textContent;
  assert.ok(text.includes(MESSAGES.stagingIntro));
  for (const word of [/docker/i, /compose/i, /portainer/i, /kubectl/i, /sudo/i, /\$ /, /python/i, /curl/i, /terminal/i, /터미널/, /명령어/, /CLI/]) {
    assert.ok(!word.test(text), String(word));
  }
});

test('the first read follows the qualification state to the run and adopts its installation head', async () => {
  const { panel, sent, line, view, field } = panelWith([
    [200, qualification({ prerequisite: 'met', eligible_conformance: { command_id: RUN, verified_installation_ref: VERIFIED, result_ref: {} } })],
    [200, conformanceReply()],
  ]);
  await panel.load();
  assert.deepEqual(sent.map(([path, method]) => [path, method]),
    [[`${API}/provider-transport-qualification`, 'GET'], [`${API}/provider-conformance/${RUN}`, 'GET']]);
  assert.equal(line.dataset.state, 'loaded');
  assert.deepEqual(panel.head, { staged: STAGED, verified: VERIFIED });
  assert.equal(view('conformance').dataset.state, 'matched');
  assert.equal(field('state', view('conformance'))[0].textContent, CONFORMANCE_STATES.matched);
  assert.equal(field('failure_code', view('conformance'))[0].textContent, NOT_SUPPLIED);
  assert.match(field('eligible_conformance', view('qualification'))[0].textContent, new RegExp(RUN));
  assert.equal(view('qualification').dataset.state, 'unqualified');
  assert.equal(view('head').textContent, MESSAGES.head(STAGED, VERIFIED));
});

test('without a verified run the read stops at the qualification state and the run is refused here', async () => {
  const { panel, sent, line } = panelWith([[200, qualification()]]);
  await panel.load();
  assert.equal(panel.head, null);
  await assert.rejects(panel.runConformance());
  assert.equal(line.textContent, MESSAGES.noHead);
  assert.equal(sent.length, 1);
});

test('the conformance run carries exactly the head read; a conflict is shown and never retried with another head', async () => {
  const { panel, sent, line } = panelWith([
    [200, qualification({ prerequisite: 'met', eligible_conformance: { command_id: RUN, verified_installation_ref: VERIFIED, result_ref: {} } })],
    [200, conformanceReply()],
    [409, { code: 'conflict', message: 'Provider conformance request could not be admitted' }],
    [503, { code: 'unavailable' }],
    [202, conformanceReply({ command_id: '00000000-0000-4000-8000-000000000002', state: 'pending', result_ref: null, completed_count: 0, matched_count: 0 })],
  ]);
  await panel.load();
  await assert.rejects(panel.runConformance());
  assert.equal(line.textContent, ERRORS.conflict);
  assert.equal(line.dataset.state, 'conflict');
  const [path, method, body, headers] = sent[2];
  assert.deepEqual([path, method], [`${API}/provider-conformance`, 'POST']);
  assert.deepEqual(body, { schema_version: 'provider-conformance-command-v2', command_id: '00000000-0000-4000-8000-000000000001',
    staged_installation_ref: STAGED, expected_verified_installation_ref: VERIFIED });
  assert.equal(headers['X-DeepTwin-CSRF'], CSRF);
  assert.deepEqual(panel.head, { staged: STAGED, verified: VERIFIED }, 'a conflict changes no head');
  // a new act after a conflict is a new command; an unread answer (503) is resent as is
  await assert.rejects(panel.runConformance());
  assert.equal(sent[3][2].command_id, '00000000-0000-4000-8000-000000000002');
  const answer = await panel.runConformance();
  assert.deepEqual(sent[4][2], sent[3][2]);
  assert.equal(answer.state, 'pending');
  assert.equal(line.textContent, MESSAGES.started('pending'));
});

test('a candidate read shows the supplied metadata and marks what the route does not send', async () => {
  const facts = Object.fromEntries(candidateFacts(candidateRead()).map(([field, , value]) => [field, value]));
  assert.equal(facts.state, MESSAGES.candidateState.registered_unqualified);
  assert.equal(facts.port_contract_version, 'tool-port-v1');
  assert.equal(facts.kind, 'tool');
  assert.match(facts.source, /third_party · https:\/\/example\.test\/synthetic/);
  assert.match(facts.license, /^Synthetic · 원문 license/);
  assert.equal(facts.license_text, 'Synthetic license\n');
  assert.equal(facts.grants, '없음');
  assert.match(facts.platforms, /linux\/amd64/);
  for (const key of ['trust', 'installation', 'binding', 'environments']) assert.equal(facts[key], NOT_SUPPLIED, key);
  const sparse = candidateRead();
  delete sparse.manifest.license;
  delete sparse.service_descriptor.platforms;
  const thin = Object.fromEntries(candidateFacts(sparse).map(([field, , value]) => [field, value]));
  assert.equal(thin.license, NOT_SUPPLIED);
  assert.equal(thin.platforms, NOT_SUPPLIED);

  const { panel, sent, field } = panelWith([[200, candidateRead()]]);
  await panel.readCandidate(CANDIDATE);
  assert.deepEqual(sent[0].slice(0, 2), [`${API}/candidates/${CANDIDATE}`, 'GET']);
  assert.equal(field('license_text')[0].textContent, 'Synthetic license\n');
  assert.equal(field('trust')[0].getAttribute('data-supplied'), 'false');
});

test('candidate registration sends the file\'s metadata only, refuses a malformed file here and shows a conflict', async () => {
  const bundle = { manifest: { a: 1 }, service_descriptor: { b: 2 }, documents: [{ document_kind: 'license', content: 'x' }] };
  assert.throws(() => candidateCommand('{', RUN), { message: MESSAGES.badJson });
  assert.throws(() => candidateCommand(JSON.stringify({ ...bundle, code: 'x' }), RUN), { message: MESSAGES.badJson });
  assert.throws(() => candidateCommand('x'.repeat(1048577), RUN), { message: MESSAGES.tooLarge });
  assert.deepEqual(candidateCommand(JSON.stringify(bundle), RUN), { command_id: RUN, ...bundle });

  const { panel, sent, line } = panelWith([
    [201, { command_id: 'x', state: 'registered_unqualified', candidate_ref: { candidate_id: CANDIDATE } }],
    [200, candidateRead()],
    [409, { code: 'conflict' }],
  ]);
  await assert.rejects(panel.registerCandidate('not json'));
  assert.equal(sent.length, 0);
  assert.equal(line.dataset.state, 'refused_here');
  await panel.registerCandidate(JSON.stringify(bundle));
  assert.deepEqual(sent[0].slice(0, 3), [`${API}/candidates`, 'POST', { command_id: '00000000-0000-4000-8000-000000000002', ...bundle }]);
  assert.equal(sent[1][0], `${API}/candidates/${CANDIDATE}`);
  assert.equal(line.textContent, MESSAGES.registered(CANDIDATE));
  await assert.rejects(panel.registerCandidate(JSON.stringify(bundle)));
  assert.equal(line.textContent, ERRORS.conflict);
});

function packet({ staged = STAGED, sizes = Array(12).fill(1) } = {}) {
  const header = new TextEncoder().encode(JSON.stringify({ schema_version: 'provider-installation-command-v1',
    command_id: '77777777-7777-4777-8777-777777777777', staged_installation_ref: staged,
    objects: sizes.map((size, index) => ({ role: `r${index}`, sha256: '0'.repeat(64), size_bytes: size })) }));
  const total = 12 + header.length + sizes.reduce((a, b) => a + b, 0);
  const bytes = new Uint8Array(total);
  bytes.set([0x44, 0x54, 0x50, 0x49, 0x56, 0x31, 0, 0]);
  new DataView(bytes.buffer).setUint32(8, header.length);
  bytes.set(header, 12);
  return bytes;
}

test('the release-evidence packet is read for its header only and sent unchanged', async () => {
  const bytes = packet();
  const header = packetHeader(bytes);
  assert.deepEqual(header.staged_installation_ref, STAGED);
  assert.equal(header.object_count, 12);
  assert.throws(() => packetHeader(bytes.subarray(0, bytes.length - 1)), { message: MESSAGES.badPacket });
  assert.throws(() => packetHeader(packet({ staged: VERIFIED })), { message: MESSAGES.badPacket });
  assert.throws(() => packetHeader(new TextEncoder().encode('#!/bin/sh\necho hi\n')), { message: MESSAGES.badPacket });

  const { panel, sent, line, field, view } = panelWith([[404, { code: 'not_found' }], [200, installationReply()]]);
  await assert.rejects(panel.verifyInstallation());
  assert.equal(line.textContent, MESSAGES.noFile);
  assert.equal(sent.length, 0);
  assert.equal(panel.choosePacket(new Uint8Array([1, 2, 3])), null);
  assert.equal(line.textContent, MESSAGES.badPacket);
  panel.choosePacket(bytes);
  assert.match(view('packet').textContent, /스테이징된 설치 extension_installation 3333/);
  await assert.rejects(panel.verifyInstallation());
  assert.equal(line.textContent, ERRORS.not_found);
  const [path, method, body, headers] = sent[0];
  assert.deepEqual([path, method], [`${API}/provider-installation`, 'POST']);
  assert.equal(body, bytes, 'the exact bytes of the file');
  assert.equal(headers['Content-Type'], INSTALLATION_MEDIA_TYPE);
  assert.equal(headers['X-DeepTwin-CSRF'], CSRF);
  await panel.verifyInstallation();
  assert.equal(sent[1][2], bytes);
  assert.equal(field('state', view('installation'))[0].textContent, '검증됨(verified)');
  assert.match(field('verified_at', view('installation'))[0].textContent, /Z \(1790000000000 ms\)$/);
  assert.deepEqual(panel.head, { staged: STAGED, verified: VERIFIED });
});

test('a head is only taken from refs of one installation, staged revision 1 and verified revision 2', () => {
  assert.deepEqual(headFrom(installationReply()), { staged: STAGED, verified: VERIFIED });
  assert.equal(headFrom(installationReply({ verified_installation_ref: { ...VERIFIED, id: RUN } })), null);
  assert.equal(headFrom(conformanceReply({ schema_version: 'provider-conformance-reply-v1' })), null);
  assert.throws(() => conformanceCommand(null, RUN), { message: MESSAGES.noHead });
  assert.throws(() => conformanceCommand({ staged: STAGED, verified: VERIFIED }, 'nope'), { message: MESSAGES.badId });
});

test('reads refuse an id that is not a UUID before any request, and each refusal code has its text', async () => {
  const { root, sent, line } = panelWith([]);
  const input = root.findAll(el => el.getAttribute('id') === 'extensions-candidate-id')[0];
  input.value = '../../etc';
  const button = root.findAll(el => el.tagName === 'BUTTON' && el.textContent === '후보 읽기')[0];
  for (const listener of button.listeners.get('click')) listener();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(sent.length, 0);
  assert.equal(line.textContent, MESSAGES.badId);
  for (const code of ['invalid_input', 'unauthenticated', 'access_denied', 'not_found', 'conflict', 'too_large', 'capacity', 'unavailable']) {
    assert.equal(typeof ERRORS[code], 'string', code);
  }
});
