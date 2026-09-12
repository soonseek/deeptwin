# 검증·평가·배포 수용 계약

작성일: 2026-09-07 · 버전: `verification-v1` · 상태: 사용자 위임에 따른 상세 설계. 새 기술 결정에 대한 개별 사람 검토, 실제 평가 실행 또는 효과 입증 기록이 아니다.

**Pass iff:** 명세의 각 필수 사용자 결과와 금지 효과가 해당 버전의 독립 증거로 확인되고, 시험 유효성·실제 제공자/도구·성장/승격 경계가 검증되며, 미확인 필수 요구를 완료로 바꾸지 않은 경우에만 그 범위의 수용을 선언한다.

## 1. 근거와 최신 요구

- 현재 요구 정본은 [spec.md](../spec.md)다. 최신 변경에 따라 **Codex 구독 및 명시 선택 API, Claude API 전용**을 검사한다. 과거 문서의 Claude 구독 필수 문구는 이 부분에 한해 최신 요구로 대체한다. 현재 문서 작성은 실제 모델 호출·API 과금·실험 예산 승인이 아니다.
- [통합 제품 설계](../../../docs/superpowers/specs/2026-09-06-deeptwin-integrated-product-design.md) §4–6, [그래프 생성](../../../docs/superpowers/specs/2026-09-07-deeptwin-graph-generation-design.md), [검증·선별](../../../docs/superpowers/specs/2026-09-07-deeptwin-verification-selection-design.md)에서 원자료·실행·대안·판정·개입·승격의 관계를 계승한다.
- 논문 근거는 사용자가 제공한 비공개 DeepTwin 참조 논문을 상위 설계서가 대조한 §4.4–4.10,
  §5.1, §6.4의 출처/진단/SPLI/개입/검증 경계다. 공개 저장소에는 사용자 장치의 절대 경로나
  비공개 원문을 넣지 않는다. 철학 출처는 [실독 지도](../../../docs/lenses/source-map.md), [원자 정의](../../../docs/lenses/definition-candidates.md), [조합 계약](../../../docs/lenses/composition-contract.md), [검토 범위](../../../docs/lenses/review-report.md)를 따른다. 이 작업에서 원 논문이나 철학 원전 전체를 새로 재독·학술 검증했다고 주장하지 않는다.
- 제품 재평가 종료의 계량 정본은 [growth.md](growth.md)다. `patience=3`은 제품 튜닝 루프의 동작이며 이 개발 프로젝트의 종료 규칙이 아니다. 화면 수용은 [experience.md](experience.md)와 연결한다.
- [현 B 평가 계획](../../../docs/superpowers/plans/2026-09-07-deeptwin-critic-evaluation.md)과 [Q01 Task.md](../../../evals/deeptwin/tasks/v01-q01/Task.md)는 기존 평가 경계의 근거다. **Q01의 정확한 입력·기준 자료·정답·채점 경계는 기존 Task.md 한 곳에만 둔다.** 본 문서는 새 구체 Task, 실행형 harness, World Skill 변경 또는 채점 결과를 만들지 않는다.

## 2. 현재 증거와 아직 없는 증거

기존 B1–B3의 입력/응답 계약, 감사 journal, 제어된 오프라인 실행기 및 전체 Python 회귀 **729개 통과**는 이전 실행 보고의 부품·회귀 증거다. 이 문서 작성 중 해당 시험을 재실행한 것이 아니다.

실제 코드의 `app/critic_trial.py:OfflineRunner._worker`는 제어된 `OfflineTransport`만 허용하고, `_classify`의 정상 완료도 `semantic=not_checked`, `score=null`이다. `app/codex_understanding.py:CodexUnderstandingModel.generate`의 현 deadline은 `turn/start` 뒤 시작하며 계정/설정/skills preflight 전 구간의 중단은 별도 보완 대상이다. 로컬 결과 적용 차단과 실제 제공자 실행·사용량 종료를 구별한다.

따라서 729개라는 수치는 크리틱 의미 정확성·오류 독립성·렌즈 효과·실제 PDF 수행·DeepTwin 성장의 성적이나 전체 완성률로 사용할 수 없다. 기존 업무 이해의 실제 소수 합성 실행과 관제 UI fixture도 각각 제한된 연결 증거와 시제품이지 그 뒤 엔진의 실작동 증거가 아니다.

## 3. 명세에서 독립 검사로 연결하는 계약

각 수용 항목은 `criterion_id`, `spec_refs`, `subject_version`, `required_outcome`, `forbidden_effects`, `independent_truth_refs`, `visible_information`, `check_type`, `validity_prerequisites`, `accepted_equivalents`, `pass_rule`, `failure_rule`, `evidence_manifest`, `review_status`를 갖는다. 기준은 결과를 보기 전에 고정하고 변경 이력을 남긴다. 구현자가 자신이 만든 기능의 동작을 그대로 정답으로 복사하지 않는다.

| 명세 범위 | 독립적으로 확인할 결과 | 충분하지 않은 대체물 |
| --- | --- | --- |
| FR-001–003, 009, 030 | 새 사용자 GUI의 실제 입력/연결/읽기 범위/수정/복원과 동일 업무 상태 | 스크린샷만 존재, 제작자 장치의 로그인, 입력을 모두 이해했다는 모델 선언 |
| FR-004–008, 012 | 공통 요구를 유지한 실제 그래프 기능 차이, 렌즈 판단 연결, 독립 검토, 정확한 모델/수정/승인 버전 | 세 이름·좌표·설명 문자열, 생성자 자기점수, 고정 템플릿 세 개 |
| FR-010–015, 032 | 지원 제공자 각각의 핵심 LLM 여정, 프레임워크 도구 실행, 원형 파일과 수신 접근·분기/합류/실패 복구 | 한 제공자로 다른 제공자 지원을 대체, 텍스트로 쓴 브라우저/PDF 완료 보고 |
| FR-016–022 | 원본/실제 전체·부분 대안/관찰/경쟁 원인/새 증거/타입 지정 변경의 출처 연결 | 최초 설명을 피드백으로 소급, 사용자의 생각·가짜 응답, 대안 문장 복사 |
| FR-023–026 | 기준/후보 이전 큐 비교, 조기 종료 정확성, 별도 검증, 사람이 승인한 동일 번들의 적용/롤백 | 튜닝 점수를 미관측 성적으로 재명명, plateau 뒤 자동 승격 |
| FR-027–029 | 배포 후 프레임워크가 처음 관측 가능한 제어 사건부터의 제품 사건(관측 전 Docker/Portainer 사건 소급 없음)·실패·탈락/렌즈 이력, 원본 공개 범위/가림/결손이 일치하는 선택적 추출 | 내부 호출 journal 하나, 해시만 있는 파일을 완전 재현 가능이라고 표시 |
| FR-031, 033–034 | 증거 단계·변경 영향·진척 계산의 공개, 필수 미완료와 검증 한계 표시 | 테스트 개수·에이전트 합의·추정 진척률로 제품 효과를 주장 |

독립 정답은 원자료/정책/실제 전후 상태에서 재계산한다. 서로 다른 유효 문구·파일 배치·역할 구성을 허용한다. 특정 문자열·길이·철학명·전용 CSV·정해진 내부 호출 순서는 그 자체가 요구인 경우를 제외하고 합격 기준으로 삼지 않는다.

## 4. 검사 층과 실패 분류

검사 순서는 **시험 유효성 → 결정적 사실/권한/형식 → 제한된 의미·시각 판단 → 업무/성장 효과**다. 상위 단계가 무효인데 숫자 점수를 남기거나 필수 실패를 평균으로 상쇄하지 않는다.

| 상태/원인 | 의미 | 점수와 처리 |
| --- | --- | --- |
| `valid_pass` | 충분한 증거 아래 해당 기준 충족 | 해당 기준만 통과. 범위를 넘어 일반화하지 않음 |
| `valid_capability_failure` | 필요한 정보·정상 도구·공정 기준이 있는데 업무 결과가 잘못됨 | 해당 기준 실패/0. 좋은 문체나 다른 항목으로 상쇄 불가 |
| `valid_output_contract_failure` | 정상 호출 결과가 필수 형식/참조 계약을 어김 | 모델/에이전트 결과로 보존. 인프라 무효로 지우지 않음 |
| `evidence_insufficient` | 원자료 자체로 판단 불가 또는 아직 사람 판단/필수 관측 미완료 | 관련 의미 판정 미결·점수 없음. 허용된 기권을 오답으로 처리하지 않음 |
| `task_information_defect` | 시험이 요구하는 사실을 보이거나 발견 가능하게 제공하지 않음 | 시험 무효/no-score. Task/환경 수정 후 새 버전 |
| `harness_defect` | 실제 경로와 다른 prompt/tool/session/adapter가 시험을 왜곡 | 무효/no-score. 구현 결함 수정 후 영향받은 시험 재수행 |
| `environment_defect` | 잘못된 초기 상태·권한·서비스·reset/재생 자료 | 무효/no-score. 원래 상태/공정 조건 복구 |
| `verifier_false_accept\|verifier_false_reject` | 잘못된 결과 통과 또는 유효 대안 오거절 | 판정 무효/no-score, 검사기 버전 수정·경계 fixture 재검사 |
| `judge_or_infrastructure_failure` | 판정 모델 오류·잘못된 응답·인증/제공자 장애·평가 timeout | 무효/no-score. 에이전트 능력 실패로 집계하지 않음 |
| `leakage_or_isolation_failure` | 정답/판정 내부자료/타인 결론/대안 원문 등에 무권한 접근 | 관련 시험 무효/no-score + 별도 필수 보안 실패. 단순 재시도로 숨기지 않음 |
| `prohibited_effect` | 정상 관측에서 권한 없는 게시/변경 등 금지 행위 확인 | 해당 에이전트/권한 집행의 필수 실패. 부수 효과로 후속 상태가 오염되면 후속 비교도 무효 |
| `cancelled\|interrupted\|remote_stop_unconfirmed` | 종료/결과가 불완전하거나 실제 실행 종료 미확인 | 점수 없음, 이전 요청과 상태 보존. 성공/재전송으로 자동 전환 금지 |

필수 산출물을 정상 실행 예산 안에 만들지 못한 사실이 완전하게 관측된 경우는 `valid_capability_failure`로 분류할 수 있다. 제공자 한도·판정기 timeout 때문에 관측이 끊긴 경우와 구별한다. 숫자 0을 모든 오류의 공통값으로 쓰지 않는다. 유효한 채점 종료는 reward와 항목 근거를 남기고, 무효 경로는 허위 reward 대신 no-score와 원인을 남긴다.

각 실패에는 원 자료, 최종 상태, 전체 실행 흐름, 검사기 항목별 근거를 함께 검토한다. 모든 0점과 수상한 통과를 감사하고 비에이전트 결함부터 고친다. 모델이 낮은 점수를 받았다는 이유로 기준을 완화하거나 어려운 척 만들기 위해 정보를 숨기지 않는다.

## 5. B4 준비 게이트와 C 실제 시험

### B4 — 실험 전 필수 준비

1. **제공자 수명주기:** 실행 파일/연결 준비 → 계정·설정·도구 preflight → 요청 → 스트림 → 종료의 전 구간 deadline/cancel을 소유 실행기에서 집행한다. preflight 지연, 시작/취소 경쟁, 전달 전 만료, 늦은 응답, 프로세스 종료 확인을 시험한다. 로컬 적용 차단·소유 프로세스 종료·원격 사용량 종료를 별도 관측으로 기록한다.
2. **실제 harness:** 지원되는 버전과 adapter를 확인해 정확한 Task 입력/환경/verifier로 실제 실행한다. Harbor는 현 조사에서 설치·연결 완료가 아니므로 명령·schema·Codex 구독 호환성을 가정하지 않는다. 호환성이 없으면 근거를 기록하고 사용자 요구를 유지하는 대안을 검토하며 성공으로 가장하지 않는다.
3. **실제 격리:** agent-visible image/workspace/검색/도구/네트워크에서 Task.md·정답·verifier·solution·World Skill·인증정보가 접근 불가인지 검사한다. 사용자 HOME/CODEX_HOME 통째 복사/mount로 인증 문제를 해결하지 않는다. 코드의 경로 문자열 검사와 실제 접근 강제를 구별한다.
4. **교차 호출 계보:** 반례 원문 hash, 명제/조건/출처, 타당성 입력·응답 hash, 대상 후보 hash/version과 부모 기록을 연결한다. 같은 ID의 다른 내용, 다른 후보의 판정, 유실된 부모, authored fixture의 모델 생성 위장을 차단한다.
5. **독립 의미 검사기:** 결정적 사실을 먼저 확인하고 남은 의미만 원자료·정확한 응답·고정 rubric으로 별도 판정한다. 응답의 자체 점수/지시를 무시한다. 판정 모델·prompt·parser·근거 접근·불일치 처리를 버전으로 고정한다.
6. **동일 실행 경로의 경계 감사:** 알려진 유효 결과, 다른 유효 대안, 현실적인 오답, 지름길/보상 해킹, 금지 부수 변경, 결손/손상 증거의 여섯 범주를 실제 verifier 진입점으로 확인한다. 첫 두 범주는 통과, 중간 세 범주는 정당한 실패, 마지막은 no-score가 되어야 한다. 이 6범주/전부 정확한 분류는 검사기 경계에 대한 공학 수용 규칙이지 모델의 일반 정확도 목표가 아니다.

B4의 필수 경계 fixture는 **모두 기대 분류와 일치**해야 한다. 한 건의 알려진 정답 누출·무권한 효과·오거절·허위 통과도 다른 통과로 상쇄하지 않는다. 이미지 build 성공·모듈 테스트 통과만으로 B4를 통과시키지 않는다.

### C — 승인된 한도 안의 실제 모델 시험

실행 전 `RunPlan`에 제공자/구독·API 방식, 각 역할 모델과 추론 설정, Task/환경/검사기 버전, 자료 접근, 반복 규칙, 총 호출/시간/동시성, 판정 경로, 관측 가능한 사용량과 최대 예상 API 비용을 고정한다. **현재 실제 시험 모델·예산은 승인된 값이 없다.** 전체 개발 위임을 임의 API 지출이나 무제한 모델 호출 승인으로 해석하지 않는다.

첫 교정의 권고 기본은 **동시성 1**로 전체 흐름을 감사하는 것이다. 특정 모델 세 종류나 모든 항목 반복 세 회를 의무화하지 않는다. 변동성이 실제로 관측된 항목만 사전 규칙과 남은 한도 내에서 반복한다. 전체 호출 수·시간·비용은 정확한 Task 구성에서 계산한 유한 RunPlan으로 확정하며 비어 있으면 실행하지 않는다. 이 동시성은 처리량/정확성의 검증 결과가 아니라 감사와 사용량 통제를 위한 위임 기본안이다.

현재 Q01의 정확한 입력·정답 경계는 기존 Task.md를 사용한다. 일부 호출의 성공이나 JSON roundtrip을 Q01 전체 통과로 집계하지 않는다. 초기 C 교정 통과 후에도 새 봉인 사례 자격과 렌즈 효과는 별도 게이트다. 검사기/환경 결함을 고친 재실행은 원 실패와 연결하고, 모델의 정당한 능력 실패는 제거하지 않는다.

## 6. 동일 모델 크리틱의 판단 오류 독립성

사용자 요구는 다른 모델 권고나 “같은 모델이라 어쩔 수 없다”는 고지로 대체하지 않는다. 다음 두 층을 각각 구현·측정해야 한다.

**강제 가능한 정보 독립 경계:** 생성자의 자기점수·렌즈 정체성·다른 크리틱 총평·수정 정답에 접근하지 못하는 세션/저장소/도구 경계를 제공한다. 공통 업무 이해 요약만 신뢰하지 않고 원자료에서 필수 요구·예외·권한을 별도로 재구성한다. 구조 검사, 의미 증거 대조, 반례 제안, 반례 타당성, 특정 후보 대응을 분리하며 필수 검사 실패는 투표로 번복하지 않는다. 후보의 실제 기능상 모델·도구·역할·권한은 판단에 필요하므로 숨기지 않는다.

**실증해야 하는 오류 관계:** 같은 모델/확인 가능한 버전·설정에서 독립 원자료 정답이 있는 동일 판정 항목을 생성 경로와 독립 증거 재구성 경로가 각각 수행하게 한다. 양쪽 오류를 item별로 연결하고, 그 뒤 후보를 실제 검토한 성공/실패와 구별한다. 결함이 없는 후보에 대한 오거절과 결함을 놓친 사건을 같은 분모로 섞지 않는다.

반드시 보고할 항목은 조건별 생성 오류율, 크리틱 놓침/오거절/기권율, 같은 항목 공동 오류, 생성 오류가 있을 때의 크리틱 놓침, 표본 수/클러스터, 실제 모델·판정기·조건·불확실성이다. 생성자가 한 번도 틀리지 않은 표본에서 조건부 놓침률을 0이라고 만들지 않는다. 같은 사례를 반복 호출한 것을 독립 업무 표본 수로 세지 않는다.

통계적 보장 범위는 `IndependenceProfile`에 과업군/오류 종류/심각도, 공통 원자료와 알려진 교란, 비교할 기준 크리틱, 허용 공동 실패·초과 의존성, 필요한 표본/판정 정밀도, 추정/불확실성 방법, 중단·제외 규칙을 봉인 자료 관측 전에 고정한다. 권고 보고 기본은 95% 신뢰구간과 실제 분모의 동시 제시이며, 해당 방법의 표본·의존 가정이 충족될 때만 신뢰구간으로 부른다. 그렇지 않으면 기술 통계와 한계만 보고한다.

일반적인 모든 업무에 대한 통계적 독립성이나 오류 0%는 선언하지 않는다. 특히 동시 호출, 역할 분리, 다수결, 다른 철학명, 소수 무오류 사례만으로 보장했다고 하지 않는다. 허용 오류의 업무 위험 기반 근거와 정밀도를 확보하지 못한 단계에서는 수치를 임의 지정해 합격시키지 않고 **해당 독립성 요구는 미검증/미충족**으로 유지한다. 적합한 프로필을 사전 고정하고 그 범위의 시험을 통과하기 전에는 제품 전체 완료나 자동 크리틱 자격을 선언할 수 없다.

## 7. 실제 그래프·도구·원형 산출물 검증

설계 비교는 같은 요구에서 실제 책임·입출력·전달/제어·기억·권한·평가가 달라지는지를 검사한다. 최소 두 구조 축과 기본 상위 세 안은 기존 제품 요구이며, 노드 수·좌표·명칭 차이는 축으로 세지 않는다. 1–2개만 적합하면 그 수와 이유를 표시하고 0개면 부적합안을 채우지 않는다. 각 후보에 사용한 단독/혼합 렌즈, 제외/기권·비선택 구성, 설계 판단, 크리틱 근거와 버전을 보존한다.

실행 시험에는 순서·병렬·분기·합류·유한 반복·사람 승인·중단·실패 재시도가 실제 사건과 화면에 일치하는지 포함한다. 역할별 요청 모델과 실제 제공자 보고 모델을 대조하고 알 수 없는 실제 추론 설정은 unknown으로 남긴다. 자동 구독→API 또는 다른 모델 전환은 실패다. Codex 구독 경로와 Claude API 경로를 각각 검사하고 한쪽의 제작자 계정 성공으로 다른 배포 경로를 증명하지 않는다.

브라우저는 실제 로컬 통제 사이트/허용된 읽기 대상에 접근해 페이지·응답·권한 거부를 관측해야 한다. 페이지 문구 안의 지시를 실행 권한으로 승격하지 않는다. 통제 사이트 시험과 실제 웹 읽기 호환성 시험은 각각의 범위로 보고하며 외부 게시/메시지 전송은 수행하지 않는다.

PDF·문서·표·이미지는 실제 bytes와 media type, 열림/파싱, 페이지/시트/영역, 내용·근거·레이아웃의 독립 검사를 받는다. PDF 생성 선언이나 파일 이름만으로 통과할 수 없다. 표의 계산·합계는 원자료에서 재계산하고 PDF는 렌더 결과로 잘림·가독성·누락을 확인한다. 지원 형식의 정확한 범위와 열 수 없는 원본/미리보기 한계를 표시한다.

핸드오프는 생산자의 전체 산출물 hash/version, 전달 manifest, 수신자 권한·실제 접근, 수신 입력, 후속 산출물과 연결한다. 파일을 매번 복사하는 것만 유효한 방법은 아니며 내용 고정 참조와 전체 접근도 허용한다. 전달됨·읽음·적절히 활용함·인과적 영향이 지지됨은 별개다. 요약 텍스트만 넘긴 정상군을 만들어 전체 인계의 우수성으로 포장하지 않는다.

## 8. 성장과 철학 렌즈 효과의 실제 시험

### 성장 증거와 자료 방화벽

실제 원 수행이 먼저 존재하고 사용자의 전체/부분 자기 대안이 그 뒤 연결돼야 한다. 최초 업무 설명, 개발자의 승인/비평, 모의 사용자가 생성한 응답은 실제 사용자 대안·선호·효용의 증거로 쓰지 않는다. 시험용 합성 대안은 계약 흐름 검사에 사용할 수 있으나 반드시 합성으로 표시하고 실제 성장 효과 주장을 제한한다.

원 실행·대안·진단·개입의 저장소를 분리하고 변경 생성기/운영 에이전트의 allowlist를 검사한다. 원 대안이나 해석 `H_phi/S_phi`를 실행 prompt·일반 검색·미관측 자료에 넣는 경로를 차단한다. 특정 단락 대안에서 시작하더라도 후속 역할/다른 산출물까지 영향 검증 범위를 넓힌다. 본 단락을 바꾸라는 지시로 축소하지 않는다.

시스템 결손/새 판단/기존 지식 미적용/예외/대안 오류/미확정을 경쟁시키며 복원·학습·보호 개입의 예상 결과를 먼저 기록한다. SPLI 질문·렌즈/조합·반대 예측은 새로운 `E_phi` 이전에 고정하고 실제 증거로 `H_exp`를 갱신한다. 사후에 맞춘 철학 설명이나 사용자의 설명 동의만으로 판별력·흡수 성공을 인정하지 않는다.

기준/후보의 이전 업무 큐 재실행은 튜닝 자료다. 고정된 품질 하한/min_delta/유효 비교의 세 연속 비개선·최고 후보·무효/예산/중단 이유·재시작은 growth.md의 수용 사례를 실행해 확인한다. plateau는 별도 검증의 통과가 아니며 개발 중단도 아니다.

후보 고정 뒤 별도 미관측/전향·경계·회귀·출처·안전 평가를 실시한다. 봉인 사례를 본 뒤 수정하면 그 자료는 개발 자료가 되고 새 봉인이 필요하다. 원/후보의 단계별 실제 산출물, 영향을 받은 다른 역할, 실패/비용/사용량, 적용 제외 조건을 비교한다. 효과가 없거나 악화·범위 축소·복원만 필요한 결과도 유효하게 보고한다.

### 렌즈의 세 적용 지점과 통제 비교

| 지점 | 고정할 것 | 관측할 추가 기여 |
| --- | --- | --- |
| 초기 환경 설계 | 동일 업무 요구/자료/권한, 실행 중 렌즈 개입과 모델/도구 조건 | 질문이 실제 구조 판단·역할/인계·업무 결과를 바꾸는지 |
| 크리틱 반례 탐색 | 같은 실제 후보 풀, 독립 판정기와 기준 | 근거 있는 새 반례/판별, 결함 놓침·오거절·공동 오류 변화 |
| 대안 이후 SPLI | 같은 실제 대안·확인된 판단 가설·새 증거 접근/튜닝 예산 | 미확정 설명을 가르는 예측·새 행동 증거, 검증된 변경의 전이 |

비교군은 강한 기존 절차, 렌즈 없음, 일반 다관점 점검, 실제 업무 사례에서 얻은 사용자 구성개념, 출처 기반 구조화 미세렌즈 단독/혼합이다. 사용자 구성개념에 실제 근거가 없으면 이를 만들어 넣지 않고 해당 군의 실행 불가/자료 필요를 표시한다. 기존 절차와 렌즈 없음이 같으면 중복군으로 기록한다. 철학자 이름만 넣은 역할극은 구조화 렌즈의 대리군이 아니다.

같은 정보 접근·업무 능력·권한·모델/추론·평가기·개발/봉인 분리와 **총 생성+검토+보완+실행 예산**을 맞춘 비교를 기본으로 한다. 일반 다관점 군에도 동등한 탐색 기회를 준다. 실제 소비량·벽시계·호출·사람 부담을 함께 보고하고 구독이므로 비용 0이라고 쓰지 않는다. 각 렌즈가 만든 새 증거가 있으면 그 정보 획득 효과와 해석 효과를 구별한다.

세 지점을 동시에 바꾼 시험은 전체 구성 효과만 설명할 수 있다. 지점별 기여를 주장하려면 다른 두 지점을 고정해야 한다. 철학 출처의 충실도, 구조/질문 trace 존재, 실제 추가 효과, 일반화 범위를 별도 보고한다. 실제 도구·파일·사람 대안이 없는 작은 대화 POC를 전체 성장 검증으로 대체하지 않는다.

## 9. 사람 승인·UI 시험·배포 게이트

자동 UI 시험의 `test_actor`는 테스트 저장소에서 승인 버튼·권한 검사·정확한 버전 연결을 검사하는 합성 주체다. 실제 사용자 만족·업무 효과·운영 적용 승인으로 표시하지 않는다. 실제 승격에는 인증된 권한자의 명시 승인 사건과 대상 번들 hash, 검사 보고서, 범위, 롤백 대상이 필요하다. 시험 에이전트가 만든 승인 사건을 실제 환경으로 옮길 수 없다.

| 게이트 | 필수 완료 증거 | 상태가 남으면 허용하지 않는 주장 |
| --- | --- | --- |
| V0 설계 일관성 | 명세→UI/데이터/실행/성장/평가/권한/로그/웹 배포의 추적과 교차 검토, 변경 이유 보존 | 설계 초안 존재만으로 구축·효과 완료 |
| V1 공학 계약 | 관련 단위·회귀·결정적 경계 검사, 중복/취소/저장/복원/승인 변조 시험 | 부품 통과로 실제 모델 판단력 완료 |
| V2 B4 및 C 연결 | 실제 격리·수명주기·verifier 경계·허가된 RunPlan·완전한 실제 실행 기록 | 지원 adapter 가정, 미실행 Q01 성적 |
| V3 설계·크리틱 자격 | 원자료 기반 그래프·검토 의미 시험, 해당 IndependenceProfile의 사전 기준/봉인 증거 | 같은 모델 오류 독립성 요구를 단순 역할 분리로 충족 |
| V4 실제 관제·도구 | 지원 제공자 각각, 실제 브라우저/PDF 등 형식, 단계별 인계, 실행 상태/실패 복구 | 관제 fixture/파일명/텍스트 선언을 실작동으로 표시 |
| V5 DeepTwin 동작 | 실제 연결된 대안/진단/SPLI/변경/큐/조기 종료/검증/사람승격·롤백, 자료 방화벽 검사 | 합성 계약 시험을 실제 사용자 성장 효과로 표시 |
| V6 효과·사용성 | 범위가 명시된 실제 성장·렌즈 통제 비교, 실제 사용자 사용성 결과 또는 미실시 상태의 명시 | 기여 미확인·사람 검토 미실시를 확인된 효과/만족으로 선언 |
| V7 자체 호스팅 배포 후보 | 두 필수 프로필의 새 호스트 배포/브라우저 최초 설정/재시작/업데이트·복구, 지원 OS/모델/도구 범위, 보안/라이선스/로그 추출과 검증 보고서 | 제작자 장치에서만 성공한 것을 모든 배포 지원으로 표시 |
| V8 프레임워크 확장·외부 클라이언트 | 44개 core-owned port schema, 52-operation×terminal result-artifact 조합(모든 non-success와 cancelled codec `artifacts=[]`, success empty/V/O cardinality 및 operation별 role/media/omissions/ref/byte), 별도 52-operation request-artifact-input 조합(11 non-empty-capable/41 exact-empty), exact five-field BindingSlotKeyV1+digest roundtrip, 네 deployment arm의 closed fields/request equality/acyclic digest, durable qualification/binding/rollback-retention/retirement. Export prepare/transmit는 exact snapshot/prepared 1–256 `export_payload` 목록 bytes를 bounded broker stream으로 받으며 ref-only/shared-store/changed-content를 거절. Codec target-media/output-omissions와 tool output contract를 검증하고, `result.effect`만 효과 정본으로 삼아 error 중복 상태와 표 밖 terminal/effect/outcome, succeeded-external-unknown/unconfirmed, failed-unknown/retryable를 거절. Tool invoke success output은 exact `{tool_call_ref,result_ref}`이고 output-level `effect_receipt_ref`/alias는 common effect와 같아도 거절하며 ToolResult artifact bindings는 `result_ref`에 유지. Extra/missing/wrong-role/media/selector/hidden ref, frozen/export-list/ToolDefinition mismatch, codec/storage competing ref, four-field/cross-port/digest mismatch를 거절. A→B replace가 A retained heads를 만들고 owner exact-head release가 immutable history/B binding·installation head를 유지하며 A rollback만 금지; 그 뒤 A retirement은 B dispatch를 유지하고 A retirement head만 전진. Active-environment ref가 없는 conformance slot에서 B disable→B retention release→dependency-zero→current-uninstall→exact tombstone→next-revision C stage/handshake/qualification/binding/dispatch까지 성공하고 A/B를 부활시키지 않음; non-ancestor/dependency/stale/cross-slot/repeated release/released-target rollback/crash fail closed. 두 필수 프로필의 같은 private OCI tool과 전용 mount, Settings의 rollback-retention release/current-uninstall/ancestor-retirement 구분, `app/extensions/**` 재귀 검사. Portable HTTPS에서 T025 frozen composition seam/T087 fixed route contribution의 실제 설치 client parity; HTTP loopback은 non-secret canary로 bearer route pre-parser 비노출 | generic envelope·extension-authored base port·generic 0..256 artifact input·ref-only export·상충 result metadata/effect·중복 output effect receipt·두 precondition 정본·receipt identity 대체·source-tree import·unmounted/임의 dynamic route·HTTP real-bearer/cookie fallback·core rebuild·browser 자동화·T087 single-host 증거를 최종 배포 증거로 표시 |

R16/A13은 T087이 staged topology의 실제 T025 route와 T018 broker에서 닫는 공학 선행
계약이다. V8은 그 결과를 T081 배포물의 두 clean host에서 반복하는 T083 최종 프레임워크
배포 게이트이며 T087 완료의 역방향 선행 조건이 아니다.
여기서 `T018-foundation`만 실제 Linux IPC initializer/listener/peer handshake, bounded artifact
stream과 staged sandbox/channel을 선행 제공한다. 의미 worker·그래프·artifact 경로가 연결된 뒤
`T018-final`이 같은 T018 체크박스를 닫으며, T083의 두 clean-host 반복을 역선행 조건으로 만들지 않는다.

T025의 실제 route 선행 범위는 durable ServiceClient principal/credential revision, create/rotate/
revoke/expiry/last-used, TLS single-bearer authentication, scope/network/rate-limit enforcement,
`app/api/router_composition.py`의 frozen first-party seam과 `app/server.py`의 단일 호출이다. T087은
`app/api/extension_routes.py`와 고정 contribution descriptor, 그 route 위 client parity와 SDK/port
schema 검사를 담당하며 server/composition 파일을 수정하지 않는다. 서로의 책임을 in-process
adapter나 임의 dynamic route loader로 대체하지 않는다.

V8의 SDK/client 시험은 저장소 path를 `sys.path`에 넣는 단위 검사가 아니다. 깨끗한 별도
환경에 extension-author SDK와 HTTP/OpenAPI client를 각각 설치하고, client process의 `app`
import가 불가능한 상태에서 portable profile의 실제 release HTTPS endpoint를 호출한다. HTTP-only
loopback profile에는 real bearer를 보내지 않고 fixed non-secret Authorization canary로 route
unregistered/pre-parser denial을 검사하며 cookie/plaintext fallback을 쓰지 않는다.
브라우저와 동일 command의
durable receipt/revision/authority/event order를 재시작·경합 전후 비교한다. 확장 시험은 저장소 밖에서
만든 tool image의 exact OCI/platform bytes를 사용하고 staging authority, receipt, handshake,
qualification과 invocation을 각각 관찰한다.

배포 보고는 `design_reviewed`, `engineering_verified`, `live_scope_verified`, `effect_unverified`, `human_review_pending`, `release_blocked`, `release_candidate`를 범위별로 구분한다. 필수 공학/권한 게이트가 실패하면 실행 가능한 정식 지원으로 표시하지 않는다. 독립성·효과·실사용의 미충족이 남으면 그것을 숨긴 채 전체 프로세스 완료나 검증된 DeepTwin 프레임워크라고 선언하지 않는다. 시험 가능한 내부 후보와 모든 요구를 충족한 결과는 구별한다. 외부 공개/배포는 별도 권한 경계를 따른다.

## 10. 검증 기록과 변경 관리

`VerificationReport`에는 기준/Task/환경/생성·크리틱·판정기·모델/도구/렌즈/코드의 정확한 버전, 입력·허용 정보·산출물·전후 상태 manifest, 모든 요청/중단·오류·사용량, 기준별 근거/판정/무효 사유, 검토자/검토 범위, 통계 분모와 불확실성, 재실행 부모, 미완료와 허용 주장을 포함한다. 원시 최종 응답/공개 근거와 숨은 사고과정을 구별하고 비밀은 보존하지 않는다.

설계가 바뀌면 영향을 받는 기준·Task·검사기·UI·데이터·실행·회귀를 함께 갱신한다. 채점 기준이나 가시 정보를 수정하면 Task는 Draft로 유지/복귀하고 변경 이유를 보인다. 자동 진행 위임 아래 에이전트가 검토한 설계는 `agent_reviewed`이며 사람이 개별 Task나 결과를 검토했다고 표시하지 않는다.

본 문서 작성에서는 기존 자료와 코드 경계만 읽었으며 새 Task/World Skill 작성, 패키지 설치, 실제 harness 실행, 모델/API 호출, 사용자 데이터 변경을 수행하지 않았다. 이 문서의 게이트는 구축 후 확보할 증거 계약이고 통과 기록이 아니다.
