// Small DOM parts shared by the pages (docs/ui/2026-09-26-product-ux-redesign.md §8): a page
// header, a card, a section with its heading, tabs with a roving tabindex, the "기술 정보"
// disclosure for raw identifiers, digests, schema names and server reasons, an empty state
// that names what is missing and the next step, a status chip that spells its state beside a
// glyph (never colour alone), button variants, a key-value list and a time stamp. Every
// part takes the document it builds in (a fake one under node) and puts text in through
// textContent only; nothing here writes markup.

import { timeText } from './ui-format.mjs';

export const TECHNICAL_SUMMARY = '기술 정보';
export const STATUS_GLYPHS = Object.freeze({ ok: '✓', warn: '!', error: '✕', info: 'i', neutral: '•' });
export const BUTTON_VARIANTS = Object.freeze(['primary', 'secondary', 'danger', 'quiet']);

export function el(document, tag, { text, className, attrs = {} } = {}, children = []) {
  const node = document.createElement(tag);
  if (className) node.setAttribute('class', className);
  for (const [name, value] of Object.entries(attrs)) {
    if (value !== undefined && value !== null && value !== false) node.setAttribute(name, value === true ? '' : String(value));
  }
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (children.length) node.append(...children.filter(Boolean));
  return node;
}

// the page's title and one line of purpose
export function pageHeader(document, { title, purpose } = {}) {
  return el(document, 'header', { className: 'page-header' }, [
    el(document, 'h1', { text: title }),
    purpose ? el(document, 'p', { className: 'page-purpose', text: purpose }) : null,
  ]);
}

// a heading and its content; `card` draws it on a raised surface
export function section(document, { title, level = 2, className = 'section', children = [], attrs = {} } = {}) {
  const heading = title ? el(document, `h${Math.min(6, Math.max(2, level))}`, { text: title, className: 'section-title' }) : null;
  return el(document, 'section', { className, attrs }, [heading, ...children]);
}

export function card(document, options = {}) {
  return section(document, { ...options, className: ['card', options.className].filter(Boolean).join(' ') });
}

// label/value rows; a value may be a node (a link, a chip) or text
export function keyValueList(document, entries, { className = 'kv-list', label } = {}) {
  const list = el(document, 'dl', { className, attrs: { 'aria-label': label } });
  for (const [key, value] of entries) {
    const dd = el(document, 'dd');
    if (value !== null && typeof value === 'object' && typeof value.tagName === 'string') dd.append(value);
    else dd.textContent = value === null || value === undefined ? '' : String(value);
    list.append(el(document, 'dt', { text: key }), dd);
  }
  return list;
}

// raw identifiers, digests, schema names and server reasons, folded away from the reading
export function technicalDetails(document, entries, { summary = TECHNICAL_SUMMARY, open = false } = {}) {
  const details = el(document, 'details', { className: 'tech-details' });
  if (open) details.open = true;
  const list = keyValueList(document, entries, { className: 'kv-list tech-list' });
  details.append(el(document, 'summary', { text: summary }), list);
  return details;
}

// what is missing and what to do next, in one place
export function emptyState(document, { missing, next, action = null } = {}) {
  return el(document, 'div', { className: 'empty-state' }, [
    el(document, 'p', { className: 'empty-missing', text: missing }),
    next ? el(document, 'p', { className: 'empty-next', text: next }) : null,
    action,
  ]);
}

// a state in words beside a glyph; the tone only adds colour to what the words say
export function statusChip(document, { tone = 'neutral', label } = {}) {
  const known = Object.hasOwn(STATUS_GLYPHS, tone) ? tone : 'neutral';
  return el(document, 'span', { className: 'status-chip', attrs: { 'data-tone': known } }, [
    el(document, 'span', { className: 'status-glyph', text: STATUS_GLYPHS[known], attrs: { 'aria-hidden': 'true' } }),
    el(document, 'span', { className: 'status-label', text: label }),
  ]);
}

export function button(document, { label, variant = 'secondary', type = 'button', attrs = {} } = {}) {
  const kind = BUTTON_VARIANTS.includes(variant) ? variant : 'secondary';
  return el(document, 'button', { text: label, className: `btn btn-${kind}`, attrs: { type, ...attrs } });
}

// "3분 전" with the absolute local time beside it (and in the title)
export function timeStamp(document, value, { now = Date.now(), className = 'time-stamp' } = {}) {
  const time = timeText(value, now);
  const wrapper = el(document, 'span', { className });
  if (!time.iso) {
    wrapper.textContent = '시각 미상';
    return wrapper;
  }
  wrapper.append(el(document, 'time', { text: time.relative, attrs: { datetime: time.iso, title: time.absolute } }),
    el(document, 'span', { className: 'time-absolute', text: time.absolute }));
  return wrapper;
}

// tabs with a roving tabindex: one tab in the tab order, arrows move and select, Home/End
// jump; each panel is labelled by its tab and only the selected one is shown
export function tabs(document, { label, items, selected, onSelect, idPrefix = 'tab', orientation = 'horizontal' } = {}) {
  if (!Array.isArray(items) || items.length === 0) throw new TypeError('tabs need at least one item');
  const list = el(document, 'div', { className: 'tabs-list',
    attrs: { role: 'tablist', 'aria-label': label, 'aria-orientation': orientation } });
  const root = el(document, 'div', { className: 'tabs' }, [list]);
  const entries = items.map(item => {
    const tab = el(document, 'button', { text: item.label, className: 'tab',
      attrs: { type: 'button', role: 'tab', id: `${idPrefix}-${item.id}`, 'aria-controls': `${idPrefix}-${item.id}-panel` } });
    const panel = item.panel ?? el(document, 'div');
    panel.setAttribute('role', 'tabpanel');
    panel.setAttribute('id', `${idPrefix}-${item.id}-panel`);
    panel.setAttribute('aria-labelledby', `${idPrefix}-${item.id}`);
    panel.setAttribute('tabindex', '0');
    list.append(tab);
    root.append(panel);
    return { id: item.id, tab, panel };
  });
  let current = null;

  function select(id, { focus = false, notify = true } = {}) {
    const target = entries.find(entry => entry.id === id);
    if (!target) return false;
    current = id;
    for (const entry of entries) {
      const on = entry === target;
      entry.tab.setAttribute('aria-selected', on ? 'true' : 'false');
      entry.tab.setAttribute('tabindex', on ? '0' : '-1');
      entry.panel.hidden = !on;
    }
    if (focus && typeof target.tab.focus === 'function') target.tab.focus();
    if (notify && typeof onSelect === 'function') onSelect(id);
    return true;
  }

  const next = orientation === 'vertical' ? 'ArrowDown' : 'ArrowRight';
  const previous = orientation === 'vertical' ? 'ArrowUp' : 'ArrowLeft';
  entries.forEach((entry, index) => {
    entry.tab.addEventListener('click', () => select(entry.id));
    entry.tab.addEventListener('keydown', event => {
      let to = null;
      if (event.key === next) to = (index + 1) % entries.length;
      else if (event.key === previous) to = (index - 1 + entries.length) % entries.length;
      else if (event.key === 'Home') to = 0;
      else if (event.key === 'End') to = entries.length - 1;
      if (to === null) return;
      event.preventDefault?.();
      select(entries[to].id, { focus: true });
    });
  });
  select(entries.some(entry => entry.id === selected) ? selected : entries[0].id, { notify: false });
  return Object.freeze({ root, list, select, get selected() { return current; } });
}
