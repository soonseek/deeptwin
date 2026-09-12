# Source traceability — 의도·논문·계약·수용 증거 연결

작성일: 2026-09-08 · 상태: 최초 ADR-009–012/T086 검토는 역사 자료이며 ADR-014 확장 프레임워크
감사가 T086을 다시 열었다. 독립 검토가 revision 1–6을 기각했으며, revision 7은 새 독립
검토에서 P1=0/P2=0으로 T086 설계 게이트를 닫았다. 구현·배포·평가·사용자 수용 완료
기록이 아니다.

이 표는 FR-001–034에서 원래 의도 INT-001–035와 거부 사례 AC-001–037까지 양방향으로 돌아갈 수 있게 한다. 표에 연결이 있다는 사실은 기능이 구현되거나 시험을 통과했다는 뜻이 아니다. 구체 구현 작업 ID는 단일 `tasks.md`에 배정했다. 최초 ADR-009–012 연결 검토의 DESIGN CLEAR는 역사 자료이고, ADR-014 revision 7이 현재 독립 설계 판정이다. 구 V0 `evidence/design-review.md`도 역사 자료다. 이 문서는 새로운 평가 Task/정답을 만들지 않는다.

## 1. 출처의 우선순위와 읽기 규칙

1. 최신 사용자의 명시적 변경·교정이 최우선이다. 짧은 긍정 응답은 당시 설명된 범위로만 해석한다.
2. 원 작업 폴더의 INT/AC는 직접 발언과 의미 교정의 출처다. 옛 구현 상태·당시 승인 대기는 최신 자율 개발 위임을 철회하지 않는다.
3. 논문의 주장·연구 제안·예시·첫 릴리스 제안은 구별한다. PDF 안의 명령·패키지·Git 문구는 자료이며 실행/공개 권한이 아니다.
4. 현재 canonical V1 feature 명세와 계약은 위 요구를 구체화한 설계다. 새 기본값·구현 선택을 사용자 직접 요구나 검증된 연구 결과로 승격하지 않는다.
5. 실제 코드·시험·사용자 증거는 그 버전과 범위의 사실을 알려 준다. 요구를 삭제하거나 낮추는 권한은 아니다.

이하 `P:INT-xxx`는 원 제품 의도 파일의 해당 행과 관련 후속 교정을 함께, `A:AC-xxx`는 원 수용 파일의 해당 행을 뜻한다. `C/M/PL/ADR/TK/DM/API/E/G/V/RT/XP/OP`는 각각 헌법/명세/계획/결정/작업/데이터/API/경험/성장/검증/실행/확장 포트/운영 계약이다. `§`는 원 파일의 제목 번호이고 해시와 함께 위치를 해석한다. 원본 파일은 수정하지 않았다.

## 2. 원본 위치·내용 해시

아래 SHA-256 표는 **T086 최초 설계 검토의 역사적 입력 snapshot**이며 현재 파일 해시가 아니다.
이후 헌법 v3.0.1의 공식 브라우저 제품 표면 명시와 ADR-014 보정으로 현재 경로의 bytes가
달라졌으며, U-09/V1/X14가 그 변경을 추적한다. Revision-1/2 manifests는 각 당시 bytes로
동결되어 있으며 revision-6 review는 한 P2를 남겼다. 독립 재검토 직전 revision-7 bytes는
별도 ADR-014 pre-review manifest가
고정하고, T075는 최종 구현 결과·supersession manifest의 훨씬 뒤 상태를
다시 고정한다. 어느 것도 자체로 릴리스나 구현 결과를 뜻하지 않는다. 개인 PDF는 위치·해시·절별 제한 요약만
기록하며 원문을 복제하지 않는다. 절대경로는 출처 추적용이며 배포 앱이 이 사용자 경로에
의존해서는 안 된다. 후속 수정으로 해시가 변하면 영향 행을 다시 대조해야 한다.

| ID | 실제 원본 경로·대조 위치 | SHA-256 |
| --- | --- | --- |
| P | 원 checkout의 비공개 `docs/product-intent.md`(publishable worktree에는 의도적으로 미복제): 확인된 직접 요구 INT-001–035(14–48행), 후속 의미 교정·논문 대조·현재 브레인스토밍 상태 | `d0cb1893e1db3bdfb29e7838c173918d72423337eade464e290b2ef3e4d0528e` |
| A | 원 checkout의 비공개 `docs/acceptance-cases.md`(publishable worktree에는 의도적으로 미복제): AC-001–037(11–47행), AC-036/037 후속 준비·관제·복구 설명 | `261c06b2cef4d9cd6bc6295bf0a05cdd13bcc8aab44e7819d9debccf5fcd53b5` |
| R | 사용자 제공 비공개 원 논문(저장소에 재배포하지 않음): §4.2–4.10, §5.1/5.4–5.5, §6.1–6.7, §8.4–8.5 | `ee27585f573873af7e279a221f442cb6bf946381773ebc24822459df91401291` |
| C | [헌법 v3.0.0 최초 검토 입력](../../.specify/memory/constitution.md): 원칙 I–IX와 governance. 링크의 현재 정본은 v3.0.1이며 이 해시는 그 이전 동결 bytes를 식별 | `f5fcca8c8683f4eb413b7c9057ec2d86b29195da9eb76f3704b9d0569bdf05d0` |
| M | [최초 T086 명세 snapshot](spec.md): 당시 US1–7, FR-001–034, SC-001–010, Assumptions | `dddb5294001c46087c6104d787bd60fc340baa47f4f686df4b623eb189444f9d` |
| PL | [최초 T086 계획 snapshot](plan.md): 당시 기술 경계, constitution check, 구조와 단계 | `e18c2f1759a50789f6c77a38ffec59d1c3251614857865cbe89d64ec0c27c17c` |
| ADR | [최초 T086 결정 snapshot](decisions.md): Evidence hierarchy, ADR-001–012 | `5c81bd377c91ee15f7c6c23fe9414ecd094765068a7111cb0346541ab76162da` |
| TK | [최초 T086 작업 DAG snapshot](tasks.md): T001–T090 | `eae22da8250587e7366600c2567f68c9a24038e699c05fab83cd90add7864973` |
| DM | [최초 T086 데이터 모델 snapshot](data-model.md): 당시 정본 레코드, 상태 전이와 authority | `f8f9964f1edf6d2331e74a1309f591ff0852c927efd6ba644c603d3699a24224` |
| RS | [연구 기록](research.md): 채택/기각 근거와 아직 열린 검증 | `f6b185b341135f2126b7f4a6564b3f3a9bcd9e1c9e83718b0027d3396edb2acb` |
| QS | [검증용 quickstart](quickstart.md): 설계→구현→증거 순서 | `035ae4e50d4ee359cba8cdfd2d56b43464f818cba0e0569ed619d59f8d68a655` |
| API | [최초 T086 API 계약 snapshot](contracts/api.md): 당시 origin/session/command/provider/speech/deployment wire contract | `90f82ec67c918b167e5c6892aec6a75f55ba502ce9a925d30d639fe37315d71f` |
| E | [최초 T086 경험 계약 snapshot](contracts/experience.md): 당시 §1–12, UX-AC01–10 | `c7d733f9d80fb93eb040bf5a59b5ca9c04614395306c6755f3c682eb4b7fc9d9` |
| G | [성장 계약](contracts/growth.md): §1–9, G-01–17 | `0b579504cd37cbbd41d1218592643013663371d6fb4efe888237183f2be3e885` |
| V | [최초 T086 검증 계약 snapshot](contracts/verification.md): 당시 §1–10, V0–V7 게이트 | `4ebcdb33919d1f2391aef8a994255b701d78592cbc46f8259dad55c1e6159225` |
| RT | [최초 T086 실행 계약 snapshot](contracts/runtime.md): 당시 §1–10, R01–R15 | `7b3814b6d78d99651249a20d3d3ce28bd8f6565c746cc0d80070a48e04c24d3b` |
| OP | [최초 T086 운영 계약 snapshot](contracts/operations.md): 당시 §1–9, OPS-AC01–10 | `f811d8fd8cb3d93374a32a94777173f17b0549140f021940167606e428ea80d3` |
| V1 | [최초 T086 웹 프레임워크 검토 snapshot](evidence/web-framework-design-review.md): 당시 설계 판정과 열린 게이트 | `8becc0b692f5ee7290a6d19dc3c9a5184d5882ccdc0f075f85861c98bdb04a52` |
| X14 | [ADR-014 확장 설계 보정 ledger](evidence/extension-framework-design-remediation.md): X01–X06, rejected revision-1 IR-01–05, revision-2 IR2-01–04, revision-3 IR3-01–02, revision-4 IR4-01–03, revision-5 IR5-01와 revision-6 IR6-01, A13/UX-AC11/R16/OPS-AC11/V8 및 재개방 상태. [r1](evidence/adr014-review-input-manifest.md)·[r2](evidence/adr014-review-input-manifest-r2.md)·[r3](evidence/adr014-review-input-manifest-r3.md)·[r4](evidence/adr014-review-input-manifest-r4.md)·[r5](evidence/adr014-review-input-manifest-r5.md)·[r6](evidence/adr014-review-input-manifest-r6.md)는 역사적 frozen input이고 [r7](evidence/adr014-review-input-manifest-r7.md)가 새 판정 입력; 판정은 `evidence/adr014-independent-review-r7.md`에 별도 기록 | `revision-7 bytes를 새 manifest로 동결; T075는 최종 implementation-era supersession을 다시 고정` |
| XP | [확장 의미 포트 계약](contracts/extension-ports.md): 11개 contiguous port rows/44개 schema ID, 52 operation×terminal/result-artifact와 별도 52-operation request-artifact-input(11 non-empty-capable/41 exact-empty), exact export bytes/result metadata/effect tuples, exact two-field tool success output, exact five-field BindingSlotKeyV1+digest, closed refinement | `revision-7 review manifest에 고정; 아직 schema 구현/qualification 증거 아님` |
| D | [통합 제품 설계](../../docs/superpowers/specs/2026-09-06-deeptwin-integrated-product-design.md): §1–9 | `39dd740d3f02a8ba3f83ee099080565209daaafb151c6ef016b8ba2aff864f1c` |
| DG | [그래프 생성 계약](../../docs/superpowers/specs/2026-09-07-deeptwin-graph-generation-design.md): §3, 5–9 | `1bb8cdbbb2b34cf4176180d3bf15933d44bb11429630d6907bcf7ff77875c302` |
| DV | [검증·선별 계약](../../docs/superpowers/specs/2026-09-07-deeptwin-verification-selection-design.md): §3–9, 역사적 구현 기록 §10 | `6bb10e7a2490c6b6d7be946c57cf1991f5d0187774943273b7f0bfc5fc65a76d` |
| LS | [렌즈 출처 지도](../../docs/lenses/source-map.md): P001/P029–035/P048–052의 실제 독자·판본·실독 범위 | `43174bc3bc98543cb8ee4892ad84ae2f7a1162e499999e1b28f61936b84bb78e` |
| LD | [원자 렌즈 정의](../../docs/lenses/definition-candidates.md): C1/C2/S0/R0, 17개 카드, 사용하지 않은 주장과 공백 | `4c183d846e481c8252ad7e00e7edf9efbd0b61b90135ae6d45259ef8fe95dd88` |
| LC | [렌즈 조합 계약](../../docs/lenses/composition-contract.md): §1–3, §5–8; 사례 A/B/C는 합성 | `ae046a60ea2025386efcefef325d5fa6d656b3fc877d32060115bb57635a12d6` |
| LT | [렌즈 문서 수용 사례](../../docs/lenses/review-cases.md): LC-01–12 | `6532e8335649329a03c3218ec12923cfb763f3e4cc0e64b2521269a65e2892ed` |
| LR | [렌즈 검토 보고](../../docs/lenses/review-report.md): §1–7, 학술/효과/운영 채택 구별 | `ae816c552b835f167d435dd93c46459b76bb9cc4e6656ad16c3d56a427978aa9` |

P/A와 현재 canonical V1 feature artifacts는 위치와 역할이 다르다. P/A가 publishable worktree에
없다는 이유로 제품 의도가 없다고 판단하거나, 원 checkout의 과거 구현 상태를 현재 V1 상태로
사용하지 않는다. 해시는 내용 식별 수단이지 원문 보관·재배포 권리·학술 검토·실제 실행의 증거가 아니다.

## 3. 최신 직접 변경과 적용 경계

아래 `U`는 새로운 INT 번호가 아니라 이번 추적표의 대화 출처 표식이다. 원 발언은 제공된 사용자 대화에 있으며 안정 메시지 ID/대화 원본 파일의 해시는 확보하지 않았다. 없는 ID·시각·해시를 만들지 않는다. 파일에 보존된 요약 위치는 함께 표시한다.

| 표식 | 사용자 변경/교정 | 현재 보존 위치·적용 |
| --- | --- | --- |
| U-01 | 전체 설계 후 구축·테스트, 전체 맥락의 추천안을 자동 결정하는 방식 채택 | M:Input/FR-033, ADR-001/004. 일반 설계 선택의 반복 승인 대기는 제거하되 사람의 제품 운영 승격·새 비용/공개 권한을 대체하지 않음 |
| U-02 | 이전 업무 큐가 일정 수준에서 큰 개선이 3회 이상 없으면 종료. 이어 개발 조기 종료가 아닌 프레임워크 동작임을 확인 | M:FR-024/SC-007, ADR-002, G:§6. 3회 연속 유효 비교·품질 하한·min_delta·최고 보존은 위임 상세 결정 |
| U-03 | 대략적인 % 진척과 산정 가능해진 시점의 잔여시간 요청 | M:FR-034, ADR-003. 전체 전달 작업 기준이며 테스트 수·제품 plateau와 연결하지 않음 |
| U-04 | Claude는 사전 승인 경로 대신 API-only로 변경 | M:최신 요구/FR-010–011/SC-001, ADR-007, E:§1/5.1, V:§1. INT-025/AC-019 및 이를 재인용한 AC-035의 **Claude 구독 부분만** 대체 |
| U-05 | 연결 제공자에 따른 실제 모델 선택, 모든 에이전트의 실행 모델 관리 | M:FR-012, E:§6.2, V:§7. 예시 최신 모델 이름은 하드코딩된 실제 계정 모델 목록이 아님 |
| U-06 | 업무 입력에 실시간 STT | M:FR-002/US1-AC3, E:§5.3/UX-AC09. 잠정/확정·타이핑·한글 IME·취소·권한·원음 보존/전송 경계 포함 |
| U-07 | 첫 입력부터 그래프가 생성되는 여정의 직관성이 중요하고 기존 용어·조건이 난해한 UX를 만들었다는 교정 | M:US1–3/FR-001–005/009, E:§3–7/12. 별도 전문 용어 학습이나 복잡한 설정을 첫 과제로 만들지 않음 |
| U-08 | 설계 비교는 관제 그래프 기반, 에이전트별 단계·시도와 일반 텍스트로 제한되지 않는 산출물이 중심 | P:현재 브레인스토밍 상태와 수행·시도/공통 다형식/동일 초점 후속 확인, M:FR-005/013–015, E:§6–7 |
| U-09 | 제품은 설치형 데스크톱 앱이 아니라 웹 기반 오픈소스 프레임워크 | M:최신 요구/US1/FR-001/027/030/SC-001/009, ADR-009–012와 그 정체성을 구현 가능하게 보강한 위임 결정 ADR-014, 헌법 II v3.0.1, API/OP/RT 웹 경계. 이전 macOS `.app`/DMG/WKWebView/런처 결정은 역사 자료로만 보존 |

INT-016의 옛 “수정·선택” 표현은 INT-033 및 P의 최우선 의미 교정, AC-029/033과 함께 해석한다. 일반 코멘트·선택·초기 요구를 자동으로 자기 대안 산출물로 바꾸지 않는다. INT-031의 자연스러운 부분 사용을 특정 완료 버튼·침묵 승인·부분 밖 변경 금지로 번역하지 않는다.

## 4. 논문과 사용자 확장을 분리하는 지도

R의 §4–5 위치는 P/D/DG/DV의 논문 대조 기록을 사용했다. §6.1–6.7, PDF 37–44쪽은 root가 이번 전체 설계에서 직접 읽었다고 전달한 범위를 추가 연결했다. 이 추적표 작성자가 원 PDF·철학 원전 전체를 새로 재독한 것으로 표시하지 않는다. 종이 쪽/뷰어 쪽 차이가 있는 경우 절 제목을 우선하고 해당 파일 해시에서 확인한다.

| 논문 위치·제안의 범위 | 현재 제품에서 유지/확장한 의미 | 연결 |
| --- | --- | --- |
| §4.2–4.4, 약 16–19쪽: 업무 모델, 구성 필요성, 구조 비교, 실행/관찰 계약 | 업무마다 다중 에이전트를 강제하지 않되 실제 멀티에이전트 역량 유지. 사용자 GUI/3모드·관제 그래프·실제 다형식은 직접 요구로 구체화 | INT-003/014/015/024/032/034/035; FR-001–005/008–015 |
| §4.5–4.7, 약 19–22쪽: 대안 수행, 관찰 차이, 시스템/전문가 경쟁 설명 | 같은 상태의 실제 자기 산출물을 받아 원인 해설을 요구하지 않음. 부분 증거와 후속 영향 구별 | INT-016/030–033; FR-016–018/022 |
| §4.8.1–4.8.5, 약 23–28쪽: 원자 렌즈, 사례 구별·대조 질문·새 증거, H_phi/S_phi 방화벽 | 초기 설계·크리틱·대안 이후 탐구의 세 지점으로 사용자 확장. 철학 이름을 전면에 안 보이며 실제 탐구 규칙·기권·조합 감사는 유지 | INT-017/021–023/029; FR-004/006/019/020/027 |
| §4.9–4.10, 약 28–30쪽: 복원/구성/보호, 처치 외 조건 통제, 출처/전이/경계/회귀 | 이전 업무 큐 자동/사람 반복과 사람 승인 환경 버전업을 중심 경험으로 확장. 3회 정체 종료는 U-02이며 논문의 수치로 주장하지 않음 | INT-012/013/018/019; FR-021–026 |
| §5.1, §5.4–5.5, 약 31–37쪽: 지식·검증·컴파일된 실행물·권한/롤백 | 대안/해석을 운영 규칙으로 직접 복사하지 않고 정확한 지식/환경/권한 번들의 사람 승인·적용·롤백 | FR-017/020/021/025/026 |
| §6.1–6.2: 논리 구성요소, 실행 엔진 선택 가능성, 실행 봉투 | LangGraph는 가능한 실행 선택이지 채택 강제나 구현 완료가 아님. 입력/출력/모델/도구/상태·오류 봉투로 제공자와 제품 상태를 분리 | FR-010–015/030/032; E:§6–7; G:§3 |
| §6.3: 저장/실험 기반, SQLite+내용 주소 저장소(CAS) 제안 | 원본·사후 대안·진단·실험·버전 계보의 분리와 무결성 근거. 저장 기술 채택은 공학 선택이며 해시만으로 재현/원인 증명 불가 | FR-017/023/027–030; G:§3/7; V:§10 |
| §6.4 및 §8.4–8.5: 다계층 평가·오류/기권·블라인드/통제 실험 | 결정적 검사·원자료 의미·시각·전문가 판단과 시험 유효성 분리. 동일 모델 독립성의 사용자 요구를 상관 감소만으로 임의 축소 금지 | INT-027/028; FR-006/025/031; V:§4–6 |
| §6.5: 보안·권한·격리 | 파일/웹 명령은 데이터. 비밀·숨은 추론·무관한 활동 수집 금지, 대안/평가 정답 접근 제한·외부 효과 통제 | FR-014/017/020/029/030; G:§4–5; V:§5/8 |
| §6.3/6.7의 첫 릴리스 제안: 텍스트/DOCX·CLI·단일 제공자·제한 분기·선택 SPLI | 현재 범위는 **GUI·실제 다형식·Codex/Claude 두 지원 경로·병렬/분기 그래프·세 지점 렌즈**로 사용자 확장됨. 논문의 최소 예시로 현재 요구를 다시 줄일 수 없음 | INT-002/021–025/029/034/035, U-04/U-06/U-08; FR-001/004–015/019/032 |
| §6.7: 코드 Apache-2.0, 문서/렌즈/데이터 CC BY 4.0 제안과 제3자 원 라이선스 구별 | 자체 작성물의 배포 라이선스 결정과 원전·업로드·이미지·번역·평가 자료 권리는 별도. 개인 PDF/전체 철학 원문을 복제하거나 Git 공개 권한을 확대하지 않음 | INT-001/004/007; FR-028/029/031/032; V:V7 |

## 5. 수용 증거 유형

| 표식 | 필요한 실제 증거 | 한계 |
| --- | --- | --- |
| D | 원문 대조·계약 교차 검토·버전/변경 기록 | 구현/효과 증거가 아님 |
| T | 결정적 단위/계약/경계/회귀 시험과 원시 결과 | 부품의 해당 조건만 증명. 기존 729개로 다른 영역을 완료시키지 않음 |
| I | 실제 웹 인스턴스·브라우저 UI·저장·내부 실행기·권한·형식·도구·재시작 통합 시험 | 통제/합성 환경이면 그 조건의 공학 증거. 내부 실행기는 제품 UI나 네이티브 런처가 아님 |
| L | 실제 선택 제공자·모델 호출·브라우저·원형 파일·전후 상태·입출력 manifest | 실제 호출 자체로 의미 정확성/사용자 만족 증명 불가 |
| S | 독립 원자료·고정 rubric·판정기 경계·실제 의미/시각 결과·불일치 | 모델 자기점수/인용 존재만으로 대체 불가 |
| H | 실제 사용자가 선행 산출물 뒤 제공한 자기 대안, 실제 권한자의 승인, 실제 사용성 관찰 | 합성 test_actor·개발 승인·가짜 대안으로 대체 불가 |
| F | 봉인/전향·경계·회귀, 조건을 맞춘 렌즈/성장 통제 비교, 실제 분모·비용·불확실성 | 튜닝 재사용·소수 무오류·에이전트 합의로 일반 효과/독립성 증명 불가 |
| R | 새 자체 호스팅 배포물·지원 호스트/브라우저·웹 연결/업데이트·복구·로그 추출·보안·라이선스·보고서 | 제작자 장치 성공만으로 배포 지원 완료 불가 |

각 구현 task는 입력 출처/버전, 의존 task, 수정 대상, 아래 수용 ID, 필요 증거 유형, 금지 부수 효과, 완료/미실시 상태를 가져야 한다. 어떤 H/F 증거가 아직 없으면 T/I를 대신 넣지 않고 미실시·추가 실제 증거 필요로 남긴다.

## 6. FR-001–034 정방향 연결

`INT/AC`는 해당 원본의 직접 요구/거부 사례다. `R` 절만 근거인 항목을 사용자 직접 발언으로 표시하지 않는다. 같은 행의 계약은 함께 적용하며 한 문서만 골라 나머지 경계를 제거하지 않는다.

| FR | INT / AC / 최신 변경·논문 | 구체 계약·수용 ID | 필요한 증거 |
| --- | --- | --- | --- |
| FR-001 | INT-002/008/010/035; AC-001/008/009/035/036; U-07/**U-09** | ADR-009/010; E:§5.1/6.3, UX-AC01/03/10; API:§1–2; DM:§3/6; OP:§2/9; V:V4/V7 | D,T,I,L,R,H(사용성 별도) |
| FR-002 | INT-003; AC-002/006/018/033; U-06/U-07; R:§4.2 | ADR-011; E:§5.2–5.3, UX-AC01/09; API:§2 Speech; DM:§3/6; V:§3/7 | T,I,L,S,H(음성·사용성) |
| FR-003 | INT-003/014/015; AC-002/008/012; R:§4.2–4.3 | E:§5.2/6.1, UX-AC01; DG:§3.1; V:§7 | D,T,L,S |
| FR-004 | INT-017/021/029; AC-012/014/016/024; R:§4.8 + 사용자 초기 확장 | E:§6.1; LD:C1/C2/R0; LC:§1–3; DG:§3.2; V:§8 | D,T,L,S,F |
| FR-005 | INT-015/021/022/032; AC-003/012/014/028; U-08 | E:§6.1/7, UX-AC01/04; DG:§3.3–3.5; V:§7 | T,I,L,S,H |
| FR-006 | INT-022/027/028/029; AC-013/022/023/024; R:§6.4/8.4–8.5 | DG:§6; DV:§4–5; V:§4–6/V3; M:SC-005 필수 결합 | D,T,I,L,S,F |
| FR-007 | INT-022/028; AC-012/013/023; R:§4.3 | DG:§3.5/7; E:§6.1, UX-AC01; V:§7 | T,L,S |
| FR-008 | INT-013/015/019; AC-011/018/021; R:§4.3–4.4 | E:§6.3/9.2; DG:§8; G:§8/G-13; V:§9 | T,I,L,H |
| FR-009 | INT-024/035; AC-004/006/017/018; U-07 | E:§4/10, UX-AC02; V:§3/9 | T,I,H |
| FR-010 | INT-025部分/035; AC-019部分/035部分; **U-04 override** | ADR-012; E:§1/5.1/6.2, UX-AC03; API:§1–2 Connections; DM:§3/6; V:§1/7/V4/V7 | D,T,I,L,R |
| FR-011 | INT-026; AC-020/021; U-04 | ADR-012; E:§5.1/6.2/10, UX-AC03/10; API:§2 Connections/Model control; DM:§3/6; V:§5/7 | T,I,L,R |
| FR-012 | INT-015/025部分/026/035; AC-021/035; U-05/U-04 | ADR-012; E:§6.2–6.3, UX-AC03; API:§2; DM:§3/6; DG:§8.3; V:§7 | T,I,L |
| FR-013 | INT-010/015/034/035; AC-003/006/011/035/037; U-08 | E:§7/10, UX-AC04/10; G:§7; V:§7 | T,I,L |
| FR-014 | INT-012/034/035; AC-011/036/037; R:§4.4/6.1/6.5 | E:§6.2/7/10, UX-AC04/10; G:§5/G-14; V:§5/7 | T,I,L,R |
| FR-015 | INT-030/032/034; AC-025/028/036; U-08; R:§4.4 | E:§7–8, UX-AC04/07; G:§3/G-02/06; V:§7 | T,I,L,S |
| FR-016 | INT-016按033校正/030/031/033; AC-025/026/029/031/033 | E:§8, UX-AC05/07; G:§2–3/G-01/02; V:§8 | T,I,H |
| FR-017 | INT-013/016按033校正/033; AC-016/030/033/034; R:§4.4–4.9 | E:§8/11; G:§3–4/G-05; V:§5/8 | T,I,L,H,F |
| FR-018 | INT-009/011/013/017/033; AC-024/027/029/030; R:§4.6–4.7 | E:§8, UX-AC05/07; G:§2–4/G-03/04; V:§8 | D,T,L,S,H |
| FR-019 | INT-017/029/033; AC-016/024/029/030; R:§4.8 | E:§8; G:§4/G-04/05/15; LC:§1/6; V:§8 | D,T,L,S,H,F |
| FR-020 | INT-013/017/029; AC-016/024/030; R:§4.8.5/5.1 | G:§4/G-05; LC:§6; V:§5/8 | D,T,I,L,F |
| FR-021 | INT-009/011/012/013; AC-005/009/030/037; R:§4.9/5.5 | G:§2–4/8/G-03/05/06; E:§9; V:§8 | D,T,I,L,S |
| FR-022 | INT-030/031/032/033; AC-025/026/027/028/031 | E:§8–9, UX-AC07; G:§2/5/G-02/06; V:§8 | T,I,L,H,F |
| FR-023 | INT-018/019; AC-005/010/011/027/037; R:§4.9–4.10 | G:§5–7/G-06/08/09/14; E:§9; V:§8 | T,I,L,S,H,F |
| FR-024 | INT-018은 반복 근거, 구체 종료는 **U-02**; AC-010/026; R 수치 아님 | G:§6–7/G-07–10/17; E:§9.1, UX-AC06; V:§8 | D,T,I,L |
| FR-025 | INT-013/018/019/028; AC-010/011/016/023/027/030/034; R:§4.10/6.4 | G:§5/8/G-10/12/14; V:§4/8–9 | T,I,L,S,H,F |
| FR-026 | INT-013/015/019; AC-005/011/016/030; R:§5.4–5.5 | E:§9.2, UX-AC06; G:§8/G-11/13; V:§9 | T,I,L,H,F |
| FR-027 | INT-005/006/023; AC-007/010/015/021/032/037 | E:§5.1/11, UX-AC08; API:§1–2; DM:§6; G:§3/7; V:§10 | T,I,L,R |
| FR-028 | INT-005/007/020; AC-007/015/032; R:§6.5/6.7 | E:§11, UX-AC08; G:G-16; V:§3/V7 | T,I,R,H |
| FR-029 | INT-006/007/023/035; AC-020/021/032/037; R:§4.4/6.4–6.5 | ADR-012; E:§5.1/11; API:§1–2; DM:§3/6–7; G:§3–5; V:§5/10/V7 | D,T,I,R |
| FR-030 | INT-002/010/035; AC-006/011/018/021/037 | ADR-009/010; E:§5.1/10, UX-AC02/10; API:§1–2; DM:§3/6; G:§7/G-08/09; V:§5/V7 | T,I,L,R |
| FR-031 | INT-001/004/009/027/028; AC-008/013/015/016/022/033/034; R:§6.4/8.4–8.5 | V:§2–4/6/8–10; LR:R0/검토 범위; G:§9 | D,T,L,S,H,F,R |
| FR-032 | INT-001/010/012/034/035; AC-009/035/036/037; R:§6.1–6.3/6.7; U-09의 프레임워크 정체성 | ADR-009/010/014; E:§6.2/6.4/7.1, UX-AC11; API:§2 Extensions/A13; DM:§3.1; RT:§1/6/R16; OP:§2.1/8/OPS-AC11; G:§3/8; V:§7/V7/V8; X14 | D,T,I,L,R |
| FR-033 | INT-001/004; AC-008/034; **U-01**, 기존 반복 질문 절차 갱신 | ADR-001/004/006; V:§3/10/V0; E:§3 | D(영향·검토·task 연결) |
| FR-034 | INT-004의 정직한 의도 보존과 **U-03/U-02**; AC-008/034 | ADR-003; M:SC-002/010; V:§3/9; G:G-17 | D(분모·근거·미확인/잔여시간 구분) |

### 6.1 실행·운영 계약의 교차 구현 연결

현재 API/DM/RT/OP를 직접 읽고 아래에 연결했다. 위 FR 행의 E/G/V와 **함께 적용하는 구현 경계**다. 구현 task는 해당 FR 행과 아래 기술 수용 항목을 둘 다 참조한다. RT의 첫 예산·후보 수, OP의 보존/용량/플랫폼 값은 위임 기본안이며 논문 수치나 실제 품질/지원 검증 결과가 아니다.

| FR 묶음 | 실행 계약 | 운영 계약 | 추가 실제 증거 |
| --- | --- | --- | --- |
| FR-001/002/030 | API:§1–2; DM:§3/6; RT:§4/R07–08 | OP:§2/5–6/9, OPS-AC01/05/07/10 | 두 프로필의 빈 호스트 웹 배포·최초 설정, 브라우저 음성, 실패/복원, 공급망 검증은 별도 외부 권한 |
| FR-003/004/005/006/007/008 | RT:§1–3/10, R01/03/13/15 | OP:§4.2/8, OPS-AC04/09 | 실제 그래프 compiler/허용 projection/크리틱 정보 경계, 필수 실패·후보 부족 |
| FR-009 | RT:§1/4–5, R07/14 | OP:§4/6, OPS-AC04/05 | 같은 객체·권한·시도·버전의 세 보기와 재접속 |
| FR-010/011/012 | API:§1–2; DM:§3/6; RT:§1/7, R04/05/10 | OP:§3, OPS-AC02 | 실제 Codex 구독·Claude API·선택 API, credential vault/모델/과금 경로/소비 예산 |
| FR-013/014/015 | RT:§2/4–6, R01/02/04/06–09/12 | OP:§4/6/8, OPS-AC03/05/09 | 실제 병렬/분기/원자 합류·브라우저·파일·원형 전달·중복 효과 방지. 실제 PDF/이미지/표 내용을 모델이 받은 projection과 원문 접근/사용은 구별 |
| FR-016/017/018/019/020/021/022 | RT:§1/5/8, R06/11 | OP:§4/8, OPS-AC03/04/09 | 원형/부분 대안과 hypothesis/inquiry·변경 컴파일 allowlist, H_phi/대안/봉인자료 방화벽. 보통 업무 정책의 검증된 변경을 금지하는 것이 아니라 안전·권한·최종 사람 승인 우회를 금지 |
| FR-023/024/025/026 | RT:§4/7–9, R07/08/10–13 | OP:§5–6, OPS-AC05/07 | 큐 재실행·제품 plateau·정확한 사람승격·예산/상태 복원·외부 효과 재생 경계 |
| FR-027 | API:§1–2; DM:§6; RT:§1/4–5/7/9, R07/10/14 | OP:§2/4.1–4.2/5.1/7, OPS-AC01/04/06/08 | 최초 프레임워크 제어 가능 사건부터 모든 필수 범주와 private evidence, 관측 전 배포 사건을 꾸미지 않음 |
| FR-028 | RT:§5/9, R12/14 | OP:§7, OPS-AC08 | 실제 preview/snapshot/redaction/export hash, 결손/제외 이유, 외부 전송 없음 |
| FR-029 | API:§1–2; DM:§3/6–7; RT:§1/6/8, R09/11/14 | OP:§3–5/7–8, OPS-AC02/04/06–09 | 비밀 canary, 키/원음·숨은 추론 제외, 최소권한·인젝션/경로/렌더러 공격·삭제/백업 |
| FR-031/032 | API:§2 Extensions/A13; DM:§3.1; RT:§1/6/10, R01–16 | OP:§2.1/8–9, OPS-AC09–11; E:§6.4/UX-AC11; V:V8 | 닫힌 의미 포트와 잘못된 tuple 거절, durable 설치/qualification/binding, 외부 operator-staged OCI, Settings 관찰, 별도 설치 SDK/client, 재귀 core 의존 경계, 공급망·라이선스·실제 수행/효과/외부승인 분리 |
| FR-033/034 | RT/OP의 위임 기본값은 ADR와 연결 | OP:§1/9는 설계·지원·외부 권한 상태 구별 | 기술 기본값 변경 시 모든 의존 FR/수용 시험 영향 기록; 제품 반복 수를 개발 진척에 전용 금지 |

## 7. 원 의도 INT-001–035 역방향 누락 검사

아래 각 행은 최소 하나의 FR 구현/검증 task로 이어져야 한다. `부분 override`는 해당 요구 전체 삭제가 아니다.

| 원 의도 | 연결 FR | 보존할 해석 |
| --- | --- | --- |
| INT-001 | FR-031/032/033 | 논문·도구는 출처, 오픈소스는 라이선스/배포 준비와 권한 구별 |
| INT-002 | FR-001/030 | 사용자 CLI 불필요 |
| INT-003 | FR-002/003 | 설명/자료에서 실제 설계 |
| INT-004 | FR-031/033/034 | 해석 변질·허위 완료 방지 |
| INT-005 | FR-027/028 | 제작자 성장 루프 |
| INT-006 | FR-027/029 | 웹 배포·최초 설정 직후부터 정상/실패 전 과정 기록 |
| INT-007 | FR-028/029 | 사용자 선택 추출·보호 |
| INT-008 | FR-001 | 비개발자 관제 환경 구성 |
| INT-009 | FR-018/021/031 | 실제 DeepTwin 평가·성장 |
| INT-010 | FR-001/013/030/032 | 프레임워크가 구성·실행 책임 |
| INT-011 | FR-018/021 | DeepTwin은 정제·흡수 엔진 |
| INT-012 | FR-014/021/032 | 역할/그래프/기억/도구 등 폭넓은 변경 후보 |
| INT-013 | FR-008/017/020/021/025/026 | 근거·권한·검증 후 적용 |
| INT-014 | FR-003 | 업무별 다중 에이전트 필요성 판단 |
| INT-015 | FR-003/005/008/012/013/026 | 실제 운영 설계의 검토 깊이 |
| INT-016 | FR-016/017 | INT-033으로 의미 교정, 설명은 보조 |
| INT-017 | FR-004/018/019/020 | 렌즈 탐구를 단순 수정 수집으로 축소 금지 |
| INT-018 | FR-023/024/025 | 이전 큐 반복, U-02로 종료 상세 추가 |
| INT-019 | FR-008/023/025/026 | 사람 최종 승인과 환경 버전업 |
| INT-020 | FR-028 | 선택 분기, 필수 직렬 마지막 단계 아님 |
| INT-021 | FR-004/005 | 초기 단독/혼합 렌즈와 기본 업무 언어 |
| INT-022 | FR-005/006/007 | 개별 독립 검토·품질/구조 다양성 |
| INT-023 | FR-027/029 | 비선택·탈락 조합까지 전체 이력 |
| INT-024 | FR-009 | 작업공간/대화/그래프 세 실제 모드 |
| INT-025 | FR-010/012 | U-04: Claude API-only만 변경, Codex 구독/최종 사용자 핵심 여정 유지 |
| INT-026 | FR-011/012 | 선택 API, 자동 과금 전환 금지 |
| INT-027 | FR-006/031 | 같은 모델 오류 독립성 목표·실증 범위 유지 |
| INT-028 | FR-006/007/025/031 | 필수 실패·근거 부족은 평균으로 상쇄 불가 |
| INT-029 | FR-004/006/019/020 | 초기/크리틱/SPLI 세 렌즈 지점 |
| INT-030 | FR-015/016/022 | 문구·개별 전달까지 해상도 |
| INT-031 | FR-016/022 | 부분 증거, 후속 영향·시험은 별도 |
| INT-032 | FR-005/015/022 | 완결 산출물과 단계적 전달의 전체 맥락 |
| INT-033 | FR-016/017/018/019/022 | 내 버전은 비교군, 원인 설명 강제 금지 |
| INT-034 | FR-013/014/015/032 | 실제 브라우저/PDF·프레임워크 도구 |
| INT-035 | FR-001/009/010/012/013/014/029/030/032 | 독립 제품 상태·도구·기록 소유, U-04 제공자 방식만 수정 |

## 8. 거부 사례 AC-001–037 역방향 연결

| 거부 사례 | 대응 FR | 구체 계약 수용 연결 |
| --- | --- | --- |
| AC-001 | FR-001 | UX-AC01/03 |
| AC-002 | FR-002/003 | UX-AC01; V:§3/7 |
| AC-003 | FR-005/013 | UX-AC04; V:§7 |
| AC-004 | FR-009 | UX-AC02 |
| AC-005 | FR-021/023/026 | UX-AC06; G-06/11 |
| AC-006 | FR-002/009/013/030 | UX-AC02/09/10; G-08/09 |
| AC-007 | FR-027/028 | UX-AC08; G-16 |
| AC-008 | FR-001/003/031/033/034 | UX-AC01; V:V0–V8 |
| AC-009 | FR-001/021/032 | UX-AC01/06; V:V4/V5 |
| AC-010 | FR-023/024/025/027 | UX-AC06; G-06–10/12 |
| AC-011 | FR-008/013/014/023/025/026/030 | UX-AC06/10; G-11/13/14 |
| AC-012 | FR-003/004/005/007 | UX-AC01; DG:§3.2–3.5; V:§7 |
| AC-013 | FR-006/007/031 | V:§5–6; DG:§6 |
| AC-014 | FR-004/005 | E:§6.1; UX-AC01 |
| AC-015 | FR-027/028/031 | UX-AC08; V:§8/10 |
| AC-016 | FR-004/017/019/020/025/026/031 | G-05/11; V:§8 |
| AC-017 | FR-009 | UX-AC02 |
| AC-018 | FR-002/008/009/030 | UX-AC02/09 |
| AC-019 | FR-010 | UX-AC03; V:§1/7/V7; U-04 부분 override |
| AC-020 | FR-011/029 | UX-AC03/10; V:§5/7 |
| AC-021 | FR-008/011/012/027/029/030 | UX-AC03/08/10; G-09/13 |
| AC-022 | FR-006/031 | V:§6/V3; M:SC-005 |
| AC-023 | FR-006/007/025 | UX-AC07/10; V:§4–6 |
| AC-024 | FR-004/006/018/019/020 | UX-AC05; G-04/05/15; V:§8 |
| AC-025 | FR-015/016/022 | UX-AC04/05/07; G-02/06 |
| AC-026 | FR-016/022/024 | UX-AC05/06; G:§2/6–7 |
| AC-027 | FR-018/022/023/025 | UX-AC07; G-06/12; V:§8 |
| AC-028 | FR-005/015/022 | UX-AC04/07; V:§7 |
| AC-029 | FR-016/018/019 | UX-AC05; G-01/02/04 |
| AC-030 | FR-017/018/019/020/021/025/026 | G-03/05/11/12; V:§8 |
| AC-031 | FR-016/022 | UX-AC05/07; G-02/06 |
| AC-032 | FR-027/028/029 | UX-AC08; G-16; V:V7 |
| AC-033 | FR-002/016/017/031 | UX-AC05/09; G-01; V:§8 |
| AC-034 | FR-017/025/031/033/034 | V:§2/8–10; G:§9 |
| AC-035 | FR-001/010/012/013/032 | UX-AC03; V:§7/V7; U-04는 구독 인용만 변경 |
| AC-036 | FR-001/014/015/032 | UX-AC04; E:§6.2/7.1; V:§7 |
| AC-037 | FR-013/014/021/023/027/029/030/032 | UX-AC04/08/10; G-14; V:§5/7/8 |

AC-036/037의 후속 문단도 적용한다. 모든 계정 연결을 설계의 선행 조건으로 만들지 않고, 준비됨/미연결/권한 부족/미지원/검증 전을 구별한다. 안전한 복구는 프레임워크가 맡되 결과 미확인 외부 쓰기를 반복하지 않으며 복구를 학습·환경 버전업으로 표시하지 않는다.

## 9. US·SC의 전체 여정 연결

| 사용자 여정 | 해당 FR 묶음 | 직접 UI/성장 수용 연결 | 필수 증거 범위 |
| --- | --- | --- | --- |
| US1 웹 접속·설명 | FR-001/002/003/010/011/012/030 | UX-AC01/03/09/10 | 실제 웹 UI·원본/읽기·한국어 음성·제공자·빈 호스트 배포, 효과와 구별 |
| US2 실제 그래프 비교 | FR-004/005/006/007/008/009/012 | UX-AC01/02; DG:§3/6–8 | 실제 생성/검토/구조 차이·버전, 독립성은 별도 실증 |
| US3 관제·산출물 | FR-008/009/012/013/014/015/030/032 | UX-AC02/04/10 | 실제 도구·원형 파일·전달·복구 |
| US4 자기 산출물 | FR-015/016/017/022 | UX-AC05/07; G-01/02/05 | 실제 선행 원본/사용자 대안과 합성 계약 시험 구별 |
| US5 차이·변경 | FR-018/019/020/021/022 | UX-AC05/07; G-03/04/05/15 | 경쟁 원인·새 증거·방화벽·개입, 철학 권위는 효과 아님 |
| US6 반복·버전업 | FR-023/024/025/026 | UX-AC06; G-06–14/17 | 실제 기준/후보 큐, product plateau, 별도 검증과 실제 사람 승인 |
| US7 기록 추출 | FR-027/028/029 | UX-AC08; G-16 | 최초 제어 사건부터 기록·실제 추출·가림/결손·비전송 경계 |

| 성공 기준 | 연결 FR/계약 | 완료 판정에서 놓치지 않을 것 |
| --- | --- | --- |
| SC-001 | FR-001/010–015/016–030/032; UX-AC01–11; XP; V:V4–V8 | 두 profile 각각에서 Claude API와 Codex 구독 경로 및 같은 out-of-tree OCI tool을 실제 broker에 연결; 별도 설치 HTTP client는 portable HTTPS의 T025-composed bearer route와 parity를 보이고 HTTP-only loopback은 real bearer 없이 pre-parser route 비노출을 보임; 계정 동시 연결은 불필요 |
| SC-002 | FR-001–034; 본 추적표 §6–8; V:§3/10; XP; X14 | 최초 T086과 rejected ADR-014 revisions 1–6은 역사 자료다. revision-7 연결 보정은 독립 검토에서 P1=0/P2=0으로 승인됐고 T086은 closed; 실제 구현·시험·결과 또는 미확인 상태는 별도 증거로 유지 |
| SC-003 | FR-004–007; DG:§3.5/7; V:§7 | 실제 구조 두 축·세 적합안, 부족하면 허위 보충 금지 |
| SC-004 | FR-013–015/032; UX-AC04; V:§7 | 브라우저/PDF/표/문서/이미지 실제 bytes·소비·계보 |
| SC-005 | FR-006/031; V:§5–6/V3 | 정보 격리와 의미/공동 오류를 별도 검사, INT-027 요구 축소 금지 |
| SC-006 | FR-016–022; G-01–05; V:§8 | 온보딩 설명≠대안, 실제/합성 출처·새 증거·부분 밖 영향 |
| SC-007 | FR-024/030; G:§6/G-07–10/17; UX-AC06 | product plateau/누적 작은 개선/무효/계보/복원, 개발 중단 아님 |
| SC-008 | FR-023/025/026; G-11–14; V:§8–9 | 별도 봉인·사람 승인·적용 해시·롤백, 외부 효과 중복 금지 |
| SC-009 | FR-027–029; UX-AC08; G-16; V:V7 | 선택·가림·비밀 제외·결손·자동 전송 없음 |
| SC-010 | FR-031/033/034; V:§2/9–10 | 구현·실제 호출·실사용·효과·외부 승인 미완료를 분리 보고 |

US/SC는 구현 단계별로 잘라 시험할 수 있지만 분할이 제품 범위 축소는 아니다. 초기 입력 → 실제 그래프 → 실제 수행 → 자기 대안 → 탐구 → 큐 재평가 → 별도 검증·사람 버전업의 연결이 남아야 한다. US7 내보내기는 언제든 가능한 선택 분기다.

## 10. T086 역사 결과, ADR-014 재개방과 변경 통제

최초 T086은 헌법 v3.0.0/3.0.1, ADR-009–012, 당시 canonical artifacts와 90개 고유 작업을
교차 검토했고 세 독립 검토가 배포/authority, provider/extension, speech/vault/auth 경계를
CLEAR 또는 DESIGN CLEAR로 기록했다. 그 당시 “미해결 중대 모순 0건”은 위 §2의 역사적
snapshot에만 적용된다. 후속 adversarial extension-framework audit가 아래 X01–X06을 발견해
ADR-014와 T086을 다시 열었으므로 현재 설계 폐쇄 판정으로 재사용하지 않는다.

1. **X01 의미 SPI:** 공통 worker envelope는 transport뿐이며, 닫힌 kind/artifact/port/trust/staging 행렬과 코어 소유 종류별 operation/schema/effect/idempotency/cancel/outcome/artifact 의미가 필요했다.
2. **X02 내구 수명주기:** verified installation을 context-keyed qualification과 target-scope-keyed binding에서 분리하고, 불변 history/head/event의 원자 보존·재시작 reconcile·안전한 supersession/rollback을 명시해야 했다.
3. **X03 실행형 확장:** 제품 내부 import/download가 아니라 외부 운영자가 digest-pinned OCI service/descriptor를 signed receipt로 staging하며, 새 서비스를 병행 검증한 뒤 binding을 바꾸고 제거는 별도 요청이어야 했다.
4. **X04 공식 UI:** `Settings > Extensions`가 출처·license·port·설치·qualification·binding·실패·영향 범위를 보여주고 제품 권한 내 bind/disable/rollback을 제공해야 했다.
5. **X05 배포 가능한 통합 표면:** source-tree helper 하나가 아니라 별도 설치 extension-author SDK와 HTTP/OpenAPI client, 실제 별도 process→실제 server parity가 필요했다.
6. **X06 코어 독립성:** nested core 전체에서 API/static/server와 direct FastAPI/Starlette/Jinja import를 재귀 차단해야 했다.

첫 ADR-014 독립 검토는 위 revision-1 보정을 승인하지 않고 다섯 후속 차단점을 남겼다.

1. **IR-01 binding 충돌:** port/scope/purpose만으로는 같은 포트의 독립 확장이 서로를 덮으므로 stable binding slot+core capability selector와 후보 extension identity 규칙이 필요했다.
2. **IR-02 배포 arm/인과성:** stage/replace/remove 당시의 required/forbidden/current/new/result-presence, extension common `preconditions={}`와 단일 arm precondition 정본, request↔service/digest equality, 미래 ref 없는 순서를 닫아야 했다.
3. **IR-03 저작 가능한 port schema:** 요약 표가 아니라 11개 포트의 config/request/result/error schema ID·모든 required field·닫힌 operation/terminal/error/refinement 규칙이 필요했다.
4. **IR-04 extension core 경계:** 재귀 scan root에 `app/extensions/**`가 명시적으로 포함되어야 했다.
5. **IR-05 실제 service client:** mounted route, durable credential lifecycle, bearer auth, rate limit, server registration과 black-box test의 T025/T087 path ownership이 필요했다.

Revision-2 독립 검토는 그 보정도 승인하지 않고 네 후속 차단점을 남겼다.

1. **IR2-01 P1 retirement reachability:** replace 뒤 current head가 새 service라 old service를
   current-only remove로 지정할 수 없었다. Current uninstall과 strict-ancestor retirement,
   target-keyed retirement head 및 preserved-current/dependency 검증을 분리해야 했다. Revision-3
   재검사에서는 immutable binding history와 retained rollback authority도 분리되지 않아 release
   없이 zero-dependency 상태에 도달할 수 없는 추가 P1을 발견했다.
2. **IR2-02 P2 artifact cardinality:** 52 operation의 terminal별 artifact 수가 닫히지 않아
   cancelled codec도 artifact를 반환할 수 있었다.
3. **IR2-03 P2 route ownership:** T025/T087이 `app/server.py` mount를 겹쳐 소유하므로 core-owned
   frozen composition seam과 fixed extension contribution의 비중첩 경계가 필요했다.
4. **IR2-04 P2 client transport:** 실제 bearer parity는 portable HTTPS에서만 수행하고 local HTTP
   loopback은 real bearer 없이 pre-parser route non-exposure를 증명해야 했다.

ADR-014, FR-032, DM §3.1–3.2, API A13, RT R16, XP, OP OPS-AC11, E UX-AC11, V V8,
T025/T087과 X14 ledger가 원래 여섯 보정 및 두 차례 rejected review를 연결한다. Revision 2에서 deployment
request/receipt를 kind-specific
closed union으로 만들고 extension common `preconditions`를 빈 객체로 고정해 arm만 유일한
precondition 정본으로 두며, manifest→service-descriptor digest를 단방향으로 두고 built-in Codex
runner port를 provider API port와 분리했다. 전용 socket/named-volume은 descriptor/request에
고정해 외부 운영자가 service 생성 때만 만들고, 제품 주도·host-path·post-start·비명시 mount는
금지한다. Binding은 stable slot/selector key로 공존/경쟁을 구분하고 XP가 저작 가능한 코어 port
schema를 고정했다. Revision 3은 four-arm deployment로 current uninstall과 strict-ancestor
   retirement를 분리하고, target-keyed retirement record/head와 preserved-current/zero-dependency
   transaction을 추가한다. Supersession/disable이 target-binding-keyed retained head를 만들고,
   owner exact-head release가 binding/installation history와 current head를 보존하면서 rollback
   적격성만 없애는 닫힌 경로를 추가해 A→B→release→retire-A를 도달 가능하게 한다. Current-uninstall tombstone을 exact stage precondition으로 다시 받아
   active-environment ref가 없는 conformance slot에서 disable→retention release→dependency-zero를
   먼저 증명한 뒤, 다음 monotonic revision의 설치·dispatch까지 이어지는 positive test도 고정한다. XP는 52-operation×terminal result artifact cardinality와 별도 request artifact-input profile을 닫고, T025의 frozen
router composition port와 T087 fixed extension contribution이 actual HTTPS parity를 비중첩 소유한다.
HTTP loopback은 non-secret pre-parser denial만 시험한다. T087 private conformance fixture와 T081 core/built-in images, 미래의 임의 제3자
descriptor 공급망은 서로 다른 lock 범위다. ADR-014는 T089 core build input을 바꾸지 않는다.
Revision 4는 exact five-field `BindingSlotKeyV1`와 canonical digest를 config/binding/command/event/
retention 전체에 동일 적용하고, 당시 52 request operation을 9 non-empty-capable/43 exact-empty로
전수 분류한다. Model/runner는 frozen list, tool은 core ToolDefinition, codec/storage는 공통
`artifact_inputs` 하나만 입력 정본으로 쓰며 fetch/browser/multimodal/document 프로필과
extra/missing/conflicting ref 거절을 R16/V8/T087에 연결한다.
Revision 5는 export prepare/transmit를 exact snapshot/prepared 1–256 `export_payload` bytes
프로필로 추가해 최종 분할을 11/41로 고치고, ref-only/shared-store/changed-content 전송을
거절한다. Result role/media/omissions/ref와 codec/tool equalities를 닫고 `result.effect` 하나만
terminal/effect/outcome 정본으로 둔다. T018-foundation은 Linux IPC/stream/sandbox 선행,
T018-final은 downstream semantic integration 뒤 수렴 게이트이며 T083은 두 clean-host 반복을
계속 소유한다.
Revision 6는 tool invoke success output을 exact `{tool_call_ref,result_ref}`로 닫아 output-level
effect receipt/alias를 거절하고 common `result.effect.effect_receipt_ref`만 정본으로 유지한다.
`result_ref`의 ToolResult artifact binding 의미와 r5의 모든 행렬·lifecycle·DAG는 바꾸지 않는다.
Revision 7은 §3.2 tool/codec 행 사이 prose만 표 아래로 옮기고, 11개 port row/zero isolated-row
구조 검사를 추가했다. operation/schema/profile/effect/lifecycle/DAG/count 의미는 그대로다.

제품 정체성, Claude API-only override, 자기 대안의 의미, critic 판단 오류 독립성, 논문 최소안
대비 현재 GUI/두 제공자/다형식/병렬 관제/세 지점 렌즈 범위는 그대로 유지한다. 목표는
오픈소스지만 현재 저장소에는 라이선스가 없어 법적 오픈소스 릴리스가 아니며, T084에서
copyright owner의 명시 승인 전 LICENSE 추가·공개를 완료로 표시하지 않는다.

각 FR에는 최소 한 구현 task와 한 수용/검증 task 또는 동일 task 안의 명시된 검증 항목이
배정됐다. UI만 있는 기능, 데이터만 저장하는 성장, 테스트만 있는 provider 지원, 모델
출력만 있는 파일 생성은 미완료다. 원본 출처 변경 → 영향 FR/AC → 계약 → 구현 task →
회귀/효과 범위를 같은 변경 기록으로 잇고, 정체성·authority·필수 범위 변경은 T086
설계 게이트를 영향 범위만큼 다시 연다.

단위/통합 검사의 합성 자료는 실제 사용자 학습 사건으로 저장하지 않는다. 시험 actor의 승인 조작은 실제 운영 승격이 아니다. 개인 논문·사용자 업로드·철학 원전·평가 정답을 공개 저장소에 복제하지 않으며 Q01 등 구체 시험의 정확한 진실은 해당 Task.md의 단일 정본으로 유지한다.

이 추적표는 FR 34개, INT 35개, AC 37개, US 7개, SC 10개와 90개 task에 연결 행을
제공하며 현재 T086은 **CLOSED FOR DESIGN**이다. revision-7 보정 bytes는
`adr014-review-input-manifest-r7.md`에 고정되고 별도 판정은
`adr014-independent-review-r7.md`에 기록됐다. T075가 최종 릴리스
후보의 변경된 bytes/supersession/요구→시험결과를 다시 고정한다.
이는 구현 진척 100%·사용자 의도 일치 보증·실제 시험 통과·철학 렌즈 효과를 뜻하지 않는다.
