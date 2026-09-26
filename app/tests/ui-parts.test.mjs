// The shared DOM parts (ui-parts.mjs) over a fake document: tabs with a roving tabindex and
// arrow keys, the "기술 정보" disclosure, the status chip that never relies on colour alone,
// the empty state, button variants, key-value rows and a time stamp. Text only, never markup.

import test from 'node:test';
import assert from 'node:assert/strict';

process.env.TZ = 'Asia/Seoul';

const {
  BUTTON_VARIANTS, STATUS_GLYPHS, TECHNICAL_SUMMARY, button, card, el, emptyState, keyValueList, pageHeader, section,
  statusChip, tabs, technicalDetails, timeStamp,
} = await import('../static/ui-parts.mjs');

let focused = null;

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.hidden = false;
    this._text = '';
  }

  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }

  set textContent(value) { this._text = String(value); this.children = []; }

  set innerHTML(_value) { throw new Error('markup is never written'); }

  append(...nodes) { this.children.push(...nodes); }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }

  dispatch(type, event = {}) {
    let prevented = false;
    for (const listener of this.listeners.get(type) ?? []) listener({ ...event, preventDefault() { prevented = true; } });
    return prevented;
  }

  focus() { focused = this; }

  findAll(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.findAll(predicate, found);
    }
    return found;
  }
}

const document = { createElement: tag => new FakeElement(tag) };

function threeTabs(options = {}) {
  const selected = [];
  const view = tabs(document, { label: '상세', idPrefix: 'detail', onSelect: id => selected.push(id), ...options,
    items: [{ id: 'input', label: '입력' }, { id: 'output', label: '산출물' }, { id: 'log', label: '기록' }] });
  const tabList = view.list.children;
  const panels = view.root.children.slice(1);
  return { view, tabList, panels, selected };
}

test('tabs: one tab in the tab order, each panel labelled by its tab, only the selected panel shown', () => {
  const { view, tabList, panels, selected } = threeTabs({ selected: 'output' });
  assert.equal(view.list.getAttribute('role'), 'tablist');
  assert.equal(view.list.getAttribute('aria-label'), '상세');
  assert.equal(view.selected, 'output');
  assert.deepEqual(tabList.map(tab => tab.getAttribute('role')), ['tab', 'tab', 'tab']);
  assert.deepEqual(tabList.map(tab => tab.getAttribute('aria-selected')), ['false', 'true', 'false']);
  assert.deepEqual(tabList.map(tab => tab.getAttribute('tabindex')), ['-1', '0', '-1']);
  assert.deepEqual(panels.map(panel => panel.hidden), [true, false, true]);
  for (const [index, tab] of tabList.entries()) {
    assert.equal(tab.getAttribute('aria-controls'), panels[index].getAttribute('id'));
    assert.equal(panels[index].getAttribute('aria-labelledby'), tab.getAttribute('id'));
    assert.equal(panels[index].getAttribute('role'), 'tabpanel');
  }
  assert.deepEqual(selected, [], 'the initial selection is not a change');
  tabList[2].dispatch('click');
  assert.equal(view.selected, 'log');
  assert.deepEqual(selected, ['log']);
  assert.throws(() => tabs(document, { items: [] }));
});

test('tabs: arrows move and select with wrap-around, Home and End jump, other keys do nothing', () => {
  const { view, tabList, panels } = threeTabs();
  assert.equal(view.selected, 'input');
  assert.equal(tabList[0].dispatch('keydown', { key: 'ArrowRight' }), true);
  assert.equal(view.selected, 'output');
  assert.equal(focused, tabList[1]);
  tabList[1].dispatch('keydown', { key: 'ArrowRight' });
  tabList[2].dispatch('keydown', { key: 'ArrowRight' });
  assert.equal(view.selected, 'input', 'ArrowRight wraps to the first tab');
  tabList[0].dispatch('keydown', { key: 'ArrowLeft' });
  assert.equal(view.selected, 'log', 'ArrowLeft wraps to the last tab');
  assert.equal(focused, tabList[2]);
  tabList[2].dispatch('keydown', { key: 'Home' });
  assert.equal(view.selected, 'input');
  tabList[0].dispatch('keydown', { key: 'End' });
  assert.equal(view.selected, 'log');
  assert.deepEqual(tabList.map(tab => tab.getAttribute('tabindex')), ['-1', '-1', '0']);
  assert.deepEqual(panels.map(panel => panel.hidden), [true, true, false]);
  assert.equal(tabList[2].dispatch('keydown', { key: 'a' }), false);
  assert.equal(tabList[2].dispatch('keydown', { key: 'ArrowDown' }), false, 'a horizontal list ignores up/down');
  assert.equal(view.selected, 'log');
});

test('tabs: a vertical list moves with up and down', () => {
  const { view, tabList } = threeTabs({ orientation: 'vertical' });
  assert.equal(view.list.getAttribute('aria-orientation'), 'vertical');
  tabList[0].dispatch('keydown', { key: 'ArrowDown' });
  assert.equal(view.selected, 'output');
  tabList[1].dispatch('keydown', { key: 'ArrowUp' });
  assert.equal(view.selected, 'input');
  assert.equal(tabList[0].dispatch('keydown', { key: 'ArrowRight' }), false);
});

test('the technical disclosure folds raw values under "기술 정보" as text', () => {
  const details = technicalDetails(document, [['실행 ID', '4ca10636-ee80-5d92-a560-59aaecd0ea64'], ['원문', '<b>raw</b>']]);
  assert.equal(details.tagName, 'DETAILS');
  assert.equal(details.getAttribute('class'), 'tech-details');
  assert.equal(details.open, undefined, 'closed unless asked');
  const [summary, list] = details.children;
  assert.equal(summary.tagName, 'SUMMARY');
  assert.equal(summary.textContent, TECHNICAL_SUMMARY);
  assert.equal(TECHNICAL_SUMMARY, '기술 정보');
  assert.equal(list.tagName, 'DL');
  assert.deepEqual(list.children.map(child => [child.tagName, child.textContent]),
    [['DT', '실행 ID'], ['DD', '4ca10636-ee80-5d92-a560-59aaecd0ea64'], ['DT', '원문'], ['DD', '<b>raw</b>']]);
  assert.equal(details.findAll(child => child.tagName === 'B').length, 0);
  assert.equal(technicalDetails(document, [], { open: true, summary: '원문' }).open, true);
});

test('a status chip spells its state beside a glyph; the tone never stands alone', () => {
  for (const [tone, glyph] of Object.entries(STATUS_GLYPHS)) {
    const chip = statusChip(document, { tone, label: '성공' });
    assert.equal(chip.getAttribute('data-tone'), tone);
    const [mark, label] = chip.children;
    assert.equal(mark.textContent, glyph);
    assert.equal(mark.getAttribute('aria-hidden'), 'true');
    assert.equal(label.textContent, '성공');
  }
  const unknown = statusChip(document, { tone: 'purple', label: '결과 미상' });
  assert.equal(unknown.getAttribute('data-tone'), 'neutral');
  assert.equal(unknown.textContent, '•결과 미상');
});

test('the empty state names what is missing and the next step; parts carry text only', () => {
  const empty = emptyState(document, { missing: '아직 기록된 사건이 없습니다.', next: '업무를 저장하면 사건이 남습니다.' });
  assert.deepEqual(empty.children.map(child => child.textContent), ['아직 기록된 사건이 없습니다.', '업무를 저장하면 사건이 남습니다.']);
  assert.equal(emptyState(document, { missing: '없음' }).children.length, 1);
  assert.deepEqual(BUTTON_VARIANTS, ['primary', 'secondary', 'danger', 'quiet']);
  for (const variant of BUTTON_VARIANTS) {
    const made = button(document, { label: '저장', variant });
    assert.equal(made.getAttribute('class'), `btn btn-${variant}`);
    assert.equal(made.getAttribute('type'), 'button');
  }
  assert.equal(button(document, { label: 'x', variant: 'shiny' }).getAttribute('class'), 'btn btn-secondary');
  const header = pageHeader(document, { title: '기록', purpose: '사건을 봅니다.' });
  assert.deepEqual(header.children.map(child => [child.tagName, child.textContent]), [['H1', '기록'], ['P', '사건을 봅니다.']]);
  assert.equal(pageHeader(document, { title: '설정' }).children.length, 1);
  const box = card(document, { title: '실행', children: [el(document, 'p', { text: '본문' })] });
  assert.equal(box.getAttribute('class'), 'card');
  assert.deepEqual(box.children.map(child => child.tagName), ['H2', 'P']);
  assert.equal(section(document, { title: '하위', level: 9 }).children[0].tagName, 'H6');
  const link = el(document, 'a', { text: '열기' });
  const list = keyValueList(document, [['상태', '완료'], ['링크', link], ['없음', null]], { label: '요약' });
  assert.equal(list.getAttribute('aria-label'), '요약');
  assert.deepEqual(list.children.map(child => child.textContent), ['상태', '완료', '링크', '열기', '없음', '']);
  assert.equal(list.children[3].children[0], link);
});

test('a time stamp reads relative with the absolute local time beside it', () => {
  const now = Date.parse('2026-09-25T00:03:00Z');
  const stamp = timeStamp(document, '2026-09-25T00:00:00.000000Z', { now });
  const [time, absolute] = stamp.children;
  assert.equal(time.tagName, 'TIME');
  assert.equal(time.textContent, '3분 전');
  assert.equal(time.getAttribute('datetime'), '2026-09-25T00:00:00.000Z');
  assert.equal(time.getAttribute('title'), '2026-09-25 09:00:00');
  assert.equal(absolute.textContent, '2026-09-25 09:00:00');
  assert.equal(timeStamp(document, 'garbled', { now }).textContent, '시각 미상');
});
