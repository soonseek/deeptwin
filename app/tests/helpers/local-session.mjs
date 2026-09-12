export async function mintLaunchURL(baseURL) {
  // The route name is a frozen pre-release test wire. This creates only the
  // superseded loopback bootstrap, not T025's offline first-owner capability.
  const response = await fetch(`${baseURL}/__test__/launch`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`Test deployment-bootstrap endpoint failed (${response.status})`);
  const value = await response.json();
  if (typeof value.capability !== 'string' || value.capability.length < 32) {
    throw new Error('Test development bootstrap returned an invalid capability');
  }
  return `${baseURL}/#bootstrap=${encodeURIComponent(value.capability)}`;
}

export function localContextOptions(options = {}) {
  // Chromium owns Fetch Metadata headers.  Overriding Sec-Fetch-Site at the
  // browser-context level makes module/resource requests fail with
  // ERR_INVALID_ARGUMENT instead of exercising the real renderer boundary.
  return { ...options };
}

export function localGet(page, path, options = {}) {
  // APIRequestContext is not a renderer and therefore does not synthesize Fetch
  // Metadata.  Browser tests that inspect server state supply the exact header
  // explicitly; application fetches continue to use Chromium's native value.
  return page.request.get(path, {
    ...options,
    headers: {
      ...(options.headers || {}),
      'Sec-Fetch-Site': 'same-origin',
    },
  });
}

export async function localRouteFetch(route, options = {}) {
  // route.fetch() leaves Chromium's renderer and uses Playwright's request
  // client, which does not synthesize Fetch Metadata.  Preserve the intercepted
  // request (cookie, CSRF and body included) and restore the transport evidence
  // that the real renderer supplied before the test delayed the response.
  const request = route.request();
  const headers = { ...(await request.allHeaders()), ...(options.headers || {}) };
  headers['sec-fetch-site'] = 'same-origin';
  if (!['GET', 'HEAD'].includes(request.method())) {
    headers.origin = new URL(request.url()).origin;
  }
  return route.fetch({ ...options, headers });
}
