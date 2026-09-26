// UI phase 6 (2026-09-26): an in-house accessibility checker for the browser tests. axe-core is
// not vendored (it was not available offline in this environment), so these checks are written
// here and run inside the page. Accessible names and roles are Chrome's own computation
// (`Element.computedName` / `computedRole`, exposed by launching with AUDIT_LAUNCH_ARGS), not a
// re-implementation. This is a test helper: it is never a served asset (app/api/assets.py).
//
// It checks what the product can check mechanically:
// - every interactive control has an accessible name; images and SVGs have a role and name or
//   are hidden from assistive technology; form fields have a real label (a placeholder is not);
// - heading levels never skip on the way down; landmarks of one role have distinct names and
//   there is one main; every IDREF in an aria-* attribute (and label[for]) resolves; no id repeats;
// - naming is not put on roles that prohibit it; live regions do not nest; aria-pressed and
//   aria-selected sit on roles that support them; no positive tabindex;
// - a status chip always carries words (state never by colour alone);
// - rendered text contrast (the text's colour against the first opaque background behind it,
//   with ancestor opacity applied) meets WCAG AA: 4.5:1, or 3:1 for large text;
// - the design tokens themselves, pair by pair as the stylesheet uses them, in both themes;
// - focus is visible: tabbing through the page, every stop matches :focus-visible and draws an
//   outline (≥ 2px) or a box shadow, whose colour has 3:1 against the surface behind it;
// - reflow: no horizontal page scroll; only allowed containers (graph, tables, code) scroll sideways.
// Passing these is not a screen-reader user test and not the owner's acceptance.

export const AUDIT_LAUNCH_ARGS = Object.freeze(['--enable-blink-features=ComputedAccessibilityInfo']);

// the token pairs the stylesheet actually draws text or edges with, and the ratio each needs
// ('text' 4.5:1 for normal text; 'ui' 3:1 for focus rings, field edges and icon glyphs)
export const TOKEN_PAIRS = Object.freeze([
  ['--color-ink', '--color-surface', 'text'], ['--color-ink', '--color-panel', 'text'],
  ['--color-ink', '--color-panel-muted', 'text'], ['--color-ink', '--color-accent-soft', 'text'],
  ['--color-ink', '--color-warn-soft', 'text'], ['--color-ink', '--color-info-soft', 'text'],
  ['--color-ink', '--color-error-soft', 'text'], ['--color-ink', '--color-ok-soft', 'text'],
  ['--color-muted', '--color-surface', 'text'], ['--color-muted', '--color-panel', 'text'],
  ['--color-muted', '--color-panel-muted', 'text'], ['--color-muted', '--color-nav', 'text'],
  ['--color-muted', '--color-accent-soft', 'text'], ['--color-muted', '--color-warn-soft', 'text'],
  ['--color-nav-ink', '--color-nav', 'text'],
  ['--color-accent', '--color-surface', 'text'], ['--color-accent', '--color-panel', 'text'],
  ['--color-accent', '--color-panel-muted', 'text'], ['--color-accent', '--color-accent-soft', 'text'],
  ['--color-accent', '--color-nav', 'text'], ['--color-accent-strong', '--color-accent-soft', 'text'],
  ['--color-on-accent', '--color-accent', 'text'], ['--color-on-accent', '--color-accent-strong', 'text'],
  ['--color-ok', '--color-ok-soft', 'text'], ['--color-warn', '--color-warn-soft', 'text'],
  ['--color-error', '--color-error-soft', 'text'], ['--color-info', '--color-info-soft', 'text'],
  ['--color-error', '--color-panel', 'text'], ['--color-ok', '--color-panel', 'text'],
  ['--color-warn', '--color-panel', 'text'], ['--color-info', '--color-panel', 'text'],
  ['--color-on-ok', '--color-ok', 'ui'], ['--color-on-warn', '--color-warn', 'ui'],
  ['--color-on-error', '--color-error', 'ui'], ['--color-on-info', '--color-info', 'ui'],
  ['--graph-ink', '--graph-bg', 'text'], ['--graph-ink', '--graph-node', 'text'],
  ['--graph-muted', '--graph-bg', 'text'], ['--graph-muted', '--graph-node', 'text'],
  ['#ffffff', '--graph-selected', 'text'], ['--graph-accent', '--graph-bg', 'ui'],
  ['--graph-node-line', '--graph-bg', 'ui'],
  ['--focus-ring-color', '--color-surface', 'ui'], ['--focus-ring-color', '--color-panel', 'ui'],
  ['--focus-ring-color', '--color-panel-muted', 'ui'], ['--focus-ring-color', '--color-nav', 'ui'],
  ['--focus-ring-color', '--graph-bg', 'ui'],
  ['--color-field-line', '--color-panel', 'ui'], ['--color-field-line', '--color-panel-muted', 'ui'],
  ['--color-field-line', '--color-surface', 'ui'],
]);

// the token pairs, resolved in the page's current theme
export async function tokenContrast(page) {
  return page.evaluate(pairs => {
    const style = getComputedStyle(document.documentElement);
    const probe = document.createElement('span');
    document.body.append(probe);
    const resolve = value => {
      probe.style.color = '';
      probe.style.color = value.startsWith('--') ? `var(${value})` : value;
      return getComputedStyle(probe).color;
    };
    const rgb = text => (text.match(/[\d.]+/g) ?? []).map(Number);
    const channel = v => { const c = v / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
    const luminance = ([r, g, b]) => 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
    const ratio = (a, b) => { const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
    const rows = pairs.map(([fg, bg, kind]) => {
      const f = resolve(fg);
      const b = resolve(bg);
      const value = ratio(rgb(f), rgb(b));
      const need = kind === 'text' ? 4.5 : 3;
      return { fg, bg, kind, fgValue: f, bgValue: b, ratio: Math.round(value * 100) / 100, need, pass: value >= need };
    });
    probe.remove();
    return { surface: style.getPropertyValue('--color-surface').trim(), rows };
  }, TOKEN_PAIRS);
}

// the structural, naming and rendered-contrast checks over the page as it stands
// `modal`: the page behind an open drawer is inert on purpose, so its one main and one h1 are
// not expected to be exposed; every other check still runs over what is exposed
export async function auditPage(page, { label = '', modal = false } = {}) {
  const violations = await page.evaluate(modal => {
    const found = [];
    const describe = node => {
      if (!node || node.nodeType !== 1) return String(node);
      const id = node.id ? `#${node.id}` : '';
      const cls = node.getAttribute('class') ? `.${node.getAttribute('class').trim().split(/\s+/).slice(0, 2).join('.')}` : '';
      const text = (node.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 40);
      return `${node.tagName.toLowerCase()}${id}${cls}${text ? ` “${text}”` : ''}`;
    };
    const add = (rule, node, detail = '') => found.push({ rule, node: describe(node), detail });
    if (typeof document.body.computedRole !== 'string') {
      add('audit-setup', document.body, 'computedRole is unavailable: launch with AUDIT_LAUNCH_ARGS');
      return found;
    }
    // shown to assistive technology: rendered and not under aria-hidden or inert
    const exposed = node => {
      if (!(node instanceof Element)) return false;
      if (node.closest('[aria-hidden="true"], [inert]')) return false;
      if (typeof node.checkVisibility === 'function') {
        return node.checkVisibility({ visibilityProperty: true });
      }
      return node.getClientRects().length > 0;
    };
    const name = node => (node.computedName ?? '').trim();
    const all = [...document.querySelectorAll('*')];

    // 1. interactive controls have an accessible name
    const interactive = 'a[href], button, input:not([type="hidden"]), select, textarea, summary, [tabindex]:not([tabindex="-1"]), '
      + '[role="button"], [role="link"], [role="tab"], [role="checkbox"], [role="radio"], [role="switch"], [role="menuitem"], '
      + '[role="option"], [role="combobox"], [role="textbox"], [role="slider"], [role="spinbutton"], [role="searchbox"]';
    for (const node of document.querySelectorAll(interactive)) {
      if (!exposed(node)) continue;
      if (node === document.querySelector('main') && node.getAttribute('tabindex') === '-1') continue;
      if (!name(node)) add('control-name', node, `role ${node.computedRole}`);
    }
    // 2. images and svgs: a role and a name, or hidden from assistive technology
    for (const node of document.querySelectorAll('img, svg, [role="img"]')) {
      if (node.closest('[aria-hidden="true"]')) continue;
      if (node.tagName.toLowerCase() === 'svg' && node.parentElement?.closest('svg')) continue;
      if (!exposed(node)) continue;
      const role = node.getAttribute('role');
      if (role === 'presentation' || role === 'none') continue;
      if (node.tagName.toLowerCase() === 'img') {
        if (!node.hasAttribute('alt') && !name(node)) add('image-name', node, 'an img needs alt (alt="" when decorative)');
        continue;
      }
      if (!['img', 'image', 'graphics-document', 'graphics-object', 'figure'].includes(node.computedRole) || !name(node)) {
        add('image-name', node, `svg role ${node.computedRole || '(none)'} name “${name(node)}”`);
      }
    }
    // 3. form fields have a real label (aria-label, aria-labelledby, <label>, title); never a placeholder alone
    for (const node of document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="reset"]):not([type="image"]), select, textarea')) {
      if (!exposed(node)) continue;
      const labelled = (node.getAttribute('aria-label') ?? '').trim()
        || (node.getAttribute('aria-labelledby') ?? '').split(/\s+/).some(id => (document.getElementById(id)?.textContent ?? '').trim())
        || [...(node.labels ?? [])].some(label => label.textContent.trim())
        || (node.getAttribute('title') ?? '').trim();
      if (!labelled) add('form-label', node, `placeholder “${node.getAttribute('placeholder') ?? ''}”`);
    }
    // 4. heading levels never skip on the way down; the page starts at h1
    const headings = [...document.querySelectorAll('h1, h2, h3, h4, h5, h6, [role="heading"]')].filter(exposed);
    let previous = 0;
    for (const node of headings) {
      const level = node.getAttribute('role') === 'heading' ? Number(node.getAttribute('aria-level') ?? 2) : Number(node.tagName[1]);
      if (previous === 0 && level !== 1 && !modal) add('heading-order', node, `the first heading is h${level}`);
      else if (previous > 0 && level > previous + 1) add('heading-order', node, `h${previous} → h${level}`);
      previous = level;
    }
    const h1 = headings.filter(node => node.tagName === 'H1').length;
    if (!modal && h1 !== 1) add('heading-order', document.body, `${h1} h1`);
    // 5. landmarks: one main; a role used twice needs distinct names
    const landmarkRoles = ['main', 'navigation', 'complementary', 'banner', 'contentinfo', 'region', 'form', 'search'];
    const landmarks = all.filter(node => landmarkRoles.includes(node.computedRole) && exposed(node));
    const mains = landmarks.filter(node => node.computedRole === 'main');
    if (!modal && mains.length !== 1) add('landmark-unique', document.body, `${mains.length} main landmarks`);
    for (const role of landmarkRoles) {
      const same = landmarks.filter(node => node.computedRole === role);
      if (same.length < 2) continue;
      const seen = new Map();
      for (const node of same) {
        const key = name(node);
        if (!key) add('landmark-unique', node, `an unnamed ${role} beside ${same.length - 1} other(s)`);
        else if (seen.has(key)) add('landmark-unique', node, `${role} “${key}” repeats`);
        seen.set(key, node);
      }
    }
    // 6. every IDREF on an exposed element resolves (a parked, hidden surface is not read)
    const refs = ['aria-labelledby', 'aria-describedby', 'aria-controls', 'aria-owns', 'aria-activedescendant', 'aria-details',
      'aria-errormessage', 'aria-flowto'];
    for (const node of all.filter(exposed)) {
      for (const attribute of refs) {
        const value = node.getAttribute(attribute);
        if (value === null) continue;
        for (const id of value.split(/\s+/).filter(Boolean)) {
          if (!document.getElementById(id)) add('aria-ref', node, `${attribute}="${id}" names nothing`);
        }
      }
      if (node.tagName === 'LABEL' && node.hasAttribute('for') && !document.getElementById(node.getAttribute('for'))) {
        add('aria-ref', node, `label for="${node.getAttribute('for')}" names nothing`);
      }
    }
    // 7. no id repeats
    const ids = new Map();
    for (const node of document.querySelectorAll('[id]')) {
      if (ids.has(node.id)) add('duplicate-id', node, `id “${node.id}” repeats`);
      ids.set(node.id, node);
    }
    // 8. naming prohibited on these roles (ARIA 1.2)
    const noName = ['generic', 'paragraph', 'presentation', 'none', 'code', 'emphasis', 'strong', 'deletion', 'insertion',
      'subscript', 'superscript', 'caption', 'time'];
    for (const node of document.querySelectorAll('[aria-label], [aria-labelledby]')) {
      if (!exposed(node)) continue;
      if (noName.includes(node.computedRole)) add('naming-prohibited', node, `aria-label on role ${node.computedRole}`);
    }
    // 9. live regions do not nest (a nested one is read twice)
    const live = node => node.getAttribute('aria-live') && node.getAttribute('aria-live') !== 'off'
      || ['status', 'alert', 'log', 'timer', 'marquee'].includes(node.getAttribute('role'));
    for (const node of all.filter(live)) {
      if (node.parentElement && [...ancestors(node.parentElement)].some(live)) add('live-nested', node, 'a live region inside another');
    }
    function* ancestors(node) { for (let at = node; at; at = at.parentElement) yield at; }
    // 10. state attributes sit on roles that support them; no positive tabindex
    for (const node of document.querySelectorAll('[aria-pressed]')) {
      if (exposed(node) && !['button', 'toggle button'].includes(node.computedRole)) add('aria-state-role', node, `aria-pressed on ${node.computedRole}`);
    }
    for (const node of document.querySelectorAll('[aria-selected]')) {
      if (exposed(node) && !['tab', 'option', 'row', 'gridcell', 'treeitem', 'columnheader', 'rowheader'].includes(node.computedRole)) {
        add('aria-state-role', node, `aria-selected on ${node.computedRole}`);
      }
    }
    for (const node of document.querySelectorAll('[tabindex]')) {
      if (Number(node.getAttribute('tabindex')) > 0) add('tabindex-positive', node, node.getAttribute('tabindex'));
    }
    // 11. a status chip always says its state in words
    for (const node of document.querySelectorAll('.status-chip')) {
      if (!exposed(node)) continue;
      if (!(node.querySelector('.status-label')?.textContent ?? '').trim()) add('state-words', node, 'a chip with no words');
    }
    // 12. rendered text contrast against the first opaque background behind it
    const parse = text => {
      // rgb()/rgba() in 0–255, or color(srgb …) (what color-mix computes to) in 0–1
      const v = (text.replace(/^color\(srgb/, '').match(/[\d.]+(?:e-?\d+)?/g) ?? []).map(Number);
      const scale = text.startsWith('color(') ? 255 : 1;
      return { r: v[0] * scale, g: v[1] * scale, b: v[2] * scale, a: v.length > 3 ? v[3] : 1 };
    };
    const over = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a),
      b: top.b * top.a + under.b * (1 - top.a), a: 1 });
    const channel = v => { const c = v / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
    const lum = c => 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
    const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
    const backdrop = node => {
      const layers = [];
      let opacity = 1;
      for (let at = node; at; at = at.parentElement) {
        const style = getComputedStyle(at);
        opacity *= Number(style.opacity);
        if (style.backgroundImage !== 'none' && at !== document.documentElement && at !== document.body
            && !at.classList.contains('app-shell')) return null;  // an image or gradient: not judged here
        const color = parse(style.backgroundColor);
        if (color.a > 0) {
          layers.push(color);
          if (color.a >= 1) break;
        }
      }
      let result = { r: 255, g: 255, b: 255, a: 1 };
      const root = parse(getComputedStyle(document.documentElement).backgroundColor);
      if (root.a > 0) result = over(root, result);
      for (const layer of layers.reverse()) result = over(layer, result);
      return { color: result, opacity };
    };
    const seenText = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let text = walker.nextNode(); text; text = walker.nextNode()) {
      if (!text.textContent.trim()) continue;
      const node = text.parentElement;
      if (!node || seenText.has(node) || !exposed(node)) continue;
      seenText.add(node);
      if (node.closest('svg, [disabled], button:disabled, .visually-hidden, option, select')) continue;
      const style = getComputedStyle(node);
      if (style.visibility !== 'visible' || parseFloat(style.fontSize) === 0) continue;
      const rect = node.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) continue;  // clipped screen-reader text
      const behind = backdrop(node);
      if (behind === null) continue;
      const fg = parse(style.color);
      const shown = over({ ...fg, a: fg.a * behind.opacity }, behind.color);
      const value = ratio(shown, behind.color);
      const size = parseFloat(style.fontSize);
      const bold = Number(style.fontWeight) >= 700;
      const large = size >= 24 || (bold && size >= 18.66);
      const need = large ? 3 : 4.5;
      if (value + 0.005 < need) add('text-contrast', node, `${value.toFixed(2)}:1 < ${need}:1 (${style.color} on rgb(${Math.round(behind.color.r)},${Math.round(behind.color.g)},${Math.round(behind.color.b)}), ${size}px)`);
    }
    return found;
  }, modal);
  return violations.map(item => ({ ...item, page: label }));
}

// tab through the page (keyboard only) and judge every stop's focus indicator
export async function focusAudit(page, { max = 80, label = '' } = {}) {
  // start the tab order at the top of the document (a fragment in the address would otherwise
  // start it at its target): a throwaway start point before everything, gone on its first blur
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    const start = document.createElement('span');
    start.tabIndex = -1;
    start.addEventListener('blur', () => start.remove(), { once: true });
    document.body.prepend(start);
    start.focus({ preventScroll: true });
  });
  const stops = [];
  const problems = [];
  let first = null;
  let ended = false;
  let wrapped = false;
  for (let index = 0; index < max; index += 1) {
    await page.keyboard.press('Tab');
    const stop = await page.evaluate(() => {
      const node = document.activeElement;
      if (!node || node === document.body || node === document.documentElement) return { body: true };
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      const parse = text => {
      // rgb()/rgba() in 0–255, or color(srgb …) (what color-mix computes to) in 0–1
      const v = (text.replace(/^color\(srgb/, '').match(/[\d.]+(?:e-?\d+)?/g) ?? []).map(Number);
      const scale = text.startsWith('color(') ? 255 : 1;
      return { r: v[0] * scale, g: v[1] * scale, b: v[2] * scale, a: v.length > 3 ? v[3] : 1 };
    };
      const channel = v => { const c = v / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
      const lum = c => 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
      const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
      // the surface the ring is drawn on: the first opaque background around the control
      let surface = null;
      for (let at = node.parentElement; at && !surface; at = at.parentElement) {
        const color = parse(getComputedStyle(at).backgroundColor);
        if (color.a >= 1) surface = color;
      }
      surface ??= parse(getComputedStyle(document.documentElement).backgroundColor);
      const outlineWidth = parseFloat(style.outlineWidth) || 0;
      const outline = style.outlineStyle !== 'none' && outlineWidth >= 2 && parse(style.outlineColor).a > 0;
      const shadow = style.boxShadow !== 'none';
      const ringRatio = outline ? ratio(parse(style.outlineColor), surface) : null;
      return {
        body: false,
        key: `${node.tagName}|${node.id}|${node.getAttribute('class') ?? ''}|${node.computedName ?? ''}|${Math.round(rect.x)},${Math.round(rect.y + scrollY)}`,
        what: `${node.tagName.toLowerCase()}${node.id ? `#${node.id}` : ''} “${(node.computedName ?? node.textContent ?? '').trim().slice(0, 40)}”`,
        focusVisible: node.matches(':focus-visible'),
        outline, shadow, ringRatio: ringRatio === null ? null : Math.round(ringRatio * 100) / 100,
        visible: rect.width > 0 && rect.height > 0,
      };
    });
    if (stop.body) {
      // past the last stop the browser takes focus into its own interface: the end of the page
      if (stops.length === 0) problems.push({ rule: 'focus-lost', node: 'body', detail: 'no tab stop at all', page: label });
      ended = true;
      break;
    }
    if (first === null) first = stop.key;
    else if (stop.key === first) { wrapped = true; break; }  // back at the first stop
    stops.push(stop.what);
    if (!stop.visible) problems.push({ rule: 'focus-visible', node: stop.what, detail: 'the focused control is not rendered', page: label });
    else if (!stop.focusVisible || (!stop.outline && !stop.shadow)) {
      problems.push({ rule: 'focus-visible', node: stop.what, detail: `focus-visible ${stop.focusVisible}, outline ${stop.outline}, shadow ${stop.shadow}`, page: label });
    } else if (stop.outline && stop.ringRatio !== null && stop.ringRatio < 3) {
      problems.push({ rule: 'focus-contrast', node: stop.what, detail: `ring ${stop.ringRatio}:1 against its surface`, page: label });
    }
  }
  return { stops, problems, ended, wrapped };
}

// reflow: no sideways page scroll; the only sideways scrollers are the allowed containers
export const SCROLL_ALLOWED = '.graph-canvas, .run-table-wrap, pre, .final-text, .artifact-text, textarea, .alternative-original-side, table';

export async function reflowAudit(page, { label = '' } = {}) {
  const report = await page.evaluate(allowed => {
    const width = document.documentElement.clientWidth;
    const problems = [];
    if (document.documentElement.scrollWidth > width + 1) problems.push(`page scrolls sideways: ${document.documentElement.scrollWidth} > ${width}`);
    for (const node of document.querySelectorAll('body *')) {
      const style = getComputedStyle(node);
      if (!['auto', 'scroll'].includes(style.overflowX)) continue;
      if (node.scrollWidth <= node.clientWidth + 1 || node.clientWidth === 0) continue;
      if (!node.matches(allowed) && !node.closest(allowed)) {
        problems.push(`${node.tagName.toLowerCase()}.${(node.getAttribute('class') ?? '').trim().split(/\s+/).join('.')} scrolls sideways`);
      }
    }
    return { width, scrollWidth: document.documentElement.scrollWidth, problems };
  }, SCROLL_ALLOWED);
  return { ...report, page: label };
}

// the polite announcements a journey makes: every live region's text changes, in order
export async function recordAnnouncements(page) {
  await page.evaluate(() => {
    const said = [];
    window.__a11yAnnouncements = said;
    const live = node => node instanceof Element && ((node.getAttribute('aria-live') && node.getAttribute('aria-live') !== 'off')
      || ['status', 'alert', 'log'].includes(node.getAttribute('role')));
    const regionOf = node => {
      for (let at = node instanceof Element ? node : node.parentElement; at; at = at.parentElement) if (live(at)) return at;
      return null;
    };
    const last = new WeakMap();
    const observer = new MutationObserver(records => {
      const touched = new Set();
      for (const record of records) {
        const region = regionOf(record.target);
        if (region) touched.add(region);
      }
      for (const region of touched) {
        const text = region.textContent.trim().replace(/\s+/g, ' ');
        if (!text) continue;
        const politeness = region.getAttribute('aria-live') ?? (region.getAttribute('role') === 'alert' ? 'assertive' : 'polite');
        said.push({ region: region.id || region.getAttribute('class') || region.getAttribute('role'), text, politeness,
          repeated: last.get(region) === text });
        last.set(region, text);
      }
    });
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  return async () => page.evaluate(() => window.__a11yAnnouncements ?? []);
}
