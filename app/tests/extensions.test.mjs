// Settings > Extensions (app/static/extensions.mjs) over a fake document, fetch and
// session adapter: what the screen shows from each fixed extension route's reply, what it
// marks as not supplied, and the exact bodies of the owner acts those routes carry —
// candidate metadata registration, release-evidence packet verification (bytes as the file
// holds them) and the verified-installation conformance run carrying exactly the head the
// screen read; a 409 is shown as a conflict and never retried with another head, an unread
// answer is resent under the same command id. The inventory lists (candidates, installations,
// binding slots) page with the server's cursor; a slot read shows the exact key, digest,
// history, retention and warning the server sent; bind/disable/rollback/release carry exactly
// the key and heads read, a stale head is shown with the server's text and not retried, and a
// release is sent only from its separate confirmation. No host/operator instruction is rendered.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  BINDING_ERRORS, CONFORMANCE_STATES, CREDENTIALS_LINK, ERRORS, INSTALLATION_MEDIA_TYPE, MESSAGES, NOT_SUPPLIED, SUPPLY,
  bindCommand, candidateCommand, candidateFacts, conformanceCommand, createExtensionsPanel, headFrom, packetHeader,
  releaseCommand, slotFacts, slotKeyRequest,
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

test('every T078 item is listed with what this server supplies; only what no route carries is not supplied', () => {
  const ids = SUPPLY.map(entry => entry.id);
  for (const id of ['source', 'license', 'port', 'qualification', 'binding', 'failure', 'environments', 'slot_key',
    'slot', 'coexistence', 'import', 'bind', 'history', 'release', 'staging', 'trust']) assert.ok(ids.includes(id), id);
  const unsupplied = SUPPLY.filter(entry => !entry.supplied).map(entry => entry.id);
  assert.deepEqual(unsupplied, ['platform', 'other_ports', 'requests']);
  const { root } = panelWith([]);
  const rows = root.findAll(el => el.getAttribute('data-supply') !== null);
  assert.equal(rows.length, SUPPLY.length);
  assert.deepEqual(rows.filter(el => el.getAttribute('data-supplied') === 'false').map(el => el.getAttribute('data-supply')), unsupplied);
  // before a slot is read there is no disable/rollback/release control; bind waits for a key and a qualification
  const acts = root.findAll(el => el.tagName === 'BUTTON').map(el => el.getAttribute('data-act'));
  for (const act of ['disable', 'rollback', 'release-start', 'release-confirm']) assert.ok(!acts.includes(act), act);
  const bind = root.findAll(el => el.getAttribute('data-act') === 'bind')[0];
  assert.equal(bind.getAttribute('aria-disabled'), 'true');
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
    [200, { schema_version: 'extension-candidate-list-v1', limit: 20, next_after: null, items: [{ candidate_id: CANDIDATE,
      state: 'registered_unqualified', extension_id: 'synthetic-tool', extension_version: '1.0.0', extension_kind: 'tool',
      port_contract_version: 'tool-port-v1', trust_tier: 'runtime_worker', trust_tier_basis: 'port_contract', links: {} }] }],
    [409, { code: 'conflict' }],
  ]);
  await assert.rejects(panel.registerCandidate('not json'));
  assert.equal(sent.length, 0);
  assert.equal(line.dataset.state, 'refused_here');
  await panel.registerCandidate(JSON.stringify(bundle));
  assert.deepEqual(sent[0].slice(0, 3), [`${API}/candidates`, 'POST', { command_id: '00000000-0000-4000-8000-000000000002', ...bundle }]);
  assert.equal(sent[1][0], `${API}/candidates/${CANDIDATE}`);
  assert.equal(sent[2][0], `${API}/candidates?limit=20`, 'the list is read again after a registration');
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

const DIGEST = 'c'.repeat(64);
const SIBLING = 'd'.repeat(64);
const QUALIFICATION = { kind: 'validation_report', id: '99999999-9999-4999-8999-999999999999', version: 1, sha256: '9'.repeat(64) };
const KEY = { port_contract_version: 'provider-port-v1', target_scope_fingerprint: 'e'.repeat(64), purpose: 'operational',
  binding_slot_id: 'default-provider', capability_selector_digest: 'f'.repeat(64) };
const SELECTOR = { selector_kind: 'provider_role', provider_id: 'claude', auth_mode: 'api', account_binding_ref: null };
const SCOPE = { instance_id: '1'.repeat(32), environment_id: null, work_id: null, node_id: null, purpose: 'operational' };
const TUPLE = { service_identity: 'provider-a', manifest_digest: '1'.repeat(64), service_descriptor_digest: '2'.repeat(64),
  selected_platform_entry_digest: '3'.repeat(64), image_manifest_digest: `sha256:${'4'.repeat(64)}` };
const HEAD1 = { revision: 1, binding_record_digest: '5'.repeat(64), state: 'active' };
const HEAD2 = { revision: 2, binding_record_digest: '6'.repeat(64), state: 'active' };
const TARGET = { revision: 1, binding_record_digest: HEAD1.binding_record_digest };
const RETAINED = { revision: 1, retention_record_digest: '7'.repeat(64), state: 'retained' };
const WARNING = '보존을 해제하면 바인딩 수정본 1(ext-a)으로는 더 이상 롤백할 수 없습니다. 현재 바인딩(수정본 2, active)과 설치, 모든 바인딩 이력은 바뀌지 않고 계속 보입니다.';
const INSTALLED = { extension_id: 'ext-a', revision: 2, installation_record_digest: VERIFIED.sha256 };

function slotRead(overrides = {}) {
  return {
    schema_version: 'extension-binding-slot-v1', binding_slot_key: KEY, binding_slot_key_digest: DIGEST,
    logical_slot: { binding_slot_id: 'default-provider', purpose: 'operational', port_contract_version: 'provider-port-v1' },
    capability_selector: SELECTOR, capability_selector_digest: KEY.capability_selector_digest, target_scope: SCOPE,
    target_scope_fingerprint: KEY.target_scope_fingerprint, extension_kind: 'provider', trust_tier: 'runtime_worker',
    head: HEAD2,
    current: { extension_id: 'ext-b', state: 'active', target_installation_ref: { ...INSTALLED, extension_id: 'ext-b' },
      installation_ref: VERIFIED, qualification_ref: QUALIFICATION, service_tuple: TUPLE, qualification_current: true },
    history: [
      { revision: 1, binding_record_digest: HEAD1.binding_record_digest, state: 'active', action: 'bind', extension_id: 'ext-a',
        target_installation_ref: INSTALLED, qualification_ref: QUALIFICATION, previous_ref: null, supersedes_ref: null, rollback_of_ref: null },
      { revision: 2, binding_record_digest: HEAD2.binding_record_digest, state: 'active', action: 'supersede', extension_id: 'ext-b',
        target_installation_ref: { ...INSTALLED, extension_id: 'ext-b' }, qualification_ref: QUALIFICATION, previous_ref: TARGET,
        supersedes_ref: TARGET, rollback_of_ref: null },
    ],
    rollback_retentions: [{ target_binding_revision_ref: TARGET, target_extension_id: 'ext-a', target_installation_ref: INSTALLED,
      target_service_tuple: TUPLE, retention_head: RETAINED, history: [], rollback_available: true, qualification_current: true,
      release_warning: WARNING }],
    coexisting_slots: [{ binding_slot_key_digest: SIBLING, binding_slot_id: 'review-provider', capability_selector_digest: KEY.capability_selector_digest,
      head: HEAD1, extension_id: 'ext-b' }],
    competition: { current_holder: 'ext-b', holders: [{ extension_id: 'ext-a', revisions: [1] }, { extension_id: 'ext-b', revisions: [2] }] },
    affected_environments: { target_environment_id: null, bound_environment_versions: [], basis: 'no_environment_version_records_extension_binding_revisions' },
    links: { self: `${API}/bindings/${DIGEST}` }, ...overrides,
  };
}

const page = (schema, items, next = null) => ({ schema_version: schema, limit: 20, items, next_after: next });
const installationRow = {
  installation_id: INSTALLATION, extension_id: 'ext-a', extension_version: '1.0.0', state: 'verified', revision: 2,
  head_ref: VERIFIED, staged_installation_ref: STAGED, verified_installation_ref: VERIFIED, target_installation_ref: INSTALLED,
  platform: 'linux/amd64', port_contract_version: 'provider-port-v1', extension_kind: 'provider', trust_tier: 'runtime_worker',
  trust_tier_basis: 'port_contract', service_tuple: TUPLE, candidate_id: CANDIDATE,
  staging: { state: 'receipt_consumed', staging_authority: 'deployment-provider-receipt-v1', request_ref: { ...STAGED, kind: 'deployment_request' },
    receipt_ref: { ...STAGED, kind: 'deployment_receipt' }, consume_command_id: RUN, installed_at: '2026-09-25T00:00:00.000Z',
    request_link: `${BASE}api/v1/deployment/provider-requests/${INSTALLATION}` },
  verified_at_ms: 1, active_binding_slot_digests: [DIGEST],
};
const candidateRow = { candidate_id: CANDIDATE, state: 'registered_unqualified', extension_id: 'synthetic-tool', extension_version: '1.0.0',
  extension_kind: 'tool', port_contract_version: 'tool-port-v1', trust_tier: 'runtime_worker', trust_tier_basis: 'port_contract',
  manifest_digest: '7'.repeat(64), service_descriptor_digest: '8'.repeat(64), registration_digest: '9'.repeat(64), links: {} };
const slotRow = { binding_slot_key_digest: DIGEST, binding_slot_key: KEY, logical_slot: slotRead().logical_slot, capability_selector: SELECTOR,
  target_scope: SCOPE, head: HEAD2, extension_id: 'ext-b', trust_tier: 'runtime_worker', extension_kind: 'provider', retained_rollback_count: 1, links: {} };

test('the inventory lists page with the server cursor and fill the candidate and installation facts', async () => {
  const { panel, sent, root, field } = panelWith([
    [200, page('extension-candidate-list-v1', [candidateRow], CANDIDATE)],
    [200, page('extension-installation-list-v1', [installationRow])],
    [200, page('extension-binding-list-v1', [slotRow])],
    [200, page('extension-candidate-list-v1', [])],
    [200, candidateRead()],
    [200, { state: 'accepted' }],
  ]);
  await panel.loadInventory();
  assert.deepEqual(sent.map(([path, method]) => [path, method]), [
    [`${API}/candidates?limit=20`, 'GET'], [`${API}/installations?limit=20`, 'GET'], [`${API}/bindings?limit=20`, 'GET']]);
  const candidateRows = root.findAll(el => el.getAttribute('data-candidate-row') !== null);
  assert.equal(candidateRows.length, 1);
  assert.match(candidateRows[0].textContent, /신뢰 등급 runtime_worker\(포트 계약 기준\)/);
  assert.equal(field('trust', root.findAll(el => el.getAttribute('data-installation-row') === INSTALLATION)[0])[0].textContent,
    'runtime_worker (포트 계약 기준)');
  assert.match(field('staging')[0].textContent, /deployment-provider-receipt-v1/);
  assert.match(root.findAll(el => el.getAttribute('data-slot-row') === DIGEST)[0].textContent, /default-provider · provider-port-v1/);
  await panel.more('candidates');
  assert.equal(sent[3][0], `${API}/candidates?limit=20&after=${CANDIDATE}`);
  await panel.readCandidate(CANDIDATE);
  assert.equal(field('trust')[0].textContent, 'runtime_worker (포트 계약 기준)');
  assert.match(field('installation')[0].textContent, new RegExp(`${INSTALLATION} verified 수정본 2`));
  assert.equal(field('binding')[0].textContent, DIGEST);
  // the staging request's own read route, as the server linked it
  await panel.readRequest(installationRow);
  assert.deepEqual(sent[5].slice(0, 2), [installationRow.staging.request_link, 'GET']);
  assert.match(root.textContent, /배포 요청 상태: accepted/);
});

test('a slot read shows the server key, digest, history, coexistence, retention and environments as sent', async () => {
  const facts = Object.fromEntries(slotFacts(slotRead()).map(([name, , value]) => [name, value]));
  assert.equal(facts.binding_slot_key, JSON.stringify(KEY));
  assert.equal(facts.binding_slot_key_digest, DIGEST);
  assert.equal(facts.capability_selector, JSON.stringify(SELECTOR));
  assert.match(facts.coexistence, /review-provider · ext-b/);
  assert.match(facts.competition, /ext-a \(수정본 1\) \/ ext-b \(수정본 2\)/);
  assert.match(facts.environments, /이 수정본을 쓰는 환경 버전 없음/);
  const { panel, sent, root, view } = panelWith([[200, slotRead()]]);
  await panel.readSlot(DIGEST);
  assert.deepEqual(sent[0].slice(0, 2), [`${API}/bindings/${DIGEST}`, 'GET']);
  assert.equal(view('slot').dataset.head, '2:active');
  assert.equal(root.findAll(el => el.getAttribute('data-revision') !== null).length, 2);
  const retention = root.findAll(el => el.getAttribute('data-retention-target') === '1')[0];
  assert.equal(retention.getAttribute('data-state'), 'retained');
  const acts = root.findAll(el => el.tagName === 'BUTTON').map(el => el.getAttribute('data-act'));
  for (const act of ['disable', 'rollback', 'release-start']) assert.ok(acts.includes(act), act);
  assert.ok(!acts.includes('release-confirm'), 'the release is a separate confirmation');
  await assert.rejects(panel.readSlot('not-a-digest'));
  assert.equal(sent.length, 1);
});

test('disable carries the exact head read; a stale head shows the server text and is never retried with another head', async () => {
  const { panel, sent, line } = panelWith([
    [200, slotRead()],
    [409, { code: 'binding_head_stale', message: BINDING_ERRORS.binding_head_stale }],
    [503, { code: 'unavailable' }],
    [200, { schema_version: 'extension-binding-command-result-v1', binding_slot_key_digest: DIGEST,
      binding_head: { revision: 3, binding_record_digest: '8'.repeat(64), state: 'disabled' } }],
    [200, slotRead({ head: { revision: 3, binding_record_digest: '8'.repeat(64), state: 'disabled' } })],
    [200, page('extension-binding-list-v1', [])],
    [200, page('extension-installation-list-v1', [])],
  ]);
  await panel.readSlot(DIGEST);
  await assert.rejects(panel.disable());
  assert.equal(line.textContent, BINDING_ERRORS.binding_head_stale);
  assert.equal(line.dataset.state, 'binding_head_stale');
  const [path, method, body, headers] = sent[1];
  assert.deepEqual([path, method], [`${API}/bindings/${DIGEST}/disable`, 'POST']);
  assert.deepEqual(body, { command_id: '00000000-0000-4000-8000-000000000001', extension_id: 'ext-b', binding_slot_key: KEY,
    binding_slot_key_digest: DIGEST, expected_current_binding_head: HEAD2 });
  assert.equal(headers['X-DeepTwin-CSRF'], CSRF);
  assert.equal(panel.slot.head.revision, 2, 'a conflict changes nothing on the page');
  // a new act after the conflict is a new command; an unread answer (503) is resent unchanged
  await assert.rejects(panel.disable());
  assert.equal(sent[2][2].command_id, '00000000-0000-4000-8000-000000000002');
  await panel.disable();
  assert.deepEqual(sent[3][2], sent[2][2]);
  assert.equal(panel.slot.head.state, 'disabled');
  assert.equal(line.textContent, MESSAGES.disabledDone({ revision: 3 }));
});

test('the slot key is the server\'s; bind echoes it with the sealed qualification and waits for both', async () => {
  assert.deepEqual(slotKeyRequest({ slotId: 'default-provider', purpose: 'operational', environmentId: '', providerId: 'claude' }), {
    port_contract_version: 'provider-port-v1', binding_slot_id: 'default-provider',
    target_scope: { environment_id: null, work_id: null, node_id: null, purpose: 'operational' }, capability_selector: SELECTOR });
  assert.throws(() => slotKeyRequest({ slotId: 'Bad Slot', purpose: 'operational', providerId: 'claude' }), { message: MESSAGES.badSlotId });
  assert.throws(() => slotKeyRequest({ slotId: 'x', purpose: 'operational', environmentId: 'nope', providerId: 'claude' }), { message: MESSAGES.badId });
  const reply = { schema_version: 'extension-binding-slot-key-v1', binding_slot_key: KEY, binding_slot_key_digest: DIGEST,
    capability_selector: SELECTOR, capability_selector_digest: KEY.capability_selector_digest, target_scope: SCOPE,
    target_scope_fingerprint: KEY.target_scope_fingerprint, current_binding_head: null };
  assert.throws(() => bindCommand(reply, 'ext-a', null, RUN), { message: MESSAGES.noQualification });
  assert.throws(() => bindCommand(null, 'ext-a', QUALIFICATION, RUN), { message: MESSAGES.noKey });
  assert.deepEqual(bindCommand(reply, 'ext-a', QUALIFICATION, RUN), { command_id: RUN, extension_id: 'ext-a',
    qualification_ref: QUALIFICATION, binding_slot_key: KEY, binding_slot_key_digest: DIGEST, capability_selector: SELECTOR,
    target_scope: SCOPE, expected_current_binding_head: null });

  const sealed = qualification({ prerequisite: 'met', qualification: { revision: 1, qualification_ref: QUALIFICATION, conformance_command_id: RUN } });
  const { panel, sent, root, line, view } = panelWith([
    [200, qualification()],
    [200, reply],
    [200, sealed],
    [200, conformanceReply()],
    [200, page('extension-candidate-list-v1', [])],
    [200, page('extension-installation-list-v1', [installationRow])],
    [200, page('extension-binding-list-v1', [])],
    [409, { code: 'qualification_not_current', message: BINDING_ERRORS.qualification_not_current }],
  ]);
  await panel.load();
  const provider = root.findAll(el => el.getAttribute('id') === 'extensions-bind-provider')[0];
  assert.equal(provider.value, 'claude', 'the provider id is the one the qualification state names');
  await panel.computeKey();
  assert.deepEqual(sent[1].slice(0, 3), [`${API}/binding-slot-keys`, 'POST', slotKeyRequest({
    slotId: 'default-provider', purpose: 'operational', environmentId: '', providerId: 'claude' })]);
  assert.equal(view('slot-key').dataset.digest, DIGEST);
  // no sealed qualification: refused on the page, no request
  await assert.rejects(panel.bind());
  assert.equal(line.textContent, MESSAGES.noQualification);
  assert.equal(sent.length, 2);
  await panel.load();
  await panel.loadInventory();
  assert.equal(root.findAll(el => el.getAttribute('data-act') === 'bind')[0].getAttribute('aria-disabled'), 'false');
  await assert.rejects(panel.bind());
  assert.deepEqual(sent[7].slice(0, 3), [`${API}/bindings`, 'POST', bindCommand(reply, 'ext-a', QUALIFICATION,
    '00000000-0000-4000-8000-000000000002')]); // the refused-here attempt drew id 1 and sent nothing
  assert.equal(line.textContent, BINDING_ERRORS.qualification_not_current);
});

test('rollback names the retained target; a release is sent only from its confirmation with the server warning', async () => {
  const slot = slotRead();
  const retention = slot.rollback_retentions[0];
  assert.throws(() => releaseCommand(slot, retention, ' ', RUN), { message: MESSAGES.badReason });
  assert.throws(() => releaseCommand(slot, retention, 'x'.repeat(501), RUN), { message: MESSAGES.badReason });
  assert.deepEqual(Object.keys(releaseCommand(slot, retention, '퇴역 전 해제', RUN)), ['command_id', 'extension_id', 'binding_slot_key',
    'binding_slot_key_digest', 'expected_current_binding_head', 'target_binding_revision_ref', 'target_installation_ref',
    'target_service_tuple', 'expected_retention_head', 'reason']);
  const released = { command_id: 'x', binding_slot_key_digest: DIGEST, new_retention_revision: 2, new_retention_record_digest: '0'.repeat(64), state: 'released' };
  const { panel, sent, root, line } = panelWith([
    [200, slot],
    [409, { code: 'retention_head_stale', message: BINDING_ERRORS.retention_head_stale }],
    [200, released],
    [200, slotRead({ rollback_retentions: [{ ...retention, retention_head: { ...RETAINED, revision: 2, state: 'released' },
      rollback_available: false, release_warning: null }] })],
    [200, page('extension-binding-list-v1', [])],
    [200, page('extension-installation-list-v1', [])],
  ]);
  await panel.readSlot(DIGEST);
  await assert.rejects(panel.rollback(retention));
  assert.deepEqual(sent[1].slice(0, 3), [`${API}/bindings/${DIGEST}/rollback`, 'POST', { command_id: '00000000-0000-4000-8000-000000000001',
    extension_id: 'ext-a', binding_slot_key: KEY, binding_slot_key_digest: DIGEST, expected_current_binding_head: HEAD2,
    target_binding_revision_ref: TARGET, expected_retention_head: RETAINED }]);
  assert.equal(line.textContent, BINDING_ERRORS.retention_head_stale);
  // the release starts with the confirmation: the server's warning verbatim and the unchanged current binding
  const start = root.findAll(el => el.getAttribute('data-act') === 'release-start')[0];
  for (const listener of start.listeners.get('click')) listener();
  await new Promise(resolve => setTimeout(resolve, 0));
  const confirm = root.findAll(el => el.getAttribute('data-view') === 'release-confirm')[0];
  assert.equal(confirm.findAll(el => el.getAttribute('data-view') === 'release-warning')[0].textContent, WARNING);
  assert.match(confirm.textContent, /현재 바인딩: 수정본 2 · active/);
  assert.equal(sent.length, 2, 'opening the confirmation sends nothing');
  await panel.release(retention, '퇴역 전 해제');
  const [path, method, body] = sent[2];
  assert.equal(path, `${API}/bindings/${DIGEST}/rollback-retentions/${TARGET.binding_record_digest}/release`);
  assert.equal(method, 'POST');
  assert.deepEqual(body, { command_id: '00000000-0000-4000-8000-000000000002', extension_id: 'ext-a', binding_slot_key: KEY,
    binding_slot_key_digest: DIGEST, expected_current_binding_head: HEAD2, target_binding_revision_ref: TARGET,
    target_installation_ref: INSTALLED, target_service_tuple: TUPLE, expected_retention_head: RETAINED, reason: '퇴역 전 해제' });
  assert.equal(line.textContent, MESSAGES.released(2));
  assert.equal(root.findAll(el => el.getAttribute('data-view') === 'release-confirm').length, 0);
  assert.equal(root.findAll(el => el.getAttribute('data-retention-target') === '1')[0].getAttribute('data-state'), 'released');
  assert.equal(root.findAll(el => el.getAttribute('data-act') === 'release-start').length, 0, 'a released target has no act');
});
