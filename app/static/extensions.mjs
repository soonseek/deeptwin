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
//   state, read-only here; the act itself lives in the credentials section, linked. Its sealed
//   qualification ref is the one a provider bind names.
// - `GET {base}api/v1/extensions/candidates?limit&after` and `…/installations?limit&after`
//   (bounded pages): the candidate list (trust tier from the port contract) and every
//   staged/verified installation with its trust tier, service tuple, the deployment request and
//   receipt that staged it (the request's own read route is linked) and its active slots.
// - `extension-bindings-v1`: `GET …/bindings?limit&after`, `GET …/bindings/{slot_key_digest}`
//   (the exact five-field BindingSlotKeyV1 and digest as the server stores them, logical slot and
//   capability selector, head, immutable history, rollback-retention heads with the server's
//   release warning, coexisting slots, same-slot holders, affected environments),
//   `POST …/binding-slot-keys` (the key and digest the server computes; the page never builds a
//   key or digest itself), and the owner acts `POST …/bindings` (bind), `…/{digest}/disable`,
//   `…/{digest}/rollback` and `…/{digest}/rollback-retentions/{target}/release`. Every act
//   carries exactly the head (and retention head) last read; a 409 is shown with the server's
//   text and the page asks for a fresh read, never retrying with another head. A release is a
//   separate confirmation that shows the server's warning verbatim.
//
// What no route supplies stays "not supplied" without a control: a supported-platform
// judgement, bindings of ports other than the provider port (no qualification record exists for
// them), a list of deployment requests that produced no installation, and environment versions
// that bind a binding revision (none records one yet). Executable staging is the instance
// operator's authority outside the product; the page describes that handoff and gives no host
// instructions. All server text reaches the DOM through textContent or attributes only.

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
  ['binding', '바인딩', true, 'slot 목록과 slot 읽기: 현재 헤드, 현재 확장·설치·검증 기록'],
  ['slot_key', '다섯 필드 slot key(포트 버전 포함)+digest', true, '서버가 계산·저장한 BindingSlotKeyV1과 digest 그대로(화면은 계산하지 않음)'],
  ['slot', '논리 slot·capability selector', true, 'binding_slot_id·purpose·포트와 selector. selector는 제공자 포트 형식만 받음'],
  ['coexistence', '같은 포트 공존·같은 slot 경쟁', true, 'slot 읽기: 같은 포트·범위·목적의 다른 slot과, 이 slot을 가졌던 확장'],
  ['bind', '바인딩·비활성화·롤백', true, '읽은 기대 헤드 그대로 보냄(다르면 409). 검증 기록이 있는 제공자 포트만'],
  ['history', '변경 불가 이력·롤백 보존 상태', true, '모든 바인딩 수정본과 각 롤백 보존 헤드(보존중·해제됨·사용됨)'],
  ['release', '롤백 보존 해제(소유자 전용)', true, '서버 경고를 보여 준 뒤 별도 확인으로만 보냄. 이력은 지워지지 않음'],
  ['environments', '영향받는 환경', true, 'slot 범위의 대상 환경. 바인딩 수정본을 기록하는 환경 버전은 아직 없어 목록은 비어 있음'],
  ['trust', '신뢰 등급', true, '후보·설치 목록: 포트 계약이 정한 신뢰 등급(trust_tier_basis=port_contract)'],
  ['staging', '운영자 배치(staging)', true, '설치 목록: 설치를 만든 배포 요청·영수증 참조와 그 요청 읽기. 배치 자체는 운영자 권한'],
  ['platform', '지원 플랫폼 판정', false, '후보의 platforms 신고와 설치된 platform만 보입니다. 호환 판정 경로는 없습니다'],
  ['other_ports', '제공자 포트 외 바인딩', false, '다른 포트에는 검증 기록이 없어 서버가 바인딩을 거절합니다(qualification_missing·selector_unsupported)'],
  ['requests', '배포 요청 목록', false, '설치로 이어지지 않은 배포 요청을 나열하는 경로가 없습니다'],
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
  bindingIntro: '바인딩은 정확한 다섯 필드 slot key(포트 버전·대상 범위·목적·slot ID·capability selector)로 구분합니다. 확장 ID는 key가 아니라 그 slot을 차지하는 후보입니다. 같은 key의 후보만 경쟁하고, 다른 slot이나 selector는 같은 포트에서도 함께 쓰입니다. 모든 조작은 이 화면이 마지막으로 읽은 헤드를 그대로 보냅니다.',
  bindFormIntro: '서버가 slot key와 digest를 계산합니다. 바인딩은 봉인된 제공자 전송 매니페스트 검증 기록과 그 검증된 설치로만 할 수 있습니다.',
  stagingIntro: '실행형 확장의 배치(staging)는 인스턴스 운영자의 권한이며 이 제품 화면의 단계가 아닙니다. 운영자는 정확한 manifest·service descriptor digest에 대한 서명된 배포 요청과 일회용 영수증 절차로 배치하고, 그 결과로 스테이징된 설치(수정본 1)가 생깁니다. 설치 목록은 각 설치를 만든 배포 요청과 영수증 참조를 보여 주고, 그 요청의 상태를 읽을 수 있습니다. 설치로 이어지지 않은 요청의 목록은 이 서버가 보내지 않습니다. 영수증만으로 "사용 가능"이 되지 않습니다.',
  inventoryIntro: '서버가 보낸 후보·설치 목록입니다. 한 번에 정해진 개수만 읽고, 다음 쪽은 따로 읽습니다.',
  noQualification: '봉인된 제공자 전송 매니페스트 검증 기록이 없어 바인딩할 수 없습니다. 먼저 API 자격증명 화면에서 전송 매니페스트를 검증해 주세요.',
  noKey: '먼저 서버에서 slot key를 계산해 주세요.',
  noInstallation: '검증된 설치를 고르세요.',
  noSlot: '먼저 slot을 읽어 주세요.',
  badSlotId: 'slot ID는 소문자로 시작하는 식별자(a–z, 0–9, . _ : -)여야 합니다.',
  badReason: '해제 사유를 1–500바이트로 적어 주세요(앞뒤 공백·제어 문자 없이).',
  keyComputed: digest => `서버가 slot key를 계산했습니다 (${digest}).`,
  bound: head => `바인딩했습니다: 수정본 ${head.revision} (${head.state}).`,
  disabledDone: head => `비활성화했습니다: 수정본 ${head.revision}.`,
  rolledBack: head => `롤백했습니다: 수정본 ${head.revision} (${head.state}).`,
  released: revision => `롤백 보존을 해제했습니다(보존 수정본 ${revision}). 바인딩 이력은 그대로입니다.`,
  releaseConfirm: '아래 서버 경고를 확인한 뒤에만 해제를 보냅니다.',
  requestRead: state => `배포 요청 상태: ${state}`,
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

// the binding routes' refusal codes with the exact texts the server sends (REFUSALS in
// app/api/extension_bindings.py; a pytest keeps the two equal)
export const BINDING_ERRORS = Object.freeze({
  invalid_input: '바인딩 요청 형식을 확인해 주세요.',
  unauthenticated: '세션이 끝났습니다. 시작 화면(./)에서 다시 로그인해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다.',
  not_found: '그 바인딩 slot 기록이 없습니다.',
  binding_head_stale: '이 slot의 현재 바인딩 헤드가 보낸 기대 헤드와 다릅니다(다른 후보가 먼저 바꿨을 수 있음). 화면이 읽은 뒤 서버 상태가 바뀌어 아무것도 바꾸지 않았습니다. 다시 읽은 뒤 확인해 주세요.',
  binding_unchanged: '이 slot은 이미 같은 설치와 같은 검증 기록으로 활성 상태입니다. 바꾼 것은 없습니다.',
  retention_head_stale: '롤백 보존 헤드가 보낸 기대 헤드와 다릅니다. 화면이 읽은 뒤 서버 상태가 바뀌어 아무것도 바꾸지 않았습니다. 다시 읽은 뒤 확인해 주세요.',
  rollback_target_invalid: '대상은 이 slot의 현재 헤드보다 앞선, 활성이었던 바인딩 수정본이어야 합니다. 바꾼 것은 없습니다.',
  retention_not_retained: "이 대상의 롤백 보존이 '보존중'이 아닙니다(이미 해제·사용됨 또는 없음). 롤백·해제할 수 없습니다.",
  target_mismatch: '보낸 대상 설치·서비스 묶음이 보존 기록과 다릅니다. 바꾼 것은 없습니다.',
  qualification_missing: '이 포트와 설치에 대한 봉인된 검증(qualification) 기록이 없습니다. 이 서버에서 검증 기록이 있는 포트는 제공자 포트(전송 매니페스트 검증)뿐입니다.',
  qualification_not_current: '검증 기록이 더 이상 현재가 아닙니다(설치 헤드·릴리스 소스·전송 매니페스트가 바뀜). 다시 검증한 뒤 시도해 주세요.',
  extension_mismatch: '보낸 확장 ID가 검증된 설치나 대상 바인딩의 확장과 다릅니다.',
  selector_mismatch: 'capability selector의 provider_id가 검증 기록의 제공자와 다릅니다.',
  selector_unsupported: '이 포트의 capability selector 형식은 계약에 아직 확정되지 않아 이 서버가 받지 않습니다.',
  command_conflict: '이 요청 ID는 이미 다른 내용으로 쓰였습니다. 새 요청으로 다시 시도해 주세요.',
  capacity: '바인딩 기록의 저장 한도에 닿았습니다.',
  unavailable: '바인딩 요청을 처리하지 못했습니다. 같은 요청 ID로만 다시 보냅니다.',
});

export const PURPOSES = Object.freeze(['operational', 'diagnosis', 'inquiry_audit', 'evaluation_development',
  'evaluation_sealed', 'release_evidence']);
export const PAGE_LIMIT = 20;
const SLOT_ID = /^[a-z][a-z0-9._:-]{0,127}$/;
const RETENTION_STATES = Object.freeze({ retained: '보존중(retained)', released: '해제됨(released)', consumed: '롤백에 사용됨(consumed)' });

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
export function candidateFacts(value, { summary = null, installations = null } = {}) {
  if (!isObject(value) || !isObject(value.candidate_ref)) fail('not a candidate read');
  const listed = isObject(summary) && summary.candidate_id === value.candidate_ref.candidate_id ? summary : null;
  const installed = Array.isArray(installations)
    ? installations.filter(row => row?.candidate_id === value.candidate_ref.candidate_id) : null;
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
    ['trust', '신뢰 등급', typeof listed?.trust_tier === 'string' ? `${listed.trust_tier} (포트 계약 기준)` : NOT_SUPPLIED],
    ['installation', '설치', installed === null ? NOT_SUPPLIED : installed.length === 0 ? '읽은 설치 목록에 이 후보의 설치 없음'
      : installed.map(row => `${row.installation_id} ${row.state} 수정본 ${row.revision}`).join(' / ')],
    ['binding', '이 후보의 설치를 쓰는 활성 slot', installed === null ? NOT_SUPPLIED
      : listText(installed.flatMap(row => row.active_binding_slot_digests ?? []))],
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

function json(value) {
  return value === undefined ? NOT_SUPPLIED : JSON.stringify(value);
}

function headText(head) {
  return isObject(head) ? `수정본 ${head.revision} · ${head.state} · ${head.binding_record_digest}` : '없음(빈 slot)';
}

function installRefText(ref) {
  return isObject(ref) ? `${ref.extension_id} 수정본 ${ref.revision} · ${ref.installation_record_digest}` : NOT_SUPPLIED;
}

function revisionRefText(ref) {
  return isObject(ref) ? `수정본 ${ref.revision} · ${ref.binding_record_digest}` : '없음';
}

// one installation list row (extension-installation-list-v1) as rows; nothing invented
export function installationRowFacts(row) {
  if (!isObject(row) || !UUID.test(row.installation_id ?? '')) fail('not an installation row');
  const staging = isObject(row.staging) ? row.staging : null;
  return [
    ['state', '상태', row.state === 'verified' ? '검증됨(verified)' : row.state === 'staged' ? '스테이징됨(staged, 검증 전)' : text(row.state)],
    ['extension', '확장 ID·버전', `${text(row.extension_id)} ${row.extension_version ?? '(버전은 검증 뒤에 기록)'}`],
    ['head_ref', '설치 헤드', refText(row.head_ref)],
    ['verified_installation_ref', '검증된 설치(수정본 2)', row.verified_installation_ref === null ? '없음' : refText(row.verified_installation_ref)],
    ['port', '포트 계약', text(row.port_contract_version)],
    ['trust', '신뢰 등급', typeof row.trust_tier === 'string' ? `${row.trust_tier} (포트 계약 기준)` : NOT_SUPPLIED],
    ['platform', '설치된 platform', text(row.platform)],
    ['service_tuple', '서비스 묶음', isObject(row.service_tuple) ? json(row.service_tuple) : NOT_SUPPLIED],
    ['staging', '배치(staging) 기록', staging === null ? NOT_SUPPLIED
      : `${text(staging.state)} · ${text(staging.staging_authority)} · 요청 ${refText(staging.request_ref)} · 영수증 ${refText(staging.receipt_ref)} · ${text(staging.installed_at)}`],
    ['candidate', '후보', row.candidate_id === null ? '연결된 후보 없음' : text(row.candidate_id)],
    ['bindings', '이 설치를 쓰는 활성 slot', Array.isArray(row.active_binding_slot_digests) ? listText(row.active_binding_slot_digests) : NOT_SUPPLIED],
  ];
}

// one slot read (extension-binding-slot-v1) as rows, the key and selector exactly as sent
export function slotFacts(value) {
  if (!isObject(value) || value.schema_version !== 'extension-binding-slot-v1') fail('not a slot read');
  const current = isObject(value.current) ? value.current : {};
  const environments = isObject(value.affected_environments) ? value.affected_environments : null;
  return [
    ['binding_slot_key_digest', 'slot key digest', text(value.binding_slot_key_digest)],
    ['binding_slot_key', '다섯 필드 BindingSlotKeyV1', json(value.binding_slot_key)],
    ['logical_slot', '논리 slot', isObject(value.logical_slot)
      ? `${value.logical_slot.binding_slot_id} · ${value.logical_slot.purpose} · ${value.logical_slot.port_contract_version}` : NOT_SUPPLIED],
    ['capability_selector', 'capability selector', json(value.capability_selector)],
    ['target_scope', '대상 범위', json(value.target_scope)],
    ['trust', '종류·신뢰 등급', `${text(value.extension_kind)} · ${text(value.trust_tier)} (포트 계약 기준)`],
    ['head', '현재 헤드', headText(value.head)],
    ['current', '현재 확장·설치', `${text(current.extension_id)} · ${installRefText(current.target_installation_ref)}`],
    ['qualification', '검증 기록', `${refText(current.qualification_ref)} · ${current.qualification_current === true ? '현재' : '현재 아님'}`],
    ['service_tuple', '서비스 묶음', isObject(current.service_tuple) ? json(current.service_tuple) : NOT_SUPPLIED],
    ['competition', '같은 slot을 가졌던 확장', Array.isArray(value.competition?.holders)
      ? value.competition.holders.map(item => `${item.extension_id} (수정본 ${item.revisions.join(', ')})`).join(' / ') : NOT_SUPPLIED],
    ['coexistence', '같은 포트·범위·목적의 다른 slot', Array.isArray(value.coexisting_slots)
      ? (value.coexisting_slots.length === 0 ? '없음' : value.coexisting_slots
        .map(item => `${item.binding_slot_id} · ${item.extension_id} · ${headText(item.head)} · ${item.binding_slot_key_digest}`).join(' / '))
      : NOT_SUPPLIED],
    ['environments', '영향받는 환경', environments === null ? NOT_SUPPLIED
      : `대상 환경 ${environments.target_environment_id ?? '없음(인스턴스 범위)'} · 이 수정본을 쓰는 환경 버전 ${environments.bound_environment_versions.length === 0 ? '없음' : listText(environments.bound_environment_versions)} (${environments.basis})`],
  ];
}

// the exact owner act bodies: every key, head and ref is the one the server sent
export function slotKeyRequest({ slotId, purpose, environmentId = '', providerId }) {
  if (!SLOT_ID.test(slotId ?? '')) fail(MESSAGES.badSlotId);
  if (!PURPOSES.includes(purpose)) fail(MESSAGES.badSlotId);
  const environment = String(environmentId ?? '').trim();
  if (environment !== '' && !UUID.test(environment)) fail(MESSAGES.badId);
  if (!SLOT_ID.test(providerId ?? '')) fail(MESSAGES.badSlotId);
  return { port_contract_version: 'provider-port-v1', binding_slot_id: slotId,
    target_scope: { environment_id: environment === '' ? null : environment, work_id: null, node_id: null, purpose },
    capability_selector: { selector_kind: 'provider_role', provider_id: providerId, auth_mode: 'api', account_binding_ref: null } };
}

export function bindCommand(key, extensionId, qualificationRef, commandId) {
  if (!isObject(key) || key.schema_version !== 'extension-binding-slot-key-v1') fail(MESSAGES.noKey);
  if (!isObject(qualificationRef)) fail(MESSAGES.noQualification);
  if (typeof extensionId !== 'string' || extensionId === '') fail(MESSAGES.noInstallation);
  if (!UUID.test(commandId)) fail(MESSAGES.badId);
  return { command_id: commandId, extension_id: extensionId, qualification_ref: structuredClone(qualificationRef),
    binding_slot_key: structuredClone(key.binding_slot_key), binding_slot_key_digest: key.binding_slot_key_digest,
    capability_selector: structuredClone(key.capability_selector), target_scope: structuredClone(key.target_scope),
    expected_current_binding_head: structuredClone(key.current_binding_head) };
}

function slotBody(slot, extensionId, commandId) {
  if (!isObject(slot) || slot.schema_version !== 'extension-binding-slot-v1' || !isObject(slot.head)) fail(MESSAGES.noSlot);
  if (!UUID.test(commandId)) fail(MESSAGES.badId);
  return { command_id: commandId, extension_id: extensionId, binding_slot_key: structuredClone(slot.binding_slot_key),
    binding_slot_key_digest: slot.binding_slot_key_digest, expected_current_binding_head: structuredClone(slot.head) };
}

export function disableCommand(slot, commandId) {
  return slotBody(slot, slot?.current?.extension_id, commandId);
}

export function rollbackCommand(slot, retention, commandId) {
  return { ...slotBody(slot, retention?.target_extension_id, commandId),
    target_binding_revision_ref: structuredClone(retention.target_binding_revision_ref),
    expected_retention_head: structuredClone(retention.retention_head) };
}

export function releaseCommand(slot, retention, reason, commandId) {
  const value = typeof reason === 'string' ? reason : '';
  const bytes = new TextEncoder().encode(value).length;
  // eslint-disable-next-line no-control-regex
  if (bytes < 1 || bytes > 500 || value !== value.trim() || /[\u0000-\u001f\u007f]/.test(value)) fail(MESSAGES.badReason);
  return { ...slotBody(slot, retention?.target_extension_id, commandId),
    target_binding_revision_ref: structuredClone(retention.target_binding_revision_ref),
    target_installation_ref: structuredClone(retention.target_installation_ref),
    target_service_tuple: structuredClone(retention.target_service_tuple),
    expected_retention_head: structuredClone(retention.retention_head), reason: value };
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
    packet: null, packetBytes: null, candidateText: null, candidates: [], candidatesNext: null,
    installations: [], installationsNext: null, slots: [], slotsNext: null, slot: null, key: null,
    releasing: null, requests: {} };
  const unanswered = { candidate: null, conformance: null, act: null };

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

  const inventorySection = section('inventory', '후보·설치 목록', MESSAGES.inventoryIntro);
  const candidateList = element('ul', undefined, { 'aria-label': '후보 목록', 'data-view': 'candidate-list' });
  const candidateMore = element('button', '후보 목록 다음 쪽', { type: 'button', 'data-act': 'candidates-more' });
  const installationList = element('div', undefined, { 'data-view': 'installation-list' });
  const installationMore = element('button', '설치 목록 다음 쪽', { type: 'button', 'data-act': 'installations-more' });
  inventorySection.append(element('h4', '후보'), candidateList, candidateMore, element('h4', '설치'), installationList,
    installationMore);

  const bindingSection = section('binding', '바인딩·롤백 보존', MESSAGES.bindingIntro);
  const slotList = element('ul', undefined, { 'aria-label': '바인딩 slot 목록', 'data-view': 'slot-list' });
  const slotMore = element('button', 'slot 목록 다음 쪽', { type: 'button', 'data-act': 'slots-more' });
  const slotInput = element('input', undefined, { id: 'extensions-slot-digest', type: 'text', inputmode: 'latin',
    autocomplete: 'off', spellcheck: 'false', maxlength: '64' });
  const slotRead = element('button', 'slot 읽기', { type: 'button', 'data-act': 'slot-read' });
  const slotView = element('div', undefined, { 'data-view': 'slot' });
  const bindForm = element('div', undefined, { 'data-view': 'bind-form' });
  const slotIdInput = element('input', undefined, { id: 'extensions-bind-slot-id', type: 'text', autocomplete: 'off',
    spellcheck: 'false', maxlength: '128' });
  slotIdInput.value = 'default-provider';
  const purposeInput = element('select', undefined, { id: 'extensions-bind-purpose' });
  for (const purpose of PURPOSES) purposeInput.append(element('option', purpose, { value: purpose }));
  purposeInput.value = 'operational';
  const environmentInput = element('input', undefined, { id: 'extensions-bind-environment', type: 'text', autocomplete: 'off',
    spellcheck: 'false', maxlength: '36' });
  const providerInput = element('input', undefined, { id: 'extensions-bind-provider', type: 'text', autocomplete: 'off',
    spellcheck: 'false', maxlength: '128' });
  const installationSelect = element('select', undefined, { id: 'extensions-bind-installation' });
  const keyCompute = element('button', 'slot key 계산', { type: 'button', 'data-act': 'slot-key' });
  const keyView = element('p', MESSAGES.noKey, { 'data-view': 'slot-key' });
  const qualificationRefView = element('p', MESSAGES.noQualification, { 'data-view': 'bind-qualification' });
  const bindButton = element('button', '계산한 slot에 바인딩', { type: 'button', 'data-act': 'bind' });
  bindForm.append(element('p', MESSAGES.bindFormIntro),
    element('label', 'slot ID(binding_slot_id)', { for: 'extensions-bind-slot-id' }), slotIdInput,
    element('label', '목적(purpose)', { for: 'extensions-bind-purpose' }), purposeInput,
    element('label', '대상 환경 ID(선택)', { for: 'extensions-bind-environment' }), environmentInput,
    element('label', '제공자 ID(provider_id)', { for: 'extensions-bind-provider' }), providerInput,
    keyCompute, keyView,
    element('label', '검증된 설치', { for: 'extensions-bind-installation' }), installationSelect,
    qualificationRefView, bindButton);
  bindingSection.append(slotList, slotMore, element('label', 'slot key digest', { for: 'extensions-slot-digest' }),
    slotInput, slotRead, slotView, element('h4', '새 바인딩'), bindForm);

  const stagingSection = section('staging', '운영자 배치(staging) 인계', MESSAGES.stagingIntro);

  root.replaceChildren(element('h2', '확장', { id: 'settings-extensions-title' }), element('p', MESSAGES.intro), line,
    supplySection, inventorySection, candidateSection, installationSection, conformanceSection, qualificationSection,
    bindingSection, stagingSection);

  function say(message, code) {
    line.textContent = message;
    line.dataset.state = code;
  }

  function refused(error) {
    if (error?.binding === true && Object.hasOwn(BINDING_ERRORS, error?.code)) {
      say(BINDING_ERRORS[error.code], error.code);
      return error.code;
    }
    const code = Object.hasOwn(ERRORS, error?.code) ? error.code : 'unavailable';
    say(ERRORS[code], code);
    return code;
  }

  async function call(method, path, { json, bytes, absolute = false, binding = false } = {}) {
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
      response = await fetch(absolute ? path : `${api}${path}`, options);
    } catch {
      throw Object.assign(new Error('refused'), { code: 'unavailable', unanswered: true, binding });
    }
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    if (!response.ok) {
      const known = Object.hasOwn(ERRORS, payload?.code) || (binding && Object.hasOwn(BINDING_ERRORS, payload?.code));
      throw Object.assign(new Error('refused'), { status: response.status, unanswered: response.status >= 500, binding,
        code: known ? payload.code : ({ 400: 'invalid_input', 401: 'unauthenticated',
          403: 'access_denied', 404: 'not_found', 409: 'conflict', 413: 'too_large', 429: 'capacity' }[response.status] ?? 'unavailable') });
    }
    if (!isObject(payload)) throw Object.assign(new Error('refused'), { code: 'unavailable', unanswered: true });
    return { status: response.status, payload };
  }

  function button(label, act, onClick, attributes = {}) {
    const node = element('button', label, { type: 'button', 'data-act': act, ...attributes });
    node.addEventListener('click', () => quiet(onClick()));
    return node;
  }

  function drawInventory() {
    candidateList.replaceChildren(...state.candidates.map(row => {
      const item = element('li', `${row.extension_id} ${row.extension_version} · ${row.extension_kind} · ${row.port_contract_version} · 신뢰 등급 ${row.trust_tier ?? NOT_SUPPLIED}(포트 계약 기준) · ${row.candidate_id}`,
        { 'data-candidate-row': row.candidate_id });
      item.append(button('이 후보 읽기', 'candidate-row-read', () => readCandidate(row.candidate_id)));
      return item;
    }));
    if (state.candidates.length === 0) candidateList.append(element('li', '등록된 후보 없음'));
    candidateMore.setAttribute('aria-disabled', state.candidatesNext === null ? 'true' : 'false');
    installationList.replaceChildren(...state.installations.map(row => {
      const block = element('div', undefined, { 'data-installation-row': row.installation_id });
      block.append(facts(installationRowFacts(row), `설치 ${row.installation_id}`));
      const request = state.requests[row.installation_id];
      block.append(element('p', request === undefined ? '' : MESSAGES.requestRead(request), { 'data-view': 'request-state' }));
      if (typeof row.staging?.request_link === 'string') {
        block.append(button('배포 요청 상태 읽기', 'request-read', () => readRequest(row)));
      }
      return block;
    }));
    if (state.installations.length === 0) installationList.append(element('p', '설치 없음'));
    installationMore.setAttribute('aria-disabled', state.installationsNext === null ? 'true' : 'false');
    const verified = state.installations.filter(row => row.state === 'verified');
    const selected = installationSelect.value;
    installationSelect.replaceChildren(...verified.map(row => element('option',
      `${row.extension_id} ${row.extension_version ?? ''} · ${row.installation_id}`, { value: row.extension_id })));
    if (verified.some(row => row.extension_id === selected)) installationSelect.value = selected;
    else if (verified.length > 0) installationSelect.value = verified[0].extension_id;
    else installationSelect.value = '';
  }

  function drawBinding() {
    slotList.replaceChildren(...state.slots.map(row => {
      const item = element('li', `${row.logical_slot.binding_slot_id} · ${row.logical_slot.port_contract_version} · ${row.logical_slot.purpose} · ${row.extension_id} · ${headText(row.head)} · 보존중 ${row.retained_rollback_count} · ${row.binding_slot_key_digest}`,
        { 'data-slot-row': row.binding_slot_key_digest });
      item.append(button('이 slot 읽기', 'slot-row-read', () => readSlot(row.binding_slot_key_digest)));
      return item;
    }));
    if (state.slots.length === 0) slotList.append(element('li', '바인딩 slot 없음'));
    slotMore.setAttribute('aria-disabled', state.slotsNext === null ? 'true' : 'false');
    const slot = state.slot;
    slotView.dataset.slot = slot?.binding_slot_key_digest ?? '';
    slotView.dataset.head = slot === null ? '' : `${slot.head.revision}:${slot.head.state}`;
    if (slot === null) {
      slotView.replaceChildren();
    } else {
      const history = element('ol', undefined, { 'aria-label': '변경 불가 바인딩 이력', 'data-view': 'history' });
      for (const row of slot.history) {
        history.append(element('li', `수정본 ${row.revision} · ${row.action} · ${row.state} · ${row.extension_id} · 설치 ${installRefText(row.target_installation_ref)} · 검증 ${refText(row.qualification_ref)} · 이전 ${revisionRefText(row.previous_ref)} · 교체 ${revisionRefText(row.supersedes_ref)} · 롤백 대상 ${revisionRefText(row.rollback_of_ref)} · ${row.binding_record_digest}`,
          { 'data-revision': String(row.revision), 'data-state': row.state }));
      }
      const retentions = element('ul', undefined, { 'aria-label': '롤백 보존', 'data-view': 'retentions' });
      for (const row of slot.rollback_retentions) {
        const state_ = row.retention_head.state;
        const item = element('li', `대상 수정본 ${row.target_binding_revision_ref.revision} (${row.target_extension_id}) · ${RETENTION_STATES[state_] ?? state_} · 보존 수정본 ${row.retention_head.revision} · ${row.qualification_current ? '검증 현재' : '검증 현재 아님'}`,
          { 'data-retention-target': String(row.target_binding_revision_ref.revision), 'data-state': state_ });
        if (state_ === 'retained') {
          item.append(button('이 수정본으로 롤백', 'rollback', () => rollback(row)),
            button('롤백 보존 해제…', 'release-start', async () => { state.releasing = row; draw(); }));
        }
        retentions.append(item);
      }
      const nodes = [facts(slotFacts(slot), 'slot 내용'), element('h4', '이력'), history, element('h4', '롤백 보존'), retentions];
      if (slot.rollback_retentions.length === 0) nodes.push(element('p', '롤백 보존 없음'));
      if (slot.head.state === 'active') nodes.push(button('이 slot 비활성화', 'disable', () => disable()));
      const releasing = state.releasing;
      if (releasing !== null) {
        const confirm = element('div', undefined, { 'data-view': 'release-confirm', role: 'group', 'aria-label': '롤백 보존 해제 확인' });
        const reason = element('input', undefined, { id: 'extensions-release-reason', type: 'text', maxlength: '500', autocomplete: 'off' });
        confirm.append(element('p', MESSAGES.releaseConfirm),
          element('p', releasing.release_warning ?? NOT_SUPPLIED, { 'data-view': 'release-warning' }),
          element('p', `현재 바인딩: ${headText(slot.head)}`),
          element('label', '해제 사유', { for: 'extensions-release-reason' }), reason,
          button('보존 해제 확인', 'release-confirm', () => release(releasing, reason.value)),
          button('취소', 'release-cancel', async () => { state.releasing = null; draw(); }));
        nodes.push(confirm);
      }
      slotView.replaceChildren(...nodes);
    }
    const key = state.key;
    keyView.textContent = key === null ? MESSAGES.noKey
      : `slot key ${JSON.stringify(key.binding_slot_key)} · digest ${key.binding_slot_key_digest} · 현재 헤드 ${headText(key.current_binding_head)}`;
    keyView.dataset.digest = key?.binding_slot_key_digest ?? '';
    const ref = qualificationRef();
    qualificationRefView.textContent = ref === null ? MESSAGES.noQualification : `검증 기록 ${refText(ref)}`;
    bindButton.setAttribute('aria-disabled', key === null || ref === null || installationSelect.value === '' ? 'true' : 'false');
    if (providerInput.value === '' && typeof state.qualification?.provider === 'string') providerInput.value = state.qualification.provider;
  }

  function qualificationRef() {
    const ref = state.qualification?.qualification?.qualification_ref;
    return isObject(ref) ? ref : null;
  }

  function draw() {
    drawInventory();
    drawBinding();
    candidateView.replaceChildren(...(state.candidate === null ? [] : [facts(candidateFacts(state.candidate, {
      summary: state.candidates.find(row => row.candidate_id === state.candidate?.candidate_ref?.candidate_id) ?? null,
      installations: state.inventoryRead === true ? state.installations : null,
    }), '후보 내용')]));
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
  const quiet = promise => promise.catch(() => {});

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
        // the list is read again so the new candidate's row (with its trust tier) is shown; the
        // registration stands even if this read fails
        try { await readPage('candidates', false); } catch { /* read again with the next list read */ }
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

  async function readPage(kind, append) {
    const cursor = { candidates: 'candidatesNext', installations: 'installationsNext', bindings: 'slotsNext' }[kind];
    const list = { candidates: 'candidates', installations: 'installations', bindings: 'slots' }[kind];
    const after = append ? state[cursor] : null;
    const { payload } = await call('GET', `/${kind}?limit=${PAGE_LIMIT}${after === null ? '' : `&after=${after}`}`,
      { binding: kind !== 'candidates' });
    if (!Array.isArray(payload.items)) throw Object.assign(new Error('refused'), { code: 'unavailable' });
    state[list] = append ? [...state[list], ...payload.items] : payload.items;
    state[cursor] = typeof payload.next_after === 'string' ? payload.next_after : null;
    return payload;
  }

  // the inventory read: the candidate, installation and binding-slot lists (first pages)
  async function loadInventory() {
    return guarded(async () => {
      await readPage('candidates', false);
      await readPage('installations', false);
      await readPage('bindings', false);
      state.inventoryRead = true;
      say(MESSAGES.loaded, 'loaded');
    });
  }

  async function more(kind) {
    return guarded(async () => {
      const cursor = { candidates: 'candidatesNext', installations: 'installationsNext', bindings: 'slotsNext' }[kind];
      if (state[cursor] === null) throw local(MESSAGES.loaded);
      await readPage(kind, true);
      say(MESSAGES.loaded, 'read');
    });
  }

  async function readRequest(row) {
    return guarded(async () => {
      const { payload } = await call('GET', row.staging.request_link, { absolute: true });
      state.requests[row.installation_id] = text(payload.state);
      say(MESSAGES.loaded, 'read');
      return payload;
    });
  }

  async function readSlot(digest) {
    return guarded(async () => {
      if (!HEX64.test(digest ?? '')) throw local(MESSAGES.noSlot);
      const { payload } = await call('GET', `/bindings/${digest}`, { binding: true });
      slotFacts(payload);
      if (state.slot?.binding_slot_key_digest !== payload.binding_slot_key_digest) state.releasing = null;
      state.slot = payload;
      if (state.releasing !== null) {
        state.releasing = payload.rollback_retentions.find(row => row.retention_head.state === 'retained'
          && row.target_binding_revision_ref.binding_record_digest
            === state.releasing.target_binding_revision_ref.binding_record_digest) ?? null;
      }
      slotInput.value = digest;
      say(MESSAGES.loaded, 'read');
      return payload;
    });
  }

  // one owner act: the same act (same key) after an unread answer resends the same body; any
  // other outcome forgets it. The slot and lists are read again after a success.
  async function act(name, path, build, done) {
    return guarded(async () => {
      let body = unanswered.act?.name === name ? unanswered.act.body : null;
      if (body === null) {
        try { body = build(randomUUID()); } catch (error) { throw local(error.message); }
      }
      say(MESSAGES.working, 'working');
      let payload;
      try {
        ({ payload } = await call('POST', path, { json: body, binding: true }));
        unanswered.act = null;
      } catch (error) {
        unanswered.act = error?.unanswered === true ? { name, body } : null;
        throw error;
      }
      const digest = payload.binding_slot_key_digest;
      state.releasing = null;
      state.key = null;
      if (HEX64.test(digest ?? '')) {
        const { payload: slot } = await call('GET', `/bindings/${digest}`, { binding: true });
        state.slot = slot;
        slotInput.value = digest;
      }
      await readPage('bindings', false);
      await readPage('installations', false);
      say(done(payload), payload.state ?? payload.binding_head?.state ?? 'done');
      return payload;
    });
  }

  async function computeKey() {
    return guarded(async () => {
      let body;
      try {
        body = slotKeyRequest({ slotId: String(slotIdInput.value ?? '').trim(), purpose: purposeInput.value,
          environmentId: environmentInput.value, providerId: String(providerInput.value ?? '').trim() });
      } catch (error) { throw local(error.message); }
      const { payload } = await call('POST', '/binding-slot-keys', { json: body, binding: true });
      if (payload.schema_version !== 'extension-binding-slot-key-v1') throw Object.assign(new Error('refused'), { code: 'unavailable' });
      state.key = payload;
      say(MESSAGES.keyComputed(payload.binding_slot_key_digest), 'key');
      return payload;
    });
  }

  const bind = () => act(`bind:${state.key?.binding_slot_key_digest}`, '/bindings',
    id => bindCommand(state.key, installationSelect.value, qualificationRef(), id), value => MESSAGES.bound(value.binding_head));
  const disable = () => act(`disable:${state.slot?.binding_slot_key_digest}:${state.slot?.head?.revision}`,
    `/bindings/${state.slot?.binding_slot_key_digest}/disable`, id => disableCommand(state.slot, id),
    value => MESSAGES.disabledDone(value.binding_head));
  const rollback = row => act(`rollback:${state.slot?.binding_slot_key_digest}:${row.target_binding_revision_ref.binding_record_digest}`,
    `/bindings/${state.slot?.binding_slot_key_digest}/rollback`, id => rollbackCommand(state.slot, row, id),
    value => MESSAGES.rolledBack(value.binding_head));
  const release = (row, reason) => act(`release:${state.slot?.binding_slot_key_digest}:${row.target_binding_revision_ref.binding_record_digest}`,
    `/bindings/${state.slot?.binding_slot_key_digest}/rollback-retentions/${row.target_binding_revision_ref.binding_record_digest}/release`,
    id => releaseCommand(state.slot, row, reason, id), value => MESSAGES.released(value.new_retention_revision));

  candidateMore.addEventListener('click', () => quiet(more('candidates')));
  installationMore.addEventListener('click', () => quiet(more('installations')));
  slotMore.addEventListener('click', () => quiet(more('bindings')));
  slotRead.addEventListener('click', () => quiet(readSlot(String(slotInput.value ?? '').trim())));
  keyCompute.addEventListener('click', () => quiet(computeKey()));
  bindButton.addEventListener('click', () => quiet(bind()));
  installationSelect.addEventListener('change', () => draw());
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
    readConformance, runConformance, loadInventory, more, readSlot, readRequest, computeKey, bind, disable,
    rollback, release,
    startRelease(row) { state.releasing = row; draw(); },
    get head() { return state.head === null ? null : structuredClone({ ...state.head }); },
    get slot() { return state.slot === null ? null : structuredClone(state.slot); },
    get key() { return state.key === null ? null : structuredClone(state.key); } });
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
  await panel.loadInventory().catch(() => {});
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
