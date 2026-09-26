// The app shell (ui-shell.mjs) over a fake document: one navigation with the current page
// marked, relative links only, a context bar that shows only what a page supplies (and hides
// when nothing is known), and the narrow-screen drawer — open moves focus into it and makes
// the rest inert, Escape closes it and returns focus to the menu button.

import test from 'node:test';
import assert from 'node:assert/strict';

import { MODE_LABELS, NAV_ID, SHELL_ITEMS, SHELL_PAGES, SHELL_SECONDARY, contextEntries, mountShell } from '../static/ui-shell.mjs';

let focused = null;

class FakeElement {
  constructor(tagName, id = null) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.dataset = {};
    this.hidden = false;
    this.inert = false;
    this.parent = null;
    this._text = '';
    const classes = new Set();
    this.classList = { add: name => classes.add(name), contains: name => classes.has(name) };
    if (id) this.attributes.set('id', id);
  }

  get id() { return this.attributes.get('id') ?? ''; }

  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }

  set textContent(value) { this._text = String(value); this.children = []; }

  set innerHTML(_value) { throw new Error('markup is never written'); }

  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }

  replaceChildren(...nodes) { this.children = []; this._text = ''; this.append(...nodes); }

  insertBefore(node, before) {
    node.parent = this;
    this.children.splice(this.children.indexOf(before), 0, node);
  }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }

  dispatch(type, event = {}) { for (const listener of this.listeners.get(type) ?? []) listener({ preventDefault() {}, ...event }); }

  focus() { focused = this; }

  querySelector(selector) {
    const matches = {
      '[aria-current="page"]': node => node.getAttribute('aria-current') === 'page',
      'a.shell-link': node => node.tagName === 'A' && node.getAttribute('class') === 'shell-link',
    }[selector];
    if (!matches) throw new Error(`unexpected selector ${selector}`);
    return this.findAll(matches)[0] ?? null;
  }

  findAll(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.findAll?.(predicate, found);
    }
    return found;
  }
}

function page({ narrow = false } = {}) {
  const app = new FakeElement('div', 'app');
  const main = new FakeElement('main', 'main');
  app.append(main);
  const docListeners = new Map();
  const mediaListeners = [];
  const media = { matches: narrow, addEventListener: (_type, listener) => mediaListeners.push(listener) };
  const document = {
    getElementById: id => (id === 'app' ? app : id === 'main' ? main : null),
    createElement: tag => new FakeElement(tag),
    createElementNS: (_ns, tag) => new FakeElement(tag),
    addEventListener: (type, listener) => docListeners.set(type, [...(docListeners.get(type) ?? []), listener]),
    key(key) { for (const listener of docListeners.get('keydown') ?? []) listener({ key, preventDefault() {} }); },
  };
  const window = { matchMedia: () => media };
  return { app, main, document, window, media, resize(matches) { media.matches = matches; for (const l of mediaListeners) l(); } };
}

const links = app => app.findAll(node => node.tagName === 'A' && node.getAttribute('class') === 'shell-link');

test('the navigation lists 업무, 실행, 버전·실험, 기록, then 설정, with the current page marked', () => {
  assert.deepEqual(SHELL_ITEMS.map(item => [item.label, item.href]), [
    ['업무', './work.html'], ['실행', './observe.html'], ['버전·실험', './versions.html'], ['기록', './records.html'],
  ]);
  assert.deepEqual(SHELL_SECONDARY.map(item => [item.label, item.href]), [['설정', './settings.html']]);
  for (const id of SHELL_PAGES) {
    const { app, document, window } = page();
    const shell = mountShell({ document, page: id, window });
    assert.ok(shell, id);
    const nav = app.findAll(node => node.getAttribute('id') === NAV_ID)[0];
    assert.equal(nav.tagName, 'NAV');
    assert.equal(nav.getAttribute('aria-label'), '주 메뉴');
    const all = links(app);
    assert.deepEqual(all.map(link => link.textContent), ['업무', '실행', '버전·실험', '기록', '설정']);
    assert.ok(all.every(link => link.getAttribute('href').startsWith('./')), 'relative links under the random base path');
    assert.deepEqual(all.filter(link => link.getAttribute('aria-current') === 'page').map(link => link.getAttribute('data-page')), [id]);
    assert.equal(app.findAll(node => node.tagName === 'HR').length, 1, 'one separator before 설정');
    assert.equal(app.dataset.page, id);
  }
});

test('the shell is inserted before the page content and mounts once; without the page mounts it does nothing', () => {
  const { app, main, document, window } = page();
  mountShell({ document, page: 'records', window });
  const order = app.children.map(node => node.getAttribute('class'));
  assert.deepEqual(order, ['skip-link', 'shell-topbar', 'shell-nav', 'shell-backdrop', 'context-bar', null]);
  assert.equal(app.children.at(-1), main);
  assert.equal(main.getAttribute('tabindex'), '-1');
  assert.equal(app.children[0].getAttribute('href'), '#main');
  assert.equal(mountShell({ document, page: 'records', window }), null, 'a second mount is refused');
  assert.equal(links(app).length, 5);
  const bare = { getElementById: () => null, createElement: tag => new FakeElement(tag) };
  assert.equal(mountShell({ document: bare, page: 'work' }), null);
  assert.equal(mountShell({}), null);
});

test('the context bar shows only what the page supplies and hides when nothing is known', () => {
  const { app, document, window } = page();
  const shell = mountShell({ document, page: 'observe', window });
  const bar = app.findAll(node => node.getAttribute('class') === 'context-bar')[0];
  assert.equal(bar.hidden, true, 'nothing known, nothing shown');
  assert.deepEqual(shell.setContext({}), []);
  assert.equal(bar.hidden, true);
  shell.setContext({ work: '화요일 공간 안내', environment: 'v3', mode: 'operating', extra: [['실행', '4ca10636', '4ca10636-full']] });
  assert.equal(bar.hidden, false);
  assert.equal(bar.getAttribute('aria-label'), '현재 맥락');
  assert.deepEqual(bar.children.map(child => child.textContent), ['업무화요일 공간 안내', '환경v3', '실행4ca10636', '운영']);
  assert.equal(bar.children[2].getAttribute('title'), '4ca10636-full');
  assert.equal(bar.children[3].getAttribute('data-mode'), 'operating');
  // an unknown mode or a blank value is never shown, never guessed
  assert.deepEqual(contextEntries({ work: '  ', mode: 'production', extra: [['실행', ''], 'bad'] }), []);
  shell.setContext({ mode: 'mystery' });
  assert.equal(bar.hidden, true);
  assert.deepEqual(MODE_LABELS, { operating: '운영', design_review: '설계 검토', isolated_experiment: '격리 실험', past_record: '과거 기록' });
  for (const [mode, label] of Object.entries(MODE_LABELS)) assert.equal(contextEntries({ mode })[0].value, label);
});

test('narrow screens: the menu button opens the drawer, Escape closes it and focus returns to the button', () => {
  const { app, main, document, window, resize } = page({ narrow: true });
  const shell = mountShell({ document, page: 'versions', window });
  const menu = shell.menu;
  assert.equal(menu.getAttribute('aria-controls'), NAV_ID);
  assert.equal(menu.getAttribute('aria-expanded'), 'false');
  assert.equal(app.dataset.navOpen, 'false');
  menu.dispatch('click');
  assert.equal(shell.isOpen, true);
  assert.equal(menu.getAttribute('aria-expanded'), 'true');
  assert.equal(main.inert, true, 'the page behind the drawer is inert');
  assert.equal(focused.getAttribute('data-page'), 'versions', 'focus moves to the current page link');
  document.key('Escape');
  assert.equal(shell.isOpen, false);
  assert.equal(main.inert, false);
  assert.equal(focused, menu, 'focus returns to the menu button');
  // the close button and the backdrop close it too
  menu.dispatch('click');
  app.findAll(node => node.getAttribute('class') === 'shell-close-button')[0].dispatch('click');
  assert.equal(shell.isOpen, false);
  menu.dispatch('click');
  app.findAll(node => node.getAttribute('class') === 'shell-backdrop')[0].dispatch('click');
  assert.equal(shell.isOpen, false);
  // widening past the breakpoint drops the drawer state without stealing focus
  menu.dispatch('click');
  focused = null;
  resize(false);
  assert.equal(shell.isOpen, false);
  assert.equal(focused, null);
  // on a wide screen Escape is not the drawer's
  shell.open();
  document.key('Escape');
  assert.equal(shell.isOpen, true);
});
