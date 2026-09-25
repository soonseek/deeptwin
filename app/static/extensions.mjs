// Settings > Extensions (settings.html#settings-extensions; T087 extension UI, T078's list).
// It shows what this server's fixed extension routes actually supply and offers only the
// owner acts those routes carry:
//
// - `GET|POST {base}api/v1/extensions/candidates[/{id}]` (extension-candidates-v1): read an
//   inert executable-extension candidate (manifest, service descriptor, support documents,
//   registration receipt) and register one from a metadata JSON file. Metadata only: no
//   code, image or executable bytes are uploaded, fetched or run by the browser or the
//   server; the source locator is never fetched.
// - `GET|POST {base}api/v1/extensions/provider-installation[/{command_id}]`
//   (provider-installation-v1): read a staged→verified installation result and submit a
//   release-evidence packet (`application/vnd.deeptwin.provider-installation-v1`) exactly as
//   the file holds it. The page reads only the packet's header to show which staged
//   installation head (revision 1) it names; it never rewrites the bytes.
// - `GET|POST {base}api/v1/extensions/provider-conformance[/{command_id}]`
//   (provider-conformance-v1): read a run and start a verified-installation run
//   (`provider-conformance-command-v2`) that carries exactly the staged and verified
//   installation refs this screen last read (expected head). A 409 is shown as a conflict
//   and the screen asks the owner to read again; it never retries with another head.
// - `GET {base}api/v1/extensions/provider-transport-qualification`: the qualification
//   state, read-only here; the act itself lives in the credentials section, linked.
//
// Everything T078 names that no route supplies (binding records, the five-field
// BindingSlotKeyV1 and digest, logical slot / capability selector, coexistence and
// competition, bind/disable/rollback, immutable binding history, rollback-retention state and
// release, affected environments, trust tier, deployment-request status) is listed as
// "not supplied" and has no control. Executable staging is the instance operator's authority
// outside the product; the page describes that handoff and gives no host instructions.
// All server text reaches the DOM through textContent or attributes only.

import { basePathFrom, createSupportedSession } from './session.mjs';

export const EXTENSIONS_MOUNT_ID = 'settings-extensions';
export const CREDENTIALS_LINK = './records.html#records-credentials';
export const NOT_SUPPLIED = '제공되지 않음(이 서버가 보내지 않음)';
export const INSTALLATION_MEDIA_TYPE = 'application/vnd.deeptwin.provider-installation-v1';
export const MAX_CANDIDATE_BYTES = 1048576;
export const MAX_PACKET_BYTES = 50364428;
const PACKET_PREFIX = [0x44, 0x54, 0x50, 0x49, 0x56, 0x31, 0, 0]; // "DTPIV1\0\0"
const MAX_PACKET_HEADER = 32768;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HEX64 = /^[0-9a-f]{64}$/;

// T078's Settings > Extensions list, each with what this server actually supplies
export const SUPPLY = Object.freeze([
  ['source', '출처(source)', true, '후보 읽기: manifest의 source.kind·locator·provenance 참조(확인되지 않은 신고 내용)'],
  ['license', '라이선스', true, '후보 읽기: license.expression과 라이선스 원문 문서(승인되지 않은 신고 내용)'],
  ['port', '종류·포트 계약', true, '후보 읽기: extension_kind, port_contract_version, artifact_form'],
  ['qualification', 'qualification', true, '설치 검증 결과, 적합성 검사 실행, 전송 매니페스트 검증 상태(제공자 포트만)'],
  ['failure', '실패', true, '적합성 검사 state(mismatch/incomplete)와 각 요청의 거절 코드. 실패 원인 코드는 응답에 없음'],
  ['import', '가져오기', true, '실행형 확장 후보 메타데이터 등록만 가능. 코드 없는 정의(lens/evaluator) 가져오기 경로는 없음'],
  ['binding', '바인딩', false, '바인딩 기록을 읽는 경로가 없습니다'],
  ['slot_key', '다섯 필드 slot key(포트 버전 포함)+digest', false, 'BindingSlotKeyV1과 그 digest를 보내는 경로가 없습니다'],
  ['slot', '논리 slot·capability selector', false, '바인딩 경로가 없어 slot과 selector를 보여 줄 수 없습니다'],
  ['coexistence', '같은 포트 공존·같은 slot 경쟁', false, '바인딩 경로가 없어 구분할 대상이 없습니다'],
  ['bind', '바인딩·비활성화·롤백', false, '이 서버에는 bind/disable/rollback 경로가 없습니다'],
  ['history', '변경 불가 이력·롤백 보존 상태', false, '바인딩 이력과 rollback-retention head를 읽는 경로가 없습니다'],
  ['release', '롤백 보존 해제(소유자 전용)', false, 'rollback-retention release 경로가 없습니다'],
  ['environments', '영향받는 환경', false, '확장을 쓰는 환경 버전을 읽는 경로가 없습니다'],
  ['trust', '신뢰 등급·지원 플랫폼 판정', false, '서버는 신뢰 등급을 응답에 싣지 않습니다(후보의 platforms 신고만 보임)'],
  ['staging', '운영자 배치(staging)', false, '운영자 권한입니다. 배포 요청 상태를 읽는 경로가 없어 안내만 보입니다'],
].map(([id, label, supplied, detail]) => Object.freeze({ id, label, supplied, detail })));

export const MESSAGES = Object.freeze({
  intro: '확장은 선택 사항입니다. 확장 없이도 기본 기능으로 업무를 계속할 수 있습니다. 이 화면은 이 서버의 확장 경로가 실제로 보내는 내용만 보여 주고, 보내지 않는 항목은 "제공되지 않음"으로 표시합니다.',
  unauthenticated: '소유자 세션이 있어야 확장을 볼 수 있습니다. 시작 화면(./)에서 로그인해 주세요.',
  loading: '확장 상태를 읽는 중…',
  loaded: '확장 상태를 읽었습니다.',
  candidateIntro: '실행형 확장 후보는 검토용 메타데이터(manifest, service descriptor, 라이선스·출처·SBOM·정책 문서)입니다. 등록해도 설치·검증·실행되지 않으며, 코드나 이미지는 올리지 않고 출처 주소도 가져오지 않습니다.',
  candidateState: Object.freeze({
    registered_unqualified: '등록됨 · 검증 전(registered_unqualified): 출처·라이선스·이미지는 확인되지 않은 신고 내용입니다.',
  }),
  installationIntro: '운영자가 배치한 제공자 설치(수정본 1)를 릴리스 증거 묶음으로 검증된 설치(수정본 2)로 기록합니다. 증거 묶음은 파일 그대로 보내며, 이 화면은 머리말만 읽어 어떤 설치 헤드를 가리키는지 보여 줍니다.',
  conformanceIntro: '검증된 설치에 대해 고정된 4개 벡터로 제공자 적합성 검사를 실행합니다. 요청에는 이 화면이 마지막으로 읽은 설치 헤드(스테이징 수정본 1과 검증 수정본 2)를 그대로 싣습니다.',
  noHead: '먼저 설치 검증 결과나 검증된 설치의 적합성 검사를 읽어야 실행할 수 있습니다.',
  head: (staged, verified) => `보낼 기대 헤드: 스테이징 ${staged.id} 수정본 ${staged.version} (${staged.sha256}) → 검증 수정본 ${verified.version} (${verified.sha256})`,
  qualificationIntro: '제공자 전송 매니페스트 검증은 읽기만 여기서 합니다. 검증 실행은 API 자격증명 화면에서 합니다.',
  qualificationLink: 'API 자격증명 화면에서 전송 매니페스트 검증하기',
  bindingIntro: '이 서버는 확장 바인딩을 다루는 경로를 제공하지 않습니다. 아래 항목은 보여 줄 서버 값이 없으므로 조작도 없습니다.',
  stagingIntro: '실행형 확장의 배치(staging)는 인스턴스 운영자의 권한이며 이 제품 화면의 단계가 아닙니다. 운영자는 정확한 manifest·service descriptor digest에 대한 서명된 배포 요청과 일회용 영수증 절차로 배치하고, 그 결과로 스테이징된 설치(수정본 1)가 생깁니다. 이 화면은 그 뒤의 검증 기록과 적합성 검사만 다룹니다. 배포 요청 상태(운영자 준비 중·영수증 대기·handshake 실패·qualification 필요)를 읽는 경로가 이 서버에 없어 여기에는 보이지 않습니다. 영수증만으로 "사용 가능"이 되지 않습니다.',
  working: '보내는 중…',
  registered: id => `후보를 등록했습니다 (후보 ${id}). 검증·설치된 것은 아닙니다.`,
  verified: id => `설치를 검증된 설치(수정본 2)로 기록했습니다 (${id}).`,
  started: state => (state === 'pending' ? '적합성 검사를 시작했습니다. 끝나면 다시 읽어 결과를 확인하세요.' : `적합성 검사를 마쳤습니다: ${state}.`),
  badJson: '후보 메타데이터 파일은 manifest, service_descriptor, documents(와 선택적 command_id)만 담은 JSON 객체여야 합니다.',
  tooLarge: '파일이 이 경로의 크기 한도를 넘습니다. 보내지 않았습니다.',
  badPacket: '제공자 설치 증거 묶음(DTPIV1) 형식이 아닙니다. 보내지 않았습니다.',
  badId: '요청 ID(UUID) 형식을 확인해 주세요.',
  noFile: '파일을 먼저 고르세요.',
});

// the fixed refusal codes of these routes; a conflict always asks for a fresh read
export const ERRORS = Object.freeze({
  invalid_input: '서버가 요청 형식을 받아들이지 않았습니다(invalid_input).',
  unauthenticated: '세션이 끝났습니다. 시작 화면(./)에서 다시 로그인해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다(access_denied).',
  not_found: '서버에 그 기록이 없습니다(not_found).',
  conflict: '서버의 현재 상태가 이 화면이 읽은 헤드와 다르거나, 같은 요청 ID가 다른 내용으로 이미 쓰였습니다(conflict). 바뀐 것은 없습니다. 다시 읽은 뒤 확인해 주세요.',
  too_large: '서버의 크기 한도를 넘었습니다(too_large).',
  capacity: '서버의 저장 한도에 닿았습니다(capacity).',
  unavailable: '서버가 지금 처리하지 못했습니다(unavailable). 같은 요청 ID로만 다시 보냅니다.',
});

export const CONFORMANCE_STATES = Object.freeze({
  pending: '진행 중(pending)',
  matched: '통과(matched): 4개 벡터 모두 일치',
  mismatch: '실패(mismatch): 일치하지 않은 벡터가 있음',
  incomplete: '실패(incomplete): 끝나지 못한 벡터가 있음',
});

function fail(message) { throw new Error(message); }

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function refText(ref) {
  if (!isObject(ref)) return NOT_SUPPLIED;
  return `${ref.kind} ${ref.id} 수정본 ${ref.version} · sha256 ${ref.sha256}`;
}

function metaRefText(ref) {
  return isObject(ref) ? `${ref.document_kind} · sha256 ${ref.sha256} · ${ref.size_bytes} bytes` : NOT_SUPPLIED;
}

function listText(value) {
  if (!Array.isArray(value)) return NOT_SUPPLIED;
  return value.length === 0 ? '없음' : value.join(', ');
}

function text(value) {
  return typeof value === 'string' && value !== '' ? value
    : Number.isSafeInteger(value) ? String(value) : NOT_SUPPLIED;
}

function isoMs(value) {
  return Number.isSafeInteger(value) ? `${new Date(value).toISOString()} (${value} ms)` : NOT_SUPPLIED;
}

// the candidate read (GET …/candidates/{id}) as [field, label, value] rows; nothing invented
export function candidateFacts(value) {
  if (!isObject(value) || !isObject(value.candidate_ref)) fail('not a candidate read');
  const manifest = isObject(value.manifest) ? value.manifest : {};
  const descriptor = isObject(value.service_descriptor) ? value.service_descriptor : {};
  const registration = isObject(value.registration) ? value.registration : {};
  const documents = Array.isArray(value.documents) ? value.documents : [];
  const license = documents.find(item => item?.document_kind === 'license');
  const compatibility = isObject(manifest.compatibility) ? manifest.compatibility : null;
  const requirements = isObject(manifest.requirements) ? manifest.requirements : {};
  const platforms = Array.isArray(descriptor.platforms) ? descriptor.platforms : null;
  return [
    ['state', '상태', MESSAGES.candidateState[value.state] ?? text(value.state)],
    ['candidate_id', '후보 ID', text(value.candidate_ref.candidate_id)],
    ['command_id', '등록 요청 ID', text(value.command_id)],
    ['registration_digest', '등록 기록 digest', text(value.registration_digest)],
    ['manifest_digest', 'manifest digest', text(value.candidate_ref.manifest_digest)],
    ['service_descriptor_digest', 'service descriptor digest', text(value.candidate_ref.service_descriptor_digest)],
    ['extension', '확장 ID·버전', manifest.extension_id === undefined ? NOT_SUPPLIED
      : `${manifest.extension_id} ${text(manifest.extension_version)}`],
    ['kind', '종류', text(manifest.extension_kind)],
    ['port_contract_version', '포트 계약 버전', text(manifest.port_contract_version)],
    ['artifact_form', '형태', text(manifest.artifact?.artifact_form)],
    ['source', '출처(가져오지 않음·확인 전)', isObject(manifest.source)
      ? `${text(manifest.source.kind)} · ${text(manifest.source.locator)} · provenance ${metaRefText(manifest.source.provenance_ref)}`
      : NOT_SUPPLIED],
    ['license', '라이선스(승인 전)', isObject(manifest.license)
      ? `${text(manifest.license.expression)} · 원문 ${metaRefText(manifest.license.text_ref)}` : NOT_SUPPLIED],
    ['license_text', '라이선스 원문', typeof license?.content === 'string' ? license.content : NOT_SUPPLIED],
    ['compatibility', '호환성 신고', compatibility === null ? NOT_SUPPLIED
      : `framework ${compatibility.framework_min}–${compatibility.framework_max} · extension API ${compatibility.extension_api_min}–${compatibility.extension_api_max} · schema ${listText(compatibility.schema_versions)}`],
    ['grants', '요청 grant', listText(requirements.grant_ids)],
    ['secrets', '요청 비밀 값 종류', listText(requirements.secret_needs)],
    ['filesystem', '파일 시스템 요구', listText(requirements.filesystem_needs)],
    ['policies', '네트워크·자원·격리 신고', isObject(requirements.network_policy_ref)
      ? [requirements.network_policy_ref, requirements.resource_profile_ref, requirements.isolation_profile_ref]
        .map(metaRefText).join(' / ') : NOT_SUPPLIED],
    ['service', '서비스 식별자', text(descriptor.service_identity)],
    ['image', '이미지 저장소·index(가져오지 않음)', descriptor.image_repository === undefined ? NOT_SUPPLIED
      : `${descriptor.image_repository} · ${text(descriptor.index?.digest)}`],
    ['platforms', '신고한 platform', platforms === null ? NOT_SUPPLIED
      : platforms.map(entry => `${entry?.platform} (manifest ${entry?.manifest?.digest})`).join(', ')],
    ['registered', '등록자·시각', registration.registered_by === undefined ? NOT_SUPPLIED
      : `${text(registration.registered_by?.id)} · ${text(registration.registered_at)} · ${text(registration.source_class)}`],
    ['support_documents', '지원 문서', documents.length === 0 ? NOT_SUPPLIED
      : documents.map(item => item?.document_kind).join(', ')],
    ['trust', '신뢰 등급', NOT_SUPPLIED],
    ['installation', '설치·qualification', NOT_SUPPLIED],
    ['binding', '바인딩·slot key', NOT_SUPPLIED],
    ['environments', '영향받는 환경', NOT_SUPPLIED],
  ];
}

// the installation reply (provider-installation-reply-v1) as rows
export function installationFacts(value) {
  if (!isObject(value) || value.schema_version !== 'provider-installation-reply-v1') fail('not an installation reply');
  return [
    ['state', '상태', value.state === 'verified' ? '검증됨(verified)' : text(value.state)],
    ['command_id', '검증 요청 ID', text(value.command_id)],
    ['staged_installation_ref', '스테이징된 설치(수정본 1)', refText(value.staged_installation_ref)],
    ['verified_installation_ref', '검증된 설치(수정본 2)', refText(value.verified_installation_ref)],
    ['revision', '설치 수정본', text(value.revision)],
    ['release_review_sha256', '릴리스 검토 sha256', text(value.release_review_sha256)],
    ['release_source_context_sha256', '릴리스 소스 문맥 sha256', text(value.release_source_context_sha256)],
    ['verified_at', '검증 시각', isoMs(value.verified_at_ms)],
  ];
}

// a conformance reply (v1 staged or v2 verified) as rows
export function conformanceFacts(value) {
  if (!isObject(value) || !['provider-conformance-reply-v1', 'provider-conformance-reply-v2'].includes(value.schema_version)) {
    fail('not a conformance reply');
  }
  const verified = value.schema_version === 'provider-conformance-reply-v2';
  return [
    ['state', '결과', CONFORMANCE_STATES[value.state] ?? text(value.state)],
    ['command_id', '실행 ID', text(value.command_id)],
    ['subject', '대상', verified ? '검증된 설치(provider-conformance-command-v2)' : '스테이징된 설치(v1, 검증 전)'],
    ['staged_installation_ref', '스테이징된 설치', refText(verified ? value.staged_installation_ref : value.installation_ref)],
    ['verified_installation_ref', '검증된 설치', verified ? refText(value.verified_installation_ref) : NOT_SUPPLIED],
    ['counts', '벡터', `완료 ${value.completed_count}/4 · 일치 ${value.matched_count}/4`],
    ['suite', '검사 모음', `${text(value.suite_version)} · sha256 ${text(value.suite_sha256)}`],
    ['context', '문맥 sha256', text(verified ? value.stage_context_sha256 : value.context_sha256)],
    ['admission', '검증 설치 승인 sha256', verified ? text(value.admission_sha256) : NOT_SUPPLIED],
    ['result_ref', '결과 기록', value.result_ref === null ? '아직 없음' : refText(value.result_ref)],
    ['failure_code', '실패 원인 코드', NOT_SUPPLIED],
  ];
}

// the exact expected head a verified-installation conformance run carries: the refs as read
export function headFrom(value) {
  const pick = (staged, verified) => (isObject(staged) && isObject(verified)
    && staged.kind === 'extension_installation' && verified.kind === 'extension_installation'
    && staged.version === 1 && verified.version === 2 && staged.id === verified.id
    ? Object.freeze({ staged: structuredClone(staged), verified: structuredClone(verified) }) : null);
  if (value?.schema_version === 'provider-installation-reply-v1') {
    return pick(value.staged_installation_ref, value.verified_installation_ref);
  }
  if (value?.schema_version === 'provider-conformance-reply-v2') {
    return pick(value.staged_installation_ref, value.verified_installation_ref);
  }
  return null;
}

export function conformanceCommand(head, commandId) {
  if (head === null || !isObject(head?.staged) || !isObject(head?.verified)) fail(MESSAGES.noHead);
  if (!UUID.test(commandId)) fail(MESSAGES.badId);
  return { schema_version: 'provider-conformance-command-v2', command_id: commandId,
    staged_installation_ref: structuredClone(head.staged),
    expected_verified_installation_ref: structuredClone(head.verified) };
}

// a metadata file → the exact registration body (no field is added besides a new command id)
export function candidateCommand(fileText, commandId) {
  if (typeof fileText !== 'string') fail(MESSAGES.badJson);
  if (new TextEncoder().encode(fileText).length > MAX_CANDIDATE_BYTES) fail(MESSAGES.tooLarge);
  let value;
  try { value = JSON.parse(fileText); } catch { fail(MESSAGES.badJson); }
  const keys = isObject(value) ? Object.keys(value) : [];
  const required = ['manifest', 'service_descriptor', 'documents'];
  if (!required.every(key => keys.includes(key)) || keys.some(key => ![...required, 'command_id'].includes(key))
      || !isObject(value.manifest) || !isObject(value.service_descriptor) || !Array.isArray(value.documents)) {
    fail(MESSAGES.badJson);
  }
  const id = value.command_id ?? commandId;
  if (!UUID.test(id)) fail(MESSAGES.badId);
  return { command_id: id, manifest: value.manifest, service_descriptor: value.service_descriptor,
    documents: value.documents };
}

// the release-evidence packet's header only (prefix, length, canonical JSON header); the
// objects after it are neither parsed nor evaluated here
export function packetHeader(bytes) {
  if (!(bytes instanceof Uint8Array)) fail(MESSAGES.badPacket);
  if (bytes.byteLength > MAX_PACKET_BYTES) fail(MESSAGES.tooLarge);
  if (bytes.byteLength < 13 || PACKET_PREFIX.some((byte, index) => bytes[index] !== byte)) fail(MESSAGES.badPacket);
  const length = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(8);
  if (length < 1 || length > MAX_PACKET_HEADER || 12 + length > bytes.byteLength) fail(MESSAGES.badPacket);
  let header;
  try {
    header = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(12, 12 + length)));
  } catch { fail(MESSAGES.badPacket); }
  const objects = header?.objects;
  const staged = header?.staged_installation_ref;
  if (!isObject(header) || header.schema_version !== 'provider-installation-command-v1' || !UUID.test(header.command_id)
      || !isObject(staged) || staged.kind !== 'extension_installation' || staged.version !== 1
      || !HEX64.test(staged.sha256 ?? '') || !Array.isArray(objects) || objects.length < 12 || objects.length > 128
      || objects.some(item => !isObject(item) || !Number.isSafeInteger(item.size_bytes) || item.size_bytes < 1)
      || 12 + length + objects.reduce((sum, item) => sum + item.size_bytes, 0) !== bytes.byteLength) {
    fail(MESSAGES.badPacket);
  }
  return Object.freeze({ command_id: header.command_id, staged_installation_ref: structuredClone(staged),
    object_count: objects.length, roles: objects.map(item => String(item.role)), total_bytes: bytes.byteLength });
}

export function createExtensionsPanel({ root, document, fetch, basePath = '/', session,
  randomUUID = () => globalThis.crypto.randomUUID() } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof fetch !== 'function') fail('a fetch function is required');
  if (typeof session?.csrfToken !== 'function') fail('a session adapter is required');
  const api = `${basePath.slice(0, -1)}/api/v1/extensions`;
  const state = { candidate: null, installation: null, conformance: null, qualification: null, head: null,
    packet: null, packetBytes: null, candidateText: null };
  const unanswered = { candidate: null, conformance: null };

  function element(tag, content, attributes = {}) {
    const node = document.createElement(tag);
    if (content !== undefined) node.textContent = content;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  function facts(rows, label) {
    const list = element('dl', undefined, { 'aria-label': label });
    for (const [field, name, value] of rows) {
      list.append(element('dt', name), element('dd', value,
        { 'data-field': field, 'data-supplied': value === NOT_SUPPLIED ? 'false' : 'true' }));
    }
    return list;
  }

  function section(id, title, intro) {
    const node = element('section', undefined, { 'data-extensions-section': id, 'aria-labelledby': `extensions-${id}-title` });
    node.append(element('h3', title, { id: `extensions-${id}-title` }));
    if (intro !== undefined) node.append(element('p', intro));
    return node;
  }

  function lookup(id, label, button) {
    const input = element('input', undefined, { id, type: 'text', inputmode: 'latin', autocomplete: 'off',
      spellcheck: 'false', maxlength: '36' });
    return [element('label', label, { for: id }), input, element('button', button, { type: 'button' })];
  }

  const line = element('p', MESSAGES.loading, { role: 'status', 'aria-live': 'polite', 'data-extensions-line': '' });

  const supply = element('ul', undefined, { 'aria-label': '서버가 제공하는 항목' });
  for (const entry of SUPPLY) {
    supply.append(element('li', `${entry.label}: ${entry.supplied ? '제공됨' : '제공되지 않음'} — ${entry.detail}`,
      { 'data-supply': entry.id, 'data-supplied': String(entry.supplied) }));
  }
  const supplySection = section('supply', '이 서버가 보내는 항목');
  supplySection.append(supply);

  const candidateSection = section('candidate', '실행형 확장 후보', MESSAGES.candidateIntro);
  const [candidateLabel, candidateId, candidateRead] = lookup('extensions-candidate-id', '후보 ID', '후보 읽기');
  const candidateFile = element('input', undefined, { id: 'extensions-candidate-file', type: 'file', accept: 'application/json,.json' });
  const candidateRegister = element('button', '이 메타데이터로 후보 등록', { type: 'button', 'data-act': 'candidate-register' });
  const candidateView = element('div', undefined, { 'data-view': 'candidate' });
  candidateSection.append(candidateLabel, candidateId, candidateRead,
    element('label', '후보 메타데이터 파일(JSON, 코드 없음)', { for: 'extensions-candidate-file' }), candidateFile,
    candidateRegister, candidateView);

  const installationSection = section('installation', '제공자 설치 검증', MESSAGES.installationIntro);
  const [installationLabel, installationId, installationRead] = lookup('extensions-installation-id', '설치 검증 요청 ID', '설치 검증 결과 읽기');
  const packetFile = element('input', undefined, { id: 'extensions-packet-file', type: 'file' });
  const packetView = element('p', '', { 'data-view': 'packet' });
  const installationVerify = element('button', '이 증거 묶음으로 설치 검증', { type: 'button', 'data-act': 'installation-verify' });
  const installationView = element('div', undefined, { 'data-view': 'installation' });
  installationSection.append(installationLabel, installationId, installationRead,
    element('label', '릴리스 증거 묶음 파일', { for: 'extensions-packet-file' }), packetFile, packetView,
    installationVerify, installationView);

  const conformanceSection = section('conformance', '제공자 적합성 검사', MESSAGES.conformanceIntro);
  const [conformanceLabel, conformanceId, conformanceRead] = lookup('extensions-conformance-id', '적합성 검사 실행 ID', '적합성 검사 읽기');
  const headView = element('p', MESSAGES.noHead, { 'data-view': 'head' });
  const conformanceRun = element('button', '읽은 헤드로 적합성 검사 실행', { type: 'button', 'data-act': 'conformance-run' });
  const conformanceView = element('div', undefined, { 'data-view': 'conformance' });
  conformanceSection.append(conformanceLabel, conformanceId, conformanceRead, headView, conformanceRun, conformanceView);

  const qualificationSection = section('qualification', '제공자 전송 매니페스트 검증', MESSAGES.qualificationIntro);
  const qualificationView = element('div', undefined, { 'data-view': 'qualification' });
  qualificationSection.append(qualificationView,
    element('a', MESSAGES.qualificationLink, { href: CREDENTIALS_LINK, 'data-link': 'transport-qualification' }));

  const bindingSection = section('binding', '바인딩·롤백 보존', MESSAGES.bindingIntro);
  bindingSection.append(facts([
    ['binding', '현재·교체·비활성 바인딩', NOT_SUPPLIED],
    ['slot_key', '다섯 필드 BindingSlotKeyV1(포트 버전 포함)과 digest', NOT_SUPPLIED],
    ['slot', '논리 slot·capability selector', NOT_SUPPLIED],
    ['coexistence', '같은 포트의 다른 slot 공존 / 같은 slot 경쟁', NOT_SUPPLIED],
    ['expected_head', '바인딩 기대 헤드 수정본', NOT_SUPPLIED],
    ['history', '변경 불가 바인딩 이력', NOT_SUPPLIED],
    ['retention', '롤백 보존 상태(보존중·해제됨·사용됨)', NOT_SUPPLIED],
    ['environments', '이 확장을 쓰는 환경 버전', NOT_SUPPLIED],
  ], '바인딩 항목'));

  const stagingSection = section('staging', '운영자 배치(staging) 인계', MESSAGES.stagingIntro);

  root.replaceChildren(element('h2', '확장', { id: 'settings-extensions-title' }), element('p', MESSAGES.intro), line,
    supplySection, candidateSection, installationSection, conformanceSection, qualificationSection, bindingSection,
    stagingSection);

  function say(message, code) {
    line.textContent = message;
    line.dataset.state = code;
  }

  function refused(error) {
    const code = Object.hasOwn(ERRORS, error?.code) ? error.code : 'unavailable';
    say(ERRORS[code], code);
    return code;
  }

  async function call(method, path, { json, bytes } = {}) {
    const options = { method, credentials: 'same-origin', headers: {} };
    if (json !== undefined) {
      options.headers = { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrfToken() };
      options.body = JSON.stringify(json);
    } else if (bytes !== undefined) {
      options.headers = { 'Content-Type': INSTALLATION_MEDIA_TYPE, 'X-DeepTwin-CSRF': session.csrfToken() };
      options.body = bytes;
    }
    let response;
    try {
      response = await fetch(`${api}${path}`, options);
    } catch {
      throw Object.assign(new Error('refused'), { code: 'unavailable', unanswered: true });
    }
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    if (!response.ok) {
      throw Object.assign(new Error('refused'), { status: response.status, unanswered: response.status >= 500,
        code: Object.hasOwn(ERRORS, payload?.code) ? payload.code : ({ 400: 'invalid_input', 401: 'unauthenticated',
          403: 'access_denied', 404: 'not_found', 409: 'conflict', 413: 'too_large', 429: 'capacity' }[response.status] ?? 'unavailable') });
    }
    if (!isObject(payload)) throw Object.assign(new Error('refused'), { code: 'unavailable', unanswered: true });
    return { status: response.status, payload };
  }

  function draw() {
    candidateView.replaceChildren(...(state.candidate === null ? [] : [facts(candidateFacts(state.candidate), '후보 내용')]));
    candidateView.dataset.candidateId = state.candidate?.candidate_ref?.candidate_id ?? '';
    installationView.replaceChildren(...(state.installation === null ? []
      : [facts(installationFacts(state.installation), '설치 검증 결과')]));
    conformanceView.replaceChildren(...(state.conformance === null ? []
      : [facts(conformanceFacts(state.conformance), '적합성 검사 결과')]));
    conformanceView.dataset.state = state.conformance?.state ?? '';
    headView.textContent = state.head === null ? MESSAGES.noHead : MESSAGES.head(state.head.staged, state.head.verified);
    headView.dataset.head = state.head === null ? '' : state.head.verified.sha256;
    if (state.head === null) conformanceRun.setAttribute('aria-disabled', 'true');
    else conformanceRun.setAttribute('aria-disabled', 'false');
    packetView.textContent = state.packet === null ? ''
      : `요청 ${state.packet.command_id} · 스테이징된 설치 ${refText(state.packet.staged_installation_ref)} · 증거 ${state.packet.object_count}개 · ${state.packet.total_bytes} bytes`;
    const value = state.qualification;
    qualificationView.replaceChildren(...(value === null ? [] : [facts([
      ['manifest_sha256', '전송 매니페스트 sha256', text(value.manifest_sha256)],
      ['prerequisite', '적합성 검사 전제', text(value.prerequisite)],
      ['eligible_conformance', '전제를 충족한 실행', value.eligible_conformance === null ? '없음'
        : `${value.eligible_conformance.command_id} · ${refText(value.eligible_conformance.verified_installation_ref)}`],
      ['qualification', '봉인된 검증 기록', value.qualification === null ? '없음'
        : `수정본 ${value.qualification.revision} · 실행 ${value.qualification.conformance_command_id}`],
      ['gateway', '게이트웨이 채택', `${text(value.gateway?.state)}${Number.isSafeInteger(value.gateway?.revision) ? ` · 수정본 ${value.gateway.revision}` : ''}`],
      ['state', '상태', value.reason === null ? 'qualified' : `unqualified (${value.reason})`],
    ], '전송 매니페스트 검증 상태')]));
    qualificationView.dataset.state = value?.state ?? '';
  }

  function adoptConformance(value) {
    conformanceFacts(value);
    state.conformance = value;
    const head = headFrom(value);
    if (head !== null) state.head = head;
  }

  function uuidOf(input) {
    const value = String(input.value ?? '').trim();
    if (!UUID.test(value)) throw Object.assign(new Error(MESSAGES.badId), { local: true });
    return value;
  }

  async function guarded(work) {
    try {
      return await work();
    } catch (error) {
      if (error?.local === true) say(error.message, 'refused_here');
      else refused(error);
      throw error;
    } finally {
      draw();
    }
  }

  const local = message => Object.assign(new Error(message), { local: true });

  async function readCandidate(id) {
    return guarded(async () => {
      const { payload } = await call('GET', `/candidates/${id}`);
      candidateFacts(payload);
      state.candidate = payload;
      say(MESSAGES.loaded, 'read');
      return payload;
    });
  }

  async function registerCandidate(fileText) {
    return guarded(async () => {
      let body = unanswered.candidate;
      if (body === null) {
        try { body = candidateCommand(fileText, randomUUID()); } catch (error) { throw local(error.message); }
      }
      say(MESSAGES.working, 'working');
      try {
        const { payload } = await call('POST', '/candidates', { json: body });
        unanswered.candidate = null;
        const id = payload.candidate_ref?.candidate_id;
        if (!UUID.test(id ?? '')) throw Object.assign(new Error('refused'), { code: 'unavailable' });
        const { payload: read } = await call('GET', `/candidates/${id}`);
        state.candidate = read;
        candidateId.value = id;
        say(MESSAGES.registered(id), 'registered');
        return payload;
      } catch (error) {
        unanswered.candidate = error?.unanswered === true ? body : null;
        throw error;
      }
    });
  }

  async function readInstallation(id) {
    return guarded(async () => {
      const { payload } = await call('GET', `/provider-installation/${id}`);
      installationFacts(payload);
      state.installation = payload;
      state.head = headFrom(payload) ?? state.head;
      say(MESSAGES.loaded, 'read');
      return payload;
    });
  }

  function choosePacket(bytes) {
    state.packet = null;
    state.packetBytes = null;
    try {
      state.packet = packetHeader(bytes);
      state.packetBytes = bytes;
      say('', 'packet');
    } catch (error) {
      say(error.message, 'refused_here');
    }
    draw();
    return state.packet;
  }

  async function verifyInstallation() {
    return guarded(async () => {
      if (state.packetBytes === null) throw local(MESSAGES.noFile);
      // the packet carries its own command id, so a resend of the same file is exact replay
      say(MESSAGES.working, 'working');
      const { payload } = await call('POST', '/provider-installation', { bytes: state.packetBytes });
      installationFacts(payload);
      state.installation = payload;
      state.head = headFrom(payload) ?? state.head;
      installationId.value = payload.command_id;
      say(MESSAGES.verified(payload.command_id), 'verified');
      return payload;
    });
  }

  async function readConformance(id) {
    return guarded(async () => {
      const { payload } = await call('GET', `/provider-conformance/${id}`);
      adoptConformance(payload);
      say(MESSAGES.loaded, 'read');
      return payload;
    });
  }

  async function runConformance() {
    return guarded(async () => {
      let body = unanswered.conformance;
      if (body === null) {
        try { body = conformanceCommand(state.head, randomUUID()); } catch (error) { throw local(error.message); }
      }
      say(MESSAGES.working, 'working');
      try {
        const { payload } = await call('POST', '/provider-conformance', { json: body });
        unanswered.conformance = null;
        adoptConformance(payload);
        conformanceId.value = payload.command_id;
        say(MESSAGES.started(payload.state), payload.state);
        return payload;
      } catch (error) {
        unanswered.conformance = error?.unanswered === true ? body : null;
        throw error;
      }
    });
  }

  // the screen's first read: the qualification state names the verified-installation run
  // that meets its prerequisite (or the sealed one's run); that run carries the installation head
  async function load() {
    return guarded(async () => {
      say(MESSAGES.loading, 'loading');
      const { payload } = await call('GET', '/provider-transport-qualification');
      if (payload.schema_version !== 'provider-transport-qualification-state-v1') {
        throw Object.assign(new Error('refused'), { code: 'unavailable' });
      }
      state.qualification = payload;
      const run = payload.eligible_conformance?.command_id ?? payload.qualification?.conformance_command_id ?? null;
      if (typeof run === 'string' && UUID.test(run)) {
        const { payload: reply } = await call('GET', `/provider-conformance/${run}`);
        adoptConformance(reply);
        conformanceId.value = run;
      }
      say(MESSAGES.loaded, 'loaded');
      return payload;
    });
  }

  const quiet = promise => promise.catch(() => {});
  candidateRead.addEventListener('click', () => quiet(guarded(async () => uuidOf(candidateId)).then(readCandidate)));
  installationRead.addEventListener('click', () => quiet(guarded(async () => uuidOf(installationId)).then(readInstallation)));
  conformanceRead.addEventListener('click', () => quiet(guarded(async () => uuidOf(conformanceId)).then(readConformance)));
  candidateFile.addEventListener('change', () => {
    const file = candidateFile.files?.[0];
    unanswered.candidate = null;
    state.candidateText = null;
    if (file) quiet(file.text().then(value => { state.candidateText = value; }));
  });
  candidateRegister.addEventListener('click', () => quiet(state.candidateText === null
    ? guarded(async () => { throw local(MESSAGES.noFile); }) : registerCandidate(state.candidateText)));
  packetFile.addEventListener('change', () => {
    const file = packetFile.files?.[0];
    if (file) quiet(file.arrayBuffer().then(buffer => choosePacket(new Uint8Array(buffer))));
  });
  installationVerify.addEventListener('click', () => quiet(verifyInstallation()));
  conformanceRun.addEventListener('click', () => quiet(runConformance()));
  draw();

  return Object.freeze({ load, readCandidate, registerCandidate, readInstallation, choosePacket, verifyInstallation,
    readConformance, runConformance,
    get head() { return state.head === null ? null : structuredClone({ ...state.head }); } });
}

export async function bootExtensions({ document, location, fetch } = {}) {
  const root = document.getElementById(EXTENSIONS_MOUNT_ID);
  if (root === null) return null;
  const basePath = basePathFrom(location.pathname);
  const session = createSupportedSession({ fetch, basePath });
  try {
    await session.establish();
  } catch (error) {
    const heading = document.createElement('h2');
    heading.textContent = '확장';
    heading.setAttribute('id', 'settings-extensions-title');
    const status = document.createElement('p');
    status.textContent = error?.code === 'unauthenticated' ? MESSAGES.unauthenticated : ERRORS.unavailable;
    root.replaceChildren(heading, status);
    return Object.freeze({ established: false });
  }
  const panel = createExtensionsPanel({ root, document, fetch, basePath, session });
  await panel.load().catch(() => {});
  return Object.freeze({ established: true, panel });
}

if (typeof globalThis.document === 'object' && globalThis.document !== null
    && typeof globalThis.document.getElementById === 'function'
    && globalThis.document.getElementById(EXTENSIONS_MOUNT_ID) !== null) {
  bootExtensions({ document: globalThis.document, location: globalThis.location,
    fetch: (...args) => globalThis.fetch(...args) }).catch(() => {
    const root = globalThis.document.getElementById(EXTENSIONS_MOUNT_ID);
    if (root) root.textContent = ERRORS.unavailable;
  });
}
