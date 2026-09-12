---
name: deeptwin-eval-world
description: Use with eval-engineering when designing or auditing DeepTwin evaluation tasks. Preserves project-specific evidence boundaries, artifact handoffs, and source routing; not a runtime agent persona or a source of task answers.
---

# DeepTwin evaluation knowledge

2026-09-07 · 신규 재사용 지식 초안, 사용자 검토 전. 아래 출처에 이미 있는 요구와 확인한 코드 경계를 안내한다. 이 스킬 자체가 평가 실행·모델 호출·운영 변경을 허가하지 않는다.

Read `$eval-engineering` first for the general evaluation workflow. Use this skill only for DeepTwin-specific adaptations. Resolve the following paths from the active repository/worktree root, not a different checkout.

## Start here

| 필요 | 읽을 출처 | 확인할 것 |
| --- | --- | --- |
| 제품 정체성과 생성 계약 | `docs/superpowers/specs/2026-09-07-deeptwin-graph-generation-design.md` §2·3·6·9 | 실제 관제 그래프, 도구/역할별 모델, 검토 자격과 미구현 경계 |
| 렌즈의 근거·미결 | `docs/lenses/review-report.md`, `docs/lenses/definition-candidates.md`, `docs/lenses/composition-contract.md` | 실제 정의 버전·출처 제한·세 사용 경로·기권·조합의 추가 가치 미검증 |
| 검증 설계 | `docs/superpowers/specs/2026-09-07-deeptwin-verification-selection-design.md` | 문서/검사자/생성/실행/성장 증거와 아직 미확정인 기준 |
| 실제 연결 범위 | `app/server.py:CAPABILITIES`, `app/requests.py:Requests.create`, `app/understanding.py:prompt_for,checked_output,_run` | 사용 시 다시 확인. 작성 당시 실제 모델 경로는 업무 이해이며 설계 생성·실행은 blocked |
| 합성 UI와 시험 한계 | `control-prototype/fixtures.mjs`, `control-prototype/tests/fixtures.test.mjs` | authored fixture·문자열 비교를 실제 엔진/효과 검사로 오인하지 않음 |

## Task 설계에서 보존할 관계

- 최초 설명·업로드·요구 수정과 실제 산출물의 전체/부분 대안은 다른 입력이다. MANUAL-001과 사용자의 기존 YouTube 업무 설명은 대안·평가 정답·성장 증거로 재사용하지 않는다.
- 각 에이전트의 완결된 원형 산출물, 생산·소비 역할, 당시 버전, 접근 권한을 연결한다. 문서·PDF·이미지·표를 짧은 텍스트 의견으로 축소하지 않는다. 파일을 물리적으로 복사하는 것만 정답은 아니며 전체 접근이 가능한 고정 버전 참조도 가능하다.
- 전체 인계·기본 정확성·필수 도구와 권한을 무렌즈 기준군에서 빼지 않는다. 렌즈가 같은 질문만 반복하거나 이미 충분한 절차에 비용만 더하는 결과도 보존한다.
- 초기 설계·비평 반례·SPLI는 입력 전제가 다르다. 개인 철학 프로필이나 철학자별 고정 에이전트로 바꾸지 않는다. 반례 타당성과 후보 대응 판정을 분리한다.
- 부분 대안의 증거 범위는 부분적이지만 영향은 후속 역할까지 넓어질 수 있다. H_phi/S_phi는 직접 운영 규칙이나 변경 후보의 근거가 아니다. 새 E_phi로 H_exp를 검증한 뒤 별도 변경·이전 큐 재평가·봉인/경계/회귀·사람의 정확한 환경 버전 승격을 거친다.

## 확인 방법과 알려진 한계

`checked_output`의 인용 존재는 의미 지지나 요구 완전성을 증명하지 않는다. 이해 단계가 누락한 예외를 생성자·크리틱이 공유할 위험을 원자료에서 검사한다. 구조 이름/문자열 차이는 실질적인 그래프 다양성의 증거가 아니다.

같은 모델에서도 생성자 자기평가·렌즈 정체성·다른 크리틱 결론에 대한 접근 경계와 별도 근거를 확인한다. 프롬프트 분리·합의·소수 무오류 결과로 판단 오류의 통계적 독립성을 선언하지 않는다. 구독/API와 실제 모델 설정을 기록하되 접근 비밀·숨은 사고과정은 남기지 않는다. 도구·모델·판정기 장애는 원인에 맞게 분류하고 업무 실패와 섞지 않는다.

현재 업무 이해 어댑터는 도구·파일·브라우저·subagent를 차단한다. 이를 그대로 PDF 제작/멀티에이전트 실행 시험의 harness로 쓰지 않는다. `app/ingestion.py`의 PDF/DOCX 텍스트 추출은 부분 읽기이며 이미지 등 의미 이해의 증명이 아니다. 구현이 바뀌면 코드·실행 근거로 이 제한을 갱신한다.

## Coverage and updates

첫 개발 Task Spec의 위치는 `evals/deeptwin/tasks/v01-q01/Task.md`이며 아직 Draft/미구현이다. 정확한 입력·초기 상태·정답·scoring·숨긴 자료는 해당 Task.md에만 둔다. World Skill은 평가받는 모델에게 제공할 업무 자료가 아니며, 기본적으로 모델-visible 환경에 포함하지 않는다.

실행형 평가 package, 실제 크리틱 자격, 렌즈의 추가 효용과 성장 효과는 확인되지 않았다. 사용 가능한 provider/model이나 검사 임계값을 추측해 적지 않는다. 검토된 실행 계획 없이 사용자 DB·모델·실서비스를 호출하지 않는다.

새 Task를 설계·감사할 때 여러 Task에 필요한 재사용 사실만 코드·사용자 결정·실제 시험 근거와 함께 갱신한다. 특정 사례의 정답을 일반 지침으로 만들지 않고, 반증된 지침은 좁히거나 수정한다. 새 재사용 내용은 사용자에게 보여 검토받으며 미실행 방법을 검증 완료로 기록하지 않는다.
