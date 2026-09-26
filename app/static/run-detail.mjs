// UI phase 3 (DOM half): the run detail screen (docs/ui/2026-09-26-product-ux-redesign.md §5.3).
// It reads the run trace (run-trace.mjs) and renders, for the page that owns the mounts:
// - the run header: work name, status chip, start/end and duration, call counts, tokens, cost;
// - "최종 결과" first: the artifacts the graph's exit produced, each with a preview, a download,
//   "내 버전 만들기" (opened in place by the page) and "과정에서 보기"; or where the run stopped;
// - "과정": a graph | timeline switch (ui-parts tabs) sharing ONE selection with
// - the selection panel: visit and attempt pickers (latest by default; a past attempt shows
//   only its own facts) and the tabs 입력 / 산출물 / 전달 / 도구·모델 / 기록.
// The graph view and the artifact viewer are the existing modules, passed in. Every string
// reaches the DOM through textContent or an attribute; raw ids and digests sit in "기술 정보".

import { artifactRoutes, coverageText, MESSAGES as ARTIFACT_MESSAGES, previewView } from './artifacts.mjs';
import {
  attemptOptionText, errorText, finalResults, pendingApprovals, resolveSelection, runSummary, selectionView,
  timelineRows, traceRoute, traceView,
} from './run-trace.mjs';
import {
  APPROVAL_STATE_TEXT, EFFECT_CLASS_LABELS, JOURNAL_LABELS, MODEL_CALL_STATE_TEXT, NODE_KIND_LABELS, NOT_RECORDED,
  NOT_RECORDED_LABEL, STOP_REASON_LABELS, TOOL_CALL_STATE_TEXT, TRACE_GAP_LABELS, TRACE_NODE_STATE_TEXT,
  VISIT_STATUS_TEXT, approvalScopeLabel, clockTime, costText, countText, durationText, formatBytes, mediaTypeLabel,
  ratesText, shortId, stateText,
} from './ui-format.mjs';
import { el, emptyState, keyValueList, statusChip, tabs, technicalDetails, timeStamp } from './ui-parts.mjs';

export const DETAIL_TABS = Object.freeze([
  ['inputs', '입력'], ['outputs', '산출물'], ['handoffs', '전달'], ['calls', '도구·모델'], ['records', '기록'],
]);
export const VIEW_TABS = Object.freeze([['graph', '그래프'], ['timeline', '타임라인']]);
export const MESSAGES = Object.freeze({
  loading: '실행 기록을 읽는 중…',
  failed: '실행 기록을 읽지 못했습니다.',
  noFinal: '아직 최종 결과가 없습니다.',
  finalLead: '그래프의 끝 단계가 만든 산출물입니다. 내 버전을 만들거나 과정에서 어떻게 만들어졌는지 볼 수 있습니다.',
  wholeRun: '실행 전체',
  wholeRunHint: '그래프나 타임라인에서 단계를 고르면 그 단계의 수행과 시도를 봅니다.',
  noAttempts: '시도 기록 없음 — 실행기가 직접 처리한 단계입니다.',
  pastAttempt: '지난 시도입니다. 이 시도가 남긴 것만 보이며, 뒤 시도의 산출물은 여기에 붙지 않습니다.',
  noInputs: '이 단계는 앞 단계에서 받은 것이 없습니다(시작 단계).',
  runInputs: '실행 전체의 입력은 업무 설명입니다. 단계를 고르면 그 단계가 받은 산출물의 정확한 버전을 봅니다.',
  noOutputs: '이 시도는 산출물을 남기지 않았습니다.',
  noVisitOutputs: '이 수행은 산출물을 남기지 않았습니다.',
  noHandoffs: '이 단계와 주고받은 전달이 기록되지 않았습니다.',
  handoffHonesty: '“전달됨”은 앞 단계의 결과가 이 수행의 입력으로 기록되었다는 뜻입니다. 받은 쪽이 실제로 활용했다는 근거와는 다른 주장입니다.',
  noCalls: '이 선택에는 도구·모델 호출 기록이 없습니다.',
  reasoning: '모델의 숨은 추론은 저장하지 않으므로 볼 수 없습니다.',
  recordsLink: '전체 기록에서 이 실행 보기',
  noJournal: '이 선택에는 시도 기록(예약·보냄·결과)이 없습니다.',
});

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

function chip(document, table, value) {
  const [label, tone] = stateText(table, value);
  return statusChip(document, { tone, label });
}

function stamp(document, value) {
  return value === NOT_RECORDED || value === null || value === undefined
    ? el(document, 'span', { className: 'time-stamp', text: NOT_RECORDED_LABEL }) : timeStamp(document, value);
}

function refText(value) {
  if (value === NOT_RECORDED || value === null || value === undefined) return NOT_RECORDED_LABEL;
  return `${value.kind} ${value.id} v${value.version} · sha256 ${value.sha256}`;
}

export function createRunDetail({
  document, request, basePath = '/', roots, graph = null, artifacts = null,
  onEdit = null, onAlternativeFile = null, onOpenApprovals = null, onSelectionChange = null,
} = {}) {
  if (typeof document?.createElement !== 'function') fail('a document is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  for (const name of ['summary', 'banner', 'final', 'views', 'graphMount', 'timeline', 'selection']) {
    if (typeof roots?.[name]?.replaceChildren !== 'function') fail(`the detail needs its ${name} mount`);
  }
  const routes = artifactRoutes(basePath);
  let trace = null;
  let runId = null;
  let selection = Object.freeze({ nodeId: null, visitNo: null, attemptNo: null });
  let generation = 0;
  let artifactsReady = Promise.resolve(null);
  let pending = null;  // a pick made while this run's trace is still being read

  // ---- process views: graph | timeline over one selection -------------------------------------
  const graphPanel = el(document, 'div', { className: 'process-panel' });
  const timelinePanel = el(document, 'div', { className: 'process-panel' });
  graphPanel.append(roots.graphMount);
  timelinePanel.append(roots.timeline);
  const viewTabs = tabs(document, { label: '과정 보기 전환', idPrefix: 'process', selected: 'graph',
    items: VIEW_TABS.map(([id, label]) => ({ id, label, panel: id === 'graph' ? graphPanel : timelinePanel })) });
  roots.views.replaceChildren(viewTabs.root);

  // ---- the selection panel ---------------------------------------------------------------------
  const selectionHead = el(document, 'div', { className: 'selection-head' });
  const pickers = el(document, 'div', { className: 'selection-pickers' });
  const selectionNotes = el(document, 'div', { className: 'selection-notes' });
  const panels = Object.fromEntries(DETAIL_TABS.map(([id]) => [id, el(document, 'div', { className: `detail-${id}` })]));
  const outputsLead = el(document, 'p', { className: 'selection-lead' });
  if (roots.artifactsMount) panels.outputs.append(outputsLead, roots.artifactsMount);
  const detailTabs = tabs(document, { label: '선택한 단계의 기록', idPrefix: 'detail', selected: 'outputs',
    items: DETAIL_TABS.map(([id, label]) => ({ id, label, panel: panels[id] })) });
  roots.selection.replaceChildren(selectionHead, pickers, selectionNotes, detailTabs.root);

  function nodeKindLabel(node) {
    return NODE_KIND_LABELS[node.kind] ?? node.kind;
  }

  // ---- header -----------------------------------------------------------------------------------
  function renderSummary() {
    const facts = runSummary(trace);
    const titleRow = el(document, 'div', { className: 'run-title-row' }, [
      el(document, 'h2', { text: facts.title, className: 'run-title', attrs: { id: 'run-title' } }),
      statusChip(document, { tone: facts.tone, label: facts.phaseLabel }),
    ]);
    const meta = el(document, 'p', { className: 'run-meta' });
    meta.append(el(document, 'span', { text: `실행 ${shortId(trace.run_id)}`, attrs: { title: trace.run_id } }),
      el(document, 'span', { text: ' · 시작 ' }), stamp(document, facts.startedAt));
    if (facts.endedAt) {
      meta.append(el(document, 'span', { text: ' · 끝 ' }), stamp(document, facts.endedAt),
        el(document, 'span', { text: ` · 걸린 시간 ${facts.duration}` }));
    } else {
      meta.append(el(document, 'span', { text: ' · 아직 끝나지 않음' }));
    }
    const stats = el(document, 'ul', { className: 'run-stats', attrs: { 'aria-label': '실행 통계' } }, [
      el(document, 'li', {}, [el(document, 'span', { className: 'stat-label', text: '호출' }),
        el(document, 'span', { text: facts.calls })]),
      el(document, 'li', {}, [el(document, 'span', { className: 'stat-label', text: '토큰' }),
        el(document, 'span', { text: facts.tokens })]),
      el(document, 'li', {}, [el(document, 'span', { className: 'stat-label', text: '비용' }),
        el(document, 'span', { text: facts.cost })]),
    ]);
    const technical = [['실행 ID', trace.run_id], ['그래프', refText(trace.graph_ref)], ['그래프 요약값', trace.graph_digest],
      ['업무 수정본', refText(trace.work?.work_revision_ref)]];
    for (const stop of trace.stops) {
      technical.push([`멈춤 기록 (${STOP_REASON_LABELS[stop.reason] ?? stop.reason})`, `${stop.at_utc} · ${stop.reason}`]);
    }
    roots.summary.replaceChildren(titleRow, meta, stats, technicalDetails(document, technical));
    if (roots.summary.dataset) roots.summary.dataset.phase = trace.phase;
  }

  function renderBanner() {
    const pending = pendingApprovals(trace);
    if (!pending.length) {
      roots.banner.replaceChildren();
      roots.banner.hidden = true;
      return;
    }
    const names = pending.map(item => `${item.nodeId}${item.attemptNo ? ` 시도 ${item.attemptNo}` : ''} (${approvalScopeLabel(item.scope)})`);
    const open = el(document, 'button', { text: '승인 화면 열기', className: 'btn btn-primary', attrs: { type: 'button' } });
    open.addEventListener('click', () => { if (typeof onOpenApprovals === 'function') onOpenApprovals(); });
    roots.banner.replaceChildren(el(document, 'p', { className: 'banner-text' }, [
      el(document, 'strong', { text: '사람 승인이 필요합니다. ' }),
      el(document, 'span', { text: names.join(', ') }),
    ]), open);
    roots.banner.hidden = false;
  }

  // ---- final results ------------------------------------------------------------------------------
  function previewInto(target, item) {
    target.replaceChildren(el(document, 'p', { className: 'final-preview-status', text: ARTIFACT_MESSAGES.previewing }));
    return request(routes.preview(runId, item.artifactId), {}).then(payload => {
      const view = previewView(payload);
      const parts = [];
      if (view.kind === 'text' || view.kind === 'json' || view.kind === 'document_text') {
        parts.push(el(document, 'pre', { className: 'artifact-text final-text', text: String(view.body.text ?? '') }));
      } else if (view.kind === 'table') {
        const table = el(document, 'table', { className: 'artifact-table' });
        for (const cells of Array.isArray(view.body.rows) ? view.body.rows.slice(0, 20) : []) {
          table.append(el(document, 'tr', {}, (Array.isArray(cells) ? cells : []).map(cell => el(document, 'td', { text: String(cell) }))));
        }
        parts.push(table);
      } else if (view.kind === 'image') {
        parts.push(el(document, 'img', { className: 'artifact-image', attrs: { src: routes.content(runId, item.artifactId), alt: `${item.role} 이미지` } }));
      } else if (view.kind === 'page_image') {
        parts.push(el(document, 'img', { className: 'artifact-image artifact-page', attrs: {
          src: routes.pageImage(runId, item.artifactId, view.body.page), alt: `${item.role} ${view.body.page}쪽 (문서 변환 워커가 그린 이미지)` } }));
      } else {
        parts.push(el(document, 'p', { text: ARTIFACT_MESSAGES[view.kind] ?? ARTIFACT_MESSAGES.unsupported }));
      }
      const coverage = coverageText(view);
      if (coverage) parts.push(el(document, 'p', { className: 'artifact-coverage', text: coverage }));
      target.replaceChildren(...parts);
      return view;
    }).catch(() => {
      target.replaceChildren(el(document, 'p', { text: '미리보기를 준비하지 못했습니다. 원본은 내려받을 수 있습니다.' }));
    });
  }

  function finalCard(item) {
    const card = el(document, 'article', { className: 'final-result', attrs: { 'data-artifact-id': item.artifactId,
      'aria-label': `최종 결과 ${item.role}` } });
    const madeBy = `“${item.responsibility}” 단계(${item.nodeId})가 만듦`;
    const facts = `${mediaTypeLabel(item.mediaType)} · ${formatBytes(item.size)}`
      + (item.attemptNo ? ` · 시도 ${item.attemptNo}` : '');
    const preview = el(document, 'div', { className: 'final-preview' });
    const actions = el(document, 'div', { className: 'final-actions' });
    const slot = el(document, 'div', { className: 'editor-slot' });
    const listed = { artifactId: item.artifactId, role: item.role, nodeId: item.nodeId, ordinal: item.ordinal,
      mediaType: item.mediaType, size: item.size, sha256: item.sha256, available: true };
    const context = { title: `${item.role} (${item.responsibility} · ${item.attemptNo ? `시도 ${item.attemptNo}` : `수행 ${item.visitNo}`})`,
      slot, anchor: card };
    if (typeof onEdit === 'function') {
      const edit = el(document, 'button', { text: '내 버전 만들기', className: 'btn btn-primary', attrs: { type: 'button' } });
      edit.addEventListener('click', () => Promise.resolve(onEdit(runId, listed, context)).catch(() => {}));
      actions.append(edit);
    }
    actions.append(el(document, 'a', { text: '원본 내려받기', className: 'btn btn-secondary', attrs: {
      href: routes.content(runId, item.artifactId), download: `${item.role}-${item.ordinal}`, rel: 'noopener' } }));
    if (typeof onAlternativeFile === 'function') {
      const file = el(document, 'button', { text: '대안 파일 올리기', className: 'btn btn-quiet', attrs: { type: 'button' } });
      file.addEventListener('click', () => Promise.resolve(onAlternativeFile(runId, listed, context)).catch(() => {}));
      actions.append(file);
    }
    const trace_ = el(document, 'button', { text: '과정에서 보기', className: 'btn btn-quiet', attrs: { type: 'button' } });
    trace_.addEventListener('click', () => select({ nodeId: item.nodeId, visitNo: item.visitNo, attemptNo: item.attemptNo },
      { focus: true, tab: 'outputs' }));
    actions.append(trace_);
    card.append(el(document, 'header', { className: 'final-head' }, [
      el(document, 'h3', { text: item.role, className: 'final-title' }),
      el(document, 'p', { className: 'final-meta', text: `${madeBy} · ${facts}` }),
    ]), preview, actions, slot, technicalDetails(document, [['산출물 ID', item.artifactId], ['밝힌 형식', item.mediaType],
      ['SHA-256', item.sha256], ['결과 기록', refText(item.resultRef)]]));
    previewInto(preview, item);
    return card;
  }

  function renderFinal() {
    const view = finalResults(trace);
    const heading = el(document, 'h2', { text: '최종 결과', attrs: { id: 'run-final-title' } });
    if (view.items.length) {
      roots.final.replaceChildren(heading, el(document, 'p', { className: 'section-lead', text: MESSAGES.finalLead }),
        ...view.items.map(finalCard));
      return;
    }
    const where = el(document, 'ul', { className: 'stopped-list', attrs: { 'aria-label': '멈춘 지점' } },
      view.stopped.map(item => {
        const go = el(document, 'button', { text: `${item.responsibility} (${item.nodeId})`, className: 'btn btn-quiet',
          attrs: { type: 'button' } });
        go.addEventListener('click', () => select({ nodeId: item.nodeId }, { focus: true }));
        return el(document, 'li', {}, [statusChip(document, { tone: item.tone, label: item.label }), go]);
      }));
    const next = view.stopped.length ? '실행이 멈춘 지점입니다. 단계를 고르면 그 단계의 시도와 오류를 봅니다.'
      : '끝 단계가 아직 결과를 기록하지 않았습니다.';
    roots.final.replaceChildren(heading, emptyState(document, { missing: MESSAGES.noFinal, next, action: view.stopped.length ? where : null }));
  }

  // ---- timeline -----------------------------------------------------------------------------------
  function renderTimeline() {
    const rows = timelineRows(trace);
    const list = el(document, 'ol', { className: 'timeline', attrs: { 'aria-label': '시간순 수행과 시도' } });
    for (const row of rows) {
      const button = el(document, 'button', { className: 'timeline-entry', attrs: { type: 'button',
        'data-node': row.nodeId, 'data-kind': row.kind, 'data-attempt': row.attemptNo ?? '', 'aria-pressed': 'false' } });
      button.append(el(document, 'time', { className: 'timeline-time', text: clockTime(row.at) || NOT_RECORDED_LABEL,
        attrs: { datetime: row.at === NOT_RECORDED ? undefined : row.at, title: row.at } }),
      el(document, 'span', { className: 'timeline-node', text: row.responsibility }),
      el(document, 'span', { className: 'timeline-what', text: `${row.nodeId} · ${row.text}` }),
      statusChip(document, { tone: row.tone, label: row.detail }));
      button.addEventListener('click', () => select({ nodeId: row.nodeId, visitNo: row.visitNo,
        attemptNo: row.kind === 'attempt' ? row.attemptNo : null }, { reveal: true }));
      list.append(el(document, 'li', {}, [button]));
    }
    const gaps = trace.gaps.map(item => el(document, 'li', { text: TRACE_GAP_LABELS[item.category] ?? item.reason }));
    roots.timeline.replaceChildren(rows.length ? list : el(document, 'p', { text: '기록된 수행이 없습니다.' }),
      ...(gaps.length ? [el(document, 'details', { className: 'trace-gaps' }, [
        el(document, 'summary', { text: `기록하지 않는 것 ${gaps.length}가지` }),
        el(document, 'ul', {}, gaps)])] : []));
  }

  function markTimeline() {
    for (const button of roots.timeline.querySelectorAll?.('button.timeline-entry') ?? []) {
      const same = button.getAttribute('data-node') === selection.nodeId && (button.getAttribute('data-kind') !== 'attempt'
        || Number(button.getAttribute('data-attempt')) === selection.attemptNo);
      button.setAttribute('aria-pressed', same ? 'true' : 'false');
    }
  }

  // ---- selection panel ------------------------------------------------------------------------------
  function renderHead(view) {
    if (view.scope === 'run') {
      selectionHead.replaceChildren(el(document, 'p', { className: 'selection-kicker', text: '선택' }),
        el(document, 'h3', { className: 'selection-title', text: MESSAGES.wholeRun }),
        el(document, 'p', { className: 'selection-hint', text: MESSAGES.wholeRunHint }));
      pickers.replaceChildren();
      selectionNotes.replaceChildren();
      return;
    }
    const node = view.node;
    const clear = el(document, 'button', { text: '실행 전체 보기', className: 'btn btn-quiet selection-clear', attrs: { type: 'button' } });
    clear.addEventListener('click', () => select({ nodeId: null }));
    const [stateLabel, tone] = stateText(TRACE_NODE_STATE_TEXT, node.state);
    selectionHead.replaceChildren(
      el(document, 'div', { className: 'selection-kicker-row' }, [el(document, 'p', { className: 'selection-kicker', text: '선택' }), clear]),
      el(document, 'h3', { className: 'selection-title', text: node.responsibility }),
      el(document, 'p', { className: 'selection-sub' }, [
        el(document, 'span', { text: `${node.node_id} · ${nodeKindLabel(node)} · ` }),
        statusChip(document, { tone, label: stateLabel }),
      ]));
    const items = [];
    if (node.visits.length > 1) {
      const visitPick = el(document, 'select', { attrs: { 'aria-label': '수행 선택' } });
      for (const visit of node.visits) {
        const option = el(document, 'option', { text: `수행 ${visit.visit_no}` });
        option.value = String(visit.visit_no);
        visitPick.append(option);
      }
      visitPick.value = String(view.visitNo);
      visitPick.addEventListener('change', () => select({ nodeId: node.node_id, visitNo: Number(visitPick.value) }));
      items.push(el(document, 'label', { className: 'picker' }, [el(document, 'span', { text: '수행' }), visitPick]));
    } else if (view.visit) {
      items.push(el(document, 'span', { className: 'picker-static', text: `수행 ${view.visitNo}` }));
    }
    if (view.attempts.length) {
      const latest = view.attempts.at(-1);
      const attemptPick = el(document, 'select', { attrs: { 'aria-label': '시도 선택' } });
      for (const attempt of view.attempts) {
        const option = el(document, 'option', { text: attemptOptionText(attempt, latest) });
        option.value = String(attempt.attempt_no);
        attemptPick.append(option);
      }
      attemptPick.value = String(view.attemptNo);
      attemptPick.addEventListener('change', () => select({ nodeId: node.node_id, visitNo: view.visitNo,
        attemptNo: Number(attemptPick.value) }));
      items.push(el(document, 'label', { className: 'picker' }, [el(document, 'span', { text: '시도' }), attemptPick]));
    }
    pickers.replaceChildren(...items);
    const notes = [];
    if (!view.visit) notes.push(el(document, 'p', { className: 'selection-note', text: '이 단계는 아직 수행되지 않았습니다.' }));
    else if (!view.attempts.length) notes.push(el(document, 'p', { className: 'selection-note', text: MESSAGES.noAttempts }));
    if (view.attempt && !view.isLatestAttempt) notes.push(el(document, 'p', { className: 'selection-note past-attempt', text: MESSAGES.pastAttempt }));
    if (view.error) {
      notes.push(el(document, 'p', { className: 'selection-error', attrs: { role: 'note' } }, [
        statusChip(document, { tone: 'error', label: `시도 ${view.attemptNo} 오류` }),
        el(document, 'span', { text: ` ${errorText(view.error)}` })]));
    }
    selectionNotes.replaceChildren(...notes);
  }

  function artifactLine(item, extra = '') {
    return `${item.role} · ${mediaTypeLabel(item.declared_media_type)} · ${formatBytes(item.size)}${extra}`;
  }

  function renderInputs(view) {
    if (view.scope === 'run') {
      panels.inputs.replaceChildren(el(document, 'p', { text: MESSAGES.runInputs }),
        keyValueList(document, [['업무', runSummary(trace).title],
          ['수정본', trace.work?.revision === undefined ? NOT_RECORDED_LABEL : `수정본 ${trace.work.revision}`]]));
      return;
    }
    const parts = [];
    if (!view.inputs.length) parts.push(el(document, 'p', { text: MESSAGES.noInputs }));
    for (const input of view.inputs) {
      const from = trace.nodes.find(node => node.node_id === input.from_node_id);
      const attempt = input.from_attempt_no === NOT_RECORDED ? '시도 번호 기록 없음' : `시도 ${input.from_attempt_no}`;
      const go = el(document, 'button', { text: '앞 단계로 이동', className: 'btn btn-quiet', attrs: { type: 'button' } });
      go.addEventListener('click', () => select({ nodeId: input.from_node_id,
        attemptNo: input.from_attempt_no === NOT_RECORDED ? null : input.from_attempt_no }, { tab: 'outputs' }));
      const list = el(document, 'ul', { className: 'plain-list' }, input.artifacts.map(item => el(document, 'li', {}, [
        el(document, 'span', { text: artifactLine(item) }),
        el(document, 'a', { text: '원본 내려받기', attrs: { href: routes.content(runId, item.artifact_id), download: `${item.role}-${item.ordinal}`, rel: 'noopener' } }),
      ])));
      parts.push(el(document, 'section', { className: 'trace-item', attrs: { 'aria-label': `입력: ${input.from_node_id}` } }, [
        el(document, 'h4', { text: `앞 단계 “${from?.responsibility ?? input.from_node_id}” (${input.from_node_id}) · ${attempt}` }),
        input.artifacts.length ? list : el(document, 'p', { text: '받은 결과에 산출물 파일이 없습니다.' }),
        el(document, 'div', { className: 'trace-actions' }, [go]),
        technicalDetails(document, [['앞 수행', input.from_execution_id], ['받은 결과 기록', refText(input.result_ref)],
          ...input.artifacts.map(item => [`${item.role} SHA-256`, item.sha256])]),
      ]));
    }
    for (const entry of view.toolCalls) {
      if (!entry.call.declared_inputs.length) continue;
      parts.push(el(document, 'section', { className: 'trace-item', attrs: { 'aria-label': '도구가 받은 입력' } }, [
        el(document, 'h4', { text: `도구 ${entry.call.tool_id}가 받은 정확한 입력` }),
        el(document, 'ul', { className: 'plain-list' }, entry.call.declared_inputs.map(item => el(document, 'li', {
          text: `${item.role} · ${mediaTypeLabel(item.media_type)} · ${formatBytes(item.declared_size)}` }))),
        technicalDetails(document, [['도구 호출 ID', entry.call.tool_call_id],
          ...entry.call.declared_inputs.map(item => [`${item.role} (${item.media_type}) SHA-256`, item.sha256])]),
      ]));
    }
    panels.inputs.replaceChildren(...parts);
  }

  function renderOutputs(view) {
    // the list's own status says when there is nothing; the lead only frames what is listed
    if (view.scope === 'run') {
      outputsLead.textContent = '이 실행이 남긴 산출물 전체입니다. 단계를 고르면 그 단계의 것만 봅니다.';
    } else if (view.scope === 'attempt') {
      outputsLead.textContent = view.outputIds.length ? `시도 ${view.attemptNo}가 남긴 산출물입니다.` : '';
    } else {
      outputsLead.textContent = view.outputIds.length ? `수행 ${view.visitNo}의 결과입니다.` : '';
    }
    if (artifacts !== null) {
      const label = view.scope === 'run' ? null : view.scope === 'attempt' ? `시도 ${view.attemptNo}의` : `수행 ${view.visitNo}의`;
      const editContext = view.scope === 'run' ? null : { nodeId: view.nodeId,
        title: role => `${role} (${view.node.responsibility} · ${view.attemptNo ? `시도 ${view.attemptNo}` : `수행 ${view.visitNo}`})` };
      artifactsReady.then(() => artifacts.filter(view.scope === 'run' ? null : view.outputIds,
        { label, nodeId: view.nodeId, editContext, producers: producers() })).catch(() => {});
    }
  }

  // artifact id -> the node whose visit recorded it first (a forwarded result is listed once by
  // the run's artifact list; the producer is the earliest visit in the trace that output it)
  function producers() {
    const found = {};
    const visits = trace.nodes.flatMap(node => node.visits.map(visit => ({ nodeId: node.node_id, visit })))
      .sort((a, b) => String(a.visit.recorded_at_utc).localeCompare(String(b.visit.recorded_at_utc)));
    for (const { nodeId, visit } of visits) {
      for (const item of visit.outputs) if (!Object.hasOwn(found, item.artifact_id)) found[item.artifact_id] = nodeId;
    }
    return found;
  }

  function handoffItem(handoff, direction) {
    const from = trace.nodes.find(node => node.node_id === handoff.from_node_id);
    const to = trace.nodes.find(node => node.node_id === handoff.to_node_id);
    const sentBy = handoff.from_attempt_no === NOT_RECORDED ? '' : ` 시도 ${handoff.from_attempt_no}`;
    const received = handoff.to_attempt_nos.length ? ` (받은 시도 ${handoff.to_attempt_nos.join(', ')})` : '';
    const title = `${from?.responsibility ?? handoff.from_node_id}${sentBy} → ${to?.responsibility ?? handoff.to_node_id}${received}`;
    const other = direction === 'in' ? handoff.from_node_id : handoff.to_node_id;
    const go = el(document, 'button', { text: direction === 'in' ? '보낸 단계로 이동' : '받은 단계로 이동',
      className: 'btn btn-quiet', attrs: { type: 'button' } });
    go.addEventListener('click', () => select({ nodeId: other }));
    return el(document, 'section', { className: 'trace-item', attrs: { 'aria-label': `전달 ${handoff.from_node_id} → ${handoff.to_node_id}` } }, [
      el(document, 'h4', { text: title }),
      keyValueList(document, [
        ['보낸 것', handoff.artifacts.length ? handoff.artifacts.map(item => artifactLine(item)).join(', ') : '산출물 파일 없음'],
        ['전달', '기록됨 (받은 수행의 입력)'],
        ['수신 확인', handoff.receipt === NOT_RECORDED ? '기록 없음' : String(handoff.receipt)],
        ['활용 근거', '기록 없음'],
      ]),
      el(document, 'div', { className: 'trace-actions' }, [go]),
      technicalDetails(document, [['보낸 수행', handoff.from_execution_id], ['받은 수행', handoff.to_execution_id],
        ['결과 기록', refText(handoff.result_ref)], ['설계된 연결', handoff.designed_edge_ids.join(', ') || '없음']]),
    ]);
  }

  function renderHandoffs(view) {
    const items = [...view.handoffsIn.map(item => handoffItem(item, 'in')),
      ...view.handoffsOut.map(item => handoffItem(item, 'out'))];
    panels.handoffs.replaceChildren(el(document, 'p', { className: 'selection-lead', text: MESSAGES.handoffHonesty }),
      ...(items.length ? items : [el(document, 'p', { text: MESSAGES.noHandoffs })]));
  }

  function toolCallItem(entry, attempt) {
    const call = entry.call;
    const [stateLabel, tone] = stateText(TOOL_CALL_STATE_TEXT, call.state);
    const dl = keyValueList(document, [
      ['단계', `${entry.nodeId} · 시도 ${entry.attemptNo}`],
      ['효과', EFFECT_CLASS_LABELS[call.effect_class] ?? call.effect_class],
      ['요청', stamp(document, call.requested_at_utc)], ['끝', stamp(document, call.settled_at_utc)],
      ['걸린 시간', durationText(call.requested_at_utc, call.settled_at_utc)],
      ['승인', call.approval_ref === NOT_RECORDED ? '승인 기록 없음(필요 없는 효과)' : '이 시도에 대한 승인 기록 있음'],
      ['결과', call.result_artifacts.length ? call.result_artifacts.map(item => artifactLine(item)).join(', ')
        : call.result_ref === NOT_RECORDED ? '결과 기록 없음' : '결과 기록 있음 (산출물 파일 없음)'],
    ]);
    const technical = [['도구 호출 ID', call.tool_call_id], ['도구', `${call.tool_id} ${call.version}`],
      ['효과 등급', call.effect_class], ['승인 기록', refText(call.approval_ref)], ['결과 기록', refText(call.result_ref)]];
    if (call.binding !== NOT_RECORDED) {
      technical.push(['그래프의 도구 연결', call.binding.binding_id], ['도구 정의', refText(call.binding.definition_ref)],
        ['권한', refText(call.binding.grant_ref)]);
    }
    if (attempt?.budget_reservation && attempt.budget_reservation !== NOT_RECORDED) {
      const reserved = attempt.budget_reservation.reserved;
      technical.push(['예약', `모델 ${reserved.model_calls} · 도구 ${reserved.tool_calls} · 출력 ${reserved.output_bytes} B`]);
    }
    return el(document, 'section', { className: 'trace-item call-item', attrs: { 'aria-label': `도구 호출 ${call.tool_id}` } }, [
      el(document, 'div', { className: 'call-head' }, [
        el(document, 'h4', { text: `도구 · ${call.tool_id} ${call.version}` }), statusChip(document, { tone, label: stateLabel })]),
      dl, technicalDetails(document, technical),
    ]);
  }

  function modelCallItem(entry) {
    const call = entry.call;
    const [stateLabel, tone] = stateText(MODEL_CALL_STATE_TEXT, call.state);
    const dl = keyValueList(document, [
      ['단계', `${entry.nodeId} · 수행 ${entry.visitNo}`],
      ['제공자 · 모델', `${call.provider} · ${call.model_label === NOT_RECORDED ? NOT_RECORDED_LABEL : call.model_label}`],
      ['토큰', `입력 ${countText(call.tokens.input)} · 출력 ${countText(call.tokens.output)}`],
      ['시작', stamp(document, call.started_at_utc)], ['끝', stamp(document, call.ended_at_utc)],
      ['걸린 시간', durationText(call.started_at_utc, call.ended_at_utc)],
      // the gap's reason only where the cost is actually not recorded
      ['비용', call.cost?.basis === NOT_RECORDED ? `${costText(call.cost)} — ${TRACE_GAP_LABELS.model_cost}`
        : costText(call.cost)],
      ['오류', call.error === null ? '없음' : call.error === NOT_RECORDED ? NOT_RECORDED_LABEL
        : `${call.error.category ?? ''} ${call.error.detail_code ?? ''}`.trim()],
    ]);
    return el(document, 'section', { className: 'trace-item call-item', attrs: { 'aria-label': `모델 호출 ${entry.nodeId}` } }, [
      el(document, 'div', { className: 'call-head' }, [
        el(document, 'h4', { text: '모델 호출' }), statusChip(document, { tone, label: stateLabel })]),
      dl,
      el(document, 'p', { className: 'call-note', text: MESSAGES.reasoning }),
      technicalDetails(document, [['호출 ID', call.call_id], ['응답한 모델', String(call.observed_model)],
        ['노력 수준', String(call.effort)], ['출력 한도', String(call.max_output_tokens)],
        ['멈춘 이유', String(call.stop_reason)], ['제공자 메시지 ID', String(call.provider_message_id)],
        ['요청 ID', String(call.request_id)], ['출력 기록', refText(call.output_ref)],
        ['캐시 토큰', `만듦 ${countText(call.tokens.cache_creation_input)} · 읽음 ${countText(call.tokens.cache_read_input)}`],
        ...(call.cost?.rates ? [['설정된 상한 단가', ratesText(call.cost.rates)]] : [])]),
    ]);
  }

  // a model attempt's provider-reported tokens, or why they are not recorded
  function attemptTokens(attempt) {
    const reservation = attempt.budget_reservation;
    if (reservation === NOT_RECORDED || !(reservation?.reserved?.model_calls > 0)) return [];
    const tokens = attempt.tokens ?? {};
    const reported = [tokens.input, tokens.output].some(value => Number.isSafeInteger(value));
    return [['토큰', reported ? `입력 ${countText(tokens.input)} · 출력 ${countText(tokens.output)}`
      : `${NOT_RECORDED_LABEL} — ${TRACE_GAP_LABELS.attempt_tokens}`]];
  }

  function attemptCost(attempt) {
    if (!attempt) return null;
    return el(document, 'section', { className: 'trace-item', attrs: { 'aria-label': `시도 ${attempt.attempt_no}의 예약과 비용` } }, [
      el(document, 'h4', { text: `시도 ${attempt.attempt_no}의 예약과 비용` }),
      keyValueList(document, [
        ...attemptTokens(attempt),
        ['비용', costText(attempt.cost)],
        ['예약', attempt.budget_reservation === NOT_RECORDED ? NOT_RECORDED_LABEL
          : `모델 ${attempt.budget_reservation.reserved.model_calls}회 · 도구 ${attempt.budget_reservation.reserved.tool_calls}회`],
        ['정산', attempt.budget_reservation === NOT_RECORDED || attempt.budget_reservation.settled === NOT_RECORDED ? NOT_RECORDED_LABEL
          : `모델 ${attempt.budget_reservation.settled.model_calls}회 · 도구 ${attempt.budget_reservation.settled.tool_calls}회`],
      ]),
      ...(attemptTokens(attempt).length ? [technicalDetails(document, [
        ['응답한 모델', String(attempt.observed_model ?? NOT_RECORDED)],
        ['제공자 메시지 ID', String(attempt.provider_message_id ?? NOT_RECORDED)],
        ['요청 ID', String(attempt.request_id ?? NOT_RECORDED)],
        ['캐시 토큰', `만듦 ${countText(attempt.tokens?.cache_creation_input)} · 읽음 ${countText(attempt.tokens?.cache_read_input)}`]])]
        : []),
    ]);
  }

  function renderCalls(view) {
    const items = [...view.modelCalls.map(modelCallItem), ...view.toolCalls.map(entry => toolCallItem(entry,
      view.attempt ?? findAttempt(entry)))];
    if (view.attempt) items.push(attemptCost(view.attempt));
    panels.calls.replaceChildren(...(items.length ? items : [el(document, 'p', { text: MESSAGES.noCalls })]));
  }

  function findAttempt(entry) {
    const node = trace.nodes.find(item => item.node_id === entry.nodeId);
    const visit = node?.visits.find(item => item.visit_no === entry.visitNo);
    return visit?.attempts.find(item => item.attempt_no === entry.attemptNo) ?? null;
  }

  function approvalItems(approvals) {
    const rows = [];
    for (const gate of approvals.gates) {
      const [label, tone] = stateText(APPROVAL_STATE_TEXT, gate.state);
      rows.push(el(document, 'li', {}, [statusChip(document, { tone, label }),
        el(document, 'span', { text: ` ${gate.node_id} · ${approvalScopeLabel(gate.approval_scope)} · ` }), stamp(document, gate.decided_at_utc)]));
    }
    for (const ask of approvals.executions) {
      const [label, tone] = stateText(APPROVAL_STATE_TEXT, ask.state);
      rows.push(el(document, 'li', {}, [statusChip(document, { tone, label }),
        el(document, 'span', { text: ` ${ask.execution_node_id} 시도 ${ask.attempt_no} · ${approvalScopeLabel(ask.approval_scope)} · ` }),
        stamp(document, ask.decided_at_utc)]));
    }
    return rows;
  }

  function renderRecords(view) {
    const parts = [];
    const approvals = approvalItems(view.approvals);
    if (approvals.length) {
      parts.push(el(document, 'section', { className: 'trace-item', attrs: { 'aria-label': '승인 기록' } }, [
        el(document, 'h4', { text: '승인 기록' }), el(document, 'ul', { className: 'plain-list' }, approvals)]));
    }
    if (view.scope === 'run') {
      parts.push(el(document, 'section', { className: 'trace-item', attrs: { 'aria-label': '멈춤 기록' } }, [
        el(document, 'h4', { text: '실행의 멈춤 기록' }),
        el(document, 'ul', { className: 'plain-list' }, trace.stops.map(stop => el(document, 'li', {}, [
          el(document, 'span', { text: `${STOP_REASON_LABELS[stop.reason] ?? stop.reason} · ` }), stamp(document, stop.at_utc)])))]));
    } else if (view.journal.length) {
      parts.push(el(document, 'section', { className: 'trace-item', attrs: { 'aria-label': `시도 ${view.attemptNo}의 기록` } }, [
        el(document, 'h4', { text: `시도 ${view.attemptNo}의 기록` }),
        el(document, 'ol', { className: 'journal' }, view.journal.map(entry => el(document, 'li', {}, [
          el(document, 'span', { className: 'journal-step', text: JOURNAL_LABELS[entry.transition] ?? entry.transition }),
          stamp(document, entry.at_utc)])))]));
    } else {
      parts.push(el(document, 'p', { text: MESSAGES.noJournal }));
    }
    if (view.visit) {
      const [label, tone] = stateText(VISIT_STATUS_TEXT, view.visit.status);
      parts.push(el(document, 'p', { className: 'visit-record' }, [el(document, 'span', { text: `수행 ${view.visitNo} 기록 시각 ` }),
        stamp(document, view.visit.recorded_at_utc), el(document, 'span', { text: ' · ' }), statusChip(document, { tone, label })]));
    }
    parts.push(el(document, 'p', {}, [el(document, 'a', { text: MESSAGES.recordsLink, className: 'records-link',
      attrs: { href: `./records.html#run=${runId}` } })]));
    panels.records.replaceChildren(...parts);
  }

  // on a narrow screen the panel sits under the views: a pick in the graph or the timeline
  // brings it into view; side by side it is already there
  function revealSelection() {
    const panelBox = roots.selection.getBoundingClientRect?.();
    const viewsBox = roots.views.getBoundingClientRect?.();
    if (!panelBox || !viewsBox || typeof roots.selection.scrollIntoView !== 'function') return;
    if (panelBox.top >= viewsBox.bottom - 1) roots.selection.scrollIntoView({ block: 'start' });
  }

  function renderSelection({ focus = false } = {}) {
    const view = selectionView(trace, selection);
    renderHead(view);
    renderInputs(view);
    renderOutputs(view);
    renderHandoffs(view);
    renderCalls(view);
    renderRecords(view);
    markTimeline();
    if (focus && typeof roots.selection.scrollIntoView === 'function') {
      roots.selection.scrollIntoView({ block: 'nearest' });
    }
    if (typeof onSelectionChange === 'function') onSelectionChange(selection, view);
    return view;
  }

  // the one selection both views share
  function select(next, options = {}) {
    if (trace === null) {
      if (runId !== null) pending = { next, options };
      return null;
    }
    const { focus = false, tab = null, fromGraph = false, reveal = false } = options;
    selection = resolveSelection(trace, next);
    if (!fromGraph && graph !== null && typeof graph.select === 'function') {
      if (selection.nodeId !== null) graph.select(selection.nodeId, { notify: false });
      else graph.clear?.();
    }
    if (tab !== null) detailTabs.select(tab, { notify: false });
    const view = renderSelection({ focus });
    if (reveal) revealSelection();
    return view;
  }

  async function show(nextRunId, { artifactsLoad = null } = {}) {
    // another run starts from the whole run; the same run read again keeps its selection
    if (nextRunId !== runId || trace === null) {
      trace = null;
      pending = null;
      selection = Object.freeze({ nodeId: null, visitNo: null, attemptNo: null });
    }
    runId = nextRunId;
    const mine = ++generation;
    artifactsReady = artifactsLoad ?? Promise.resolve(null);
    roots.summary.replaceChildren(el(document, 'p', { attrs: { role: 'status' }, text: MESSAGES.loading }));
    try {
      const value = traceView(await request(traceRoute(basePath, nextRunId), {}));
      if (mine !== generation) return null;
      trace = value;
      const keep = selection.nodeId !== null ? resolveSelection(trace, selection) : null;
      selection = keep ?? Object.freeze({ nodeId: null, visitNo: null, attemptNo: null });
      renderSummary();
      renderBanner();
      renderFinal();
      renderTimeline();
      const picked = pending;
      pending = null;
      if (picked !== null) select(picked.next, picked.options);
      else renderSelection();
      return trace;
    } catch (error) {
      if (mine === generation) {
        trace = null;
        roots.summary.replaceChildren(el(document, 'p', { attrs: { role: 'alert' }, text: MESSAGES.failed }));
      }
      throw error;
    }
  }

  function reset() {
    trace = null;
    runId = null;
    pending = null;
    selection = Object.freeze({ nodeId: null, visitNo: null, attemptNo: null });
  }

  return Object.freeze({
    show, select, reset, selectTab: id => detailTabs.select(id, { notify: false }),
    selectView: id => viewTabs.select(id, { notify: false }),
    get trace() { return trace; }, get selection() { return selection; }, get runId() { return runId; },
  });
}
