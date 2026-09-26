// The app shell every signed-in page mounts (docs/ui/2026-09-26-product-ux-redesign.md §3):
// one left navigation — 업무, 실행, 버전·실험, 기록, then 설정 — with the current page marked
// `aria-current="page"`, and one context bar above the page for the current work, the
// environment version and the mode badge (운영 / 설계 검토 / 격리 실험 / 과거 기록,
// experience.md §4). A page fills the bar only with what it actually knows; with nothing
// known the bar is hidden, and an unknown mode is never shown. Below 1024px the navigation
// folds behind a menu button: it opens as a drawer, the rest of the page is inert while it
// is open, Escape or the close button shuts it and focus returns to the menu button. The
// start screen (setup and login) stays outside the shell. Links are relative, so the shell
// works under the instance's random base path. Text goes in through textContent only.

export const SHELL_ITEMS = Object.freeze([
  Object.freeze({ id: 'work', href: './work.html', label: '업무', icon: 'work' }),
  Object.freeze({ id: 'observe', href: './observe.html', label: '실행', icon: 'observe' }),
  Object.freeze({ id: 'versions', href: './versions.html', label: '버전·실험', icon: 'versions' }),
  Object.freeze({ id: 'records', href: './records.html', label: '기록', icon: 'records' }),
]);
export const SHELL_SECONDARY = Object.freeze([
  Object.freeze({ id: 'settings', href: './settings.html', label: '설정', icon: 'settings' }),
]);
export const SHELL_PAGES = Object.freeze([...SHELL_ITEMS, ...SHELL_SECONDARY].map(item => item.id));
export const MODE_LABELS = Object.freeze({
  operating: '운영', design_review: '설계 검토', isolated_experiment: '격리 실험', past_record: '과거 기록',
});
export const NAV_ID = 'shell-nav';
export const NARROW_QUERY = '(max-width: 1023.98px)';
export const SHELL_TEXT = Object.freeze({
  nav: '주 메뉴', open: '메뉴', openLabel: '메뉴 열기', close: '메뉴 닫기', skip: '본문으로 건너뛰기',
  context: '현재 맥락', brand: 'DeepTwin',
});

const SVG = 'http://www.w3.org/2000/svg';
// 20×20 line icons, drawn with currentColor; decorative (the link text names the place)
const ICONS = Object.freeze({
  work: [['path', { d: 'M6 3h5.5L15 6.5V16a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z' }],
    ['path', { d: 'M11 3v4h4M8 10.5h5M8 13.5h3.5' }]],
  observe: [['path', { d: 'M3 10h3.2l2.1-5 3.4 10 2.1-5H17' }]],
  versions: [['circle', { cx: '6', cy: '5', r: '2' }], ['circle', { cx: '6', cy: '15', r: '2' }],
    ['circle', { cx: '14', cy: '7', r: '2' }], ['path', { d: 'M6 7v6M14 9c0 3-8 2-8 4' }]],
  records: [['circle', { cx: '10', cy: '10', r: '7' }], ['path', { d: 'M10 6v4l2.5 2' }]],
  settings: [['path', { d: 'M3.5 6.5h13M3.5 13.5h13' }], ['circle', { cx: '8', cy: '6.5', r: '2', class: 'icon-knob' }],
    ['circle', { cx: '12.5', cy: '13.5', r: '2', class: 'icon-knob' }]],
  menu: [['path', { d: 'M3.5 5.5h13M3.5 10h13M3.5 14.5h13' }]],
  close: [['path', { d: 'M5 5l10 10M15 5L5 15' }]],
});

function icon(document, name) {
  if (typeof document.createElementNS !== 'function' || !Object.hasOwn(ICONS, name)) return null;
  const svg = document.createElementNS(SVG, 'svg');
  for (const [attribute, value] of Object.entries({ viewBox: '0 0 20 20', width: '20', height: '20',
    'aria-hidden': 'true', focusable: 'false', class: 'shell-icon' })) svg.setAttribute(attribute, value);
  for (const [tag, attributes] of ICONS[name]) {
    const shape = document.createElementNS(SVG, tag);
    for (const [attribute, value] of Object.entries(attributes)) shape.setAttribute(attribute, value);
    svg.append(shape);
  }
  return svg;
}

function element(document, tag, { text, className, attrs = {} } = {}, children = []) {
  const node = document.createElement(tag);
  if (className) node.setAttribute('class', className);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
  if (text !== undefined) node.textContent = text;
  node.append(...children.filter(Boolean));
  return node;
}

// the context bar's entries from what a page knows; nothing known → nothing shown
export function contextEntries({ work = null, environment = null, mode = null, extra = [] } = {}) {
  const entries = [];
  const text = value => (typeof value === 'string' && value.trim() ? value.trim() : null);
  if (text(work)) entries.push({ kind: 'work', label: '업무', value: text(work) });
  if (text(environment)) entries.push({ kind: 'environment', label: '환경', value: text(environment) });
  for (const item of Array.isArray(extra) ? extra : []) {
    if (Array.isArray(item) && text(item[0]) && text(item[1])) {
      entries.push({ kind: 'item', label: text(item[0]), value: text(item[1]), title: text(item[2]) });
    }
  }
  if (typeof mode === 'string' && Object.hasOwn(MODE_LABELS, mode)) entries.push({ kind: 'mode', mode, value: MODE_LABELS[mode] });
  return entries;
}

function navList(document, items, page, className) {
  const list = element(document, 'ul', { className });
  for (const item of items) {
    const attrs = { href: item.href, 'data-page': item.id };
    if (item.id === page) attrs['aria-current'] = 'page';
    list.append(element(document, 'li', {}, [
      element(document, 'a', { className: 'shell-link', attrs }, [icon(document, item.icon),
        element(document, 'span', { text: item.label })]),
    ]));
  }
  return list;
}

export function mountShell({ document, page, window = globalThis.window } = {}) {
  if (typeof document?.getElementById !== 'function' || typeof document.createElement !== 'function') return null;
  const app = document.getElementById('app');
  const main = document.getElementById('main');
  if (app === null || main === null || typeof app.insertBefore !== 'function') return null;
  if (app.dataset.shell === 'mounted') return null;
  app.dataset.shell = 'mounted';
  app.classList?.add('app-shell');
  if (SHELL_PAGES.includes(page)) app.dataset.page = page;

  const skip = element(document, 'a', { className: 'skip-link', text: SHELL_TEXT.skip, attrs: { href: '#main' } });
  const menu = element(document, 'button', { className: 'shell-menu-button', attrs: {
    type: 'button', 'aria-expanded': 'false', 'aria-controls': NAV_ID, 'aria-label': SHELL_TEXT.openLabel } },
  [icon(document, 'menu'), element(document, 'span', { text: SHELL_TEXT.open })]);
  const topbar = element(document, 'header', { className: 'shell-topbar' }, [menu,
    element(document, 'a', { className: 'shell-brand', attrs: { href: './work.html' } },
      [element(document, 'span', { text: 'Deep' }), element(document, 'span', { className: 'shell-brand-light', text: 'Twin' })])]);
  const close = element(document, 'button', { className: 'shell-close-button', attrs: { type: 'button' } },
    [icon(document, 'close'), element(document, 'span', { text: SHELL_TEXT.close })]);
  const nav = element(document, 'nav', { className: 'shell-nav', attrs: { id: NAV_ID, 'aria-label': SHELL_TEXT.nav } }, [
    element(document, 'div', { className: 'shell-nav-head' }, [
      element(document, 'a', { className: 'shell-brand', attrs: { href: './work.html' } },
        [element(document, 'span', { text: 'Deep' }), element(document, 'span', { className: 'shell-brand-light', text: 'Twin' })]),
      close,
    ]),
    navList(document, SHELL_ITEMS, page, 'shell-nav-list'),
    element(document, 'hr', { className: 'shell-nav-separator' }),
    navList(document, SHELL_SECONDARY, page, 'shell-nav-list shell-nav-secondary'),
  ]);
  const backdrop = element(document, 'div', { className: 'shell-backdrop', attrs: { 'aria-hidden': 'true' } });
  const context = element(document, 'div', { className: 'context-bar', attrs: { role: 'group', 'aria-label': SHELL_TEXT.context } });
  context.hidden = true;
  for (const node of [skip, topbar, nav, backdrop, context]) app.insertBefore(node, main);
  main.setAttribute('tabindex', '-1');

  const media = typeof window?.matchMedia === 'function' ? window.matchMedia(NARROW_QUERY) : null;
  const narrow = () => media?.matches === true;
  const outside = () => [topbar, context, main];

  function setOpen(open, { restoreFocus = true } = {}) {
    const wasOpen = app.dataset.navOpen === 'true';
    app.dataset.navOpen = open ? 'true' : 'false';
    menu.setAttribute('aria-expanded', open ? 'true' : 'false');
    for (const node of outside()) node.inert = open;
    if (open) {
      (nav.querySelector?.('[aria-current="page"]') ?? nav.querySelector?.('a.shell-link') ?? close).focus?.();
    } else if (wasOpen && restoreFocus) {
      menu.focus?.();
    }
  }

  menu.addEventListener('click', () => setOpen(app.dataset.navOpen !== 'true'));
  close.addEventListener('click', () => setOpen(false));
  backdrop.addEventListener('click', () => setOpen(false));
  document.addEventListener?.('keydown', event => {
    if (event.key === 'Escape' && app.dataset.navOpen === 'true' && narrow()) {
      event.preventDefault?.();
      setOpen(false);
    }
  });
  // widening the window past the breakpoint shows the rail: the drawer state is dropped
  media?.addEventListener?.('change', () => { if (!narrow()) setOpen(false, { restoreFocus: false }); });
  setOpen(false, { restoreFocus: false });

  function setContext(values = {}) {
    const entries = contextEntries(values);
    context.replaceChildren(...entries.map(entry => (entry.kind === 'mode'
      ? element(document, 'span', { className: 'mode-badge', text: entry.value, attrs: { 'data-mode': entry.mode } })
      : element(document, 'span', { className: 'context-item', attrs: { 'data-kind': entry.kind, ...(entry.title ? { title: entry.title } : {}) } }, [
        element(document, 'span', { className: 'context-label', text: entry.label }),
        element(document, 'span', { className: 'context-value', text: entry.value }),
      ]))));
    context.hidden = entries.length === 0;
    return entries;
  }

  return Object.freeze({ nav, menu, context, setContext, open: () => setOpen(true), close: () => setOpen(false),
    get isOpen() { return app.dataset.navOpen === 'true'; } });
}
