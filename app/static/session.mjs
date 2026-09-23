// T048 (DOM-half prerequisite) / T025: the shell's session client for the
// SUPPORTED factory (app/api/session_routes.py behind app/api/web_boundary.py).
// Pure logic over an injected fetch: the deployment base path is derived from
// the document location (never guessed), the CSRF token comes from
// GET {base}session (bound to the owner cookie the browser already holds), and
// `request` is the adapter the run observer (runtime.mjs) and the approvals
// module need — same-origin credentials, `X-DeepTwin-CSRF` on every non-GET,
// JSON bodies, the closed error partition preserved on thrown errors, and
// paths confined to this deployment's API under its base path. The token
// lives only in this closure: it is never returned, logged or attached to a
// snapshot. The preview's `/api/session/csrf` and root-absolute paths
// (app.mjs) are not this module's; this is the supported path only.

// the fixed session route and header of the supported boundary
export const SESSION_PATH = '/session';
export const CSRF_HEADER = 'X-DeepTwin-CSRF';
// the run routes' partition (app/api/runs.py) plus the session boundary's own
// refusals (app/api/web_boundary.py). A refusal keeps its envelope code; an
// unknown code is labelled by its status, an unknown status is `unavailable`
export const ERROR_CODES = Object.freeze(['invalid_input', 'unauthenticated', 'access_denied', 'not_found',
  'conflict', 'too_large', 'unavailable', 'credentials', 'capacity', 'setup_incomplete', 'setup_unavailable']);
const CODE_BY_STATUS = Object.freeze({
  400: 'invalid_input', 401: 'unauthenticated', 403: 'access_denied', 404: 'not_found',
  409: 'conflict', 413: 'too_large', 429: 'capacity', 503: 'unavailable',
});
const METHODS = Object.freeze(['GET', 'POST']);
const QUERY_KEY = /^[a-z][a-z_]{0,31}$/;

// the deployment base path is "/" (portable) or "/<32 hex>/" (local profile)
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
const LOCATION_BASE = /^\/[0-9a-f]{32}\//;
// one API path under the base: plain segments only, no query, fragment,
// dot segments, empty segments or scheme
const API_SEGMENTS = /^\/api\/v1(?:\/(?!\.{1,2}(?:\/|$))[A-Za-z0-9_.:-]+)+$/;

function fail(message, code = 'invalid_input', status = undefined) {
  throw Object.assign(new Error(message), { code, status });
}

function requireBase(value) {
  if (typeof value !== 'string' || !BASE_PATH.test(value)) fail('base path is not a deployment base path');
  return value.slice(0, -1); // "" or "/<32 hex>"
}

export function basePathFrom(pathname) {
  if (typeof pathname !== 'string' || !pathname.startsWith('/')) fail('the document location is not a path');
  const match = LOCATION_BASE.exec(pathname);
  return match ? match[0] : '/';
}

export function sessionRoutes(basePath = '/') {
  const prefix = requireBase(basePath);
  return Object.freeze({ session: `${prefix}${SESSION_PATH}` });
}

function partition(payload, status) {
  if (ERROR_CODES.includes(payload?.code)) return payload.code;
  return CODE_BY_STATUS[status] ?? 'unavailable';
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

function refusal(payload, status) {
  const message = typeof payload?.message === 'string' ? payload.message : `요청을 완료하지 못했습니다 (${status}).`;
  return Object.assign(new Error(message), { code: partition(payload, status), status });
}

export function createSupportedSession({ fetch, basePath = '/' } = {}) {
  if (typeof fetch !== 'function') fail('an injected fetch function is required');
  const prefix = requireBase(basePath);
  const routes = sessionRoutes(basePath);
  let token = null;

  async function send(path, options) {
    let response;
    try {
      response = await fetch(path, options);
    } catch (error) {
      throw Object.assign(new Error(String(error?.message ?? error)), { code: 'unavailable', status: undefined });
    }
    return response;
  }

  async function establish() {
    token = null;
    const response = await send(routes.session, { method: 'GET', credentials: 'same-origin', headers: {} });
    const payload = await readJson(response);
    if (!response.ok) throw refusal(payload, response.status);
    if (payload?.state !== 'authenticated' || typeof payload.csrf_token !== 'string' || !payload.csrf_token) {
      fail('브라우저 세션 응답을 읽지 못했습니다.', 'unavailable', response.status);
    }
    token = payload.csrf_token;
    return Object.freeze({ state: 'authenticated' });
  }

  function requirePath(path) {
    if (typeof path !== 'string' || !path.startsWith(prefix + '/api/')) fail('path is outside this deployment\'s API');
    if (!API_SEGMENTS.test(path.slice(prefix.length))) fail('path is not a plain API path');
    return path;
  }

  async function request(path, { method = 'GET', body, query } = {}) {
    let target = requirePath(path);
    if (!METHODS.includes(method)) fail('method is not GET or POST');
    if (query !== undefined) {
      // a read may carry a few plain named parameters (an event cursor, a page size), encoded
      // here: never a caller-built query string
      if (method !== 'GET' || typeof query !== 'object' || query === null || Array.isArray(query)) {
        fail('only a read carries query parameters');
      }
      const entries = Object.entries(query);
      if (entries.length > 4 || entries.some(([key, value]) => !QUERY_KEY.test(key)
          || typeof value !== 'string' || value.length < 1 || value.length > 512)) {
        fail('query parameters are out of bounds');
      }
      if (entries.length) target += `?${new URLSearchParams(entries)}`;
    }
    const headers = {};
    const options = { method, credentials: 'same-origin', headers };
    if (method === 'GET') {
      if (body !== undefined) fail('a read carries no body');
    } else {
      if (typeof body !== 'object' || body === null || Array.isArray(body)) fail('a command body must be an object');
      if (token === null) fail('브라우저 세션이 아직 없습니다.', 'unauthenticated');
      headers[CSRF_HEADER] = token;
      headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    const response = await send(target, options);
    const payload = await readJson(response);
    if (!response.ok) {
      // 401: the cookie no longer stands. 403 on a command: the token no longer matches the
      // cookie (the owner logged in again elsewhere and the session rotated) — reads still
      // pass, so only re-establishing repairs it; a 403 on a read is an origin/host refusal
      if (response.status === 401 || (method !== 'GET' && response.status === 403)) token = null;
      throw refusal(payload, response.status);
    }
    if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
      fail('서버 응답을 읽지 못했습니다.', 'unavailable', response.status);
    }
    return payload;
  }

  async function uploadSource(path, input = {}) {
    const target = requirePath(path);
    const uuid = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
    const validId = value => typeof value === 'string' && new RegExp(`^${uuid}$`).test(value)
      && value !== '00000000-0000-0000-0000-000000000000';
    const route = new RegExp(`^/api/v1/works/(${uuid})/sources$`).exec(target.slice(prefix.length));
    if (!route || !validId(route[1]) || typeof input !== 'object' || input === null
        || Object.keys(input).some(key => !['metadata', 'bytes', 'signal'].includes(key))) fail('invalid source upload');
    const { metadata: m, bytes, signal } = input;
    const fields = ['schema_version', 'command_id', 'expected_revision', 'name', 'declared_media_type', 'size', 'sha256'];
    if (!m || Object.keys(m).length !== fields.length || fields.some(key => !Object.hasOwn(m, key))
        || m.schema_version !== 'owner-source-upload-v1' || !validId(m.command_id)
        || !Number.isSafeInteger(m.expected_revision) || m.expected_revision < 1
        || typeof m.name !== 'string' || !m.name || new TextEncoder().encode(m.name).length > 255
        || ['.', '..'].includes(m.name) || /[\/\\\p{Cc}\p{Cf}\p{Cs}]/u.test(m.name)
        || typeof m.declared_media_type !== 'string' || m.declared_media_type.length > 127
        || !/^[a-z0-9][a-z0-9!#$&^_.+\-]*\/[a-z0-9][a-z0-9!#$&^_.+\-]*$/.test(m.declared_media_type)
        || !Number.isSafeInteger(m.size) || m.size < 0 || m.size > 10485760
        || typeof m.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(m.sha256)
        || !(bytes instanceof Uint8Array) || bytes.byteLength !== m.size
        || (signal !== undefined && !(signal instanceof AbortSignal))) fail('invalid source metadata or bytes');
    const encoded = new TextEncoder().encode(JSON.stringify(m));
    if (encoded.length > 1536) fail('source metadata is too large');
    const header = btoa(String.fromCharCode(...encoded)).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
    if (header.length > 2048) fail('source metadata is too large');
    if (token === null) fail('브라우저 세션이 아직 없습니다.', 'unauthenticated');
    const response = await send(target, { method: 'POST', credentials: 'same-origin', signal,
      headers: { [CSRF_HEADER]: token, 'Content-Type': 'application/octet-stream', 'X-DeepTwin-Source-Metadata': header },
      body: bytes });
    const payload = await readJson(response);
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) token = null;
      throw refusal(payload, response.status);
    }
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) fail('서버 응답을 읽지 못했습니다.', 'unavailable', response.status);
    return payload;
  }

  return Object.freeze({
    establish,
    request,
    uploadSource,
    snapshot() {
      return Object.freeze({ established: token !== null, basePath });
    },
    // the account panel's session commands (password change, revoke-others) carry the same
    // CSRF value; a password change rotates the session, and its answer's value is adopted
    csrfToken() {
      if (token === null) fail('브라우저 세션이 아직 없습니다.', 'unauthenticated');
      return token;
    },
    adopt(next) {
      if (typeof next !== 'string' || next.length < 16 || next.length > 256) fail('the rotated CSRF value is malformed', 'unavailable');
      token = next;
    },
  });
}
