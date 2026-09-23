# DeepTwin Control Workspace UI Implementation Plan

> **역사적 시제품 경계:** 그래프/산출물/대안 관계를 검토한 기록은 보존하지만, 제공자와
> 배포 경계는 후속 정본이 대체한다. 현재 제품은 자체 호스팅 웹 기반 오픈소스 프레임워크와
> 공식 브라우저 UI이며, Claude는 API-only, Codex 구독은 서버 소유 관리형 실행기를 사용한다.
> 아래 양쪽 구독 또는 로컬 앱 표현은 현재 구현 요구가 아니다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the revised, graph-first Korean control-workspace prototype so a nondeveloper can inspect candidate structures, exact typed outputs, alternative evidence and paired prior-queue examples without mistaking simulated states for a working DeepTwin engine.

**Architecture:** A new `control-prototype/` directory preserves the rejected `prototype/` unchanged. Native browser modules share one version-aware state model across design/run/growth areas and workspace/conversation/graph views. Static, explicitly synthetic fixtures provide coherent graphs and real local files; user test drafts remain separate from every pre-authored diagnosis and evaluation.

**Tech Stack:** Existing Node built-in HTTP/test modules, browser ES modules, HTML/CSS/SVG and tab-scoped sessionStorage; no new package installation. Browser verification uses the already bundled Playwright module and installed Chrome. This is a prototype choice, not a production framework decision.

---

## Status, authority and evidence

The user confirmed the integrated UI specification §11, then authorized this UI-only implementation with “시작해” in response to the implementation handoff. **Scoped code implementation, independent specification/quality reviews and automated/visual checks are complete; actual user screen acceptance is pending.** The final source `4954450` passed all 79 tests without failures or skips. The local server is running; the Codex open request was queued and actual visible display could not be checked because the Mac is locked. This document plus the [fixture code packet](2026-09-06-control-workspace-fixtures.md) is one plan; its checkboxes track verified execution, not authoring completion. Actual agent/model/browser-tool execution, authentication, billing, automatic learning, production export and environment promotion remain out of scope. Execution evidence is tracked in [the implementation ledger](../../ui/control-workspace-implementation.md); user UI acceptance remains unconfirmed.

Source: [UI specification](../specs/2026-09-06-deeptwin-ui-structure-design.md) §10.1, §10.3–10.7 and §11; [review cases](../../ui/initial-ui-review-cases.md). Later direct user corrections outrank earlier generic UI proposals. Do not reuse the old user work description, failed manual POC, old prototype's fixed role/text data, or user alternatives as fixtures. Preserve the existing dirty UI plans and historical failed observations.

The working directory for every command below is `<repo>`. `node` means the available `<node-runtime>/dependencies/node/bin/node` when PATH lacks it. Commands are for the implementing agent; the user is not asked to operate a CLI. Read `frontend-design` before UI implementation, `pdf` before creating/rendering fixture PDFs, and the relevant testing/review skills during execution. Do not install or connect a provider to make a demonstration look real.

## Boundaries and reversible prototype decisions

- First view: execution graph of the synthetic source run, with design and growth accessible immediately. This aids the identity review; it does not fix the production first-use/default mode.
- Design comparison: all three full graphs share an inspection focus; each graph can scroll at a readable size. A pre-authored merged version demonstrates version/review semantics, never automatic natural-language design generation.
- Formats: text/Markdown has whole/region and actual character-range selection; CSV has a rendered table and declared region selection; SVG has a native image view; PDF has a real file plus a clearly labeled SVG page derivative. File alternatives can be attached to a precise target in memory. Native universal document/image editors, arbitrary-file execution and automated semantic comparison are not implemented.
- Drafts: exact run/attempt/artifact/scope keys, 20,000 characters per field, tab storage only. File bytes remain memory-only; a reload does not pretend to restore them. No migration of the rejected prototype's storage key.
- Persist only after successful storage writes; failed reads block automatic replacement. Reset removes this new key only, after confirmation; failed deletion leaves memory intact. Draft typing does not rerender the focused textarea or infer submission/learning.
- Fixture exploration is separate from current test input. Switching to the fixed example never creates a causal link between a fresh draft and pre-authored lenses, scores or candidates. No fake progress animation, model response, login, action success or approval completion.
- Ordinary UI uses work language. Only the audit detail names synthetic lens routes, definitions/combinations and rejected candidates. Those records are not actual philosophical-source verification or error-independence evidence.
- Connection/record/approval details are read-only demonstrations. Record selection and redaction preview operate, but no file export or transmission is claimed. Explicit API choice is displayed as unconnected, never invoked automatically.

## Files and dependency order

All paths below are relative to the working directory stated above and therefore identify exact files; no globs are used for staging.

| Task | New files | Responsibility |
| --- | --- | --- |
| 1 | `control-prototype/fixtures.mjs`, `build-assets.mjs`, `tests/fixtures.test.mjs`, `assets/` generated allowlisted files | Coherent synthetic graphs, source/alternative/paired artifacts, actual file bytes and provenance. Full code in fixture packet. |
| 2 | `control-prototype/state.mjs`, `tests/state.test.mjs` | Version/scoped navigation, drafts, read/write/reset failure boundaries. |
| 3 | `control-prototype/primitives.mjs`, `tests/primitives.test.mjs` | Escaping, readable graph, format-specific artifact views. |
| 4 | `control-prototype/workspace.mjs`, `tests/workspace.test.mjs` | Three work areas, aligned design comparison, run inspection, separated example investigation and paired evaluation. |
| 5 | `control-prototype/server.mjs`, `tests/server.test.mjs` | Local explicit allowlist, minimum CSP and no repository exposure. |
| 6 | `control-prototype/app.mjs`, `index.html`, `styles.css`, `tests/browser.test.mjs` | Browser events, IME-safe editing, modal/selection/file lifetime, responsive shell. |
| 7 | `control-prototype/tests/browser-review.test.mjs`, `README.md`; `docs/ui/control-workspace-review.md` | Actual DOM checks, screenshots, implementation evidence and user review handoff. |

Tasks 2 and 3 can run independently after the fixture interfaces are committed. Task 4 depends on both; Task 5 can run alongside 2–4. Task 6 depends on 4 and 5. Task 7 integrates all. Each task gets its own spec-compliance and code-quality review before dependent work. The plan's self-review is performed by the author, not delegated.

## Task 1: Synthetic fixture and real-file contract

**Files:** the three source/test files and generated allowlist specified in [the fixture packet](2026-09-06-control-workspace-fixtures.md). That packet contains the complete code, tests and exact RED/GREEN commands for this task; do not substitute a new fixture schema.

- [x] Follow the packet's failing-test step, verify the intended failure, add its implementation and verify the tests. Before its first asset-generation command, follow the PDF skill's authoring marker instructions once for the expected PDF outputs; do not run that marker while merely reading this plan.
- [x] Render generated PDF pages with the bundled PDF tooling and inspect the rendered pages beside their SVG derivatives. PDF bytes/metadata tests do not prove layout fidelity. Fix clipped or mismatched content before accepting the fixture.
- [x] Commit only the explicit files/assets in the packet. No actual user documents, credentials, source PDFs or prior prototype files are copied.

## Task 2: Shared scoped state and honest persistence

**Create:** `control-prototype/tests/state.test.mjs`, then `control-prototype/state.mjs`.

- [x] Write the failing state tests:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { RUNS, ARTIFACTS } from '../fixtures.mjs';
import { createState, transition, context, draftKey, load, save, reset, KEY } from '../state.mjs';
const memory = () => { const m = new Map(); return { m, getItem:k=>m.get(k)??null, setItem:(k,v)=>m.set(k,v), removeItem:k=>m.delete(k) }; };
test('drafts and context survive views, overlays and exact attempts', () => {
  let s=createState(); const before=context(s); const key=draftKey(s);
  s=transition(s,{type:'draft',value:'\n\n나의 시험 버전'});
  for(const mode of ['workspace','conversation','graph']) s=transition(s,{type:'mode',value:mode});
  s=transition(s,{type:'overlay',value:'logs'}); s=transition(s,{type:'overlay',value:'connection'}); s=transition(s,{type:'close'});
  assert.deepEqual(context(s),before); assert.equal(s.drafts[key],'\n\n나의 시험 버전');
  const other=Object.keys(RUNS).find(id=>id!==s.run);
  s=transition(s,{type:'run',value:other}); assert.notEqual(draftKey(s),key);
  s=transition(s,{type:'run',value:before.run}); assert.equal(draftKey(s),key);
});
test('empty output never inherits latest artifact; malformed scopes rejected',()=>{
  let s=createState(); const r=Object.values(RUNS).find(r=>r.attempts.some(a=>!a.outputs.length));
  const empty=r.attempts.find(a=>!a.outputs.length);
  s=transition(s,{type:'attempt',run:r.id,value:empty.id}); assert.equal(context(s).artifact,null);
  assert.equal(transition(s,{type:'scope',value:{kind:'text',start:0,end:2}}),s);
  s=createState(); assert.equal(transition(s,{type:'artifact',value:'missing'}),s);
});
test('partial scope is keyed; sample is never a result of fresh input',()=>{
  let s=createState(); const c=context(s),region=ARTIFACTS[c.artifact].regions[0];
  const whole=draftKey(s); s=transition(s,{type:'scope',value:{kind:'region',id:region.id}});
  assert.notEqual(draftKey(s),whole); s=transition(s,{type:'draft',value:'한국어 부분 대안'});
  assert.equal(s.sample,false); s=transition(s,{type:'sample',value:true}); assert.equal(s.sample,true);
  s=transition(s,{type:'draft',value:'다른 시험 입력'}); assert.equal(s.sample,false);
});
test('persistence does not overwrite unread snapshots or reset on failure',()=>{
  const storage=memory(),s=createState(); storage.m.set('other','keep');
  assert.equal(save(storage,s,false).ok,true); assert.deepEqual(load(storage).state,s);
  storage.m.set(KEY,'broken'); const restored=load(storage); assert.equal(restored.blocked,true);
  assert.equal(save(storage,s,true).ok,false); assert.equal(storage.m.get(KEY),'broken');
  assert.equal(save(storage,s,false).ok,true); assert.equal(reset(storage).ok,true); assert.equal(storage.m.get('other'),'keep');
  assert.equal(reset({removeItem(){throw Error('blocked')}}).ok,false);
  assert.equal(load({getItem(){throw Error('blocked')}}).blocked,true);
  assert.equal(save({setItem(){throw Error('quota')}},s,false).ok,false);
  const bad=structuredClone(s);bad.drafts['["missing",null,[],null,{"kind":"whole"}]']='orphan';
  storage.m.set(KEY,JSON.stringify(bad));assert.equal(load(storage).blocked,true);
  const resource=RUNS[s.run].nodes.find(n=>!RUNS[s.run].attempts.some(a=>a.node===n.id));
  const inspected=transition(s,{type:'node',value:resource.id});assert.equal(context(inspected).attempt,null);assert.equal(context(inspected).artifact,null);
});
```

- [x] Run `node --test control-prototype/tests/state.test.mjs`. Expected: FAIL because `state.mjs` does not exist. A syntax error or broken fixture is not the intended failure.
- [x] Add the complete state implementation:

```js
import { ARTIFACTS, RUNS, DESIGNS, REVISED_DESIGN, CASE, ROUNDS, LOGS } from './fixtures.mjs';
export const KEY='deeptwin:control-ui:v1';
const areas=['design','run','growth'],modes=['workspace','conversation','graph'];
const designs=[...DESIGNS,REVISED_DESIGN];
const startingRun=Object.values(RUNS).find(r=>r.attempts.some(a=>a.outputs.includes(CASE.original)));
const firstTarget=run=>{ const a=run.attempts.find(a=>a.outputs.includes(CASE.original))??run.attempts.find(a=>a.outputs.length)??run.attempts[0]; return {node:a.node,attempt:a.id,artifact:a.outputs[0]??null,scope:{kind:'whole'}}; };
export function createState(){return {version:1,area:'run',mode:'graph',run:startingRun.id,targets:{[startingRun.id]:firstTarget(startingRun)},design:DESIGNS[0].id,focus:'transfer',round:ROUNDS[0].id,pairs:{},sample:false,difference:CASE.differences[0].id,drafts:{},notes:{},workText:'',designText:'',overlay:null,records:[],redact:true};}
export function context(s){return {run:s.run,...s.targets[s.run]};}
export function draftKey(s){const c=context(s),a=RUNS[c.run].attempts.find(a=>a.id===c.attempt);return JSON.stringify([c.run,c.attempt,a?.inputs??[],c.artifact,c.scope]);}
export function noteKey(s){return JSON.stringify([s.area,s.area==='design'?s.design:s.area==='growth'?[s.sample,s.difference,s.round]:draftKey(s)]);}
function validTarget(run,t){
  if(!run||!t)return false;const a=run.attempts.find(a=>a.id===t.attempt);
  if(!a)return t.attempt===null&&t.artifact===null&&t.scope?.kind==='whole'&&run.nodes.some(n=>n.id===t.node);
  if(a.node!==t.node||!(t.artifact===null&&!a.outputs.length||[...a.inputs,...a.outputs].includes(t.artifact)))return false;
  const sc=t.scope,f=ARTIFACTS[t.artifact];
  return sc?.kind==='whole'||!!f&&(sc?.kind==='region'&&f.regions.some(r=>r.id===sc.id)||sc?.kind==='text'&&f.type==='text'&&Number.isInteger(sc.start)&&Number.isInteger(sc.end)&&sc.start>=0&&sc.start<sc.end&&sc.end<=f.body.length);
}
export function transition(s,a){
  const n=structuredClone(s),t=n.targets[n.run];
  if(a.type==='area'&&areas.includes(a.value))n.area=a.value;
  else if(a.type==='mode'&&modes.includes(a.value))n.mode=a.value;
  else if(a.type==='run'&&RUNS[a.value]){n.run=a.value;n.targets[n.run]??=firstTarget(RUNS[n.run]);}
  else if(a.type==='attempt'){
    const run=RUNS[a.run??s.run],attempt=run?.attempts.find(x=>x.id===a.value);if(!attempt)return s;
    n.run=run.id;n.targets[n.run]={node:attempt.node,attempt:attempt.id,artifact:attempt.outputs[0]??null,scope:{kind:'whole'}};
  }else if(a.type==='node'){
    const run=RUNS[s.run],last=[...run.attempts].reverse().find(x=>x.node===a.value);if(!run.nodes.some(x=>x.id===a.value))return s;
    if(!last){n.targets[n.run]={node:a.value,attempt:null,artifact:null,scope:{kind:'whole'}};return n;}
    return transition(s,{type:'attempt',value:last.id});
  }else if(a.type==='artifact'){
    const attempt=RUNS[s.run].attempts.find(x=>x.id===t.attempt);if(!attempt||![...attempt.inputs,...attempt.outputs].includes(a.value))return s;
    t.artifact=a.value;t.scope={kind:'whole'};
  }else if(a.type==='scope'){t.scope=a.value;if(!validTarget(RUNS[s.run],t))return s;}
  else if(a.type==='draft'&&typeof a.value==='string'&&a.value.length<=20000&&t.artifact){n.drafts[draftKey(s)]=a.value;n.sample=false;}
  else if(a.type==='note'&&typeof a.value==='string'&&a.value.length<=20000)n.notes[noteKey(s)]=a.value;
  else if(['workText','designText'].includes(a.type)&&typeof a.value==='string'&&a.value.length<=20000)n[a.type]=a.value;
  else if(a.type==='design'&&designs.some(x=>x.id===a.value))n.design=a.value;
  else if(a.type==='focus'&&['transfer','approval','memory','evaluation'].includes(a.value))n.focus=a.value;
  else if(a.type==='round'&&ROUNDS.some(x=>x.id===a.value))n.round=a.value;
  else if(a.type==='pair'){
    const r=ROUNDS.find(x=>x.id===s.round),run=RUNS[a.side==='baseline'?r.baselineRun:r.candidateRun];
    if(!['baseline','candidate'].includes(a.side)||!(run.attempts.some(x=>x.id===a.value)||typeof a.value==='string'&&a.value.startsWith('@')&&run.nodes.some(x=>x.id===a.value.slice(1))))return s;
    n.pairs[`${s.round}:${a.side}`]=a.value;
  }else if(a.type==='sample')n.sample=a.value===true;
  else if(a.type==='difference'&&CASE.differences.some(x=>x.id===a.value))n.difference=a.value;
  else if(a.type==='overlay'&&['connection','logs','audit','approval','artifact'].includes(a.value))n.overlay=a.value;
  else if(a.type==='close')n.overlay=null;
  else if(a.type==='record'&&LOGS.some(x=>x.id===a.value))n.records=n.records.includes(a.value)?n.records.filter(x=>x!==a.value):[...n.records,a.value];
  else if(a.type==='redact')n.redact=!!a.value;
  else return s;return n;
}
function checked(raw){
  if(typeof raw!=='string'||raw.length>2000000)throw Error('size');const x=JSON.parse(raw),seed=createState();
  if(x.version!==1||!areas.includes(x.area)||!modes.includes(x.mode)||!RUNS[x.run]||!validTarget(RUNS[x.run],x.targets?.[x.run]))throw Error('context');
  if(!designs.some(d=>d.id===x.design)||!['transfer','approval','memory','evaluation'].includes(x.focus)||!ROUNDS.some(r=>r.id===x.round)||!CASE.differences.some(d=>d.id===x.difference))throw Error('reference');
  if(Object.keys(x).some(k=>!Object.hasOwn(seed,k)))throw Error('schema');
  for(const [id,t] of Object.entries(x.targets))if(!validTarget(RUNS[id],t))throw Error('target');
  for(const name of ['drafts','notes','pairs'])if(!x[name]||Array.isArray(x[name])||Object.values(x[name]).some(v=>typeof v!=='string'||v.length>20000))throw Error('text');
  for(const key of Object.keys(x.drafts)){
    const parts=JSON.parse(key);if(!Array.isArray(parts)||parts.length!==5)throw Error('draft key');
    const [id,attempt,inputs,artifact,scope]=parts,run=RUNS[id],a=run?.attempts.find(a=>a.id===attempt);
    if(!a||!artifact||JSON.stringify(inputs)!==JSON.stringify(a.inputs)||!validTarget(run,{node:a.node,attempt,artifact,scope}))throw Error('draft reference');
  }
  for(const [key,value] of Object.entries(x.pairs)){
    const [id,side]=key.split(':'),round=ROUNDS.find(r=>r.id===id);if(!round||!['baseline','candidate'].includes(side))throw Error('pair key');
    const run=RUNS[side==='baseline'?round.baselineRun:round.candidateRun];if(!run.attempts.some(a=>a.id===value)&&!(value.startsWith('@')&&run.nodes.some(n=>n.id===value.slice(1))))throw Error('pair reference');
  }
  if(!Array.isArray(x.records)||x.records.some(v=>typeof v!=='string')||typeof x.sample!=='boolean'||typeof x.redact!=='boolean')throw Error('flags');
  if(x.records.some(id=>!LOGS.some(log=>log.id===id))||new Set(x.records).size!==x.records.length)throw Error('record reference');
  if(typeof x.workText!=='string'||typeof x.designText!=='string'||x.workText.length>20000||x.designText.length>20000)throw Error('fields');
  if(x.overlay!==null&&!['connection','logs','audit','approval','artifact'].includes(x.overlay))throw Error('overlay');return x;
}
export function load(storage){try{const raw=storage.getItem(KEY);return {state:raw===null?createState():checked(raw),blocked:false,message:raw===null?'이 탭의 새 시험 상태':'이 탭의 보관본 복원 · 첨부 파일은 복원하지 않음'};}catch{return {state:createState(),blocked:true,message:'보관본 읽기 실패 · 이전 값은 덮어쓰지 않음'};}}
export function save(storage,state,blocked){if(blocked)return {ok:false,message:'자동 보관 중지 · 기존 보관본 유지'};try{storage.setItem(KEY,JSON.stringify(state));return {ok:true,message:'이 탭에만 보관 · 파일 첨부는 메모리에만 있음'};}catch{return {ok:false,message:'보관 실패 · 현재 입력은 메모리에 남음 · 새로고침 주의'};}}
export function reset(storage){try{storage.removeItem(KEY);return {ok:true};}catch{return {ok:false,message:'초기화 실패 · 현재 작성 내용 유지'};}}
```

- [x] Run `node --test control-prototype/tests/state.test.mjs`. Expected: all four tests PASS; no skipped tests.
- [x] Commit: `git add -- control-prototype/state.mjs control-prototype/tests/state.test.mjs` then `git commit -m "feat: add scoped control workspace state"`.

## Task 3: Graph and typed artifact primitives

**Create:** `control-prototype/tests/primitives.test.mjs`, then `control-prototype/primitives.mjs`.

- [x] Write the failing tests:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { ARTIFACTS, DESIGNS } from '../fixtures.mjs';
import { e, graph, artifact } from '../primitives.mjs';
test('graphs expose nodes, edges and synchronized functions',()=>{
  for(const d of DESIGNS){const html=graph(d,d.focus.approval,'designNode');
    for(const n of d.nodes)assert.ok(html.includes(`data-value="${n.id}"`));
    assert.equal((html.match(/data-edge=/g)??[]).length,d.edges.length);
    assert.ok(html.includes('관계도'));assert.ok(html.includes('tabindex="0"'));}
});
test('all formats retain original file access and distinct representation',()=>{
  for(const f of Object.values(ARTIFACTS)){const html=artifact(f.id);assert.ok(html.includes(f.path));
    if(f.type==='csv')assert.match(html,/<table/);if(f.type==='svg')assert.match(html,/<img/);
    if(f.type==='pdf'){assert.ok(html.includes(f.preview));assert.ok(html.includes('파생 미리보기'));}
    if(f.type==='text')assert.match(html,/<pre/);}
  assert.equal(e('</textarea><script>'),'&lt;/textarea&gt;&lt;script&gt;');
  assert.ok(artifact(null).includes('출력 없음'));assert.ok(artifact('missing').includes('미확인'));
});
```

- [x] Run `node --test control-prototype/tests/primitives.test.mjs`. Expected: missing-module FAIL.
- [x] Add the complete primitives:

```js
import { ARTIFACTS } from './fixtures.mjs';
export const e=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const button=(label,action,value='',active=false)=>`<button type="button" data-action="${e(action)}" data-value="${e(value)}" aria-pressed="${active}">${e(label)}</button>`;
export const list=items=>`<ul>${items.map(x=>`<li>${e(x)}</li>`).join('')}</ul>`;
export function graph(g,selected=[],action='node',prefix=''){
  const node=id=>g.nodes.find(n=>n.id===id),arrow=`arrow-${g.id}-${action}-${prefix.replace(/[^a-zA-Z0-9-]/g,'')}`;
  const kinds={task:'산출물',control:'통제',memory:'기억',tool:'도구·모델',telemetry:'관측',revisit:'되돌아감'};
  return `<div class="graph-scroll" tabindex="0" aria-label="관계도 가로 탐색"><svg class="graph" viewBox="0 0 900 520" role="group" aria-label="${e(g.label??g.id)} 관계도">
  <defs><marker id="${e(arrow)}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path class="arrow" d="M0 0 L10 5 L0 10 Z"/></marker></defs>
  ${g.edges.map((edge,i)=>{const a=node(edge.from),b=node(edge.to);return `<path marker-end="url(#${e(arrow)})" data-edge="${i}" class="edge ${e(edge.kind)}" d="M ${a.x+70} ${a.y+48} C ${a.x+70} ${a.y+95}, ${b.x+70} ${b.y-38}, ${b.x+70} ${b.y}"/><text class="edge-label" x="${(a.x+b.x)/2+70}" y="${(a.y+b.y)/2+24}">${e(kinds[edge.kind]??edge.kind)}</text>`;}).join('')}
  ${g.nodes.map(n=>`<g class="node ${e(n.kind)} ${selected.includes(n.id)?'selected':''}" role="button" tabindex="0" aria-label="${e(n.label)}" aria-pressed="${selected.includes(n.id)}" data-action="${e(action)}" data-value="${e(prefix+n.id)}"><rect x="${n.x}" y="${n.y}" width="140" height="48" rx="7"/><text x="${n.x+8}" y="${n.y+19}">${e(n.label)}</text><text class="kind" x="${n.x+8}" y="${n.y+37}">${e({agent:'에이전트',control:'통제',resource:'자원'}[n.kind])}</text></g>`).join('')}</svg></div>`;
}
export function artifact(id,{selectable=false,scope={kind:'whole'}}={}){
  if(!id)return '<p class="empty">출력 없음 · 다른 시도의 최신 파일로 채우지 않음</p>';
  const f=ARTIFACTS[id];if(!f)return '<p class="empty">산출물 미확인</p>';
  let body='';
  if(f.type==='text')body=`<pre ${selectable?'id="original-body"':''}>${e(f.body)}</pre>`;
  if(f.type==='csv'){const rows=f.body.trimEnd().split('\n').map(r=>r.split(','));body=`<div class="table-scroll"><table>${rows.map((row,i)=>`<tr>${row.map(v=>`<${i?'td':'th'}>${e(v)}</${i?'td':'th'}>`).join('')}</tr>`).join('')}</table></div>`;}
  if(f.type==='svg')body=`<div class="artifact-canvas"><img class="artifact-image" src="${e(f.path)}" alt="${e(f.label)} 전체 이미지"/></div>`;
  if(f.type==='pdf')body=`<p class="notice">원 PDF의 동일 조판 자료로 만든 SVG 파생 미리보기 · 원본은 아래 파일에서 확인</p><div class="artifact-canvas"><img class="artifact-image pdf" src="${e(f.preview)}" alt="${e(f.label)} 페이지 파생 미리보기"/></div>`;
  const excerpt=scope.kind==='region'?f.regions.find(r=>r.id===scope.id)?.text:scope.kind==='text'?f.body.slice(scope.start,scope.end):null;
  return `<article data-artifact="${e(id)}"><header><strong>${e(f.label)}</strong><small>${e(id)} · ${e(f.type)}</small></header>${body}<a href="${e(f.path)}" target="_blank" rel="noopener" download>원본 파일 열기/받기</a>${selectable?`<div class="scope-controls">${button('전체','scope','whole',scope.kind==='whole')}${f.regions.map(r=>button(r.label,'scope',r.id,scope.kind==='region'&&scope.id===r.id)).join('')}${f.type==='text'?button('선택한 실제 문구','textScope'):''}</div>${excerpt?`<blockquote data-selected-region>${e(excerpt)}</blockquote>`:''}<p>현재 범위: ${e(scope.kind==='whole'?'전체':scope.kind==='region'?f.regions.find(r=>r.id===scope.id)?.label:`문자 ${scope.start}–${scope.end}`)}</p>`:''}</article>`;
}
```

- [x] Run `node --test control-prototype/tests/primitives.test.mjs`. Expected: both tests PASS. The CSV renderer is deliberately limited to the controlled, unquoted fixture cells; it must not be presented as an arbitrary CSV importer.
- [x] Commit: `git add -- control-prototype/primitives.mjs control-prototype/tests/primitives.test.mjs` then `git commit -m "feat: render graphs and typed fixture artifacts"`.

## Task 4: Connected work areas, not independent result cards

**Create:** `control-prototype/tests/workspace.test.mjs`, then `control-prototype/workspace.mjs`.

- [x] Write the failing tests:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { DESIGNS, REVISED_DESIGN, ROUNDS, CASE } from '../fixtures.mjs';
import { createState, transition } from '../state.mjs';
import { render, overlay } from '../workspace.mjs';
test('candidate focus compares functions and merged review remains new',()=>{
  let s=transition(createState(),{type:'area',value:'design'});s=transition(s,{type:'focus',value:'approval'});
  const html=render(s);for(const d of DESIGNS){assert.ok(html.includes(d.label));assert.ok(html.includes(d.contracts.approval));}
  s=transition(s,{type:'design',value:REVISED_DESIGN.id});assert.ok(render(s).includes(REVISED_DESIGN.version));
  assert.ok(overlay(s,'approval').includes('미연결'));
});
test('new drafts cannot receive fixed diagnosis; sample exposes complete loop',()=>{
  let s=transition(createState(),{type:'draft',value:'내가 새로 입력한 실제 시험 문구'});s=transition(s,{type:'area',value:'growth'});
  assert.ok(render(s).includes('분석 결과 없음'));assert.ok(!render(s).includes(CASE.differences[0].hypotheses[0].claim));
  s=transition(s,{type:'sample',value:true});const html=render(s);
  assert.ok(html.includes(CASE.original));assert.ok(html.includes(CASE.alternative));
  for(const r of ROUNDS)assert.ok(html.includes(r.id));assert.ok(html.includes('별도 최종 근거'));assert.ok(html.includes('부분 밖 영향'));
});
test('three modes preserve area-specific objects, not disabled tabs',()=>{
  for(const area of ['design','run','growth'])for(const mode of ['workspace','conversation','graph']){
    let s=transition(createState(),{type:'area',value:area});s=transition(s,{type:'mode',value:mode});
    const html=render(s);assert.ok(html.includes(`data-area="${area}"`));assert.ok(html.includes(`data-mode="${mode}"`));
    if(mode==='conversation')assert.ok(html.includes('data-field="note"'));
    assert.ok(html.includes('data-value="connection"'));assert.ok(html.includes('data-value="logs"'));
  }
});
```

- [x] Run `node --test control-prototype/tests/workspace.test.mjs`. Expected: missing-module FAIL.
- [x] Add this complete rendering module. All pre-authored work/diagnosis/evaluation text comes from the explicit fixture exports; fresh test input is escaped and stored separately.

```js
import { ARTIFACTS, RUNS, DESIGNS, REVISED_DESIGN, CASE, ROUNDS, WORK_MODEL, LOGS } from './fixtures.mjs';
import { context, draftKey, noteKey } from './state.mjs';
import { e, button as b, list, graph, artifact } from './primitives.mjs';
const focusLabels={transfer:'산출물 전달',approval:'책임·승인',memory:'기억 접근',evaluation:'평가·관측'};
const jobName=id=>({j1:'화요일 공간 이용',j2:'목요일 공간 이용'}[id]??id);
const allDesigns=[...DESIGNS,REVISED_DESIGN];
const panel=(title,body)=>`<section class="panel"><h2>${e(title)}</h2>${body}</section>`;
const field=(name,label,value)=>`<label class="editor-label">${e(label)}<textarea maxlength="20000" data-field="${name}">${e(value)}</textarea></label>`;
function ribbon(s){
  if(s.area==='design'){const d=allDesigns.find(d=>d.id===s.design);return `검토 중 설계 ${d.version} · 공통 업무 모델 · 실제 구성 없음`;}
  if(s.area==='growth')return s.sample?`고정 합성 사례 ${CASE.id} · 비교 ${s.round} · 현재 입력의 분석 결과가 아님`:'현재 시험 입력 · 실제 대안 분석/평가 없음';
  const c=context(s),r=RUNS[c.run];return `환경 ${r.env} · 업무 ${jobName(r.job)} · 실행 ${r.id} · 관찰 ${r.observedAt} · 수행 ${c.attempt??'기록 없음'} · 산출물 ${c.artifact??'없음'}`;
}
function design(s){
  const chosen=allDesigns.find(d=>d.id===s.design);
  const cards=DESIGNS.map(d=>`<section class="candidate" data-design="${e(d.id)}"><h3>${e(d.label)} · ${e(d.version)}</h3>${graph(d,d.focus[s.focus],'designNode',d.id+':')}<p>${e(d.contracts[s.focus])}</p><p>같은 기능의 위치: ${d.focus[s.focus].map(id=>e(d.nodes.find(n=>n.id===id)?.label)).join(' / ')||'없음'}</p><p class="notice">${e(d.review)}</p>${b('이 구조 살펴보기','design',d.id,d.id===s.design)}</section>`).join('');
  return panel('업무와 설계의 연결',`<p>${e(WORK_MODEL.purpose)}</p><p>완료: ${e(WORK_MODEL.done)}</p><p>출처: ${e(WORK_MODEL.source)}</p><p>미확정: ${e(WORK_MODEL.unknown)}</p><details><summary>업무 설명·자료 입력의 UI 확인</summary>${field('workText','시험용 업무 설명 · 자동 분석하지 않음',s.workText)}<p>자료 자동 해석·업무 모델 생성 미연결. 아래 모델은 고정 예시입니다.</p></details>`)
  +`<div class="focus-bar">${Object.entries(focusLabels).map(([k,v])=>b(v,'focus',k,s.focus===k)).join('')}</div><div class="candidates">${cards}</div>`
  +panel('선택한 설계와 수정 이력',`<h3>${e(chosen.label)} · ${e(chosen.version)}</h3>${graph(chosen,chosen.focus[s.focus],'designNode',chosen.id+':')}<p>${e(chosen.contracts[s.focus])}</p><p>${e(chosen.review)}</p>${field('designText','업무 언어로 남기는 수정 요청 · 생성 미연결',s.designText)}${b('사전 구성된 병합 예시 보기','design',REVISED_DESIGN.id)}<p>이 버튼은 위 요청을 처리하지 않습니다. 병합 예시는 별도 버전이며 원안의 합격·승인을 상속하지 않습니다.</p>${b('정확한 승인 대상 미리보기','overlay','approval')}${b('생성·검토 감사 예시','overlay','audit')}`);
}
function inspector(s){
  const c=context(s),r=RUNS[c.run],a=r.attempts.find(a=>a.id===c.attempt),node=r.nodes.find(n=>n.id===c.node);
  const history=r.attempts.filter(x=>x.node===c.node);
  const files=ids=>ids.length?ids.map(id=>b(ARTIFACTS[id].label,'artifact',id,c.artifact===id)).join(''):'<p>없음</p>';
  return panel(node?.label??'선택 대상',`<div class="history">${history.map(x=>b(`수행 ${x.stage} / 시도 ${x.try} · ${x.status}`,'attempt',x.id,x.id===c.attempt)).join('')}</div><p>${e(a?.status??'이 노드의 수행 기록 없음')}</p><h3>정확한 입력</h3>${files(a?.inputs??[])}<h3>개별 출력</h3>${files(a?.outputs??[])}<h3>실제 수신 수행</h3>${(a?.consumers??[]).map(x=>b(`${x.artifact} → ${x.attempt}`,'consumer',x.attempt)).join('')||'<p>전달 기록 없음</p>'}<details><summary>도구·평가·전달 사건</summary>${list(a?.events??['사건 기록 없음'])}</details><p class="notice">예정 연결 ≠ 전달 기록 ≠ 적절한 활용 ≠ 인과 증거</p>`);
}
function editor(s){
  const c=context(s);if(!c.artifact)return '';
  return panel('같은 상태에서 나의 버전',`${artifact(c.artifact,{selectable:true,scope:c.scope})}${b('원본을 넓게 보기','overlay','artifact')}${field('draft','전체 또는 선택한 부분의 자기 버전 · 이유 불필요',s.drafts[draftKey(s)]??'')}<p id="draft-status">${s.drafts[draftKey(s)]?'시험용 초안 있음 · 미분석':'자기 대안 없음'}</p><label>시험용 대안 파일 · 이 탭 메모리에만 보관<input id="alternative-file" type="file" accept=".pdf,.png,.jpg,.jpeg,.svg,.csv,.md,.txt"/></label><div id="file-status"></div><p class="notice">보이는 원본과 초안은 그대로 보존합니다. 첨부·편집·부분 선택 자체는 학습/실험/승인이 아닙니다.</p>${b('현재 입력의 개선 영역','currentGrowth')}`);
}
function run(s){
  const c=context(s),r=RUNS[c.run],g=graph(r,[c.node]);
  const selector=`<div class="run-picker">${Object.values(RUNS).map(r=>b(`${jobName(r.job)} / ${r.id} / ${r.env}`,'run',r.id,r.id===s.run)).join('')}</div>`;
  const relation=s.mode==='graph'?g:`<details class="context-graph"><summary>동일 실행의 전체 관계도</summary>${g}</details>`;
  return selector+`<div class="workbench">${panel('실행 관제 · 합성 기록',relation)+inspector(s)}</div>`+editor(s);
}
function pair(s,side,round){
  const r=RUNS[side==='baseline'?round.baselineRun:round.candidateRun];
  const selected=s.pairs[`${round.id}:${side}`],empty=selected?.startsWith('@')?{id:null,node:selected.slice(1),inputs:[],outputs:[],consumers:[],events:['선택 자원의 수행 기록 없음 · 추정으로 채우지 않음'],status:'기록 미확인'}:null;
  const a=empty??r.attempts.find(a=>a.id===selected)??[...r.attempts].reverse().find(a=>a.outputs.length)??r.attempts[0];
  return panel(side==='baseline'?'비교 기준 실행':'변경 후보 실행',`<p>${e(jobName(r.job))} · ${e(r.id)} · 환경 ${e(r.env)}</p>${graph(r,[a.node],'pairNode',side+':')}<div>${r.attempts.map(x=>b(`수행 ${x.stage}/시도 ${x.try} ${x.status}`,'pairAttempt',side+':'+x.id,x.id===a.id)).join('')}</div><p>입력: ${a.inputs.map(e).join(', ')||'없음'} · ${e(a.status)}</p>${a.inputs.length?`<details><summary>선택 수행의 입력 실물</summary>${a.inputs.map(id=>artifact(id)).join('')}</details>`:''}${a.outputs.map(id=>artifact(id)).join('')||artifact(null)}<details><summary>선택 수행 사건·후속 전달</summary>${list(a.events)}${list(a.consumers.map(x=>`${x.artifact} → ${x.attempt}`))}</details>`);
}
function growth(s){
  if(!s.sample)return panel('현재 입력의 개선 영역',`<p>분석 결과 없음 · 실제 탐구·실험 엔진 미연결</p><p>현재 자기 버전과 작성 맥락은 보존됩니다. 미리 만든 가설·평가를 이 입력의 분석 결과로 붙이지 않습니다.</p>${b('원 산출물로 돌아가기','area','run')}${b('별도의 고정 합성 사례 탐색','sample','yes')}`);
  const d=CASE.differences.find(d=>d.id===s.difference),origin=Object.values(RUNS).find(r=>r.attempts.some(a=>a.outputs.includes(CASE.original))),round=ROUNDS.find(r=>r.id===s.round);
  return `<p class="sample-banner">사전 구성된 합성 사례 · 현재 시험 입력과 별개 · 실제 진단/렌즈/평가 결과가 아님</p>${b('현재 시험 입력으로 돌아가기','sample','no')}`
  +panel('원본과 비교군 · 부분 대안',`<p>고정 사례 ${e(CASE.id)} · 부분 ${e(CASE.region)}</p><div class="pair">${artifact(CASE.original)}${artifact(CASE.alternative)}</div><div>${CASE.differences.map(x=>b(x.label,'difference',x.id,x.id===d.id)).join('')}</div><p>관찰 원본: ${e(d.original)}</p><p>관찰 대안: ${e(d.alternative)}</p>`)
  +panel('차이와 관련 실행 · 원인 미확정',graph(origin,d.nodes,'sampleNode')+d.hypotheses.map(h=>`<article class="hypothesis"><h3>${e(h.kind==='system'?'시스템 설명':'판단 조건 설명')} · ${e(h.claim)}</h3><dl><dt>지지</dt><dd>${e(h.support)}</dd><dt>반대</dt><dd>${e(h.counter)}</dd><dt>미설명</dt><dd>${e(h.unknown)}</dd><dt>구별할 새 업무</dt><dd>${e(h.probe)}</dd><dt>새 증거의 상태</dt><dd>${e(h.newEvidence)}</dd></dl></article>`).join('')+b('출처·조합·탈락 감사 예시','overlay','audit'))
  +panel('이전 업무 큐 · 모든 비교 회차',`<div class="rounds">${ROUNDS.map(r=>b(`${jobName(r.job)} · ${r.id} · ${r.result}`,'round',r.id,r.id===s.round)).join('')}</div><p>현재 후보 ${e(round.candidate)} · ${e(round.result)}</p><p>비교 조건/한계: ${e(round.limits)}</p><div class="pair">${pair(s,'baseline',round)}${pair(s,'candidate',round)}</div><h3>부분 밖 영향과 검사 근거</h3><table><tr><th>검사</th><th>상태</th><th>근거</th></tr>${round.checks.map(c=>`<tr><td>${e(c.label)}</td><td>${e(c.result)}</td><td>${b(c.evidence,'evidence',c.evidence)}</td></tr>`).join('')}</table><p>별도 최종 근거: ${e(round.finalEvidence)}</p><p>최종 승인 대상/상태: ${e(round.approval)}</p>${b('정확한 승인 대상 미리보기','overlay','approval')}<p>승인 기록 ≠ 운영 적용. 반복 튜닝 결과를 미관측 최종 근거로 재사용하지 않습니다.</p>`);
}
export function overlay(s,id){
  if(id==='artifact')return artifact(context(s).artifact);
  if(id==='approval'){
    const d=allDesigns.find(x=>x.id===s.design),r=ROUNDS.find(x=>x.id===s.round);
    return `<h2>승인 대상 미리보기 · 실제 승인 미연결</h2><p>${e(s.area==='design'?`설계 버전 ${d.version} · ${d.review}`:s.area==='growth'&&s.sample?`환경 후보 ${r.candidate} · ${r.approval}`:'이번 외부 행동의 실제 요청 없음')}</p><p>검증·사용자 결정·실제 적용은 별도입니다. 이 창을 닫거나 열어도 권한·운영 버전은 바뀌지 않습니다.</p><button disabled>실제 승인·적용 미연결</button>`;
  }
  if(id==='connection')return `<h2>연결·도구·복구</h2><p>현재 대상: ${e(ribbon(s))}</p><table><tr><th>실행 경로</th><th>현재 상태</th></tr><tr><td>Claude 본인 구독</td><td>제품 필수 요구 · 공식 통합 미검증/미연결</td></tr><tr><td>Codex 본인 구독</td><td>제품 필수 요구 · 공식 통합 미검증/미연결</td></tr><tr><td>사용자가 선택하는 API</td><td>미연결 · 자동 과금 전환 없음</td></tr></table><p>브라우저·파일 생성 도구는 프레임워크가 관리할 대상입니다. 이 시제품은 도구를 호출하지 않습니다.</p><p>예시 복구 조건: 권한 부족 작업만 대기; 결과 미확인 외부 쓰기는 확인 전 반복하지 않음; 확인된 저장 경계 밖 복원은 미확인.</p><p>초안의 실제 탭 보관 상태는 주 화면 하단에서 확인합니다. 로그인 버튼이나 성공 애니메이션은 제공하지 않습니다.</p>`;
  if(id==='audit')return `<h2>감사 예시 · 실제 엔진 미연결</h2><p>미세렌즈 정의·조합·탈락·예측은 합성 이력이며 철학 원전 검증·오류 독립성 증거가 아닙니다.</p>${['generation','critic','diagnosis'].map((key,i)=>`<h3>${['초기 설계 생성','별도 크리틱 검토','대안 이후 차이 탐구'][i]}</h3>${list(CASE.audit[key])}`).join('')}<p>해석 기록은 감사용입니다. 후보의 근거에는 별도의 새 업무 증거가 필요하며 원 수행 입력에 대안·사후 해석을 넣지 않습니다.</p>`;
  if(id==='logs')return `<h2>기록 선택·가림 미리보기</h2><p>배포 후 프레임워크가 관측 가능한 첫 제어 사건부터 요청·설계·변경·실행·대안·탐구·실패·승인 기록을 연결할 제품 요구입니다. 아래는 고정 합성 목록입니다.</p>${LOGS.map(x=>`<label class="record"><input type="checkbox" data-record="${e(x.id)}" ${s.records.includes(x.id)?'checked':''}/> ${e(x.label)} <small>${e(s.redact?'출처 가림 예시':x.source)}</small></label>`).join('')}<label><input type="checkbox" id="redact" ${s.redact?'checked':''}/> 출처 표지만 가림 · 본문 자동 가림 아님</label><p>선택 ${s.records.length}개 · 이 시제품은 실제 묶음 추출/전송을 하지 않습니다. 원문 결손·재현 한계는 숨기지 않습니다.</p><button disabled>실제 추출 미연결</button><button disabled>제작자 전달 미연결</button><p>추출과 전송은 별개이며 공유 없이도 업무를 이용할 수 있습니다.</p>`;
  return '<p>선택한 상세 없음</p>';
}
export function render(s){
  const title={design:'설계 비교',run:'실행 관제',growth:'개선 실험'}[s.area];
  const note=s.mode==='conversation'?panel('동일 대상의 대화',`<p>${e(ribbon(s))}</p>${field('note','시험용 대화 메모 · 전송/자동 분석 없음',s.notes[noteKey(s)]??'')}`):'';
  return `<div class="shell" data-area="${s.area}" data-mode="${s.mode}"><aside class="rail"><h1>DeepTwin</h1><p>멀티에이전트 관제</p>${Object.entries({design:'설계 비교',run:'실행 관제',growth:'개선 실험'}).map(([k,v])=>b(v,'area',k,s.area===k)).join('')}<div class="utilities">${b('연결·복구','overlay','connection')}${b('기록 추출','overlay','logs')}</div></aside><main><div class="sample-banner">화면 시제품 · 합성 실행 기록 · AI/외부 도구/학습 미연결</div><header class="ribbon">${e(ribbon(s))}</header><div class="heading"><h1 tabindex="-1" id="page-title">${title}</h1><nav aria-label="같은 대상의 보기">${Object.entries({workspace:'작업공간',conversation:'대화',graph:'그래프'}).map(([k,v])=>b(v,'mode',k,s.mode===k)).join('')}</nav></div>${note}${s.area==='design'?design(s):s.area==='run'?run(s):growth(s)}<footer><p id="storage-status" role="status"></p>${b('탭 보관 다시 시도','save')}${b('시험용 작성 내용 초기화','reset')}<p>이 탭 보관은 영구 저장이 아닙니다. 첨부 파일은 새로고침하면 없어집니다.</p></footer></main></div>`;
}
```

- [x] Run `node --test control-prototype/tests/workspace.test.mjs`. Expected: all three tests PASS. Do not accept string-presence checks as the final UI identity test; Task 7 exercises the actual relationships and human review.
- [x] Commit: `git add -- control-prototype/workspace.mjs control-prototype/tests/workspace.test.mjs` then `git commit -m "feat: connect design run and improvement workspaces"`.

## Task 5: Explicit local server boundary

**Create:** `control-prototype/tests/server.test.mjs`, then `control-prototype/server.mjs`.

- [x] Write the failing tests:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { ARTIFACTS } from '../fixtures.mjs';
import { createServer, port } from '../server.mjs';
test('only explicit local assets can be read; no writes or traversal',async()=>{
  const server=createServer();server.listen(0,'127.0.0.1');await once(server,'listening');
  const request=(path,method='GET')=>new Promise((resolve,reject)=>{const req=http.request({host:'127.0.0.1',port:server.address().port,path,method},res=>{const chunks=[];res.on('data',x=>chunks.push(x));res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(chunks)}));});req.on('error',reject);req.end();});
  try{
    for(const path of ['/server.mjs','/tests/server.test.mjs','/../README.md','/%2e%2e/README.md','/.git/config','/assets/missing.pdf'])assert.equal((await request(path)).status,404);
    assert.equal((await request('/','POST')).status,405);
    const pdf=Object.values(ARTIFACTS).find(f=>f.type==='pdf'),r=await request('/'+pdf.path.replace(/^\//,''));
    assert.equal(r.status,200);assert.equal(r.body.subarray(0,5).toString(),'%PDF-');
    assert.equal(r.headers['content-type'],'application/pdf');
    assert.match(r.headers['content-security-policy'],/connect-src 'none'/);assert.match(r.headers['content-security-policy'],/object-src 'none'/);
    assert.equal(port(undefined),4183);for(const bad of ['0','65536','abc'])assert.throws(()=>port(bad));
  }finally{await new Promise(resolve=>server.close(resolve));}
});
```

- [x] Run `node --test control-prototype/tests/server.test.mjs`. Expected: missing-module FAIL, assuming Task 1 assets are present.
- [x] Add the server:

```js
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { ARTIFACTS } from './fixtures.mjs';
const routes=new Map([['/',['index.html','text/html; charset=utf-8']],['/index.html',['index.html','text/html; charset=utf-8']],['/styles.css',['styles.css','text/css; charset=utf-8']]]);
for(const name of ['app','fixtures','state','primitives','workspace'])routes.set(`/${name}.mjs`,[`${name}.mjs`,'text/javascript; charset=utf-8']);
const mime={pdf:'application/pdf',svg:'image/svg+xml',csv:'text/csv; charset=utf-8',md:'text/plain; charset=utf-8',txt:'text/plain; charset=utf-8'};
for(const f of Object.values(ARTIFACTS))for(const path of [f.path,f.preview].filter(Boolean)){
  const local=path.replace(/^\//,'');if(!/^assets\/[a-zA-Z0-9._-]+$/.test(local))throw Error('Unsafe fixture asset path');
  const ext=local.split('.').at(-1);if(!mime[ext])throw Error('Unsupported fixture extension');routes.set('/'+local,[local,mime[ext]]);
}
const csp="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
export function createServer(){return http.createServer(async(req,res)=>{
  res.setHeader('Content-Security-Policy',csp);res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','no-referrer');res.setHeader('Cache-Control','no-store');
  const end=(status,text)=>{res.writeHead(status,{'Content-Type':'text/plain; charset=utf-8'});res.end(text);};
  if(req.method!=='GET'){res.setHeader('Allow','GET');return end(405,'GET only');}
  let path;try{path=decodeURIComponent((req.url??'').split('?')[0]);}catch{return end(400,'Invalid path');}
  if(!path.startsWith('/')||path.includes('\\')||path.includes('\0')||path.split('/').some(x=>x.startsWith('.')))return end(404,'Not found');
  const f=routes.get(path);if(!f)return end(404,'Not found');
  try{const data=await readFile(new URL(f[0],import.meta.url));res.writeHead(200,{'Content-Type':f[1]});res.end(data);}catch{return end(500,'Local asset unavailable');}
});}
export function port(value){if(value===undefined)return 4183;if(!/^\d+$/.test(value)||Number(value)<1||Number(value)>65535)throw Error('PORT must be 1–65535');return Number(value);}
if(process.argv[1]&&pathToFileURL(resolve(process.argv[1])).href===import.meta.url){
  const server=createServer();server.on('error',err=>{console.error(err.code==='EADDRINUSE'?'Port in use; choose another PORT.':'Local server failed.');process.exitCode=1;});
  const chosen=port(process.env.PORT);server.listen(chosen,'127.0.0.1',()=>console.log(`DeepTwin control UI: http://127.0.0.1:${chosen}`));
}
```

- [x] Run `node --test control-prototype/tests/server.test.mjs`. Expected: PASS, including real PDF byte delivery. Server source, tests, asset generator and repository documents must remain unavailable over HTTP.
- [x] Commit: `git add -- control-prototype/server.mjs control-prototype/tests/server.test.mjs` then `git commit -m "feat: serve control UI on a restricted loopback endpoint"`.

## Task 6: Browser interaction and presentation

**Create:** `control-prototype/tests/browser.test.mjs`, `app.mjs`, `index.html`, `styles.css`.

- [x] Write the failing DOM test below. The dependency is Task 5, not a package installation. A missing Playwright environment setting is an explicit failure, never a skipped test represented as success.

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { pathToFileURL } from 'node:url';
import { createServer } from '../server.mjs';
import { CASE, ARTIFACTS, RUNS } from '../fixtures.mjs';
const modulePath=process.env.CONTROL_PLAYWRIGHT_MODULE;
if(!modulePath)throw Error('Set CONTROL_PLAYWRIGHT_MODULE to the existing bundled Playwright module.');
const {chromium}=await import(pathToFileURL(modulePath).href);
test('real DOM preserves exact input, relationships and simulation boundary',async()=>{
  const server=createServer();server.listen(0,'127.0.0.1');await once(server,'listening');
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.locator('#page-title').waitFor();assert.equal(await page.locator('#page-title').textContent(),'실행 관제');
    const own=page.locator('[data-field="draft"]');
    for(const prefix of ['','\n','\n\n\n']){
      const text=prefix+'한국어 시험 초안 </textarea><script>bad</script>';
      await own.fill(text);
      for(const mode of ['conversation','graph','workspace'])await page.locator(`[data-action="mode"][data-value="${mode}"]`).click();
      assert.equal(await own.inputValue(),text);await page.reload();assert.equal(await own.inputValue(),text);
    }
    await page.locator('[data-action="overlay"][data-value="logs"]').click();await page.locator('#detail-close').click();
    assert.ok((await own.inputValue()).includes('한국어 시험 초안'));
    await page.locator('[data-action="currentGrowth"]').click();assert.ok((await page.locator('main').textContent()).includes('분석 결과 없음'));
    assert.equal(await page.getByText(CASE.differences[0].hypotheses[0].claim,{exact:true}).count(),0);
    await page.locator('[data-action="sample"][data-value="yes"]').click();assert.ok((await page.locator('main').textContent()).includes('사전 구성된 합성 사례'));
    assert.ok(await page.locator('.pair [data-artifact]').count()>=4);
    await page.locator('[data-action="area"][data-value="run"]').click();
    const r=Object.values(RUNS).find(r=>r.attempts.some(a=>!a.outputs.length));
    await page.locator(`[data-action="run"][data-value="${r.id}"]`).click();
    const empty=r.attempts.find(a=>!a.outputs.length);
    await page.locator('[data-action="mode"][data-value="graph"]').click();
    await page.locator(`[data-action="node"][data-value="${empty.node}"]`).first().click();
    await page.locator(`[data-action="attempt"][data-value="${empty.id}"]`).click();
    assert.equal(await page.locator('[data-field="draft"]').count(),0);
    assert.ok((await page.locator('main').textContent()).includes(empty.status));
    const pdf=Object.values(ARTIFACTS).find(f=>f.type==='pdf');const res=await page.request.get(`http://127.0.0.1:${server.address().port}/${pdf.path.replace(/^\//,'')}`);
    assert.equal((await res.body()).subarray(0,5).toString(),'%PDF-');assert.deepEqual(errors,[]);
  }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
});
```

- [x] Run `CONTROL_PLAYWRIGHT_MODULE=<node-runtime>/dependencies/node/node_modules/playwright/index.mjs node --test control-prototype/tests/browser.test.mjs`. Expected: FAIL because the new entry/UI does not yet exist, not because dependencies or fixture references are wrong.
- [x] Add `control-prototype/index.html`:

```html
<!doctype html>
<html lang="ko"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><title>DeepTwin · 관제 작업대 시제품</title><link rel="stylesheet" href="/styles.css"/></head><body><div id="app"></div><dialog id="detail-dialog" aria-label="현재 대상의 상세"><button id="detail-close" type="button">닫기</button><div id="detail-body"></div></dialog><script type="module" src="/app.mjs"></script></body></html>
```

- [x] Add `control-prototype/app.mjs`:

```js
import { ARTIFACTS, RUNS, CASE, DESIGNS, REVISED_DESIGN, ROUNDS } from './fixtures.mjs';
import { createState, transition, context, draftKey, noteKey, load, save, reset } from './state.mjs';
import { render, overlay } from './workspace.mjs';
import { e, artifact, list } from './primitives.mjs';
const root=document.querySelector('#app'),dialog=document.querySelector('#detail-dialog'),body=document.querySelector('#detail-body');
let storage;try{storage=window.sessionStorage;}catch{storage=null;}
const loaded=load(storage);let state=loaded.state,blocked=loaded.blocked,status=loaded.message,trigger=null,selection=null;
const attachments=new Map();
function showStatus(){document.querySelector('#storage-status').textContent=status;}
function persist(){const r=save(storage,state,blocked);status=r.message;showStatus();return r;}
function showFile(){
  const box=document.querySelector('#file-status');if(!box)return;box.replaceChildren();const item=attachments.get(draftKey(state));
  const draftStatus=document.querySelector('#draft-status');if(draftStatus)draftStatus.textContent=(state.drafts[draftKey(state)]||item)?'시험용 자기 버전 초안 있음 · 미분석':'자기 대안 없음';
  const p=document.createElement('p');p.textContent=item?`${item.file.name} · ${item.file.size} bytes · 현재 범위에 첨부 · 메모리 전용`:'이 범위의 파일 첨부 없음 · 새로고침 뒤 복원되지 않음';box.append(p);
  if(item){const a=document.createElement('a');a.href=item.url;a.download=item.file.name;a.textContent='첨부한 실제 파일 받기';box.append(a);if(['image/png','image/jpeg'].includes(item.file.type)){const img=document.createElement('img');img.className='artifact-image';img.src=item.url;img.alt='사용자가 첨부한 시험 이미지';box.append(img);}}
}
function paint(){
  root.innerHTML=render(state);selection=null;
  for(const el of root.querySelectorAll('textarea[data-field]')){
    const key=el.dataset.field;el.value=key==='draft'?state.drafts[draftKey(state)]??'':key==='note'?state.notes[noteKey(state)]??'':state[key];
  }
  showStatus();showFile();
}
function detail(id,from){state=transition(state,{type:'overlay',value:id});trigger=from;body.innerHTML=overlay(state,id);if(!dialog.open)dialog.showModal();document.querySelector('#detail-close').focus();persist();}
function close(){state=transition(state,{type:'close'});if(dialog.open)dialog.close();trigger?.focus({preventScroll:true});trigger=null;persist();}
document.querySelector('#detail-close').addEventListener('click',close);dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
function change(action){const active=document.activeElement,keep=active?.dataset.action?[active.dataset.action,active.dataset.value]:null;state=transition(state,action);paint();persist();const next=keep?root.querySelector(`[data-action="${CSS.escape(keep[0])}"][data-value="${CSS.escape(keep[1]??'')}"]`):null;(next??document.querySelector('#page-title')).focus({preventScroll:true});}
function capture(){
  selection=null;const pick=window.getSelection(),box=document.querySelector('#original-body');if(!box||!pick||pick.isCollapsed||pick.rangeCount!==1)return;
  const range=pick.getRangeAt(0);if(!box.contains(range.startContainer)||!box.contains(range.endContainer))return;
  const prefix=document.createRange();prefix.selectNodeContents(box);prefix.setEnd(range.startContainer,range.startOffset);const start=prefix.toString().length,end=start+range.toString().length;
  selection={key:draftKey(state),scope:{kind:'text',start,end}};
}
document.addEventListener('selectionchange',capture);root.addEventListener('pointerup',capture);root.addEventListener('keyup',capture);
root.addEventListener('pointerdown',event=>{if(event.target.closest('[data-action="textScope"]')){capture();event.preventDefault();}});
root.addEventListener('input',event=>{
  const el=event.target;if(!(el instanceof HTMLTextAreaElement)||!el.dataset.field)return;
  state=transition(state,{type:el.dataset.field,value:el.value});persist();
  if(el.dataset.field==='draft')showFile();
});
root.addEventListener('change',event=>{
  if(event.target.id!=='alternative-file')return;const file=event.target.files?.[0];if(!file)return;
  if(file.size>5*1024*1024||!['pdf','png','jpg','jpeg','svg','csv','md','txt'].includes(file.name.split('.').at(-1).toLowerCase())){status='첨부 거절 · 허용 형식의 5 MiB 이하 시험 파일만 사용';showStatus();return;}
  const key=draftKey(state),old=attachments.get(key);if(old)URL.revokeObjectURL(old.url);attachments.set(key,{file,url:URL.createObjectURL(file)});state=transition(state,{type:'sample',value:false});showFile();
});
dialog.addEventListener('change',event=>{
  if(event.target.dataset.record)state=transition(state,{type:'record',value:event.target.dataset.record});
  else if(event.target.id==='redact')state=transition(state,{type:'redact',value:event.target.checked});else return;
  const record=event.target.dataset.record,isRedact=event.target.id==='redact';body.innerHTML=overlay(state,state.overlay);persist();
  (isRedact?body.querySelector('#redact'):body.querySelector(`[data-record="${CSS.escape(record)}"]`))?.focus();
});
function act(target){
  const action=target.dataset.action,value=target.dataset.value;
  if(action==='overlay')return detail(value,target);
  if(action==='textScope'){if(selection?.key===draftKey(state))change({type:'scope',value:selection.scope});return;}
  if(action==='scope')return change({type:'scope',value:value==='whole'?{kind:'whole'}:{kind:'region',id:value}});
  if(action==='sample')return change({type:'sample',value:value==='yes'});
  if(action==='currentGrowth'){state=transition(state,{type:'sample',value:false});return change({type:'area',value:'growth'});}
  if(action==='consumer')return change({type:'attempt',value});
  if(action==='evidence'&&ARTIFACTS[value]){trigger=target;body.innerHTML='<h2>고정 사례의 평가 근거 · 합성 자료</h2>'+artifact(value);dialog.showModal();document.querySelector('#detail-close').focus();return;}
  if(action==='designNode'){const id=value.split(':')[0];return change({type:'design',value:id});}
  if(action==='pairNode'||action==='pairAttempt'){
    const [side,id]=value.split(':'),r=ROUNDS.find(r=>r.id===state.round),run=RUNS[side==='baseline'?r.baselineRun:r.candidateRun];
    const attempt=action==='pairNode'?[...run.attempts].reverse().find(a=>a.node===id):run.attempts.find(a=>a.id===id);if(attempt)return change({type:'pair',side,value:attempt.id});if(action==='pairNode')return change({type:'pair',side,value:'@'+id});return;
  }
  if(action==='sampleNode'){
    const r=Object.values(RUNS).find(r=>r.attempts.some(a=>a.outputs.includes(CASE.original))),a=[...r.attempts].reverse().find(a=>a.node===value);
    trigger=target;body.innerHTML=`<h2>고정 사례의 관련 실행 · ${e(r.id)}</h2><p>${e(a?.id??'수행 기록 없음')}</p>${list(a?.events??[])}${(a?.outputs??[]).map(id=>artifact(id)).join('')}`;dialog.showModal();document.querySelector('#detail-close').focus();return;
  }
  if(action==='save'){
    if(blocked&&!window.confirm('읽지 못한 기존 보관본을 현재 시험 상태로 교체할까요? 취소하면 양쪽을 유지합니다.'))return;
    const result=save(storage,state,false);if(result.ok)blocked=false;status=result.message;showStatus();return;
  }
  if(action==='reset'){
    if(!window.confirm('이 수정 시제품의 시험 입력과 첨부만 초기화할까요?'))return;const r=reset(storage);if(!r.ok){status=r.message;showStatus();return;}
    for(const item of attachments.values())URL.revokeObjectURL(item.url);attachments.clear();state=createState();blocked=false;status='이 시제품의 시험 입력만 초기화됨';paint();return;
  }
  change({type:action,value});
}
root.addEventListener('click',event=>{const target=event.target.closest('[data-action]');if(target&&!target.disabled)act(target);});
root.addEventListener('keydown',event=>{const g=event.target.closest('g[data-action]');if(g&&['Enter',' '].includes(event.key)){event.preventDefault();act(g);}});
window.addEventListener('pagehide',()=>{for(const item of attachments.values())URL.revokeObjectURL(item.url);attachments.clear();});
window.addEventListener('pageshow',showFile);
paint();if(state.overlay)detail(state.overlay,null);
```

- [x] Add `control-prototype/styles.css`. The visual treatment follows the accepted control-workbench structure: dark operational canvas, high-contrast paper artifacts, restrained teal active state, amber limitations. It does not reuse the rejected document-card shell.

```css
:root{color-scheme:light dark;--bg:light-dark(#edf2f3,#0e151a);--panel:light-dark(#fff,#17232a);--ink:light-dark(#172c34,#e1edf0);--muted:light-dark(#536972,#9db2bd);--line:light-dark(#c7d5da,#3a505c);--active:light-dark(#087f83,#56d7d3);--warn:light-dark(#855e0c,#f4cb73);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;background:var(--bg);color:var(--ink)}
*{box-sizing:border-box}body{margin:0}button,input,textarea{font:inherit}button,a,input{touch-action:manipulation}button{border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--ink);padding:8px 11px;cursor:pointer;margin:3px}button[aria-pressed=true]{border-color:var(--active);box-shadow:inset 0 -2px var(--active)}button:disabled{cursor:not-allowed;opacity:.55}:focus-visible{outline:3px solid var(--active);outline-offset:3px}a{color:var(--active)}h1{font-size:25px;line-height:1.25}h2{font-size:19px;margin:0 0 13px}h3{font-size:16px}p{margin:9px 0}small{color:var(--muted);display:block;overflow-wrap:anywhere}
.shell{display:grid;grid-template-columns:216px minmax(0,1fr);min-height:100vh}.rail{background:#14252d;color:#e6f1f2;padding:24px 14px;position:sticky;top:0;height:100vh;display:flex;flex-direction:column;gap:8px}.rail button{background:#1d333d;color:#e6f1f2;text-align:left}.utilities{margin-top:auto;display:grid}main{min-width:0;padding:18px 24px}.sample-banner{background:light-dark(#e3eff0,#16383c);padding:9px 13px;border-radius:6px;font-size:13px}.ribbon{padding:11px 0;color:var(--muted);font:12px/1.6 ui-monospace,monospace;overflow-wrap:anywhere;border-bottom:1px solid var(--line)}.heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.heading nav{display:flex;flex-wrap:wrap}.panel,.candidate{border:1px solid var(--line);background:var(--panel);border-radius:10px;padding:17px;margin:13px 0;min-width:0}.workbench{display:grid;grid-template-columns:minmax(0,1.8fr) minmax(270px,1fr);gap:16px}.candidates{display:grid;grid-template-columns:1fr;gap:13px}.pair{display:grid;grid-template-columns:1fr;gap:16px}.focus-bar{position:sticky;top:0;background:var(--bg);padding:8px 0;z-index:2}.history,.run-picker,.rounds{display:flex;gap:4px;flex-wrap:wrap}.notice,.empty{color:var(--warn);font-size:13px}.editor-label{display:block;margin:16px 0;font-weight:600}textarea{display:block;width:100%;min-height:135px;padding:12px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:7px;font-weight:400;resize:vertical}.record{display:block;margin:12px 0}.record small{padding-left:25px}input[type=file]{display:block;max-width:100%;margin:8px 0}.hypothesis{border-left:3px solid var(--active);padding:10px 15px;margin:14px 0}dl{display:grid;grid-template-columns:90px minmax(0,1fr);gap:8px}dt{font-weight:600}dd{margin:0;overflow-wrap:anywhere}details{padding:10px 0}summary{cursor:pointer;font-weight:600}footer{border-top:1px solid var(--line);margin-top:25px;padding:20px 0;color:var(--muted)}
.graph-scroll{overflow:auto;border:1px solid #334852;border-radius:8px;background:#111c23;max-width:100%}.graph{display:block;width:100%;min-width:760px;height:auto}.graph text{fill:#edf6f6;font:13px -apple-system,"Apple SD Gothic Neo",sans-serif}.graph .kind{fill:#a6bcc7;font-size:11px}.node{cursor:pointer}.node rect{fill:#1d303b;stroke:#64808f;stroke-width:1.5}.node.control rect{fill:#342e21;stroke:#c3a666;stroke-dasharray:5 3}.node.resource rect{fill:#242c3b;stroke:#879bbc;stroke-dasharray:2 3}.node.selected rect,.node:focus rect{stroke:#5ef0dd;stroke-width:3}.edge{fill:none;stroke:#6cadb8;stroke-width:1.5}.edge.control{stroke:#caad75;stroke-dasharray:5 3}.edge.memory,.edge.tool,.edge.telemetry,.edge.resource{stroke:#8995be;stroke-dasharray:2 4}.edge.revisit,.edge.return{stroke:#d195e7}.graph .edge-label{fill:#c5d6dc;font-size:10px}.arrow{fill:#91bfc7}
article[data-artifact]{background:light-dark(#fff,#f4f6f3);color:#21343b;border:1px solid #b8c8cd;padding:16px;border-radius:8px;margin:12px 0;min-width:0}article[data-artifact] a{color:#086d72}article[data-artifact] small{color:#536b76}article[data-artifact] button{background:#edf5f4;color:#21343b}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit;font-size:15px;line-height:1.75}.artifact-canvas{overflow:auto;max-width:100%}.artifact-canvas .artifact-image{min-width:612px}.artifact-image{display:block;width:100%;height:auto;max-height:850px;object-fit:contain;border:1px solid #c1cfd0}.pdf{background:white}.table-scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px;table-layout:fixed}td,th{border:1px solid var(--line);padding:8px;text-align:left;overflow-wrap:anywhere}article table{--line:#bccbcf}.scope-controls{margin-top:12px}.scope-controls+p{font-size:12px}dialog{width:min(1100px,94vw);max-height:92vh;overflow:auto;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:12px;padding:20px}dialog::backdrop{background:#08141bcc}#detail-close{position:sticky;top:0;float:right;z-index:4}#detail-body{clear:both;min-width:0}
@media(max-width:1150px){.candidates{grid-template-columns:1fr}.candidate .graph{min-width:760px}.workbench{grid-template-columns:1fr}.pair{grid-template-columns:1fr}.rail{width:auto}main{padding:16px}}@media(max-width:700px){.shell{display:block}.rail{position:static;height:auto;padding:13px;display:flex;flex-direction:row;flex-wrap:wrap;gap:3px}.rail h1,.rail p{width:100%;margin:2px 0}.utilities{margin:0;display:flex;flex-wrap:wrap}.heading{display:block}main{padding:10px}.panel,.candidate{padding:12px}.focus-bar{position:static}dl{grid-template-columns:1fr}dd{margin-bottom:9px}.graph{min-width:760px}.ribbon{font-size:11px}}
```

- [x] Run `CONTROL_PLAYWRIGHT_MODULE=<node-runtime>/dependencies/node/node_modules/playwright/index.mjs node --test control-prototype/tests/browser.test.mjs`. Expected: PASS. Automated DOM composition, Enter activation of an actual selection, graph focus and modal return were checked. Physical Korean IME and OS-level BFCache navigation remain unverified and are not inferred from these tests.
- [x] Commit: `git add -- control-prototype/app.mjs control-prototype/index.html control-prototype/styles.css control-prototype/tests/browser.test.mjs` then `git commit -m "feat: add interactive control-workspace browser shell"`.

## Task 7: Failure-path verification and actual screen review

**Create:** `control-prototype/tests/browser-review.test.mjs`, `control-prototype/README.md`, `docs/ui/control-workspace-review.md`. The tests generate screenshots under `control-prototype/review-output/`; do not stage these until they have been inspected for accidental user/private content.

- [x] Add the complete regression/visual-capture test. Each failed behavioral assertion requires a targeted failing regression followed by the minimal fix in its responsible module; it is not waived because the other views look correct.

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createServer } from '../server.mjs';
import { KEY } from '../state.mjs';
import { CASE, ROUNDS } from '../fixtures.mjs';
const modulePath=process.env.CONTROL_PLAYWRIGHT_MODULE;
if(!modulePath)throw Error('CONTROL_PLAYWRIGHT_MODULE is required; browser coverage cannot silently skip.');
const {chromium}=await import(pathToFileURL(modulePath).href);
const output=fileURLToPath(new URL('../review-output/',import.meta.url));
test('scoped selection, files, blocked storage and legible connected screens',async()=>{
  await mkdir(output,{recursive:true});
  const server=createServer();server.listen(0,'127.0.0.1');await once(server,'listening');
  const url=`http://127.0.0.1:${server.address().port}`,browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const context=await browser.newContext({viewport:{width:1440,height:1050},colorScheme:'dark'}),page=await context.newPage(),errors=[],external=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(url+'/')&&r.url()!==url)external.push(r.url());});
    await page.goto(url);await page.locator('#page-title').waitFor();
    await page.locator('[data-action="scope"]').nth(1).click();await page.locator('[data-field="draft"]').fill('일부만 남기는 한국어 시험 대안');
    await page.locator('#alternative-file').setInputFiles({name:'trial.md',mimeType:'text/plain',buffer:Buffer.from('synthetic file alternative')});
    assert.ok((await page.locator('#file-status').textContent()).includes('trial.md'));
    const trigger=page.locator('[data-action="overlay"][data-value="logs"]');await trigger.click();await page.locator('[data-record]').first().check();await page.keyboard.press('Escape');
    assert.equal(await trigger.evaluate(el=>el===document.activeElement),true);
    assert.equal(await page.locator('[data-field="draft"]').inputValue(),'일부만 남기는 한국어 시험 대안');
    await page.reload();assert.ok(!(await page.locator('#file-status').textContent()).includes('trial.md'));
    assert.equal(await page.locator('[data-field="draft"]').inputValue(),'일부만 남기는 한국어 시험 대안');
    await page.locator('[data-action="node"][data-value="extract"]').first().click();
    await page.locator('[data-action="artifact"][data-value="source-policy"]').click();
    await page.locator('#original-body').evaluate(el=>{const range=document.createRange();range.setStart(el.firstChild,3);range.setEnd(el.firstChild,28);const s=window.getSelection();s.removeAllRanges();s.addRange(range);});
    await page.locator('[data-action="textScope"]').click();assert.ok((await page.locator('main').textContent()).includes('문자 3–28'));
    await page.locator('[data-field="draft"]').fill('선택 문구의 시험 대안');
    for(const mode of ['conversation','workspace','graph'])await page.locator(`[data-action="mode"][data-value="${mode}"]`).click();
    assert.equal(await page.locator('[data-field="draft"]').inputValue(),'선택 문구의 시험 대안');
    await page.locator('[data-action="area"][data-value="design"]').click();await page.locator('[data-action="focus"][data-value="approval"]').click();
    assert.equal(await page.locator('.candidates .candidate').count(),3);
    assert.equal(await page.locator('.candidates .candidate').evaluateAll(cards=>cards.every(c=>c.querySelectorAll('g.selected').length>0)),true);
    await page.screenshot({path:output+'01-design.png',fullPage:true});
    await page.locator('[data-action="area"][data-value="run"]').click();await page.locator('[data-action="node"][data-value="draft"]').first().click();
    await page.locator(`[data-action="artifact"][data-value="${CASE.original}"]`).click();await page.locator('[data-action="scope"][data-value="p1-summary"]').click();await page.locator('[data-field="draft"]').fill('동시에 이용 가능한 공간과 시간대별 선택지를 구분하는 시험용 부분 문구');
    await page.screenshot({path:output+'02-run-and-alternative.png',fullPage:true});
    await page.locator('[data-action="currentGrowth"]').click();await page.screenshot({path:output+'03-new-input-unanalysed.png',fullPage:true});
    await page.locator('[data-action="sample"][data-value="yes"]').click();await page.screenshot({path:output+'04-fixed-inquiry.png',fullPage:true});
    for(const round of ROUNDS){await page.locator(`[data-action="round"][data-value="${round.id}"]`).click();const text=await page.locator('main').textContent();assert.ok(text.includes(round.baselineRun)&&text.includes(round.candidateRun));assert.ok(text.includes(round.finalEvidence));}
    await page.screenshot({path:output+'05-paired-review.png',fullPage:true});
    for(const name of ['connection','logs','audit','approval']){
      await page.locator(`[data-action="overlay"][data-value="${name}"]`).first().click();await page.screenshot({path:output+`06-${name}.png`,fullPage:true});await page.locator('#detail-close').click();
    }
    for(const width of [1440,1024,390])for(const scheme of ['light','dark']){
      await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme:scheme});
      for(const area of ['design','run','growth'])for(const mode of ['workspace','conversation','graph']){
        await page.locator(`[data-action="area"][data-value="${area}"]`).click();await page.locator(`[data-action="mode"][data-value="${mode}"]`).click();
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,`${area}/${mode}/${width}/${scheme}`);
        for(const img of await page.locator('img').all()){await img.evaluate(el=>el.decode());assert.ok(await img.evaluate(el=>el.naturalWidth>0));}
      }
      await page.screenshot({path:output+`07-growth-${width}-${scheme}.png`,fullPage:true});
    }
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);await context.close();
    const writeContext=await browser.newContext();await writeContext.addInitScript(()=>{Storage.prototype.setItem=function(){throw new Error('test quota');};});
    const writePage=await writeContext.newPage();await writePage.goto(url);await writePage.locator('[data-field="draft"]').fill('쓰기 실패에도 남을 입력');
    assert.ok((await writePage.locator('#storage-status').textContent()).includes('보관 실패'));assert.equal(await writePage.locator('[data-field="draft"]').inputValue(),'쓰기 실패에도 남을 입력');await writeContext.close();
    const readContext=await browser.newContext();await readContext.addInitScript(key=>{const rawGet=Storage.prototype.getItem;sessionStorage.setItem(key,'original-unread-snapshot');window.readTestSnapshot=()=>rawGet.call(sessionStorage,key);Storage.prototype.getItem=function(){throw new Error('test read');};},KEY);
    const readPage=await readContext.newPage();await readPage.goto(url);await readPage.locator('[data-field="draft"]').fill('읽기 실패 뒤 새 입력');
    assert.equal(await readPage.evaluate(()=>window.readTestSnapshot()),'original-unread-snapshot');
    readPage.once('dialog',dialog=>dialog.dismiss());await readPage.locator('[data-action="save"]').click();assert.equal(await readPage.evaluate(()=>window.readTestSnapshot()),'original-unread-snapshot');await readContext.close();
    const deleteContext=await browser.newContext();await deleteContext.addInitScript(()=>{Storage.prototype.removeItem=function(){throw new Error('test delete');};});
    const deletePage=await deleteContext.newPage();await deletePage.goto(url);await deletePage.locator('[data-field="draft"]').fill('지우지 못한 입력');deletePage.once('dialog',dialog=>dialog.accept());await deletePage.locator('[data-action="reset"]').click();
    assert.equal(await deletePage.locator('[data-field="draft"]').inputValue(),'지우지 못한 입력');assert.ok((await deletePage.locator('#storage-status').textContent()).includes('초기화 실패'));await deleteContext.close();
  }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
});
```

- [x] Run `CONTROL_PLAYWRIGHT_MODULE=<node-runtime>/dependencies/node/node_modules/playwright/index.mjs node --test control-prototype/tests/browser-review.test.mjs`. Expected: PASS and the named screenshots. This is actual UI behavior against synthetic data, not actual runtime or engine verification.
- [x] At 1440px and 1024px verify that candidate graphs are stacked at readable widths with a shared inspection focus, not forced into three cropped miniatures. Pair graphs also stack at these widths. A future wider-screen layout may use columns only if each full graph retains legible labels; that change needs the same screenshots and state checks.
- [x] Inspect each generated screenshot with the image-viewing tool. Check full node labels, directed links, readable graphs without shrinking text, current run/attempt and comparison versions, typed image/PDF page appearance, and modal content. At small widths the graph's own horizontal scroll is permitted; body overflow, unreadable reduced graphs and inaccessible selected nodes fail. Capture a focused screenshot of each graph if a full-page capture makes labels unreadable; screenshots must not substitute for actual navigation tests.
- [x] Write `control-prototype/README.md` with this exact initial content:

```markdown
# DeepTwin 수정 관제 UI 시제품

비개발자 관제 작업대의 구조와 조작을 검토하는 로컬 시제품입니다. 설계·실행·개선은 같은 환경의 작업 영역이며 작업공간·대화·그래프로 같은 대상을 봅니다. 그래프 노드, 수행/시도, 입력·출력·전달, 자기 버전과 고정 사례의 반복 비교가 연결됩니다.

## 실행 담당자 안내

작업 폴더에서 `node control-prototype/build-assets.mjs`로 합성 파일을 생성한 뒤 `node control-prototype/server.mjs`를 실행합니다. PDF 생성 전 프로젝트의 PDF 스킬 절차를 따릅니다. 주소는 `http://127.0.0.1:4183`이며 사용자는 열린 화면으로 검토합니다. 포트 충돌 시 기존 프로세스를 종료하지 말고 다른 PORT를 선택합니다. 패키지 설치는 없습니다.

## 실제 작동과 미연결 구분

실제 작동: 그래프/시도/파일/비교 초점/회차 탐색, 원 파일 접근, 형식별 표시, 시험용 부분 선택·초안, 대화 메모, 로컬 파일 첨부, 선택 기록 가림 미리보기, 세 보기 왕복과 탭 보관.

미연결: 자료 자동 해석, 자연어 설계 생성·병합, 에이전트/외부 도구 수행, 구독 인증·API 과금, 렌즈·크리틱 추론, 실제 재실험·평가·승인·운영 반영, 로그 묶음 추출·제작자 전송. 버튼은 미연결 결과를 성공 처리하지 않습니다.

고정 합성 사례는 현재 입력과 별개입니다. 새 초안에 사전 가설·점수·변경 후보가 붙지 않습니다. 원본 PDF와 파생 SVG 미리보기를 구별하며, 표시용 영문 원자료는 실제 업무나 사용자 피드백이 아닙니다. 일반 탐색·판단 설명은 한국어로 제공하고 감사에서만 내부 경로를 확인합니다.

## 보관과 안전

문자 초안은 `deeptwin:control-ui:v1` 하나의 sessionStorage 키에 보관합니다. 영구 보관·비밀 저장을 보장하지 않습니다. 이전 시제품 키는 읽거나 변경하지 않습니다. 읽기 실패 시 자동 덮어쓰기를 막고, 쓰기/초기화 실패 때 현재 입력을 유지합니다. 초기화는 이 키만 사용자의 확인 후 지웁니다.

첨부 파일은 최대 5 MiB이며 이 탭 메모리에만 있습니다. 새로고침 후 복원하지 않습니다. 사용자 SVG/PDF/HTML을 실행하지 않고 래스터 이미지 외에는 메타데이터와 원 파일 접근만 제공합니다. 새 첨부로 교체하면 이전 첨부의 메모리 참조는 해제됩니다. 실제 개인정보 자료를 시험에 넣지 마세요.

## 검증과 한계

순수 검사: `node --test control-prototype/tests/fixtures.test.mjs control-prototype/tests/state.test.mjs control-prototype/tests/primitives.test.mjs control-prototype/tests/workspace.test.mjs control-prototype/tests/server.test.mjs`.

브라우저 검사: 기존 번들 Playwright의 절대 경로를 CONTROL_PLAYWRIGHT_MODULE로 지정해 `node --test control-prototype/tests/browser.test.mjs control-prototype/tests/browser-review.test.mjs`를 실행합니다. 미지정은 명시 오류이며 검사를 건너뛰고 성공으로 기록하지 않습니다.

결과는 `docs/ui/control-workspace-review.md`에 실행 근거와 관찰 한계를 구별해 남깁니다. 사용자 정체성 수용·실제 두 구독 지원·도구 수행·흡수/전이/회귀 효과는 별도 검증 대상입니다.
```

- [x] Create `docs/ui/control-workspace-review.md` with the following unfilled-status content, then update only rows for which actual evidence has been collected. This initial record deliberately does not claim a pass.

```markdown
# 수정 관제 작업대 화면 검토

대상: control-prototype/ · 기존 실패 시제품 prototype/와 별도.
근거: ../superpowers/specs/2026-09-06-deeptwin-ui-structure-design.md §10–11.
입력: 새 중립 합성 자료; 사용자 업무 설명·대안·실제 엔진 결과 아님.

| 확인 대상 | 실행/관찰 근거 | 현재 판정 |
| --- | --- | --- |
| 원본·입력·수신 버전과 실물 PDF/CSV/SVG/문서 | 아직 실행 결과 미기록 | 대기 |
| 서로 다른 후보 그래프의 같은 초점·수정본 재검토 | 아직 화면 관찰 미기록 | 대기 |
| 실패 재시도/새 수행·복수 출력·세 보기 맥락 | 아직 브라우저 결과 미기록 | 대기 |
| 부분 자기 버전과 새 입력/고정 탐구 사례 분리 | 아직 브라우저 결과 미기록 | 대기 |
| 차이·경쟁 근거·감사·이전 큐·부분 밖 영향·정확한 승인 | 아직 화면 관찰 미기록 | 대기 |
| 저장/복구·첨부 수명·선택 기록·미전송 | 아직 실패 경로 결과 미기록 | 대기 |
| 1440/1024/390, 밝음/어두움, 키보드·실제 한국어 IME | 아직 자동/수동 관찰 미기록 | 대기 |
| 사용자의 제품 정체성·조작 수용 | 사용자 화면 검토 전 | 미확인 |
| 실제 모델/도구·렌즈/평가·운영 적용 | UI 시제품 범위 밖 | 미실시 |

과거 UI-01–15 관찰 및 V02/V03 정체성 실패는 그대로 보존한다. 새 코드 테스트가 과거 실패나 사용자 미확인을 덮지 않는다. 결과를 기록할 때 커밋, 명령, 실제 검사 수/실패/건너뜀, 캡처 경로, 확인한 내용과 한계를 함께 남긴다. 파일·화면 표시 검사는 DeepTwin 효과 증거가 아니다.
```

- [x] Run the full pure-test command and both browser tests above. Run `git diff --check`; inspect the exact changed files and protected dirty plan hash. Record actual counts rather than copying this plan's expected values. Do not infer physical IME, accessibility certification, empirical improvement or user approval from automated tests.
- [x] Commit the exact tested source/README/review document changes, with screenshots only after inspection: `git add -- control-prototype/tests/browser-review.test.mjs control-prototype/README.md docs/ui/control-workspace-review.md`, then inspect the staged file list and commit `test: verify revised control workspace and record review boundaries`. Any fixes in earlier modules must be explicitly staged by their names and reviewed, not swept up with `git add .`.
- [x] Start the local server in a persistent tool session; `http://127.0.0.1:4183` is running. The Codex panel open request returned queued. Preserve the worktree and provide actual screenshots without asking the user to operate a CLI.
- [ ] Confirm actual visible display after the user unlocks the Mac, then obtain the user's screen review of the specified relationships. The locked Mac prevented this check. User acceptance, physical Korean IME and OS-level BFCache remain unverified; update observations only from actual evidence.

## Spec coverage and completion boundary

| Spec | Planned implementation/verification |
| --- | --- |
| §10.1 common environment and three views | Tasks 2/4/6; context/draft/overlay and 3×3 browser navigation checks. |
| §10.3 exact stage/attempt/typed output | Tasks 1–4; failed/retry/revisit data, exact consumers and real-file checks; Task 7 past-selection inspection. |
| §10.4 self alternative and partial scope | Tasks 2/3/6; native typed display, region/text selection, draft/file input, exact keys and explicit preview/editor capability limits. |
| §10.5 discrepancy/trace/hypotheses/evidence | Tasks 1/4; separate fixed example, actual linked trace/artifacts and three audit routes; Tasks 6/7 prevent new-input contamination. |
| §10.6 prior queue, local/downstream impact and exact version | Tasks 1/4/7; two jobs×two rounds, true paired references, declined candidate and final-evidence/approval absence. |
| §10.7 synchronized design comparison/merge | Tasks 1/3/4/7; distinct graph contracts and shared focus, separate pre-authored merged version, no inherited approval. |
| §8/§11 connections, files, recovery and optional logs | Tasks 2/4–7; visible unconnected capabilities, no side-effect repeats/API fallback, tab recovery and log preview/return. Real integrations deferred, not silently substituted. |

Implementation completion requires passing actual scoped tests, inspected artifacts/screenshots and an honest review record. **User UI acceptance remains a separate gate.** Production skills/packages, model/tool execution, source-grounded lens definitions, independent critic evidence, export/replay/evaluation and operational approval must follow their own designs and tests; this plan does not authorize or claim them.

## Author's plan self-review

- [x] Check every module export/import and fixture field against the complete code packets. Fixed resource nodes without attempts, orphan draft references, paired resource selection and clickable evidence references.
- [x] Parse every JavaScript code block without evaluating it; distinguish plan syntax checks from product tests. Fourteen blocks across the two packets parsed; no module evaluation, generated assets or product tests occurred.
- [x] Scan for missing code, unresolved placeholders and stale scope/approval language; fix substantive gaps. Full browser commands replace abbreviated commands. Native textarea restoration, fresh-input/example separation and legible graph/typed-page scroll boundaries are explicit.
- [x] Verify spec coverage above, safe file targets and preservation of existing user changes. Existing rejected prototype and both dirty plans remain untouched; actual production capabilities remain outside this UI plan.
- [x] Present the finished plan and recommend subagent-driven execution with review after each task; user authorized the scoped implementation with “시작해”.
