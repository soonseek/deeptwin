// T066: the versions page's boot — the supported session from the owner's cookie,
// then the versions panel; without a session it says so and mounts nothing.

import { basePathFrom, createSupportedSession } from './session.mjs';
import { createVersionsPanel } from './versions.mjs';

export async function boot({ document, location, fetch, crypto } = {}) {
  const status = document.getElementById('session-status');
  const root = document.getElementById('versions');
  if (status === null || root === null) throw new Error('the page has no mounts');
  const basePath = basePathFrom(location.pathname);
  const session = createSupportedSession({ fetch, basePath });
  try {
    await session.establish();
  } catch (error) {
    status.dataset.state = error?.code ?? 'unavailable';
    status.textContent = error?.code === 'unauthenticated'
      ? '소유자 세션이 없습니다. 시작 화면(./)에서 로그인한 뒤 다시 열어 주세요.' : '세션을 확인하지 못했습니다.';
    return null;
  }
  status.dataset.state = 'authenticated';
  status.textContent = '브라우저 세션이 연결되어 있습니다.';
  const panel = createVersionsPanel({ root, document, request: session.request, basePath, crypto });
  await panel.load().catch(() => {});
  return panel;
}

if (typeof globalThis.document === 'object' && globalThis.document?.getElementById?.('versions')) {
  boot({ document: globalThis.document, location: globalThis.location, crypto: globalThis.crypto,
    fetch: (...args) => globalThis.fetch(...args) }).catch(() => {});
}
