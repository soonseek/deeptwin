const freeze = value => {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
};
const N = (id, label, kind, x, y) => ({ id, label, kind, x, y });
const E = (from, to, kind = 'task') => ({ from, to, kind });
const mark = label => `${label} · synthetic UI fixture`;
const artifactRecords = {};
function addArtifact(id, label, type, body, regions, preview) {
  const extension = { text: 'md', csv: 'csv', svg: 'svg', pdf: 'pdf' }[type];
  const artifact = { id, label: mark(label), type, path: `assets/${id}.${extension}`, body,
    regions: regions ?? [{ id: 'whole', label: '산출물 전체', text: body }] };
  if (preview) artifact.preview = preview;
  artifactRecords[id] = artifact;
  return id;
}
function wrap(text, width = 76) {
  const lines = [];
  let line = '';
  for (const word of text.split(/\s+/)) {
    if (word.length > width) throw new Error('Fixture word exceeds page width');
    if (line && line.length + word.length + 1 > width) { lines.push(line); line = word; }
    else line += `${line ? ' ' : ''}${word}`;
  }
  if (line) lines.push(line);
  return lines;
}
function addPDF(id, title, summary, schedule, notes) {
  const regions = [
    { id: 'p1-summary', label: '1쪽: 요약 문단', text: summary },
    { id: 'p1-schedule', label: '1쪽: 공간별 일정', text: schedule },
    { id: 'p1-notes', label: '1쪽: 예약·공개 유의사항', text: notes },
  ];
  const lines = ['SYNTHETIC UI FIXTURE - NOT AN ACTUAL LIBRARY PLAN', title, '',
    'SUMMARY', ...wrap(summary), '', 'ROOM SCHEDULE', ...wrap(schedule), '',
    'BOOKING AND PUBLICATION NOTES', ...wrap(notes), '',
    'No reservation, public post, approval or model execution has occurred.'];
  const displayTitle = title.replace('Tuesday', '화요일').replace('Thursday', '목요일')
    .replace('room-use briefing - draft 1', '공간 이용 안내문 · 1차').replace('room-use briefing - draft 2', '공간 이용 안내문 · 2차');
  return addArtifact(id, displayTitle, 'pdf', lines.join('\n'), regions, `assets/${id}-page-1.svg`);
}
const escapeXML = value => String(value).replace(/[<>&"']/g, character => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' }[character]));
function timeline(rows, caption) {
  const minute = time => Number(time.slice(0, 2)) * 60 + Number(time.slice(3));
  const bars = rows.map((row, index) => {
    const start = 190 + (minute(row.start) - 14 * 60) * 3;
    const width = (minute(row.end) - minute(row.start)) * 3;
    const y = 125 + index * 85;
    return `<g><text x="28" y="${y + 24}" fill="#173b3f">${escapeXML(row.room)} (${row.capacity})</text><rect x="${start}" y="${y}" width="${width}" height="36" rx="5" fill="#167880"/><text x="${start + 9}" y="${y + 24}" fill="white">${row.start}-${row.end}</text></g>`;
  }).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="820" height="410" viewBox="0 0 820 410" role="img"><title>${escapeXML(caption)}</title><rect width="820" height="410" fill="#f5faf9"/><g font-family="Arial,sans-serif" font-size="16"><text x="28" y="35" fill="#173b3f">SYNTHETIC UI FIXTURE - ROOM WINDOWS</text><text x="28" y="65" fill="#456366">${escapeXML(caption)}</text>${[14, 15, 16, 17].map(hour => `<text x="${190 + (hour - 14) * 180}" y="103" fill="#456366">${hour}:00</text>`).join('')}${bars}<text x="28" y="395" fill="#456366">Intervals are displayed records, not live bookings or evaluated evidence.</text></g></svg>`;
}

const pipelineNodes = [N('source', '입력 자료', 'resource', 90, 75), N('extract', '근거 확인', 'agent', 255, 75),
  N('slots', '이용 시간 구성', 'agent', 420, 75), N('draft', '안내문 작성', 'agent', 585, 200),
  N('review', '안내문 검토', 'agent', 585, 355), N('approve', '공개 승인', 'control', 750, 355),
  N('files', '파일·버전 보관', 'resource', 255, 445), N('model', '모델 연결', 'resource', 420, 445),
  N('observe', '실행 기록·검사', 'resource', 750, 75)];
const pipelineEdges = [E('source', 'extract'), E('extract', 'slots'), E('slots', 'draft'), E('draft', 'review'),
  E('review', 'draft', 'revisit'), E('review', 'approve', 'control'), E('files', 'extract', 'memory'),
  E('files', 'draft', 'memory'), E('model', 'extract', 'tool'), E('model', 'draft', 'tool'),
  E('model', 'review', 'tool'), E('draft', 'observe', 'telemetry'), E('review', 'observe', 'telemetry')];
const designs = [
  { id: 'pipeline', label: '단계별 근거 전달', version: 'design-a-v1', nodes: pipelineNodes, edges: pipelineEdges,
    focus: { transfer: ['extract', 'slots', 'draft'], approval: ['review', 'approve'], memory: ['files', 'extract', 'draft'], evaluation: ['review', 'observe'] },
    contracts: {
      transfer: '예정된 전달: 근거 확인 → 정리된 제약 → 이용 시간 CSV → 완결된 PDF·문서 → 별도 안내문 검토로 이어집니다. 필수 항목이 빠지면 해당 전달을 멈춥니다.',
      approval: '예정된 권한: 사람이 검토된 최종 안내문의 공개를 승인합니다. 앞 단계 에이전트는 공개·예약 권한이 없으며 해결되지 않은 결함을 그대로 남깁니다.',
      memory: '예정된 기억: 단계마다 원 파일과 버전을 보존합니다. 후속 역할은 공용 편집판의 최신값 대신 명시적으로 전달받은 파일 버전을 읽습니다.',
      evaluation: '예정된 평가: 이용 시간 전달 시 출처·시간 제약을 검사하고, 공개 결정 전에는 완결된 안내문을 별도로 검토합니다.',
    }, review: '합성 설계 검토: 단계별 책임을 읽기 쉽지만 전달에서 빠진 맥락이 후속 산출물로 퍼질 수 있습니다. 실제 실행하거나 점수를 측정한 후보가 아닙니다.' },
  { id: 'supervised', label: '감독자와 작성 전 확인', version: 'design-b-v1',
    nodes: [N('source', '입력 자료', 'resource', 90, 75), N('supervise', '업무 감독', 'control', 255, 75),
      N('extract', '근거 확인', 'agent', 420, 75), N('slots', '이용 시간 구성', 'agent', 420, 230),
      N('approve', '근거 충돌 확인', 'control', 585, 230), N('draft', '안내문 작성', 'agent', 750, 230),
      N('files', '역할별 자료 범위', 'resource', 255, 445), N('model', '모델 연결', 'resource', 420, 445),
      N('observe', '판단 기록·검사', 'resource', 750, 75)],
    edges: [E('source', 'supervise'), E('supervise', 'extract', 'control'), E('supervise', 'slots', 'control'),
      E('extract', 'approve'), E('slots', 'approve'), E('approve', 'draft', 'control'), E('draft', 'supervise', 'revisit'),
      E('files', 'extract', 'memory'), E('files', 'slots', 'memory'), E('model', 'draft', 'tool'),
      E('model', 'extract', 'tool'), E('approve', 'observe', 'telemetry')],
    focus: { transfer: ['supervise', 'extract', 'slots', 'approve', 'draft'], approval: ['supervise', 'approve'],
      memory: ['files', 'extract', 'slots'], evaluation: ['approve', 'observe'] },
    contracts: {
      transfer: '예정된 전달: 감독자가 근거 확인과 시간 구성 역할에 범위를 정해 병렬로 맡깁니다. 두 결과의 버전을 작성 전 확인 지점에서 대조합니다.',
      approval: '예정된 권한: 수용 인원이나 시간대의 충돌이 미해결이면 공개 가능한 안내문을 쓰기 전에 사람이 판단합니다. 감독자는 업무 배분만 담당합니다.',
      memory: '예정된 기억: 역할별 읽기 범위와 감독자의 충돌 해결 기록을 분리합니다. 근거 확인 역할끼리 상대 결과나 최종 승인 권한을 덮어쓸 수 없습니다.',
      evaluation: '예정된 평가: 작성 전 역할 사이의 충돌을 확인한 뒤 명시적 규칙으로 산출물을 검사합니다. 공개 권한을 주는 행위는 이 검사와 별개입니다.',
    }, review: '합성 설계 검토: 문구가 만들어지기 전에 불확실성을 다룰 수 있지만 감독자와 앞선 확인 절차가 병목이 될 수 있습니다. 지연·품질을 실측한 결과는 없습니다.' },
  { id: 'shared', label: '공유 근거 작업공간', version: 'design-c-v1',
    nodes: [N('source', '입력 자료', 'resource', 90, 75), N('board', '공유 근거판', 'resource', 255, 230),
      N('extract', '근거 확인', 'agent', 420, 75), N('slots', '이용 시간 구성', 'agent', 420, 230),
      N('draft', '안내문 작성', 'agent', 585, 75), N('review', '충돌 검토', 'agent', 585, 355),
      N('approve', '공개 승인', 'control', 750, 355), N('model', '모델 연결', 'resource', 420, 445),
      N('observe', '버전 검사·기록', 'resource', 750, 75)],
    edges: [E('source', 'board'), E('board', 'extract', 'memory'), E('extract', 'board', 'memory'),
      E('board', 'slots', 'memory'), E('slots', 'board', 'memory'), E('board', 'draft', 'memory'),
      E('draft', 'board', 'memory'), E('board', 'review'), E('review', 'board', 'revisit'), E('review', 'approve', 'control'),
      E('model', 'extract', 'tool'), E('model', 'draft', 'tool'), E('board', 'observe', 'telemetry')],
    focus: { transfer: ['board', 'extract', 'slots', 'draft'], approval: ['review', 'approve'],
      memory: ['board', 'extract', 'slots', 'draft'], evaluation: ['review', 'observe'] },
    contracts: {
      transfer: '예정된 전달: 공간 정보·가능한 시간대·문서 초안을 형식과 버전이 있는 공유 근거판에 올립니다. 읽는 역할은 실제 소비한 출처 버전을 기록해야 합니다.',
      approval: '예정된 권한: 충돌 검토자가 버전을 정리하고 사람이 최종 공개를 승인하기 전에는 각 역할의 결과를 잠정 상태로 둡니다. 에이전트가 스스로 승인하지 않습니다.',
      memory: '예정된 기억: 단계별 파일이나 감독자 전용 상태 대신 버전 있는 근거와 충돌·변경 이력을 함께 보관하는 공유 작업공간을 사용합니다.',
      evaluation: '예정된 평가: 협업 도중 오래된 자료 읽기·상충하는 시간대·출처를 계속 확인하고 최종 공개 전에는 완결된 안내문을 다시 검사합니다.',
    }, review: '합성 설계 검토: 반복 작업과 맥락 공유가 유연하지만 동시 수정 충돌과 오래된 자료 사용을 통제해야 합니다. 최적 설계나 실제 평가 결과라고 주장하지 않습니다.' },
];
export const DESIGNS = freeze(designs);
export const REVISED_DESIGN = freeze({ ...designs[0], id: 'pipeline-gate', label: '단계별 전달 + 근거 확인', version: 'design-a-b-v2',
  nodes: [...pipelineNodes, N('evidence-gate', '근거 충돌 확인', 'control', 585, 75)],
  edges: [...pipelineEdges.filter(edge => !(edge.from === 'slots' && edge.to === 'draft')),
    E('slots', 'evidence-gate'), E('evidence-gate', 'draft', 'control')],
  focus: { ...designs[0].focus, transfer: ['extract', 'slots', 'evidence-gate', 'draft'], approval: ['evidence-gate', 'review', 'approve'] },
  contracts: { ...designs[0].contracts,
    transfer: '수정된 전달 계획: 삽입한 확인 지점이 시간대·충돌 항목을 가진 새 자료를 받습니다. 소비 버전과 누락 항목 처리가 잘 결합되는지 다시 검토해야 합니다.',
    approval: '수정된 권한 계획: 앞선 확인 지점은 근거 충돌을 해결하고 최종 공개는 별도의 사람 권한으로 남깁니다. 승인 책임의 중복·충돌을 다시 검토해야 합니다.',
  }, review: '합성 병합 예시: design-a-b-v2의 결합 검토 대기 상태입니다. 원 후보의 합격·점수·승인을 상속하지 않습니다. 실제 구성이나 실행 권한은 주어지지 않았습니다.' });

export const WORK_MODEL = freeze({
  purpose: '도서관 담당자가 가능한 2시간 이용안을 비교할 수 있도록 출처가 있는 안내문을 만듭니다. 시작 시간이 다른 공간을 동시에 이용 가능한 것으로 혼동하지 않도록 합니다.',
  done: '완결된 안내문·공간별 이용 시간 CSV·시각 일정을 통해 수용 인원, 준비 시간과 공개 전 확인사항을 읽을 수 있어야 합니다. 사람의 실제 공개 승인은 이 화면 예시와 별개입니다.',
  source: '인터페이스 검토를 위해 만든 전부 합성(synthetic)인 도서관 공간 자료입니다. 규칙과 이용 기록은 실제 장소·사람·예약을 가리키지 않습니다.',
  unknown: '실제 개관 시간·접근성 규칙·근무 인원·실시간 예약은 확인하지 않았습니다. 외부 시스템은 연결되어 있지 않습니다.',
});
addArtifact('source-policy', '공간 이용 규칙', 'text', `# Synthetic room-use policy\n\nAll offered sessions must have a continuous two-hour room window. A room becomes available only after the previous booking ends and its setup buffer has elapsed. Setup time is not visitor time. Capacity applies to that room, not to every interval mentioned in a brief.\n\nThe quiet room supports 8 visitors, the workshop 20, and the hall 40. A total capacity may be added only for the same offered start and end times. A coordinator must approve publication; this packet neither reserves a room nor grants publication permission.\n\nThe planner must preserve source date, previous booking end, setup minutes, closing time, candidate start and candidate end in every scheduling handoff. If any required value is missing, the next stage must show an unresolved constraint rather than guess.\n`);
const jobs = {
  j1: { label: '화요일 공간 이용', day: 'Tuesday', workshopPrevious: '14:30', workshopSetup: 30, workshopCorrect: '15:00',
    source: 'room,previous_end,setup_minutes,closes,capacity\nQuiet,14:00,0,17:00,8\nWorkshop,14:30,30,17:00,20\nHall,14:00,0,17:00,40\n',
    baseline: 'Tuesday afternoon offers three rooms for a shared 14:00-16:00 activity window. The quiet room holds 8 visitors, the workshop 20, and the hall 40, allowing us to present a combined capacity of 68. Publish these options together once the coordinator has reviewed the briefing.',
    c1: 'Offer the quiet room and hall from 14:00 to 16:00, with a combined capacity of 48. Offer the workshop separately from 15:00 to 17:00. The workshop should not appear in the simultaneous 14:00 capacity total; publication still requires the coordinator to release the briefing.',
    c2: 'The 14:00-16:00 group comprises the quiet room and hall, providing 48 places in total. The workshop first becomes ready at 15:00 after its recorded booking and 30-minute setup period, so its 20 places belong to a separate 15:00-17:00 option. These are proposed windows, not confirmed reservations.',
  },
  j2: { label: '목요일 공간 이용', day: 'Thursday', workshopPrevious: '13:30', workshopSetup: 30, workshopCorrect: '14:00',
    source: 'room,previous_end,setup_minutes,closes,capacity\nQuiet,14:00,0,17:00,8\nWorkshop,13:30,30,17:00,20\nHall,14:00,0,16:00,40\n',
    baseline: 'Thursday offers the quiet room, workshop and hall together from 14:00 to 16:00, providing a combined capacity of 68. The workshop setup finishes before that window begins. The hall closes at 16:00, so later alternatives must not silently extend its session. Publication remains subject to coordinator release.',
    c1: 'Offer the quiet room and hall together from 14:00 to 16:00, giving a combined capacity of 48. Keep the workshop in a separate 15:00-17:00 option with 20 places. This draft applies a blanket later-workshop rule, even though Thursday source records show that the workshop is already ready at 14:00.',
    c2: 'All three rooms have a feasible common 14:00-16:00 window on Thursday, for a combined capacity of 68. The workshop booking ends at 13:30 and its 30-minute setup finishes by 14:00. The hall closes at 16:00; the complete two-hour session fits exactly and must not be extended without a new source record.',
  },
};
for (const [id, job] of Object.entries(jobs)) addArtifact(`source-${id}`, `${job.label} 현황 원자료`, 'csv', job.source,
  job.source.trim().split('\n').slice(1).map((line, index) => ({ id: `row-${index + 1}`, label: `원자료 ${index + 1}행`, text: line })));

const runs = {};
function makeRun(jobId, suffix, mode, minute) {
  const job = jobs[jobId];
  const roomLabel = room => ({ Quiet: '조용한 공간', Workshop: '작업실', Hall: '다목적실' }[room]);
  const key = `${jobId}-${suffix}`;
  const runId = `run-${key}`;
  const finalId = `brief-${key}`;
  const stageOneId = `brief-${key}-v1`;
  const summary = job[mode];
  const workshopStart = mode === 'c2' ? job.workshopCorrect : '14:00';
  const workshopEnd = workshopStart === '15:00' ? '17:00' : '16:00';
  const rows = [{ room: 'Quiet', start: '14:00', end: '16:00', capacity: 8 },
    { room: 'Workshop', start: workshopStart, end: workshopEnd, capacity: 20 },
    { room: 'Hall', start: '14:00', end: '16:00', capacity: 40 }];
  const schedule = rows.map(row => `${row.room}: ${row.start}-${row.end}, ${row.capacity} places.`).join(' ');
  const notes = 'Retain the dated occupancy source and room-use policy with this brief. Capacity figures describe people, not bookings. A release decision must inspect the complete schedule and unresolved constraints; viewing this fixture cannot publish, reserve, or approve anything.';
  const handoff = mode === 'c2'
    ? `# Synthetic source-derived handoff v2\n\nJob=${jobId}; policy=source-policy; source=source-${jobId}.\nWorkshop previousEnd=${job.workshopPrevious}; setupMinutes=${job.workshopSetup}; derivedAvailable=${job.workshopCorrect}; closes=17:00; capacity=20.\nQuiet previousEnd=14:00; setupMinutes=0; closes=17:00; capacity=8. Hall previousEnd=14:00; setupMinutes=0; closes=${jobId === 'j2' ? '16:00' : '17:00'}; capacity=40.\nThe slot planner must derive a continuous two-hour interval from these source fields. It cannot take the diagnostic alternative or interpretive audit as an operational input.\n`
    : `# Synthetic capacity-only handoff v1\n\nJob=${jobId}; source=source-${jobId}; requestedWindow=14:00-16:00.\nQuiet capacity=8; Workshop capacity=20; Hall capacity=40.\nThe recorded payload does not carry previous-booking end, setup duration or closing-time fields. This omission is observable in the fixture; causal attribution is not established by the display.\n`;
  addArtifact(`handoff-${key}`, `${job.label} 전달 자료 ${suffix}`, 'text', handoff);
  const csv = `room,start,end,capacity\n${rows.map(row => `${row.room},${row.start},${row.end},${row.capacity}`).join('\n')}\n`;
  addArtifact(`slots-${key}`, `${job.label} 시간표 ${suffix}`, 'csv', csv,
    rows.map((row, index) => ({ id: `row-${index + 1}`, label: `${roomLabel(row.room)} 이용 시간`, text: `${row.room},${row.start},${row.end},${row.capacity}` })));
  addArtifact(`diagram-${key}`, `${job.label} 시각 일정 ${suffix}`, 'svg', timeline(rows, `${job.day}: ${mode} displayed schedule`),
    rows.map((row, index) => ({ id: `row-${index + 1}`, label: `${roomLabel(row.room)} 시각 영역`, text: `${row.room} ${row.start}-${row.end}, capacity ${row.capacity}` })));
  addPDF(stageOneId, `${job.day} room-use briefing - draft 1`, `Draft awaiting a full brief check. ${summary}`, schedule, notes);
  addArtifact(`review-${key}-v1`, `${job.label} 1차 문서 검토 ${suffix}`, 'text', `# Synthetic draft review\n\nThe submitted PDF is ${stageOneId}, not the latest PDF in another attempt. Preserve a complete room schedule and distinguish a release decision from the mere display of proposed windows. Add an explicit statement that this packet creates no booking.\n\nThis first review records wording and publication-scope observations only. It does not establish that the setup constraint has been transmitted or that all source calculations are correct. A later complete-brief review remains a distinct stage occurrence.\n`);
  addPDF(finalId, `${job.day} room-use briefing - draft 2`, summary, schedule, notes);
  addArtifact(`brief-note-${key}`, `${job.label} 동봉 안내문 ${suffix}`, 'text', `# Synthetic briefing companion\n\n${summary}\n\n## Complete proposed schedule\n\n${schedule}\n\n## Publication boundary\n\n${notes}\n`);
  const assessment = mode === 'c2'
    ? 'The displayed schedule carries source-derived ready times into both the paragraph and the slot table. The downstream visual schedule reflects those same intervals. This synthetic authored agreement is not measured improvement or unseen transfer evidence.'
    : mode === 'c1'
      ? 'The summary applies a later-workshop rule, while the slot CSV and diagram still use 14:00-16:00. Tuesday wording can appear better while downstream disagreement remains. On Thursday the blanket rule suppresses a valid shared window. This candidate is not suitable for release.'
      : jobId === 'j1'
        ? 'The summary, slot CSV and diagram agree on 14:00, but the workshop source booking ends at 14:30 and requires 30 minutes of setup. Agreement between artifacts therefore does not establish correctness. The demonstration records an unresolved release-blocking inconsistency.'
        : 'The Thursday 14:00-16:00 interval is consistent with the displayed source values. The capacity-only handoff still omits safety-relevant fields, so success on this one fixture is not a general correctness claim.';
  addArtifact(`assessment-${key}`, `${job.label} 완결 산출물 검토 ${suffix}`, 'text', `# Synthetic complete-brief check\n\n${assessment}\n\nSource references: source-policy, source-${jobId}. Checked artifacts: ${finalId}, slots-${key}, diagram-${key}, brief-note-${key}. No evaluator, philosophical source review, external reservation or model has run.\n`);
  const attempt = (name, node, stage, attemptNumber, status, inputs, outputs, events) => ({
    id: `${runId}-${name}`, node, stage, try: attemptNumber, status, inputs, outputs, consumers: [], events,
  });
  const attempts = [
    attempt('extract-1', 'extract', 1, 1, 'complete', [`source-${jobId}`, 'source-policy'], [`handoff-${key}`],
      [mark('기록된 버전의 원자료를 읽은 예시입니다.'), mode === 'c2' ? '전달 규약 v2는 이전 예약 종료·준비 시간·종료 시각을 포함합니다. 진단용 자기 대안과 해석 기록은 실행 입력에서 제외됩니다.' : '전달 규약 v1에는 시간 의존성 항목이 없습니다. 이 누락 상태를 그대로 보존합니다.']),
    attempt('slots-1', 'slots', 1, 1, 'complete', [`handoff-${key}`], [`slots-${key}`, `diagram-${key}`],
      [mark(mode === 'c2' ? '원자료 항목에서 이용 가능 시간을 도출한 상태를 표시합니다.' : '불완전한 전달 자료의 요청 시간대를 복사한 상태입니다. 실제 계산을 수행한 기록이 아닙니다.')]),
  ];
  if (mode === 'baseline') attempts.push(attempt('draft-1-failed', 'draft', 1, 1, 'failed', [`slots-${key}`, 'source-policy'], [],
    [mark('파일 저장 전에 시간이 초과된 예시입니다. 산출물도 후속 수신자도 없습니다.')]));
  attempts.push(
    attempt('draft-1-complete', 'draft', 1, mode === 'baseline' ? 2 : 1, 'complete', [`slots-${key}`, 'source-policy'], [stageOneId],
      [mark('첫 수행의 PDF를 고유 버전으로 보관한 예시입니다.'), mode === 'c1' ? '후보 c1은 작성 지시만 바꿔 모든 작업실을 늦은 별도 시간대로 나눕니다. 이용 시간 전달의 누락 항목은 복원하지 않습니다.' : '실행 입력에 전문가 대안 원문은 포함되어 있지 않습니다.']),
    attempt('review-1', 'review', 1, 1, 'complete', [stageOneId, `source-${jobId}`], [`review-${key}-v1`], [mark('이 검토는 1차 초안을 받습니다. 이후 재방문 결과를 소급하여 받지 않습니다.')]),
    attempt('draft-2', 'draft', 2, 1, 'complete', [stageOneId, `review-${key}-v1`, `slots-${key}`], [finalId, `brief-note-${key}`],
      [mark('검토 뒤 새로 수행한 단계입니다. 실패한 저장의 재시도와 구별하며 PDF와 동봉 문서를 함께 산출합니다.')]),
    attempt('review-2', 'review', 2, 1, 'complete', [finalId, `brief-note-${key}`, `slots-${key}`, `diagram-${key}`, `source-${jobId}`, 'source-policy'], [`assessment-${key}`],
      [mark('완결 산출물의 별도 검토에서 후속 일정과 공개 제약을 확인한 예시입니다.')]),
    attempt('release-1', 'approve', 1, 1, 'waiting', [finalId, `assessment-${key}`], [],
      [mark('사람의 공개 승인은 기록되지 않았습니다. 이 예시 열람은 승인이나 외부 작업 실행이 아닙니다.')]),
  );
  for (const producer of attempts) producer.consumers = producer.outputs.flatMap(artifact => attempts
    .filter(receiver => receiver.inputs.includes(artifact)).map(receiver => ({ attempt: receiver.id, artifact })));
  runs[runId] = { id: runId, job: jobId, env: mode === 'baseline' ? 'env-demo-0.2' : `env-demo-0.3-${mode}`,
    observedAt: `2026-09-06T09:${String(minute).padStart(2, '0')}:00Z (synthetic observation)`,
    nodes: pipelineNodes, edges: pipelineEdges, attempts };
}
makeRun('j1', 'origin', 'baseline', 0);
makeRun('j2', 'origin', 'baseline', 1);
makeRun('j1', 'b1', 'baseline', 10);
makeRun('j1', 'c1', 'c1', 11);
makeRun('j2', 'b1', 'baseline', 12);
makeRun('j2', 'c1', 'c1', 13);
makeRun('j1', 'b2', 'baseline', 20);
makeRun('j1', 'c2', 'c2', 21);
makeRun('j2', 'b2', 'baseline', 22);
makeRun('j2', 'c2', 'c2', 23);

const alternative = 'Offer the quiet room and hall from 14:00 to 16:00, with a combined capacity of 48. Offer the workshop as a separate 15:00-17:00 option only after its setup window. Do not advertise three simultaneous rooms.';
addArtifact('alternative-summary', '자기 버전 예시 · 요약 부분만', 'text', alternative,
  [{ id: 'p1-summary', label: '원본의 요약 문단만 제공한 자기 버전', text: alternative }]);
export const CASE = freeze({ id: 'case-summary-window', original: 'brief-j1-origin', alternative: 'alternative-summary', region: 'p1-summary',
  differences: [
    { id: 'd-window', label: '동시 이용 시간과 별도로 가능한 시간의 구별', original: jobs.j1.baseline, alternative,
      nodes: ['extract', 'slots', 'draft', 'review'], hypotheses: [
        { id: 'h-transfer', kind: 'system', claim: '기록된 전달에서 시간 의존성 항목이 빠져 작성자가 성립하지 않는 공통 시간대를 받았을 가능성이 있습니다.',
          support: '원 전달에는 수용 인원과 요청 시간대만 있고 이전 예약 종료·준비 시간은 없습니다. 그 이용 시간 CSV는 작업실을 14시에 시작합니다.',
          counter: '작성자는 전체 이용 규칙도 받았습니다. 전달 항목의 누락만으로 최종 문구의 원인이 확정되지는 않습니다.',
          unknown: '이 항목만 복원했을 때 해당 시간 계산과 최종 안내문이 함께 바뀌는지 실제 개입으로 확인한 적이 없습니다.',
          probe: '후속 통제 시험에서는 모델을 바꾸거나 자기 대안 문구를 복사하지 않은 채 원자료의 시간 의존성 항목만 복원해 봅니다.',
          newEvidence: '미수집입니다. 표시한 회차는 작성된 합성 예시이며 이 설명을 뒷받침하는 실제 실험 증거가 아닙니다.' },
        { id: 'h-grouping', kind: 'judgment', claim: '자기 대안은 늦은 시간 자체를 선호하기보다 동시 이용 인원과 각각 가능한 이용안을 구별한 것일 수 있습니다.',
          support: '14시 동시 이용 인원에서만 작업실을 제외합니다. 준비 시간이 지난 뒤에는 작업실을 별도 이용안으로 여전히 제안합니다.',
          counter: '일회성 표현 수정이나 잘못된 대안도 일부 양상을 만들 수 있습니다. 이 문단만으로 재사용 가능한 판단 규칙이 확정되지는 않습니다.',
          unknown: '모든 공간이 동시에 준비된 경우에도 같은 구분 원칙을 쓰는지 확인할 독립적인 새 업무 응답이 없습니다.',
          probe: '작업실이 더 일찍 준비되는 새 사례를 출처와 함께 제시하고 실제 자기 대안이나 선택을 받습니다. 개인 성향을 분류하는 설문은 요구하지 않습니다.',
          newEvidence: '미수집입니다. 목요일 비교는 합성 UI 예시이지 이 사용자의 응답이나 검증된 해석 근거가 아닙니다.' },
      ] },
  ],
  audit: {
    generation: [
      'SYNTHETIC GEN-01: hypothetical micro-unit source-dependency@fixture-1 produced the pipeline candidate. This is not a verified philosopher source.',
      'SYNTHETIC GEN-02: hypothetical uncertainty-gate@fixture-1 produced the supervisor candidate; work-contract evidence remains separate from lens interpretation.',
      'SYNTHETIC GEN-03: hypothetical source-dependency@fixture-1 + shared-evidence@fixture-1 hybrid produced the shared workspace. Internal hybrid generation is not user structural merging.',
      'SYNTHETIC GEN-04 declined: a four-writer candidate changed role count without two genuine structural differences. Rejection is retained; no numeric score is invented.',
      'SYNTHETIC MERGE-01: user-structural-merge illustration creates design-a-b-v2; composition checks are pending and candidate approvals are not inherited.',
    ],
    critic: [
      'SYNTHETIC CRIT-01: separately authored criterion-based trace for each candidate records handoff gaps, authority conflicts, stale reads and abstentions; no model was called.',
      'SYNTHETIC CRIT-02: blindness and information separation are design intentions. Judgment-error independence has not been verified by these fixtures.',
      'SYNTHETIC CRIT-03: invalid diversity is declined rather than hidden by an average score. Source fidelity, task fitness and empirical usefulness are distinct unverified checks.',
    ],
    diagnosis: [
      'SYNTHETIC DIAG-01: fixed example alternative covers only p1-summary; unchanged schedule and notes are neither authored nor approved by the example contributor.',
      'SYNTHETIC DIAG-02: hypothetical contrast question and prediction are separate from new work evidence, which is absent. Interpretive H_phi/S_phi records are not candidate inputs.',
      'SYNTHETIC DIAG-03: system-normal, one-off exception, alternative error, unknown cause and no generalizable knowledge remain possible; no personality profile is produced.',
      'SYNTHETIC DIAG-04: new drafts entered in the UI have no generated hypotheses or evaluation. They must not be attached to this pre-authored demonstration result.',
    ],
  },
});
function round(job, number) {
  const key = `${job}-c${number}`;
  const improved = number === 2;
  return { id: `round-${job}-${number}`, job, candidate: `env-demo-0.3-c${number}`,
    baselineRun: `run-${job}-b${number}`, candidateRun: `run-${key}`,
    result: improved ? '합성 예시: 연결된 결과가 일치함 · 실제 개선 검증 아님' : job === 'j1' ? '합성 예시: 변화가 혼재함 · 후속 불일치 남음' : '합성 예시: 다른 업무에서 악화 · c1 공개 후보 탈락',
    checks: [
      { label: '선택한 요약 부분', result: improved ? '원자료를 반영한 문구의 예시' : '문구만 바뀐 예시', evidence: `brief-${key}` },
      { label: '부분 밖 영향 · 후속 이용 시간표', result: improved ? '일정이 함께 맞춰진 예시' : '전달 시간표가 그대로여서 문구와 불일치함', evidence: `slots-${key}` },
      { label: '부분 밖 영향 · 시각 일정', result: improved ? '원자료에서 도출한 이용 시간을 표시함' : '이전의 작업실 14시 일정이 남아 있음', evidence: `diagram-${key}` },
      { label: '완결 산출물 검토와 남은 한계', result: improved ? '실제 검증 통과를 주장하지 않음' : '공개를 막아야 할 후보의 한계', evidence: `assessment-${key}` },
    ],
    limits: '합성 비교 기록입니다. 입력·규칙 버전은 같게 구성했지만 실제 모델·실행기·외부 상태·소요 시간·확률적 반복·인과 추정은 없습니다. 부분 증거가 후속 영향의 범위를 제한하지 않습니다.',
    finalEvidence: '별도의 봉인·미관측·후속 수집 근거 없음. 이 사례는 조정 과정의 비교를 설명하는 예시이며 최종 검증 자료로 셀 수 없습니다.',
    approval: `정확한 env-demo-0.3-c${number}에 대한 사람의 승인 대기 상태입니다. 현재 환경은 env-demo-0.2이며 실제 적용이나 되돌리기는 수행하지 않았습니다.`,
  };
}
export const ROUNDS = freeze([round('j1', 1), round('j2', 1), round('j1', 2), round('j2', 2)]);
export const RUNS = freeze(runs);
export const ARTIFACTS = freeze(artifactRecords);
export const LOGS = freeze([
  { id: 'log-start', label: '최초 사용 기록의 합성 예시입니다. 계정이나 외부 도구는 연결되지 않았습니다.', source: 'synthetic-fixture' },
  { id: 'log-work', label: '업무 모델과 source-policy/source-j1/source-j2의 합성 자료 버전을 등록한 예시입니다.', source: 'synthetic-fixture' },
  { id: 'log-design', label: 'GEN-01–04의 생성 경로·탈락 설계·별도 검토의 한계를 보존합니다.', source: 'synthetic-fixture' },
  { id: 'log-merge', label: 'MERGE-01의 design-a-b-v2는 표시용 병합 기록이며 결합 검토 대기 상태입니다.', source: 'synthetic-fixture' },
  { id: 'log-original', label: 'run-j1-origin과 원 산출물 버전은 회차별 비교 기준 실행과 별도로 보존합니다.', source: 'synthetic-fixture' },
  { id: 'log-alternative', label: 'case-summary-window는 고정된 부분 자기 대안을 p1-summary에만 연결합니다.', source: 'synthetic-fixture' },
  { id: 'log-inquiry', label: 'DIAG-01–04는 경쟁 설명과 새 근거의 부재를 보여 주는 예시이지 엔진 실행 결과가 아닙니다.', source: 'synthetic-fixture' },
  { id: 'log-rounds', label: '네 비교 회차에 혼재·악화 사례, 이후 일치 예시와 선택한 부분 밖 산출물을 모두 남깁니다.', source: 'synthetic-fixture' },
  { id: 'log-approval', label: '정확한 후보의 승인·운영 적용은 기록되지 않았습니다. 예시를 보는 행위는 이를 승인하지 않습니다.', source: 'synthetic-fixture' },
  { id: 'log-export', label: '추출 범위의 합성 예시입니다. 실제 추출·전송은 수행하지 않았으며 인증정보도 포함하지 않습니다.', source: 'synthetic-fixture' },
]);
