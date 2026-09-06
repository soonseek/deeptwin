export const SCENES = [
  { id: 'V01', title: '업무 입력', subtitle: '자료와 완료 조건을 나란히 확인합니다.' },
  { id: 'V02', title: '설계 비교', subtitle: '역할의 연결과 검토 책임이 다른 세 예시입니다.' },
  { id: 'V03', title: '역할과 산출물', subtitle: '역할별 완결된 원문과 앞뒤 입력을 읽습니다.' },
  { id: 'V04', title: '내 버전', subtitle: '원문 전체 또는 선택한 부분에 자기 내용을 남깁니다.' },
  { id: 'V05', title: '차이와 새 증거', subtitle: '관찰과 설명, 아직 필요한 증거를 구별합니다.' },
  { id: 'V06', title: '반복과 승인 대상', subtitle: '전체 회차와 별도 최종 확인 자료를 읽습니다.' },
  { id: 'V07', title: '연결과 복구', subtitle: '준비 상태와 돌아갈 수 있는 경계를 확인합니다.' },
  { id: 'V08', title: '기록 미리보기', subtitle: '포함 범위와 가림을 검토하고 업무로 돌아갑니다.' }
];
export const MODES = [
  { id: 'workspace', label: '작업공간' },
  { id: 'conversation', label: '대화' },
  { id: 'graph', label: '그래프' }
];
export const CONTEXT = {
  environment: '동네 도서관 · 디자인 테스트', job: 'sample-job-1',
  run: 'sample-run-1', sourceVersion: 'source-v1', environmentVersion: 'environment-example-1'
};
export const SOURCE = [
  '이 자료는 화면 검토를 위해 새로 작성한 가상의 새봄도서관 운영 메모다. 실제 기관, 일정, 모집 공고가 아니다. 안내 대상은 도서관을 처음 방문하는 주민이며, 주말 프로그램의 참여 조건을 한 장의 안내문으로 정리하려 한다.',
  '예시 프로그램 이름은 「함께 만드는 작은 책」이다. 예시 일정은 어느 토요일 오후 2시부터 4시까지, 장소는 1층 이야기방이다. 구체적인 날짜는 아직 정하지 않았다. 참가자는 각자 기억하고 싶은 동네의 모습을 그림이나 짧은 글로 표현하고, 마지막에 작은 책 한 권으로 묶는다.',
  '예시 참여 정원은 어린이와 보호자를 합쳐 12명이다. 어린이는 보호자와 함께 오며, 참여 비용은 없다. 종이와 색연필은 도서관이 준비하고, 개인 사진을 가져오는 것은 선택이다. 접수 방식과 접근성 지원 문의 방법은 담당자의 확인이 필요하다.',
  '작성자는 확정된 항목과 확인이 필요한 항목을 분리해야 한다. 빠진 날짜나 접수 주소를 추정해 채우지 않는다. 검토자는 안내문에서 필요한 준비물, 동반 조건, 미정 항목을 찾을 수 있는지 확인한다. 이 메모를 근거로 한 어떤 문장도 실제 모집이나 예약으로 사용하지 않는다.'
];
const roleData = [
  {
    id: 'organizer', name: '자료 정리', artifact: 'brief', version: 'brief-v1',
    title: '프로그램 자료 정리', input: 'source-v1', upstream: null, downstream: 'writer',
    tool: '제공된 텍스트 읽기 · 이 시제품의 고정 예시',
    paragraphs: [
      '새봄도서관의 「함께 만드는 작은 책」은 화면 검토용 가상 프로그램이다. 주민이 동네의 기억을 그림이나 짧은 글로 옮기고 작은 책으로 묶는 활동을 안내한다. 이 자료 정리는 운영 메모의 확정 항목과 미정 항목을 나누어 다음 작성 역할에 전달하기 위한 완결된 예시 산출물이다.',
      '현재 메모에서 읽을 수 있는 일정은 토요일 오후 2시부터 4시까지이며, 장소는 1층 이야기방이다. 실제 날짜는 없다. 어린이와 보호자를 합친 예시 정원은 12명이고, 어린이는 보호자와 함께 참여한다. 참여 비용이 없다는 조건은 안내문에 넣을 수 있다.',
      '종이와 색연필은 도서관이 준비한다. 개인 사진은 원하는 참여자만 가져오므로 필수 준비물로 바꾸지 않는다. 접수 방식과 접근성 지원 문의 방법은 담당자 확인이 필요하다. 확인 전에는 임의의 주소나 전화번호를 생성하지 않고 미정 상태를 유지한다.',
      '다음 역할에는 참여 대상, 활동 내용, 시간과 장소, 준비물, 확인할 항목 순서로 안내문을 작성하도록 자료를 건넨다. 원문에 없는 모집 시작일이나 확정 날짜를 추가하지 않았는지 검토할 수 있도록 source-v1을 출처로 남긴다. 실제 전달이나 내용 활용을 수행한 기록은 없으며 이 연결은 디자인 테스트 예시다.'
    ]
  },
  {
    id: 'writer', name: '안내문 작성', artifact: 'announcement', version: 'announcement-v1',
    title: '함께 만드는 작은 책 · 안내문', input: 'brief-v1', upstream: 'organizer', downstream: 'reviewer',
    tool: '텍스트 초안 · PDF 연결 전',
    paragraphs: [
      '동네에서 기억하고 싶은 장면이 있나요? 가상의 새봄도서관 「함께 만드는 작은 책」에서는 그 장면을 그림이나 짧은 글로 남기고, 함께 작은 책을 만듭니다. 이 안내문은 디자인 테스트용 예시이며 실제 프로그램의 모집 공고가 아닙니다.',
      '프로그램은 토요일 오후 2시부터 4시까지 1층 이야기방에서 진행하는 설정입니다. 구체적인 날짜는 담당자 확인 뒤 기재할 예정입니다. 어린이는 보호자와 함께 참여하며, 어린이와 보호자를 합친 예시 정원은 12명입니다. 참여 비용은 없습니다.',
      '종이와 색연필은 도서관이 준비하는 것으로 설정되어 있습니다. 개인 사진을 가져오는 것은 선택입니다. 별도의 사진이 없어도 동네의 기억을 글이나 그림으로 표현할 수 있습니다. 처음 작은 책을 만드는 사람도 활동 내용을 이해할 수 있도록 순서를 현장에서 안내한다는 문장은 아직 운영자 확인이 필요합니다.',
      '접수 방법과 접근성 지원 문의 방법은 아직 정해지지 않았습니다. 이 두 항목과 정확한 날짜를 확인한 뒤 실제 안내문으로 사용할 수 있는지 다시 검토해야 합니다. 이 텍스트는 brief-v1을 참고해 준비한 고정 예시이며, PDF 파일 생성이나 외부 게시를 수행하지 않았습니다.'
    ]
  },
  {
    id: 'reviewer', name: '발행 검토', artifact: 'review', version: 'review-v1',
    title: '안내문 발행 전 검토 기록', input: 'announcement-v1', upstream: 'writer', downstream: null,
    tool: '원문 대조 · 외부 게시 미연결',
    paragraphs: [
      '이 검토 기록은 가상의 프로그램 안내문 announcement-v1과 그 앞선 자료 정리 brief-v1을 나란히 읽는 디자인 테스트 예시다. 실제 검토 엔진을 실행한 결과가 아니며, 이 기록의 존재는 안내문 승인이나 발행을 뜻하지 않는다.',
      '안내문은 토요일 오후 시간, 1층 이야기방, 보호자 동반, 합계 12명 정원, 무료 참여 조건을 드러낸다. 종이와 색연필은 제공하고 개인 사진은 선택이라는 원 자료의 구별도 남아 있다. 날짜와 접수 방법이 확정되지 않았다는 점을 지우면 독자가 실제 접수가 가능한 것으로 오해할 수 있다.',
      '현장에서 활동 순서를 안내한다는 내용은 원 운영 메모에 없는 추가 문장이다. 안내문은 이를 운영자 확인 필요로 표시했지만, 실제 발행 전에는 담당자에게 확인하거나 문장을 제외하는 판단이 필요하다. 접근성 지원 문의 경로도 확인 전에는 주소나 연락처를 임의로 채울 수 없다.',
      '따라서 예시 검토 상태는 발행 보류다. 담당자는 정확한 날짜, 접수 방식, 접근성 지원 문의 경로와 현장 안내 여부를 확인해야 한다. 그 뒤 새 안내문 버전을 다시 대조할 수 있다. 외부 게시 요청, 승인 기록, 실제 운영 버전은 현재 없으며 이 문서가 그 공백을 대신하지 않는다.'
    ]
  }
];
export const ROLES = roleData.map(role => ({ ...role, text: role.paragraphs.join('\n\n') }));
export const DESIGNS = [
  { id: 'serial', name: '순차 전달', version: 'design-serial-v1', structure: '자료 정리 → 안내문 작성 → 발행 검토',
    memory: '앞선 역할의 확정 산출물만 다음 역할에 전달', permission: '각 역할은 입력 읽기와 텍스트 출력만 계획',
    reason: '처음 쓰는 업무에서 원문이 안내문으로 바뀌는 과정을 따라가기 쉽습니다.',
    tradeoff: '앞 단계 누락이 뒤로 전달될 수 있어 마지막 원문 대조가 필요합니다.',
    evidence: '설계 근거 예시: 출처와 미정 항목의 책임을 단계별로 나눕니다. 효과 실측 없음.' },
  { id: 'parallel', name: '독립 작성 후 합류', version: 'design-parallel-v1', structure: '원 자료 → 자료 정리 + 안내문 작성 → 발행 검토',
    memory: '정리와 작성은 같은 원 자료를 독립 열람하고 서로의 초안을 보지 않음', permission: '검토 역할만 두 산출물을 함께 읽도록 계획',
    reason: '정리 역할의 누락을 그대로 이어받지 않는 별도 확인 경로를 만듭니다.',
    tradeoff: '두 해석의 불일치를 해결할 합류 검토가 늘어납니다.',
    evidence: '설계 근거 예시: 독립 작성과 비교 책임이 순차안과 다릅니다. 실제 독립 실행 없음.' },
  { id: 'gated', name: '검토 후 되돌림', version: 'design-gated-v1', structure: '자료 정리 → 안내문 작성 → 발행 검토 ↺ 안내문 작성',
    memory: '초안과 검토 기록을 버전별 보존하고 확인된 항목만 수정에 반영', permission: '검토 통과 전 외부 게시 경로를 보류하도록 계획',
    reason: '미정 항목을 해결할 때 새 초안과 이전 검토 기준을 함께 추적합니다.',
    tradeoff: '종료 조건이 없으면 검토가 반복되므로 횟수와 담당자 판단 경계가 필요합니다.',
    evidence: '설계 근거 예시: 재검토와 발행 보류 경계가 추가됩니다. 자동 반복 엔진 없음.' }
];
export const ROUNDS = [
  { id: 'round-1', label: '1회 · 개선 예시', candidate: 'candidate-1', input: 'queue-A / source-v1',
    baseline: '개인 사진을 준비해 주세요.', result: '개인 사진은 선택입니다.',
    status: '개선', evidence: '선택 준비물 구별이 복원된 비교 예시. 독자 이해 효과는 미검증.' },
  { id: 'round-2', label: '2회 · 악화 예시', candidate: 'candidate-2', input: 'queue-A / source-v1',
    baseline: '구체적인 날짜는 담당자 확인 뒤 기재합니다.', result: '토요일에 만나요.',
    status: '악화', evidence: '짧게 만드는 변경에서 날짜 미확정 표시가 사라진 회귀 예시.' },
  { id: 'round-3', label: '3회 · 실패 예시', candidate: 'candidate-2', input: 'queue-B / source-example-B',
    baseline: '접수 방법 확인 필요.', result: '후보 산출물 없음 — 자료 읽기 실패 예시.',
    status: '실패', evidence: '입력 확보 실패는 품질 합격이나 사용자 선호로 해석하지 않습니다.' },
  { id: 'round-4', label: '4회 · 미확인 예시', candidate: 'candidate-3', input: 'queue-C / source-example-C',
    baseline: '접근성 문의 경로 확인 필요.', result: '수행 응답 없음 — 결과 미확인 예시.',
    status: '미확인', evidence: '응답 유실만으로 실패를 확정하거나 외부 행동을 반복하지 않습니다.' }
];
export const RECORDS = [
  { id: 'input', title: '초기 자료', ref: 'source-v1', text: '새로 작성한 가상 운영 메모. 실제 요청 수집 없음.' },
  { id: 'design', title: '설계 비교', ref: 'design-serial-v1', text: '세 구조를 비교하는 고정 예시. 실제 후보 생성 없음.' },
  { id: 'artifact', title: '역할 산출물', ref: 'announcement-v1', text: '읽기용 텍스트가 존재함. 실제 에이전트 실행·PDF 생성 없음.' },
  { id: 'alternative', title: '사용자 대안 범위', ref: 'local-draft', text: '이 고정 예시에 사용자 입력을 포함하지 않음. 작성 초안은 화면 상태로만 보관.' },
  { id: 'inquiry', title: '설명과 보류', ref: 'inquiry-example-1', text: '경쟁 설명 형식 예시. 확보한 새 수행 증거 없음.' },
  { id: 'failure', title: '탈락·실패·결손', ref: 'round-2 / round-3', text: '날짜 누락으로 후보 재검토, 입력 읽기 실패. 예시 담당자: 검토자 A.' },
  { id: 'iteration', title: '회차 비교', ref: 'round-1..4', text: '개선·악화·실패·미확인 전체 회차의 형식 예시.' },
  { id: 'approval', title: '승인·적용', ref: 'candidate-3', text: '승인 기록 없음. 실제 적용 없음. 운영 버전 없음.' }
];
export const EXPLORATIONS = {
  initial: { label: '초기 설계', source: 'source-v1의 미정 날짜·접수 조건', question: '미정 항목을 누가 확인하고 어느 단계에서 보류할까요?' },
  critic: { label: '설계 검토', source: '선택 설계 버전의 역할·권한 계획', question: '정리 역할이 날짜를 빠뜨리면 다음 검토에서 발견할 수 있을까요?' },
  alternative: { label: '내 버전 이후', source: '현재 역할·원본 버전·선택 범위와 사용자 초안', question: '표현 차이가 자료 누락 때문인지, 읽는 순서 때문인지 구별할 새 자료가 필요합니다.' }
};
