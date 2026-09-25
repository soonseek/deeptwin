// T023 (FR-002): what DeepTwin has actually read of each retained original, over
// `source-readings-v1`. Storing an original never reads it; this panel reads one only
// when the owner presses `내용 읽기` for it, and then shows exactly how much was read:
// complete, partial (with what was not read) or unreadable (with why). When the reader
// (the isolated document worker, for PDF/DOCX) is not attached or does not answer,
// nothing is recorded and the panel says so; the original stays stored and a retry is
// safe. Nothing is read, sent or inferred implicitly. Server text reaches the DOM through
// textContent only.

const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export const COMMAND_SCHEMA = 'source-reading-command-v1';

export const MESSAGES = Object.freeze({
  intro: '원본을 저장해도 내용은 읽지 않습니다. 자료마다 “내용 읽기”를 누를 때만 이 인스턴스가 글자를 읽고, 얼마나 읽었는지 기록합니다.',
  empty: '저장된 원본이 없습니다.',
  unsaved: '업무를 저장하면 원본마다 읽기 상태가 보입니다.',
  notRead: '아직 읽지 않음',
  reading: '읽는 중…',
  readerMissing: 'PDF·DOCX 읽기 도구가 이 인스턴스에 연결되어 있지 않습니다. 원본은 그대로 보관됩니다.',
  deleted: '원본이 삭제되어 읽을 수 없습니다.',
});

export const STATE_LABELS = Object.freeze({
  complete: '전부 읽음', partial: '일부만 읽음', unreadable: '읽을 수 없음',
});

export const REASON_LABELS = Object.freeze({
  truncated: '길이 한도(약 60,000바이트)까지만 보관했습니다',
  pages_without_text: '글자 층이 없는 쪽이 있습니다(스캔 이미지 등)',
  invalid_encoding: 'UTF-8이 아닌 바이트가 있어 그 부분은 읽지 못했습니다',
  unsupported_format: '이 형식은 읽을 수 없습니다(텍스트·PDF·DOCX만 읽습니다)',
  corrupt: '문서를 열지 못했습니다(손상되었거나 형식이 다릅니다)',
  too_large: '읽기 도구의 한도를 넘는 문서입니다',
  no_text: '읽을 글자가 없습니다',
  deleted: '원본이 삭제되었습니다',
});

export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '요청 형식이 맞지 않습니다.',
  unauthenticated: '브라우저 세션이 없습니다. 시작 화면에서 다시 로그인해 주세요.',
  access_denied: '세션 확인에 실패했습니다. 화면을 다시 열어 주세요.',
  not_found: '이 업무의 현재 수정본에서 그 원본을 찾지 못했습니다. 화면을 다시 열어 주세요.',
  conflict: '이 읽기 명령은 이미 다른 대상으로 처리되었습니다. 다시 누르면 새 명령으로 읽습니다.',
  reader_unavailable: '읽기 도구가 응답하지 않아 아무것도 기록하지 않았습니다. 원본은 그대로 보관되며 다시 시도할 수 있습니다.',
  capacity: '기록 한도에 도달했습니다.',
  unavailable: '처리하지 못했습니다. 원본은 그대로 보관됩니다.',
});

function fail(message) {
  throw new Error(message);
}

export function readingSummary(reading) {
  if (reading === null || reading === undefined) return MESSAGES.notRead;
  const label = STATE_LABELS[reading.state] ?? '상태 미확인';
  const reasons = (Array.isArray(reading.reasons) ? reading.reasons : []).map(code => REASON_LABELS[code] ?? code);
  const pages = Number.isInteger(reading.page_count) ? ` · ${reading.page_count}쪽` : '';
  const kept = reading.state === 'unreadable' ? '' : ` · ${Number(reading.kept_characters).toLocaleString('en-US')}자`;
  return `${label}${pages}${kept}${reasons.length ? ` — ${reasons.join(' · ')}` : ''}`;
}

export function createSourceReadings({ root, document, request, crypto, basePath = '/', workId, onChange = () => {} } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  if (typeof crypto?.randomUUID !== 'function') fail('a UUID source is required');
  if (typeof workId !== 'function' || typeof onChange !== 'function') fail('a work reader is required');
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const api = `${basePath.slice(0, -1)}/api/v1/source-readings`;
  let listing = null;
  let generation = 0;  // the latest load wins: an older answer arriving late is dropped
  const busy = new Set();

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', '', { role: 'status', 'aria-live': 'polite' });
  const list = element('ul', undefined, { class: 'reading-list', 'aria-label': '원본 읽기 상태' });
  root.replaceChildren(element('h2', '자료 읽기'), element('p', MESSAGES.intro), status, list);

  function say(text, code) {
    status.textContent = text;
    status.dataset.state = code;
  }

  function failed(error) {
    // the session's closed partition keeps the envelope's exact reason beside its code
    const named = Object.hasOwn(ERROR_MESSAGES, error?.reason) ? error.reason : error?.code;
    const code = Object.hasOwn(ERROR_MESSAGES, named) ? named : 'unavailable';
    say(ERROR_MESSAGES[code], code);
  }

  function render() {
    if (listing === null) {
      list.replaceChildren(element('li', MESSAGES.unsaved));
      return;
    }
    if (!listing.sources.length) {
      list.replaceChildren(element('li', MESSAGES.empty));
      return;
    }
    const rows = listing.sources.map(entry => {
      const row = element('li', undefined, { 'data-source-id': entry.source_id,
        'data-reading-state': entry.reading?.state ?? 'not_read' });
      row.append(element('span', entry.name, { class: 'original-name' }),
        element('span', entry.original_state === 'deleted' && entry.reading === null ? MESSAGES.deleted : readingSummary(entry.reading),
          { class: 'reading-state' }));
      if (entry.reading && entry.reading.state !== 'unreadable' && entry.reading.excerpt) {
        const detail = element('details');
        detail.append(element('summary', '읽힌 글자 앞부분'), element('p', entry.reading.excerpt, { class: 'reading-excerpt' }));
        row.append(detail);
      }
      if (entry.original_state !== 'deleted') {
        const button = element('button', busy.has(entry.source_id) ? MESSAGES.reading : (entry.reading ? '다시 읽기' : '내용 읽기'),
          { type: 'button', 'aria-label': `${entry.name} ${entry.reading ? '다시 읽기' : '내용 읽기'}` });
        if (busy.has(entry.source_id)) button.disabled = true;
        button.addEventListener('click', () => readNow(entry));
        row.append(button);
      }
      return row;
    });
    list.replaceChildren(...rows);
  }

  async function load({ announce = true } = {}) {
    const id = workId();
    if (typeof id !== 'string' || !UUID.test(id)) {
      listing = null;
      render();
      return null;
    }
    const mine = ++generation;
    try {
      const value = await request(`${api}/${id}`, {});
      if (mine !== generation) return listing;
      listing = value;
      if (announce && listing.reader_attached === false && listing.sources.length) say(MESSAGES.readerMissing, 'reader_missing');
    } catch (error) {
      if (mine !== generation) return listing;
      failed(error);
    }
    render();
    return listing;
  }

  async function readNow(entry) {
    const id = workId();
    if (busy.has(entry.source_id) || typeof id !== 'string' || !UUID.test(id)) return;
    busy.add(entry.source_id);
    say(MESSAGES.reading, 'reading');
    render();
    try {
      const reading = await request(`${api}/${id}`, { method: 'POST', body: {
        schema_version: COMMAND_SCHEMA, command_id: crypto.randomUUID(), source_ref: entry.source_ref } });
      say(`${entry.name}: ${readingSummary(reading)}`, reading.state);
    } catch (error) {
      failed(error);
    } finally {
      busy.delete(entry.source_id);
    }
    await load({ announce: false });
    onChange(listing);
  }

  return Object.freeze({ load, get listing() { return listing; } });
}
