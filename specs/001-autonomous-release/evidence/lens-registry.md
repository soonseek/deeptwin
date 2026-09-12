# 철학 렌즈 레지스트리와 조합 경계 — T029 구현 증거

확인일: 2026-09-08 · 범위: T029 · 실제 모델/사용자 대안/효과 시험: **0회**

## 판정

기존 DG-L01의 17개 원자적 렌즈 정의를 하나의 검토 문서 묶음으로 고정해 읽고, 세 허용 경로의
qualification·적용/비적용/기권·조합·중복·미해결 충돌을 fail-closed 계약으로 구현했다. 문서 검토,
학술 검토, 실제 효과 검증, 운영 채택은 서로 다른 상태이며 문서 검토만으로 어떤 렌즈도 활성화되지
않는다. 독립 공격 검토의 세 차례 수정 후 현재 T029 범위의 P1/P2 blocker는 없다.

이 판정은 렌즈가 실제 업무 품질을 높였거나, 철학 해석이 학술적으로 승인됐거나, 크리틱 판단 오류가
독립적이라는 증거가 아니다. 실제 graph evidence verifier와 lineage는 T030/T035/T056, production
hard gate 연결은 T036, 별도 학술·효과·독립성 실증은 T076/T077에 남는다.

## 구현한 경계

- `app/services/lenses.py`는 `definition-candidates.md`, `composition-contract.md`, `source-map.md`,
  `review-report.md`, `review-cases.md`가 같은 디렉터리의 정확한 검토 byte 묶음일 때만 `draft-1`
  레지스트리를 연다. 공통 C1/C2/S0/R0 계약이나 카드 한 글자라도 달라지면 새 미검토 버전으로
  취급해 로드를 거절한다.
- 17개 카드 각각은 정확한 ID·버전과 전체 정의/조합 계약 및 카드 byte에 묶인 content ref를 가진다.
  문서 검토 상태는 `passed_scoped`지만 scholarly review는 `not_reviewed`, effect는
  `not_validated`, adoption은 `not_adopted`, qualified path는 빈 목록이다.
- `initial_design`, `critic_counterexample`, `post_alternative_spli`의 입력 형태와 증거 역할을
  구별한다. 최초 업무 설명을 사용자 대안이나 SPLI로 재분류할 수 없고, SPLI는 원 수행·실제 대안·
  관찰 차이·고정 H_exp의 서로 다른 기록과 `whole|partial` 범위를 요구한다.
- 애플리케이션이 제공하는 trusted verifier가 exact qualification, route, applicability를 확인하지
  않으면 `proposed`가 되지 않는다. 부재·unknown·failed·revoked·다른 ref/path/scope,
  not-applicable, 기존 절차 중복을 서로 다른 감사 상태로 남긴다.
- 결정과 조합 입력은 공개 생성자가 아니라 해당 레지스트리 인스턴스만 발급한다. 재구성한 값이나
  같은 문서 묶음의 다른 레지스트리에서 발급한 값을 넘기면 거절한다. 이 process capability는
  직렬화하지 않는다. 재시작 가능한 durable decision record는 후속 verifier 통합 전까지 지원됐다고
  주장하지 않는다.
- 조합 입력은 호출자가 쓴 자유 해시가 아니라 domain의 immutable `design_decision` ref에 묶이며,
  bind와 compose 양쪽에서 evidence verifier를 다시 거친다. 표시용 alias는 canonical identity가
  아니며, 하나의 alias가 서로 다른 ref를 가리키거나 같은 typed identity가 두 content hash를
  주장하면 거절한다.
- 한 렌즈 결정은 여러 graph 설계판단에 기여할 수 있다. 반대로 같은 렌즈가 같은 canonical 판단에
  두 번 기여해 자기 중복/자가충돌을 만드는 것은 거절한다. 여러 렌즈가 같은 판단에 같은 proposal
  content를 내면 중복, 다른 proposal이면 `unresolved_conflict`로 보존하며 평균·다수결·숨은
  우선순위로 해결하지 않는다.
- 서로 다른 path/scope/partial 범위의 결정을 한 조합으로 섞지 않는다. 필수 제약 실패는 가치 충돌의
  한쪽이나 높은 점수로 유지하지 않고 `rejected_required_constraint`로 분리한다.
- 일반 감사 projection에는 정의 ref·문서 bundle·경로·범위·qualification 상태·결정·근거 ref만
  포함한다. process capability나 개인 철학/성격 프로필은 포함하지 않는다.

## 검토에서 재현하고 닫은 결함

1. 변경한 공통 계약이 기존 카드의 문서 검토 상태를 상속할 수 있던 문제를 전체 bundle byte pin으로
   차단했다.
2. 기본 레지스트리의 자체 qualification, 동일 해시를 여러 SPLI 증거 역할에 재사용, 서로 다른
   path/scope 조합, 충돌 그룹 안 중복 유실을 차단했다.
3. 공개 `LensDecision._create`와 caller-supplied judgment hash로 발급/판단 동일성을 위조하던 경로를
   registry issuance capability와 typed graph ref/verifier binding으로 교체했다.
4. 한 렌즈당 입력 하나만 허용해 문서 계약의 복수 요소 기여를 막던 문제를 `lens_ref -> inputs[]`로
   수정하고, 결정별 최소 한 입력 및 각 입력의 exact decision/issuer/verifier 결합을 검사했다.

최종 독립 재감사는 공개 API 기준 activation, cross-registry, canonical alias, 복수 기여 및
중복/자가충돌 반례를 재실행했고 T029 완료 가능으로 판정했다. 서로 다른 typed ID가 실제로 같은
판단을 가리키는 이중 등록 방지는 production graph store verifier의 후속 책임이며 현재 효과 검증으로
확대하지 않는다.

## 실행 증거

```text
/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python \
  -m pytest -q app/tests/test_lens_registry.py
..........................                                               [100%]
26 passed

/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python \
  -m pytest -q app/tests/test_lens_registry.py \
  app/tests/test_codex_api_mode.py app/tests/test_runtime_ledger.py
82 passed in 11.03s

/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python \
  -m pytest -q app/tests
1875 passed, 1 dependency deprecation warning in 30.26s

/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python \
  -m compileall -q app/services/lenses.py
git diff --check -- app/services/lenses.py app/tests/test_lens_registry.py
PASS
```

현재 구현/시험 SHA-256:

```text
ae33bfb1c484ee479d3856be8bbe5615ade50f2e64fd9c31a1bc1c240da242a3  app/services/lenses.py
7aa84a44f5a04d8bf3dff15d2bf051c4e43d443c06eecab70acd4e94dc72c1de  app/tests/test_lens_registry.py
```

검토 문서 bundle SHA-256은 코드의 exact pin과 일치한다.

```text
4c183d846e481c8252ad7e00e7edf9efbd0b61b90135ae6d45259ef8fe95dd88  definition-candidates.md
ae046a60ea2025386efcefef325d5fa6d656b3fc877d32060115bb57635a12d6  composition-contract.md
43174bc3bc98543cb8ee4892ad84ae2f7a1162e499999e1b28f61936b84bb78e  source-map.md
ae816c552b835f167d435dd93c46459b76bb9cc4e6656ad16c3d56a427978aa9  review-report.md
6532e8335649329a03c3218ec12923cfb763f3e4cc0e64b2521269a65e2892ed  review-cases.md
```
