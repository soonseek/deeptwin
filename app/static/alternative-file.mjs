// T053 (US4): answer a run artifact with the owner's own file, and — when only part
// of the original is answered — say which part with a formal selector on the
// exact original: a region of an image, a region of a PDF page, a JSON pointer, or
// a span of time. Regions are entered as percentages and sent as integer basis
// points of the page or image. The server computes no semantic alignment between
// the original and the file, so every selector is stored `unresolved`; this form
// says so plainly instead of implying the two are aligned. A format with no formal
// selector is answered whole, and "whole" is claimed only when the owner ticks that
// they reviewed the whole original. Nothing here reads or renders the file.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
export const FILE_SCHEMA = 'alternative-file-v1';
export const MAX_FILE_BYTES = 4 * 1024 * 1024;
export const REGION_SCALE = 10_000;
const MEDIA = /^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}\/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$/;

export const MESSAGES = Object.freeze({
  intro: '원본을 고친 내 파일을 올립니다. 원본은 그대로 남습니다. 이유를 적지 않아도 됩니다.',
  alignment: '원본과 내 파일 사이의 의미 정렬은 계산하지 않습니다. 선택한 영역은 원본 위의 위치로만 기록되고 정렬은 "미정"으로 남습니다.',
  wholeOnly: '이 형식은 부분 선택을 지원하지 않습니다. 원본 전체를 검토했을 때만 올릴 수 있습니다.',
  textHint: '텍스트·표는 "내 버전 편집"으로 바꾼 줄·칸을 기록할 수 있습니다. 여기서는 전체로만 올립니다.',
  whole: '원본 전체를 검토했습니다.',
  needSelector: '고친 부분을 하나 이상 지정하거나 전체 검토를 선택하세요.',
  noFile: '올릴 파일을 선택하세요.',
  tooLarge: '파일은 4 MiB까지 올릴 수 있습니다.',
  sending: '올리는 중…',
});

export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '이 파일이나 선택 영역을 받을 수 없습니다(원본과 같은 파일·빈 파일·형식에 맞지 않는 선택 영역).',
  unauthenticated: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다.',
  not_found: '산출물을 찾지 못했습니다.',
  conflict: '같은 요청으로 다른 파일이 이미 기록되었습니다.',
  too_large: MESSAGES.tooLarge,
  unavailable: '저장소에 연결하지 못했습니다.',
});

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

// the selector kinds a format can bind (app/services/alternative_drafts.py REGION_KINDS)
export function selectorKind(mediaType) {
  if (mediaType === 'application/pdf') return 'page_region';
  if (mediaType === 'application/json') return 'structured_path';
  if (typeof mediaType === 'string' && mediaType.startsWith('image/')) return 'image_region';
  if (typeof mediaType === 'string' && (mediaType.startsWith('audio/') || mediaType.startsWith('video/'))) return 'time_range';
  return null;
}

function points(percent, label) {
  const value = Number(percent);
  if (!Number.isFinite(value) || value < 0 || value > 100) fail(`${label} must be between 0 and 100`);
  return Math.round(value * (REGION_SCALE / 100));
}

// one formal selector from the owner's typed fields, validated before it is sent
export function selectorFrom(kind, fields) {
  if (kind === 'image_region' || kind === 'page_region') {
    const locator = { x: points(fields.x, 'x'), y: points(fields.y, 'y'),
      width: points(fields.width, 'width'), height: points(fields.height, 'height') };
    if (locator.width <= 0 || locator.height <= 0 || locator.x + locator.width > REGION_SCALE
        || locator.y + locator.height > REGION_SCALE) fail('the region leaves the original');
    if (kind === 'page_region') {
      const page = Number(fields.page);
      if (!Number.isInteger(page) || page < 1 || page > 10_000) fail('the page is out of range');
      locator.page = page;
    }
    return { kind, locator };
  }
  if (kind === 'structured_path') {
    const pointer = String(fields.pointer ?? '');
    if (pointer.length > 1024 || !/^(\/([^~/]|~[01])*)*$/.test(pointer)) fail('the JSON pointer is invalid');
    return { kind, locator: { pointer } };
  }
  if (kind === 'time_range') {
    const start = Math.round(Number(fields.start) * 1000);
    const end = Math.round(Number(fields.end) * 1000);
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > 86_400_000) {
      fail('the time range is invalid');
    }
    return { kind, locator: { start_ms: start, end_ms: end } };
  }
  fail('this format has no formal selector');
}

export function selectorText(selector) {
  const pct = value => `${(value / 100).toFixed(2)}%`;
  const { kind, locator } = selector;
  if (kind === 'image_region') return `이미지 영역 x ${pct(locator.x)}, y ${pct(locator.y)}, 너비 ${pct(locator.width)}, 높이 ${pct(locator.height)}`;
  if (kind === 'page_region') return `${locator.page}쪽 영역 x ${pct(locator.x)}, y ${pct(locator.y)}, 너비 ${pct(locator.width)}, 높이 ${pct(locator.height)}`;
  if (kind === 'structured_path') return `JSON 위치 ${locator.pointer || '(전체 문서)'}`;
  return `${(locator.start_ms / 1000).toFixed(3)}초–${(locator.end_ms / 1000).toFixed(3)}초`;
}

function base64(bytes) {
  let binary = '';
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  }
  return btoa(binary);
}

const FIELDS = Object.freeze({
  image_region: [['x', 'x (%)'], ['y', 'y (%)'], ['width', '너비 (%)'], ['height', '높이 (%)']],
  page_region: [['page', '쪽'], ['x', 'x (%)'], ['y', 'y (%)'], ['width', '너비 (%)'], ['height', '높이 (%)']],
  structured_path: [['pointer', 'JSON 위치 (예: /items/0/title)']],
  time_range: [['start', '시작 (초)'], ['end', '끝 (초)']],
});

export function createAlternativeFileForm({ root, document, request, basePath = '/', crypto, onFrozen } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  if (typeof crypto?.randomUUID !== 'function') fail('a crypto with randomUUID is required');
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const runs = `${basePath.slice(0, -1)}/api/v1/runs`;
  let target = null;
  let selectors = [];

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', '', { role: 'status', 'aria-live': 'polite' });
  const body = element('div');
  root.replaceChildren(element('h2', '대안 파일'), status, body);

  function say(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  function open(runId, artifact) {
    if (typeof runId !== 'string' || !UUID.test(runId) || !UUID.test(artifact?.artifactId ?? '')) fail('an artifact is required');
    const kind = selectorKind(artifact.mediaType);
    target = { runId, artifactId: artifact.artifactId, kind, mediaType: artifact.mediaType };
    selectors = [];
    const file = element('input', undefined, { type: 'file', 'aria-label': '내 파일 선택' });
    const whole = element('input', undefined, { type: 'checkbox', id: 'alternative-file-whole' });
    whole.checked = false;
    const parts = [element('p', MESSAGES.intro), element('p', MESSAGES.alignment), file];
    const chosen = element('ul', undefined, { 'aria-label': '지정한 부분' });
    if (kind === null) {
      const text = ['text/plain', 'text/markdown', 'text/csv'].includes(artifact.mediaType) ? MESSAGES.textHint : MESSAGES.wholeOnly;
      parts.push(element('p', text));
    } else {
      const inputs = {};
      const fieldset = element('fieldset');
      fieldset.append(element('legend', '고친 부분 지정'));
      for (const [name, label] of FIELDS[kind]) {
        const id = `alternative-file-${name}`;
        inputs[name] = element('input', undefined, { id, type: name === 'pointer' ? 'text' : 'number', step: 'any' });
        fieldset.append(element('label', label, { for: id }), inputs[name]);
      }
      const add = element('button', '이 부분 추가', { type: 'button' });
      add.addEventListener('click', () => {
        try {
          const selector = selectorFrom(kind, Object.fromEntries(Object.entries(inputs).map(([key, node]) => [key, node.value])));
          selectors.push(selector);
          chosen.append(element('li', selectorText(selector)));
          say(`지정한 부분 ${selectors.length}곳`, 'selected');
        } catch (error) {
          say(`선택 영역을 확인해 주세요: ${error.message}`, 'invalid_input');
        }
      });
      fieldset.append(add);
      parts.push(fieldset, chosen);
    }
    const send = element('button', '내 버전으로 기록', { type: 'button' });
    send.addEventListener('click', () => submit(file, whole.checked === true).catch(() => {}));
    parts.push(whole, element('label', MESSAGES.whole, { for: 'alternative-file-whole' }), send);
    body.replaceChildren(...parts);
    say('', 'open');
    return target;
  }

  async function submit(fileInput, reviewedWhole) {
    if (target === null) fail('no artifact is open');
    const picked = fileInput?.files?.[0];
    if (!picked) { say(MESSAGES.noFile, 'invalid_input'); return null; }
    if (picked.size > MAX_FILE_BYTES) { say(MESSAGES.tooLarge, 'too_large'); return null; }
    if (!reviewedWhole && (target.kind === null || selectors.length === 0)) {
      say(target.kind === null ? MESSAGES.wholeOnly : MESSAGES.needSelector, 'invalid_input');
      return null;
    }
    const media = MEDIA.test(picked.type ?? '') ? picked.type : 'application/octet-stream';
    const bytes = new Uint8Array(await picked.arrayBuffer());
    say(MESSAGES.sending, 'sending');
    try {
      const frozen = await request(`${runs}/${target.runId}/artifacts/${target.artifactId}/alternative-files`, {
        method: 'POST', body: { schema_version: FILE_SCHEMA, command_id: crypto.randomUUID(), media_type: media,
          name: String(picked.name || 'alternative').slice(0, 255).replace(/[\\/\u0000]/g, '_'),
          content_b64: base64(bytes), selectors: reviewedWhole ? [] : selectors, reviewed_whole: reviewedWhole } });
      const scope = frozen.coverage === 'whole' ? '원본 전체에 대한 내 버전으로 기록했습니다.'
        : `지정한 ${frozen.selectors.length}곳을 내 근거로 기록했습니다. 나머지는 검토하지 않은 영역입니다.`;
      say(`${scope} 정렬은 미정으로 남았습니다.`, 'frozen');
      if (typeof onFrozen === 'function') {
        Promise.resolve(onFrozen(target.runId, target.artifactId, frozen.alternative_ref.id)).catch(() => {});
      }
      return frozen;
    } catch (error) {
      const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
      say(ERROR_MESSAGES[code], code);
      throw error;
    }
  }

  return Object.freeze({ open, submit, get selectors() { return [...selectors]; } });
}
