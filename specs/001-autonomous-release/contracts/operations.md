# Operations contract — 웹 배포·보관·복구·안전한 기록 추출

작성일: 2026-09-08 · 계약 ID: OPS-002 · 상태: 최초 ADR-009–012/T086 검토는 역사 자료이며 ADR-014 확장 경계 감사가 T086을 다시 열었다. 실제 배포·보안 인증·출시 준비 완료를 뜻하지 않음.

## 1. 범위와 결정의 권위

[헌법 3.0.1](../../../.specify/memory/constitution.md), [기능 명세](../spec.md), [경험 계약](experience.md), [성장 계약](growth.md)을 따른다. 목표 릴리스는 자체 호스팅 가능한 오픈소스 웹 프레임워크이며 브라우저 UI가 제품 표면이다. 현재 저장소에는 라이선스가 없어 아직 법적으로 오픈소스 릴리스가 아니다. 배포 부트스트랩·최초 웹 설정·일상 사용을 구분하고 네이티브 앱/DMG/내장 WebView/제품 런처를 필수 경계로 두지 않는다. **Claude는 공식 API-only, Codex는 공식 구독과 명시 선택 API**다. 제품에 유료 경로를 제공하는 결정은 개발 유료 시험·계정/권한 확대·공개·구매의 승인이 아니다.

아래 `OPS-D` 값은 가역적인 운영 기본값에 대한 에이전트 추천 결정이며 사용자가 개별 수치/기술을 검토했다고 기록하지 않는다. 전체 여정이나 필수 검증을 축소하는 근거로 사용하지 않는다. 구현 전 계약 교차 검토, 구현 후 실제 근거가 필요하다.

| 결정 | 첫 배포 후보 기본값 | 범위·이유 |
| --- | --- | --- |
| OPS-D01 플랫폼 | 같은 immutable source commit/exact Compose digest/서비스별 `image_locks[]`를 쓰는 `local-no-terminal-v1`(macOS arm64 Docker Desktop+Portainer CE UI)과 `portable-compose-v1`(Linux x86_64 Docker Engine/Compose+pinned HTTPS edge와 operator TLS secrets) | release tag는 immutable identity 확인 뒤 표시용일 뿐. 각 image lock은 자신의 OCI index 또는 Docker manifest list와 플랫폼별 manifest/config/layers의 media type·digest·byte size를 고정. 둘 다 깨끗한 호스트에서 시험하고 실제 통과한 Docker/Portainer/브라우저 버전만 `PlatformSupportManifest`에 고정 |
| OPS-D02 배포 | 재현 가능한 오픈소스 control-plane/worker 배포물, 외부 운영자 화면과 분리된 최초 소유자 웹 설정 | 비개발자 경로는 터미널을 성공 조건으로 쓰지 않음. Portainer는 DeepTwin 화면/런처가 아니라 Docker 관리자 권한을 가진 외부 배포 authority이며 일반 업무는 DeepTwin 브라우저 UI에서만 수행 |
| OPS-D03 도구 | 격리 브라우저의 공개 웹 읽기/탐색·스냅샷, 인스턴스 소유 파일 읽기/생성, 문서/PDF·표·이미지 렌더링 | 실제 산출물과 다음 역할의 원형 파일 활용을 검증. 임의 셸·무제한 코드 실행·외부 발송/구매는 기본 허용 도구가 아님 |
| OPS-D04 핵심 보존 | 원본·대안·실행/변경/렌즈/평가/승인의 내용과 필수 계보는 **기한 없음·자동 삭제 없음** | 전체 로그 요구와 반복 평가/재현 맥락 유지. 권한 있는 사용자가 웹 UI에서 보관·삭제를 결정 |
| OPS-D05 파생 보관 | 다시 만들 수 있는 미리보기 캐시: 14일 또는 1 GiB 중 먼저 도달 시 LRU 정리. 민감 본문 없는 상세 진단: 30일 또는 100 MiB 중 먼저 도달 시 순환 | 이것들은 유일한 원본·도구 관찰 증거·핵심 사건을 포함하면 안 됨. 정리된 항목 종류·기간·수량을 핵심 사건으로 남김 |
| OPS-D06 저장소 경고 | vault 5 GiB부터 용량 안내. 남은 디스크 2 GiB 미만 경고, 512 MiB 미만이면 새 모델/도구 dispatch와 큰 쓰기 차단 | 자료를 몰래 삭제하지 않음. 산출물 예상 크기·실제 저장 오류를 추가 검사하며 남은 공간 수치만으로 안전을 보장하지 않음 |
| OPS-D07 백업/업데이트 | 데이터 마이그레이션 전 암호화 백업·복원 검사 필수, 자동 업데이트는 기본 꺼짐 | 서버 릴리스와 업무 환경 버전 분리. 백업 자동 삭제 없음; 권한 있는 사용자가 웹 관리 화면에서 선택 정리 |
| OPS-D08 추출/전송 | 기본은 메타데이터 중심 미리보기 후 선택한 로컬 파일 생성. 제작자 자동 전송 없음 | 원문 포함·가림·빠진 근거를 사용자에게 보여 주고 진단 가능성을 과장하지 않음 |

OPS-D03의 유한한 첫 도구 범위는 **설계→실행→자기 대안→탐구→이전 큐 재평가→사람 승격** 전체 연결을 포함한다. 추가 도구/형식/플랫폼은 등록된 버전·권한·입출력·격리·시험 계약으로 확장한다. ‘지원하지 않음’과 ‘구현했으나 미검증’은 다른 상태다.

## 2. 배포·의존성·최초 기록

서버가 최초 설정 상태를 제어할 수 있게 된 뒤 업무 자료·키·마이크·모델에 접근하기 전에
인스턴스 전용 `setup_session_id`와 배포 확인 기록을 만든다. 이미지 다운로드·호스트 준비처럼
프레임워크 밖에서 발생해 관측하지 못한 사건을 과거 로그로 꾸미지 않는다. **프레임워크가 실제로
제어한 최초 배포/설정 사건부터** 기록하고 그 전의 관측 한계를 표시한다.

| 상태 | GUI에 보여 줄 사실·행동 | 상태 변경 전 조건 |
| --- | --- | --- |
| `checking` | 서버/worker/UI 릴리스, 지원 플랫폼·여유 공간·무결성·마이그레이션 점검 | 최초 제어 사건 기록 가능. 알려지지 않은 플랫폼을 자동 적합 판정하지 않음 |
| `needs_destination` | 배포 authority가 지정한 named volume·artifact·backup 위치와 필요 용량 | 제품 UI가 호스트 경로를 재귀 변경하지 않음; 변경은 exact DeploymentRequest로 외부 운영면에 넘김 |
| `needs_component` | 빠진 구성요소 이름·목적·출처·고정 버전·크기·라이선스와 exact 배포 요청 | 제품이 image/model을 직접 설치하지 않음; 운영면이 검증한 receipt 전에는 준비됨으로 표시하지 않음 |
| `operator_preparing` / `receipt_pending` | 외부 운영면에 넘긴 request ID·고정 digest와 마지막 관측 상태 | 다운로드/컨테이너 변경을 제품이 수행했다고 꾸미지 않음; raw 운영 로그나 비밀을 받지 않음 |
| `checking_runtime` | 현재 실행 중인 인스턴스 저장소·서버·worker·UI의 실제 handshake/manifest 검사 | 준비 검사는 추론·사용자 자료 전송·마이크 캡처가 아님 |
| `ready_web` | 웹 입력·저장 가능, 연결 전 모델 기능은 준비 필요 | 세션·UI·저장소·worker 상태 확인. 모델 로그인 완료와 구별 |
| `needs_connection` | Codex 구독 / Claude API / 선택 Codex API 연결·복귀 | 현재 업무 초안 보존, 필요한 경로만 연결 |
| `failed` / `cancelled` | 실패 단계·보존 범위·웹 UI 재시도/진단 추출 | 프레임워크가 소유한 부분 배포만 정리 가능. 기존 사용자 자료·계정을 손대지 않음 |

배포물은 호스트 전역 Python/Node·셸 설정·사용자의 Codex/Claude 설정을 덮지 않는다. 사용자 홈 전체를 복사·마운트하지 않는다. 마이크 권한은 해당 브라우저 기능의 명시 행위에서 요청하며 보안 설정을 끄거나 무신뢰 HTTP로 우회하는 절차를 제공하지 않는다. 라이선스가 재배포를 허용하지 않는 구성요소는 공식 지원 방식의 사용자 동의 다운로드를 설계하고, 이를 확인하지 못하면 그 경로는 준비되지 않은 상태다.

### 2.0 Task7 세션 root·서빙 소유권 (T025 부분 구현)

배포 전용 `initialize_session_root`는 명시적인 별도0700 소유 디렉터리의 부재/빈 상태에만
`root.key`(정확히32 random bytes,0400)와 canonical `manifest.json`(0400)을 O_EXCL로 생성하고
파일/디렉터리를 fsync한다. 기존 정상 상태는 읽고 검증하는 no-op이며, 부분 상태·symlink·hardlink·
잘못된 소유권/모드·epoch는 교체하거나 복구하지 않는다. 서빙 `open_session_root`는 읽기/검증 및
CSRF 유도만 제공하며 init/raw-key getter/general MAC 기능이 없다. manifest integrity는
root-key HMAC-SHA256이며 정확한 preimage는 data-model의 SessionRootReceipt 설명을 따른다.
초기 epoch1만 지원하고 DB는 완전한 canonical manifest의 SHA256을 pin한다.

지원 administrative main은 `--data-dir`, `--deployment-config`, `--session-root-dir`,
`--expected-uid`, `--expected-gid`를 모두 요구한다. 이는 운영 입력이며 일반 사용자 안내가 아니다.
내부 listener는 canonical `0.0.0.0:8080`; Uvicorn workers1/reloadFalse/proxy_headersFalse/
forwarded_allow_ips empty/access_logFalse를 고정한다. capability 생성/출력이나 사용자 Codex/STT
초기화가 없다. 구성/root 부재는 startup failure다. Compose/edge topology를 변경하거나
`Forwarded`/`X-Forwarded-*`를 신뢰하여 HTTPS로 간주하지 않으며 portable edge gate는 열린 상태다.

업무 DB 디렉터리의 소유자 전용0600 비밀 없는 `owner-auth.lock`에 OS exclusive lock을 유지한다.
두 번째 serving instance는 startup에서 실패한다. shutdown/cancellation 때 실행 중인 native
Argon2 작업이 실제 끝나기 전에는 lock/native slot을 해제하지 않는다. 프로세스 종료 시 OS가
lock을 해제한다. 이는 단일 control-plane process 제약이며 다중 프로세스 semaphore 주장이나
재시작을 넘는 일반 rate-limit 보장은 아니다. 최초 claim window/시도수만 DB에 지속한다.

root/config/DB 불일치 및 `setup_incomplete`는 자동 복구되지 않는다. 별도 signed recovery,
최종 웹 UI, 실제 TLS edge/Linux UID/container network, provider/runtime story 검증은 남아 있다.

Task7의 secret-canary 검증은 실제 auth/work/event/snapshot 및 일반 domain-record projection,
captured logs/stdout/repr와 현행 export category의 private-auth 제외를 대상으로 한다. 세션 cookie와
CSRF의 명시적인 발급/조회 응답은 허용된 비밀 전달 경로다. 현행 export 모듈은 제공된 item의
manifest builder일 뿐 DB collector/archive 경로가 아니므로, 전체 collector/archive 유출 검증은
T071의 필수 미완료 조건으로 유지한다. 구성한 manifest를 end-to-end export 증거로 취급하지 않는다.

### 2.1 의존성/플랫폼 manifest

| 레코드 | 필수 필드 | 조건 |
| --- | --- | --- |
| `BuildInputLockManifest` | `schema_version`, `generated_at`, `resolver_versions`, `runtime_abis[]`, `glibc_floor`, `target_platforms[]`, `artifacts[]`, `upstream_image_locks[]`, `model_component_locks[]`, `license_provenance_refs[]`, `build_input_lock_set_digest` | T089가 최종 서비스 빌드 전에 확정하는 입력 계약. 각 artifact는 출처·버전·크기·digest·플랫폼·재배포 상태를 고정한다. 각 upstream image는 OCI index 또는 Docker manifest list와 플랫폼별 manifest/config/layer 각각의 media type·digest·byte size를 고정한다. SBOM/attestation은 `provenance_descriptors[]`에 media type·digest·byte size·artifact type으로 따로 보존해 runnable platform으로 오인하지 않는다. canonical manifest에서 `build_input_lock_set_digest` 하나만 제외해 lock-set digest를 계산하며 아직 만들지 않은 DeepTwin 서비스 image digest를 대신하지 않음 |
| `PlatformSupportManifest` | `schema_version`, `release_id`, `source_commit`, `compose_digest`, `data_schema_version`, `build_input_lock_set_digest`, `server_architectures[]`, `container_runtimes[]`, `tested_host_profiles[]`, `tested_browsers[]`, `required_capabilities[]`, `image_locks[]`, `edge_profile`, `deployment_evidence_refs[]` | T081이 최종 서비스 이미지에서 생성. 각 final image lock은 OCI index v1과 platform별 manifest/config/ordered layer 및 별도 `provenance_descriptors[]`의 media type·digest·byte size를 묶고 T089 입력 lock digest를 연결한다. edge profile은 image/version/config digest, local-http 또는 operator-TLS-secret mode, header/SSE canary를 고정. 실제 시험 조건과 일치하지 않거나 목록이 비면 지원 완료 불가 |
| `ComponentManifest` | `component_id`, `version`, `source_url`, `source_commit?`, `download_url?`, `sha256`, `server_platform`, `size_bytes`, `license_id`, `license_text_ref`, `redistribution_basis_ref`, `purpose`, `mount_or_scope`, `required`, `signature_evidence_ref?` | 서버·worker·웹 자산·모델 가중치·글꼴·뷰어·렌즈 출처·테스트 자산 각각 배포 권리 확인. 라이브러리 라이선스가 서비스/자료의 이용 권한을 대신하지 않음 |
| `ExtensionServiceDescriptor` | `schema_version`, extension ID/version, port-contract version, service/image ID, 하나의 OCI index descriptor와 닫힌 `platforms[]`별 manifest/config/ordered-layer media type·digest·size, entrypoint/protocol, UID/resources/isolation/network/secret/broker endpoint, exact dedicated socket/named-volume mounts, SBOM/provenance/license refs | 실행형 제3자 확장의 외부 운영자 staging 입력. manifest digest를 역참조하지 않고 manifest가 descriptor digest를 단방향 참조하며 request가 둘을 함께 묶는다. 각 staging request는 같은 index/descriptor에서 정확히 한 host platform entry를 선택·고정한다. 외부 운영자는 service 생성 시 descriptor/request에 고정된 전용 socket/named-volume mount만 만들 수 있다. mutable tag·host path·제품/runtime 시작 후 또는 비명시 mount·runtime download를 허용하지 않으며 exact receipt와 실제 component handshake에 연결됨 |
| `SetupRecord` | `event_ref`, `setup_session_id`, `release_id`, `component_ref?`, `stage`, `state`, `received_bytes?`, `expected_bytes?`, `error_code?`, `evidence_ref?` | 설정 URL의 비밀 query·호스트 전체 경로·원문 오류 덤프는 일반 이벤트에 넣지 않음 |

릴리스에 고정 잠금파일, 재현 가능한 빌드 절차, SBOM, 라이선스/NOTICE 묶음, 구성요소 무결성·보안 검토 결과를 포함한다. 다운로드 파일과 같은 미검증 응답의 해시만 비교해 배포자 진위를 확인했다고 하지 않는다. 허용 manifest는 이미 검증된 앱에 고정되거나 검토한 서명 키로 검증되며 신뢰 키 교체에도 별도 버전·증거가 필요하다. 최신 버전을 설치 때 임의 선택하지 않는다. 취약점 검토는 시점·검사 도구·범위·미해결 상태를 남기며 ‘검사 실행됨’을 ‘취약점 없음’으로 바꾸지 않는다. 새 렌즈·코드·데이터의 라이선스를 기존 패키지와 같은 것으로 추정하지 않는다.

### 2.2 첫 릴리스 배포 권한과 컨테이너 경계

`local-no-terminal-v1`에서 인스턴스 운영자는 지원 macOS에 Docker Desktop과 기존 Portainer
CE Docker Desktop Extension을 각각의 GUI로 설치하고 Portainer에서 immutable source commit과
exact digest로 검증된 `deploy/compose.yaml` stack을 연다. release tag만 신뢰하지 않는다. 일반 사용자는 Portainer를 일상 업무에 쓰지 않는다.
Portainer는 Docker Engine 전체를 관리할 수 있는 호스트 관리자이므로 DeepTwin보다 낮은 권한의
플러그인처럼 설명하면 안 된다. 정확한 버전 조합이 새 호스트에서 설치·배포·복구되지 않으면 이
프로필은 실패이며 CLI를 수행해 놓고 비개발자 배포가 통과했다고 기록하지 않는다.

`portable-compose-v1`은 Linux x86_64의 지원 Docker Engine/Compose에서 release-pinned `edge`가
운영자가 제공한 TLS certificate/key Docker secret로 HTTPS를 직접 종료한다. v1은 암묵적 ACME,
mutable proxy image 또는 자격 검증하지 않은 외부 reverse proxy에 의존하지 않는다. 이 경로의
운영자에게 관리 도구 사용을 허용하는 것은 일반 사용자의 DeepTwin 업무를 CLI로 바꾸지 않는다.
두 프로필은 같은 서비스/volume/network/Compose schema와
service-keyed final image-lock set과 동일한 T089 build-input lock-set digest를 사용하되 각 final image의 index 및 플랫폼 manifest/config/layer digest를 별도로 고정하고 T081/T083에서
각각 독립 시험한다.

| 서비스/작업 | 유일하게 허용한 mount·network | 금지 경계 |
| --- | --- | --- |
| `edge` | local loopback HTTP 또는 portable HTTPS publish, pinned static config, portable 전용 read-only TLS secrets, internal control-plane network | 업무/session/provider-credential/Codex-auth mount, Docker socket, direct external egress; v1 ACME |
| `control-plane` | 업무 DB/불변 artifact volume, session-root·deployment-receipt public verify key read-only, sealed deployment-request write channel와 signed-receipt read channel, internal edge network와 전용 IPC sockets | credential/private signing root/record, Codex auth, Docker socket, 일반 outbound network, host publish |
| `credentialed-provider-gateway` | credential root read-only, 암호화 credential record read-write, 승인 provider egress | 업무 DB/artifact, Docker socket, 임의 redirect/proxy 상속 |
| `public-fetch-broker` | 공개 웹용 제한 egress와 전용 IPC socket만 | credential/work DB/artifact mount, 제품 UI/API origin, 사설/metadata network |
| `browser-worker` | 전용 broker/control socket, read-only root, bounded tmpfs/scratch | 직접 network, credential/work DB, 제품 브라우저 profile |
| `document-worker` | 전용 control socket, digest·크기·media type가 고정된 bounded artifact stream, bounded scratch | 직접 network, credential/work DB/artifact volume mount, active document code |
| `speech-worker` | 전용 control socket, pinned read-only STT model, bounded audio scratch | 직접 network, credential/work DB, runtime model download |
| `evaluation-worker` / built-in `runtime-extension-worker` | sealed/purpose-minimized projection, 전용 model/tool socket, bounded scratch | 직접 network, 업무 DB/credential mount, 다른 평가·진단 목적 접근 |
| operator-staged `extension-service` | exact OCI/service descriptor, 전용 pair-authenticated broker socket, port가 선언하고 qualification한 최소 resource/network/secret capability | control-plane/work DB/Docker socket/host path mount, runtime code download, 다른 extension socket, manifest 밖 egress·secret |
| `codex-runner` | 공식 제공자 egress, 전용 auth volume, typed projection socket | DeepTwin credential vault/work DB/artifact, Claude fallback |
| `backup-crypto-worker` | 별도 backup-key root read-only, backup staging/output, bounded archive stream socket; network none | provider credential root/record, provider egress, 업무 DB mount, 일반 도구/모델 실행 |
| `vault-init`/`vault-maintenance`/`session-root-init`/`session-root-maintenance`/`backup-key-init` | 배포 authority가 단독 실행하는 서로 분리된 credential/session/backup-key maintenance mount | control-plane API에서 실행, 관련 장기 실행 service와 동시 root access, 평문 root 전달 |
| `deployment-receipt-root-init`/`deployment-receipt-job` | init만 물리적으로 분리된 `deployment-signing-private`와 `deployment-verify-public` volume을 생성; job은 private RO+sealed-request read+signed-receipt write만; 배포 authority가 단독 실행 | control-plane/장기 실행 service의 private signing mount, job의 work/public-secret mount, Docker socket/Portainer credential, 서명만으로 실제 runtime 상태를 확정 |

Portainer CE용 descriptor는 immutable image digest·named volume·explicit network/security/resource
설정만 사용한다. `build:`, 상대 host bind/config, Git submodule, mutable image tag, webhook/GitOps
자동 갱신에 의존하지 않는다. 제공한 Chromium seccomp를 CE UI 배포가 실제 적용하지 못하면 해당
clean-host profile은 실패다. 유료판 전용 relative-path 기능, host file 수동 편집이나 CLI 명령으로
성공을 대체하지 않는다.

모든 장기 실행 container는 고정 non-root UID, read-only root filesystem, `cap_drop: ALL`,
no-new-privileges와 필요한 크기의 tmpfs/scratch만 사용한다. 서비스 쌍마다 분리한 Unix-domain socket
volume의 소유권/권한, Linux `SO_PEERCRED`, schema/크기 제한과 per-boot channel nonce를 함께
검사한다. Docker Desktop의 Linux VM에서도 이 경계를 시험하며 이를 macOS App Sandbox로
표현하지 않는다. DeepTwin container에는 Docker socket을 mount하지 않는다. 직접 egress가
OS 수준으로 차단됐다는 주장은 `network_mode: none` worker에만 하고, egress broker/gateway/
runner는 각자의 DNS/IP/redirect/TLS/proxy 우회 시험 결과를 별도로 공개한다.

Chromium worker는 별도 `browser-sandbox-v1`을 사용한다. `--no-sandbox`, privileged와
`SYS_ADMIN` 실행은 금지하고, non-root user namespace와 Chromium sandbox가 실제 활성인지 positive
probe로 확인한다. 릴리스가 고정한 seccomp profile은 Chromium이 요구하는 `clone`, `setns`,
`unshare` 범위만 허용하고 그 밖의 기본 차단을 유지한다. `init: true`, bounded `/dev/shm`, pids,
memory/CPU/file-descriptor limit와 owned profile/scratch를 설정한다. 브라우저가 뜬다는 사실만으로
sandbox 통과라 하지 않으며 seccomp/userns를 지원하지 않는 host에서는 worker를 비특권 완화로
실행하지 않고 지원 실패로 표시한다.

`DeploymentControlPort`는 제품과 특권 배포 사이의 계약이다. 제품은 versioned platform/health/
bootstrap/update/recovery receipt를 읽고, exact manifest/hash가 묶인 요청을 만들고, 결과 receipt를
검증할 수 있다. container/image/volume/TLS를 직접 변경하거나 Docker socket을 읽는 메서드는 없다.
두 필수 프로필에서는 인증된 Portainer 또는 Linux 운영자 surface가 실제 배포 효과를 수행한다. 새 배포 adapter가
추가되어도 제품의 일반 owner/service-client 권한을 호스트 관리자 권한으로 승격하지 않는다.

ADR-014의 executable extension 배포 효과도 이 경계를 재사용한다. `DeploymentRequest.kind`는
`extension_stage`, `extension_replace`, `extension_uninstall_current`,
`extension_retire_superseded`의 서로 다른 닫힌 schema를 사용한다. Stage는 never-installed absent
head/revision 1 또는 exact uninstall tombstone/그 다음 monotonic revision만 허용하고, replace는 이미 commit된 current head/next installation revision과 별도 new-service identity를
요구한다. Current uninstall은 current head와 정확한 current service tuple, next installation
revision, 비어 있는 binding/rollback/environment dependency snapshot을 요구하고 성공 시
installation tombstone/head를 전진시킨다. Superseded retirement는 보존할 current head, 그 head의
strict ancestor인 기존 installation/정확한 service tuple, backward descendant proof, 빈 dependency
snapshot과 target-keyed absent retirement head/revision 1을 요구한다. 성공해도 current installation
head는 byte-for-byte 유지되고 target retirement head만 전진한다. 준비와 receipt consumption에서
head/ancestry/dependency를 각각 다시 검증한다.

외부 운영면만 고정 OCI service를 가져와 생성·교체·제거하며 one-shot signed receipt는 exact
request/nonce/instance/origin과 arm별 관측을 되돌린다. 제품은 receipt를 one-use 검증한 뒤 실제
component handshake/target-absence/dependency postcondition과 port qualification을 수행한다. 서명은
operator 진술일 뿐 container bytes/권한을 대신하지 않는다. Core image rebuild, product-side
download, Docker API, host-path·post-start·unmanifested mount, 임의 Compose fragment 또는 mutable
registry tag는 지원 경로가 아니다. Replace는 새 identity를 병행 staging하는 비파괴 효과이고,
binding CAS 뒤 old ancestor가 더 이상 active binding, retained rollback, active environment에
필요하지 않을 때만 retire-superseded가 가능하다. 여기서 immutable binding history는 retained
rollback이 아니다. Supersession/disable transaction은 exact old binding revision별 rollback-
retention head를 `retained`로 만들고, rollback은 이를 consume해야 한다. Owner의 별도
`ReleaseExtensionRollbackRetention` command만 exact current binding head와
`BindingSlotKeyV1={port_contract_version,target_scope_fingerprint,purpose,binding_slot_id,
capability_selector_digest}` 및 그 ADR-008 canonical digest, target
binding/installation/service tuple, expected retained head를 CAS하여 `released`로 전진시킨다. 이 transaction은
binding/installation head와 service를 바꾸지 않고 history를 삭제하지 않으며
`extension.rollback_retention_released` event를 함께 commit한다. 모든 retained head가
released/consumed되고 다른 dependency도 0일 때만 retirement snapshot이 유효하다. Current/cross-
slot target, stale/mismatched head, duplicate release 또는 released-target rollback은 fail closed다.
계약 밖 destructive in-place replace는
`rollback_unavailable`/outage로 기록한다.

`DeploymentRequest`는 exact `deployment-request-v1` schema와
`deeptwin-deployment-request-v1` domain, canonical base64url 32-byte random request nonce,
digest 자신을 제외한 ADR-008 canonical JSON SHA-256 request digest, instance/`OriginProfile`,
closed `kind`, kind-specific `effect_payload`, closed `preconditions`와 생성·만료를 결합한 immutable
tagged union이다. Release/update/recovery는 각 branch의 exact precondition object를 쓰지만,
extension 네 branch의 common `preconditions`는 반드시 `{}`이고 arm-specific `effect_payload`만
정본이다. Release/update/recovery payload는 current/target release·schema, service-keyed image-lock
set과 old/new authority epoch를 요구한다. Extension payload는 data-model §3.2/API §1의 네 exact
request schema와 required/forbidden field를 그대로 적용한다. 현재/superseded installation ref와
snapshot/proof는 이미 존재한 입력이고 아직 존재하지 않는 installation/retirement record/head ref는
어느 arm에도 들어가지 않는다.
Extension common `preconditions` 아래에 이를 복제·override하거나 current/future ref를 넣어 두 번째
정본을 만들면 거절한다. 서로 다른 kind의 필드를 섞거나 빠뜨리거나 금지 필드를 null로라도 넣으면 거절한다. prepared/cancelled/
receipt_pending/accepted/rejected/expired는 별도 revisioned CAS lifecycle이며 먼저 commit된
cancel은 뒤의 receipt를 거절한다.

root-init은 private seed와 public trust set을 각각 `deployment-signing-private`와
`deployment-verify-public` named volume에 쓴다. one-shot receipt job은 private만 RO, control-plane은
public만 RO로 mount한다. 서로 분리된 고정 exchange volume은 control-plane-write/job-read sealed request와
job-write/control-plane-read signed receipt만 전달한다. content-digest filename, exclusive staging,
fsync+atomic rename와 consumed tombstone을 쓰며 브라우저 upload, Docker socket 또는 Portainer
credential은 이 경로에 들어오지 않는다. `DeploymentReceipt`는 동일 request ID/digest/nonce/kind와
실제 adapter/version, matching kind-specific `effect_result`, observed/verified/unverified facts,
time/outcome, key ID, trust class와 signature를 포함한다. release result는 old/new release/schema/
image-lock/epoch를, extension result는 exact request digest와 arm-specific service observation 및
request-bound existing head/target/revision/digest equality만 고정하고 아직 생성되지 않은
installation/retirement record/head identity는 포함하지 않는다. mixed-kind/stale/replay/already-consumed/cross-instance/cross-
origin/signature mismatch를 거절한다.

Extension `effect_result`도 네 닫힌 result schema를 사용한다. 관측은 필드 없는 `absent`, 완전한
five-field tuple/reachability/time의 `present`, 또는 그 request-bound tuple을 `expected_*`로 반복한
`unknown`이다. 성공 stage는 absent→present, replace는 distinct present→present/old reachable,
current uninstall은 current present→absent다. 성공 superseded retirement는 descendant current가
present/reachable인 채 exact ancestor target이 present→absent다. 실패/unknown uninstall은 absent
성공을 주장하지 못하고 모든 non-absent 관측은 current tuple과 같다. 실패/unknown retirement도
target-after absent를 금지하고 current/target non-absent 관측을 각각 request-bound tuple과 같게 한다.
모든 반복 head/ref/revision/snapshot/proof digest는 request와 byte-for-byte 같아야 한다. 비조상,
stale/changed current head, 남은 dependency나 관련 없는 service 관측은 receipt 검증에서 거절한다.

`deployment-receipt-v1`은 `deeptwin-deployment-receipt-v1` domain을 포함하고 signature를 제외한
모든 exact field의 ADR-008 canonical JSON을 Ed25519로 서명한다. 32-byte public key와 nonce/digest,
64-byte signature는 canonical base64url-no-padding이며 strict schema는 duplicate/unknown field/
algorithm을 거절한다. key ID는 배포에 고정한 versioned public trust-set digest에 속해야 하고 공용
test vector가 preimage/encoding을 고정한다. Release/update/recovery는 별도 immutable
`DeploymentReceiptConsumption`을 winning lifecycle/transition과 함께 unique-CAS로 기록한다.
Stage/replace/current-uninstall 성공은 receipt 검증 뒤 exact postcondition을 수행하고 immutable
installation record/tombstone와 installation head, receipt consumption, accepted lifecycle, public
event를 한 transaction으로 commit한다. Superseded retirement 성공은 preserved-current CAS/handshake,
target absence, ancestry와 zero-dependency 재검사를 통과한 뒤 target-keyed retirement record/head,
consumption/event만 atomically commit하고 installation head를 바꾸지 않는다. Failed/unknown은
success head를 만들지 않고 lifecycle/event만 atomically 보존하며, unknown target은 관측 상태가
별도 reconciliation event로 풀릴 때까지 rollback/rebinding을 막는다. Signed receipt는
수정하지 않는다. 각 arm은 기존 입력→request→receipt→postcondition→해당 record/head→consumption/
event 순서로만 이전 digest/ref를 참조한다. Event와 consumption은 transaction/event ID를 공유할
뿐 서로를 content-hash하지 않는다. 서명은 배포 authority의 진술만 인증하고 host 관리자의 Docker 상태 진실성은
보장하지 않으므로, image/runtime 준비는 각 component의 독립 handshake와 migration/backup
gate까지 일치해야만 적용한다.

`deploy/bootstrap/index.html`은 두 profile이 공통으로 쓰는 체크섬 검증 오프라인 정적 release
artifact다. WebCrypto로 32-byte random raw capability와 그 SHA-256 verifier를 로컬에서 만들고
네트워크 요청을 하지 않는다. 두 profile 모두 DNS label로도 유효한 lowercase 32-hex-character
128-bit instance ID를 만들며,
local profile은 추가 lowercase 32-hex-character 128-bit base path 및 검증한
사용자 선택 port로 exact `http://<instance-id>.localhost:<port>/<instance-path>/`를 만들고,
portable profile은 instance 전용 hostname의 canonical HTTPS URL과 `base_path=/`를 검증한다.
`OriginProfile={deployment_profile_id,instance_id,mode,scheme,host,port,base_path,origin_base,digest}`의 digest는 digest 자신을
제외한 앞선 field의 ADR-008 canonical JSON SHA-256이다. userinfo/query/fragment, IP-literal ambiguity,
dot segment, encoded separator, duplicate slash를 거절하고 ASCII/IDNA host 소문자화, default-port 제거,
정확히 한 trailing slash를 적용한다. `port` field는 URL 생략 여부와 관계없이 effective integer
1..65535(기본 80/443 포함)이고 origin_base는 default port를 생략한다. local base_path는 exact
`/<hex32>/`, portable은 exact `/`다. 비밀이 아닌 이 profile과 verifier/recovery
epoch만 Portainer/Compose configuration block에 넣고, raw capability는 별도로 한 번 표시해 해당
origin의 DeepTwin 최초 설정 화면에 입력한다. `raw_capability_b64u`와 `verifier_b64u`는 canonical
base64url-no-padding이며 각각 정확히 32 bytes로 decode되고 JS/Python 공용 vector가 대체 인코딩을
거절한다. edge/control-plane/bootstrap/session/CSRF/receipt는
같은 profile digest를 검증한다. 서버는 기동 시 시작한 10분/5회 한도 안에서 cheap
schema/Host/Origin/verifier 검사를 먼저 하고 일치를 원자 소비한 뒤에만 Argon2를 시작하며 raw 값은
URL/query/log/DB에 넣지 않는다. 청구 전 분실은 새 쌍으로 교체하고, 소유자 복구는 배포 authority가
epoch를 올린 뒤 모든 과거 session/authenticator, service client, 미사용 human capability와 pending
approval/consent challenge를 무효화하는 별도 흐름이다. 이 HTML은 DeepTwin 제품 UI나 별도 네이티브
런처가 아니라 최초 소유권 전달용 외부 배포 보조물이며, 최초 설정 자체는 브라우저의 DeepTwin
화면에서 수행한다.

loopback profile은 helper가 만든 exact random `<instance-id>.localhost:port/<instance-path>/`
origin/base path를 사용한다. host-only HttpOnly `SameSite=Strict` cookie는 그 path에만 한정하고 HTTP
loopback이라 `Secure`/`__Host-` prefix를 주장하지 않는다. HTTPS profile은 Secure HttpOnly
`__Host-deeptwin_session` SameSite=Strict cookie를 쓴다. 둘 다 32-byte random session token을
발급하고 서버에는 SHA-256 digest만 두며 idle 12시간/absolute 7일을 넘기지 않는다. 별도 32-byte
session root의 HMAC-SHA-256으로 ADR-008 canonical JSON
`{domain:"deeptwin-csrf-v1",origin_base,session_token_b64url,recovery_epoch}`에 묶은
base64url-no-padding CSRF token을 도출한다. `origin_base`는 배포 검증된 trailing-slash 포함 외부 base
URL 문자열이고 token/HMAC 비교는 constant-time이며 인증된 no-store session read가
새로고침 뒤 다시 제공한다. mutation은 이를 `X-DeepTwin-CSRF`에 정확히 한 번 보내며 duplicate/
comma-folded/noncanonical 값은 거절한다. Cookie가 port로 격리되지 않는 한계는 random host/path, exact
Host/Origin과 cross-port canary로 완화하지만 동일 host 관리자 침해 방어로 주장하지 않는다.
어느 mode도 session/CSRF를 `sessionStorage`, `localStorage`, URL 또는 service worker에 두지 않는다.
one-shot `session-root-init`은 별도 named volume에 root와 immutable epoch manifest를 exclusive-create하고
control-plane만 read-only mount한다. owner recovery는 control-plane 정지 중
`session-root-maintenance`가 더 높은 epoch의 새 generation을 원자 승격한 뒤 재기동한다. equal epoch는
정상 시작이다. valid deployment recovery receipt와 strictly greater root/config epoch이면 restricted
reconciliation mode에서 general API/dispatch를 차단한 채 단일 DB transaction으로 owner epoch advance와
모든 과거 authority 폐기를 완료한 뒤 bootstrap을 연다. rollback/skipped epoch 또는 receipt 없는
missing/stale/malformed/mismatch는 평문 fallback 없이 시작 실패다.

모든 `*-root-init`/`backup-key-init` job은 absent storage에만 O_EXCL create+file/directory fsync하고,
exact valid existing root/manifest이면 verify-only no-op 성공한다. malformed ownership/version/epoch는
교체하지 않고 실패한다. 최초 session genesis만 exact configured epoch로 선행 receipt 없이 만들 수
있고 이후 root/key 변경은 matching request-bound receipt가 있는 maintenance 경로만 허용한다.

## 3. 연결·비밀·과금의 운영 경계

Codex 구독의 첫 릴리스 인증 프로필은 공식 device-authorization을 runner가 소유하고, DeepTwin GUI에는 공식
verification URL·user code·expiry와 redacted status만 표시한다. container 내부 loopback callback이
host browser에 닿는다고 가정하지 않는다. callback/PKCE는 별도 qualification 전에는 지원하지 않는다.
DeepTwin은 구독 token을 읽어 추출하거나 다른 실행 환경에 복사하지 않는다. runner auth volume은
provider gateway/일반 worker와 분리하며 자동 로그아웃·계정 교체를 하지 않는다.

Claude는 API 키를 GUI에서 설정·교체·삭제한다. Claude 구독 키/로그인/사전 승인 절차는 제공하지 않는다. Codex API도 구독과 구분한 명시 선택이다. 각 경로에 provider/model·실제 과금 방식·자료 전송·적용 범위·예산을 표시한다. 키 저장/목록 조회/연결 상태 확인이 유료 추론 시작이나 크레딧 구매가 아니다. 과금·사용량/크레딧을 조회할 수 없으면 `unknown`으로 두고 0원/무제한으로 표시하지 않는다.

T025는 외부 HTTP 클라이언트의 공통 권한 경계를 완결한다. `ServiceClient` principal과
immutable credential revision/head를 DB에 보존하고, create/rotate/revoke/expiry/recovery,
one-time bearer 반환, digest-only storage, last-used CAS를 담당한다. `app/api/service_clients.py`를
등록하고, `app/api/router_composition.py`의 core-owned frozen composition port와 이를 한 번 호출하는
`app/server.py`를 소유한다. 이 port는 build-installed first-party descriptor
`app/api/route_contributions/*.json`만 받아 unique ID/route, exact `/api/v1`, auth/scope,
`app.api.*` factory allowlist를 검사하고 app 생성 뒤 추가를 거절한다. TLS의 단일 Bearer header만 허용하며 browser cookie fallback,
자기 scope 확대, human approval/bootstrap/deployment 권한을 거절한다. trusted-network profile,
client/source/route별 rate limit과 restart/rotate/revoke 경합도 같은 T025 시험 범위다. T087은
`app/api/extension_routes.py`와 고정 `app/api/route_contributions/extensions-v1.json`만 소유하며 이
seam을 통해 등록하고 `app/server.py`/composition port를 수정하지 않는다. 공통 경계를 재구현하지
않고 extension-specific client method와 실제 server의 별도-process HTTPS parity만 추가한다.

API 키와 프레임워크가 소유한 암호화 키는 `CredentialVault` 포트 뒤의 배포별 보호 저장소에
보관한다. 첫 release에서는 `credentialed-provider-gateway`만 최소 권한으로 열 수 있고 control-plane,
브라우저·모델·도구 worker에는 vault나 복호화 키를 mount하지 않는다. 기존 macOS Keychain adapter는
개발/역사 evidence이며 두 release profile의 선택지가 아니다. 운영용 vault binding은 회전·잠김/
접근 거절·백업 제외·감사와 재시작 시험을 통과해야 한다.

두 첫 배포 프로필의 기본 구현은 PyNaCl 1.6.2/libsodium XChaCha20-Poly1305 기반
`credential-record-v1` encrypted-file vault다. one-shot `vault-init` job이 data와 분리된 named
volume에 32-byte root를 exclusive-create하고, provider gateway가 이를 read-only로 mount한다.
key bytes는 환경변수·DB·일반 로그·백업에 두지 않으며 root volume이 없거나 소유권/형식이 틀리면
시작을 차단한다. 24-byte nonce를 새로 만들고 전체 `(key_id,nonce)` 유일성을 검사하며 RNG 충돌은
재생성하거나 차단한다. `schema/algorithm_id/key_id/vault_id/record_id/record_version/provider/
auth_mode/created_at` ADR-008 canonical header를 AAD로 인증하고 `algorithm_id`는
`xchacha20poly1305-ietf`다. UTF-8 JSON clear envelope에는 exact header, canonical base64url-no-padding
nonce와 `encrypted.ciphertext`(ciphertext+16-byte tag)만 두고 combined nonce+ciphertext를 중복 저장하지
않는다. decoded nonce=24 bytes, decoded ciphertext/tag=16..65,552 bytes, envelope≤96 KiB를 강제하며
duplicate/unknown key, invalid/noncanonical UTF-8/base64url, unknown algorithm/version, nonce 재사용,
metadata/ciphertext 교환·절단·변조는 거절한다.

회전은 gateway를 중지한 상태에서 배포 authority가 `vault-maintenance`를 단독 실행해 새 root와
모든 재암호화 record generation을 staging하고 전부 검증·fsync한 뒤 manifest를 원자 승격한다.
중단 시 이전 완전 generation으로 복구할 수 있어야 한다. cold restart, 잠김, key mismatch,
ciphertext/metadata swap/tamper, 부분 회전과 backup/restore 경계를 시험한다. 제품 웹 페이지나
일반 worker는 root를 읽거나 표시하지 않는다. XChaCha vault는 업무 DB/data volume만 유출됐을 때
credential 평문을 분리하는 경계이며 Docker host/Portainer 관리자 또는 실행 중 gateway 침해까지
막는다고 주장하지 않는다. 외부 secret manager는 같은 `CredentialRootPort`의
별도 deployment-trusted adapter이며 검증 없이 더 안전하다고 주장하지 않는다.

- `SecretBinding = {connection_id, provider, auth_mode, secret_ref, state, created_at, rotated_at?, scope_ref}`만 보호된 구성에 보존한다. 키 bytes·키의 해시·원문 접두/접미는 기록하지 않는다. UI 표시용 연결 이름은 사용자 입력이므로 비공개 자료로 취급한다.
- 공개 연결 응답은 `{connection_id, provider, auth_mode, state, key_present, checked_at?, catalog_ref?, billing_state}`의 허용목록이다. `secret_ref`도 브라우저에 전달하지 않는다.
- 키 입력은 마스킹·브라우저 저장 비활성·민감 필드로 다루고 저장 응답 뒤 필드/메모리 참조를 해제한다. 관리 런타임의 완전 메모리 소거를 보장하지 않는다. localStorage·URL·분석 이벤트·프롬프트·도구 환경·예외 덤프·내보내기에 키가 없어야 한다.
- 명시적 create/rotate 요청에서만 edge/control-plane의 bounded no-store memory가 최대 64 KiB raw
  secret를 받아 authenticated gateway IPC로 한 번 전달한다. 정상 저장/실행은 opaque handle만 쓰며
  secret를 journal/DB/log/error/metric/export/model·tool worker에 복제하지 않고 gateway receipt 뒤
  참조를 best-effort 해제한다. 관리 런타임의 완전 메모리 소거는 보장하지 않는다.
- Keychain adapter의 사용자 잠금은 `needs_unlock`, encrypted-file vault는 `missing_root`/
  `permission_denied`/`tampered`/`maintenance_required`로 구분해 deployment-operator action으로
  연결한다. 평문 파일/일반 환경변수로 자동 대체하지 않는다. 연결 변경은 실행 중 설정을 바꾸지
  않고 새 버전/다음 실행에 적용한다.
- 다른 환경에 저장된 키/구독 로그인을 자동 탐색해 사용하지 않는다. 기존 Claude 구독 구성은 역사로 보존하고 `needs_reconfiguration`으로 표시하며 명시 API 설정 전 실행하지 않는다.
- API 한도·구독 제한·인증 실패에는 관련 실행을 보류한다. 다른 provider/model/과금 경로로 자동 전환하지 않는다. 세부 예약·사용량 집행은 상위 실행 예산/제공자 계약이 정본이다.
- create 실패의 valid orphan, 성공 rotate의 predecessor와 delete 대상은 모두 immutable retirement intent와 `cleanup_pending` 상태를 가진다. binding이 가리키지 않는 record는 어떤 catalog/provider send에도 열 수 없다. delete는 먼저 binding을 CAS로 `revoked_pending_erasure`로 바꾸고 종속 catalog/selection authority를 폐기한다.
- gateway 정지 중 `vault-maintenance`는 retired record를 제외한 새 generation을 검증·원자 승격한 뒤 superseded/staging generation의 locally managed file/root material을 제거하고 부재를 확인한다. 그 전 또는 crash/rollback 중에는 `cleanup_pending`이며 `erasure_completed`라고 하지 않는다. rollback은 revoked/retired credential을 provider용으로 복원할 수 없다. 모든 locally managed copy 제거가 확인된 뒤에만 `erasure_completed`로 기록하며 host snapshot·관리자 복사본·swap·이미 만든 backup까지 삭제했다고 주장하지 않는다.
- `erasure_completed`는 DeepTwin이 관리한 로컬 암호문 제거만 뜻하며 Anthropic/OpenAI의 원격 API credential 폐기가 아니다. 원격 무효화가 필요하면 제공자 관리 화면의 별도 행위로 안내하고 실제 provider evidence 없이 완료로 표시하지 않는다.

## 4. 보관·기록 데이터와 접근

인스턴스 전용 vault 디렉터리는 0700, 내부 비밀이 아닌 데이터/DB/원본 파일은 0600을 기본으로 한다. 원본·불변 버전·실행/진단/평가 영역을 논리·접근 정책으로 나눈다. 임의 심볼릭 링크/경로 이탈·다른 vault 참조를 거부한다. 실제 소유권·권한 검사 실패에는 자동 광범위 chmod를 하지 않고 준비 실패로 표시한다.

기존 일반 SQLite를 암호화 DB로 표현하지 않는다. 첫 로컬 후보의 업무 데이터 보호는 OS 사용자 권한·인스턴스 접근 경계이며, 전체 디스크 암호화 여부는 별도 확인/안내할 수 있지만 OS 설정을 자동 변경하지 않는다. 로컬 동일 OS 계정·관리자·디스크 획득에 대한 보장 한계를 표시한다. API/백업 키 보호와 원본 데이터의 저장 암호화는 다른 주장이다.

웹 UI↔백엔드는 동일 출처 세션·Host/Origin·CSRF·객체 권한을 검사한다. 로컬 전용 profile은
loopback만, 네트워크 profile은 명시된 인터페이스와 trusted host/origin 및 HTTPS 종료를 요구한다.
`0.0.0.0` 바인딩만으로 원격 접근이 안전하다고 표시하지 않고 다른 localhost 앱도 신뢰하지 않는다.
파일은 vault ID와 artifact ID로 요청하며 브라우저가 보낸 임의 호스트 경로를 직접 읽지 않는다.

### 4.1 사건·증거의 최소 필드

`public`은 인증된 instance client/UI에 제공할 수 있는 허용목록을 뜻하며 인터넷 공개·자동 공유를 뜻하지 않는다. HTTPS service client도 자신의 scope 안에서만 볼 수 있고, 원문·이름·URL 같은 사용자 데이터는 별도 객체·목적 권한이 필요한 private evidence에 둔다.

| 레코드 | 필수 필드 | 내용·접근 |
| --- | --- | --- |
| `EventEnvelope` | `schema_version`, `event_id`, `vault_id`, `sequence`, `observed_at_utc`, `recorded_at_utc`, `actor_kind`, `actor_ref`, `event_type`, `object_refs[]`, `correlation_id`, `causation_id?`, `status`, `error_code?`, `public_metadata`, `private_evidence_refs[]`, `retention_class`, `policy_ref` | enum/구조/크기 허용목록. 이벤트별 extra 필드 거절. 원문 예외/HTTP body/provider delta를 metadata로 통째 넣지 않음 |
| `ObjectRef` | `kind`, `id`, `version?`, `content_hash?` | 환경·업무·입력·모델/도구 설정·후보·실행/시도·산출물·렌즈·실험/회차·승인/적용을 연결. 실제 없는 버전은 만들지 않음 |
| `PublicEventView` | `event_id`, `sequence`, `observed_at_utc`, `event_type`, `object_refs`, `status`, `error_code?`, `public_metadata` | `public_metadata`는 event별 단계·수량·bytes·duration·revision·종료 이유 같은 enum/수치에 한함. private 참조·본문·토큰·사용자 경로·파일명·계정/실제 URL 제외 |
| `PrivateEvidence` | `evidence_id`, `kind`, `media_type`, `byte_length`, `content_hash`, `storage_ref`, `source_ref?`, `created_at`, `access_policy_ref`, `retention_class`, `availability`, `redaction_state` | 허용된 원본·요청 projection·모델 최종 응답·도구 관찰·평가 근거. 숨은 사고과정·비밀은 이 영역에도 수집하지 않음 |
| `RecordGap` | `gap_id`, `object_refs`, `phase`, `reason`, `first_seen_at`, `last_seen_at?`, `affected_claims[]`, `recoverability`, `evidence_ref?` | 저장 실패·누락·삭제·원격 결과 미확인·접근권한 제한을 명시. 해시만 있을 때 원문 재현 가능으로 세지 않음 |

순서는 vault 안의 원자적 sequence와 인과 참조로 판정한다. provider가 보낸 시각과 프레임워크가 관측한 시각은 구분한다. 해시/순서 검사는 결손·변조 탐지의 일부일 뿐 동일 호스트 관리자에 대한 변조 불가능한 원장 증명이 아니다. 각 이벤트의 실제 타입 enum은 데이터 모델에서 이 envelope를 참조해 등록한다.

### 4.2 기록할 범주와 실패 정책

필수 핵심 사건은 `deployment/setup/auth/service_client`, `connection/credential_erasure/catalog/model_selection`, `extension/deployment/installation/service_retirement/qualification/binding/rollback-retention/rollback`, `work/source/ingestion/STT`, `understanding/design/review/selection`, `run/attempt/tool/handoff/artifact`, `alternative/difference/hypothesis/inquiry/lens`, `candidate/evaluation/loop_stop`, `validation/approval/promotion/rollback`, `retention/export/backup/update/recovery/security`다. 생성·탈락·수정·실패·취소·미결·질문 거절도 남기며, 준비한 배포 요청을 실행하지 않고 폐기하면 `deployment.request_cancelled`를 기록한다. 클릭/키 입력 전체가 아니라 이 의미 있는 제품 사건을 기록한다.

원본/입력·모델·권한·예산·프로필과 호출 의도를 내구적으로 보존하지 못하면 새 provider/tool dispatch를 하지 않는다. 실행 결과와 산출물 저장/terminal 사건도 연결한다. 외부 효과 이후 기록 실패 시 성공으로 마감하거나 재실행하지 않고 상태 확인 필요·결손을 남긴다. read-only 복구와 가능한 보관 확인을 우선하고, 이미 발생한 외부 효과를 취소됐다고 주장하지 않는다.

상세 진단 기록이 포화되어도 핵심 사건이 정상 보존되면 진단만 순환한다. 핵심 기록까지 저장할 수 없으면 새 유료/외부 행동을 차단하고 현재 작업·초안·확인된 결과를 가능한 범위에서 보존한다. 공간 확인과 실제 쓰기 사이 경합이 있으므로 `disk_full`, 실패한 트랜잭션, 원격 결과 미확인을 별도로 시험한다.

## 5. 보존·삭제·백업·복구

### 5.1 보존/삭제 계약

`RetentionPolicy = {policy_id, version, core_mode: manual_only, cache_max_age_days: 14, cache_max_bytes: 1073741824, diagnostics_max_age_days: 30, diagnostics_max_bytes: 104857600, effective_at, actor_ref}`를 기본값으로 둔다. 실제 도구 스냅샷처럼 다시 얻을 수 없는 관찰 증거는 캐시로 분류하지 않는다. `stt-local-ko-v1` 원음은 application-level durable storage 없이 browser memory/container tmpfs에만 두고 worker restart 시 잃는다. host-admin/swap/crash capture는 이 주장 밖이며, 전사·수정·엔진/동작 사건은 해당 핵심 기록 정책을 따른다.

삭제는 웹 UI 미리보기에서 원본·추출·썸네일·대안·후속 파생물·평가/승인 근거·백업·내보낸 파일의 참조와 복구 여부를 확인한 뒤 실행한다. 선택하지 않은 원본·다른 환경을 자동 삭제하지 않는다. 전체 vault 삭제는 정확한 vault 식별·영향 확인을 요구하며 stack/container 제거와 구분한다.

내용 삭제 후 남기는 최소 tombstone은 `{object_id, former_kind, deleted_at, deletion_request_id, affected_refs, reason_code}`다. 삭제된 내용/파일명/비밀을 tombstone에 복사하지 않는다. 더 넓은 개인정보 삭제가 요청되면 선택 범위를 확대해 실제 삭제 결과를 보고한다. 기록을 수정해 과거 검증이 여전히 완전하다고 꾸미지 않고 `evidence_deleted`·재현 제한/재검증 필요를 표시한다. 이미 제3자/모델 제공자에게 보낸 데이터나 관리 밖 복사본까지 삭제됐다고 주장하지 않는다.

### 5.2 백업과 복원

`백업 만들기`는 일관된 DB snapshot과 내용 파일·해시·버전·연결 참조를 암호화된 묶음으로 만든다.
credential/key/Codex token과 provider/session/backup/deployment-receipt private roots·`Authenticator`·
`BrowserSession`·`ServiceClient` credential digest/binding·미결 approval/consent challenge·모든
미소비 human/bootstrap capability 및 verifier·원음·재생성 cache는 복원 가능한 권한에서 제외한다. 과거
approval/consent 결과는 역사 evidence로 보존할 수 있지만 새 배포의 실행 권한이 아니다. 내보내기와
달리 선택한 vault의 개인 원문을 포함하므로 GUI에 명확히 표시한다. 외부/네트워크 저장 위치로
백업을 만드는 것은 명시 선택이며 자동 업로드하지 않는다.

`BackupManifest = {schema_version, backup_id, vault_id, server_release, data_schema_version, snapshot_sequence, created_at, item_refs[], encryption_profile_ref, key_mode: instance_backup_key|portable_recovery, excluded_categories[], consistency_evidence_ref}`는 암호화할 내부 manifest다. 외부 `BackupReceipt = {backup_id, ciphertext_sha256, ciphertext_size, encryption_profile_ref, completed_at, restore_verification_ref}`로 완성 파일을 확인하여 자기참조 해시를 피한다. 암호화는 data-model §7의 고정 age-x25519-v1 프로필을 사용하며 자체 암호 알고리즘을 만들지 않는다. 전체 복호화 인증이 완료되기 전에 원문을 복원본으로 활성화하지 않는다.

- 기본 자동 백업은 데이터 마이그레이션 직전이다. 일상 예약 백업은 사용자가 GUI에서 켜며 주기/보관 위치를 선택한다. 어떤 백업도 기본 자동 삭제하지 않는다.
- 같은 배포의 기본 age identity는 provider credential vault와 분리한 `backup-key` volume에 두며
  networkless `backup-crypto-worker`만 read-only로 mount한다. 다른 배포 복원용은 사용자에게 복구
  비밀의 별도 보관을 안내한다. 복구 비밀을 backup 안에 함께 넣거나 log로 남기지 않는다.
  `backup-key` volume에만 있는 키를 host/volume 상실 대비 복원 가능으로 표시하지 않는다.
- `backup_pending → snapshotting → encrypting → verify_restore → ready` 또는 실패 상태로 구별한다. 파일 생성만으로 복구 가능이라 하지 않는다. 마지막 복원 검증 시각과 검증 범위를 보인다.
- 복원은 빈 인스턴스 소유 staging vault에서 archive 경로/크기/해시·암호·스키마·참조를 검사한 뒤 사용자가 선택한다. 기본은 별도 복원본 생성이며 활성 vault를 덮지 않는다. 모델/도구를 실행하지 않고 데이터 열기·계보·상태 일관성을 검증한다.
- control-plane은 age identity/provider credential root를 mount하지 않고 typed archive stream과
  opaque backup-key handle만 전달한다. portable recovery identity는 one-shot masked input으로
  `backup-crypto-worker`에 전달하며 DB/log/export에 남기지 않는다.
- `backup-crypto-worker`는 검증된 age 1.3.2의 `age`/`age-keygen`만 가지며 shell이나 caller argv를
  제공하지 않는다. code-owned wrapper가 native X25519 recipient/identity만 허용하고 fixed argv와
  owned descriptor를 구성한다. SSH/scrypt/plugin/PQ/tag/arbitrary identity·recipient·path/flag는
  spawn 전에 거절하고, PATH plugin sentinel·image inventory·network-none roundtrip로 이를 검증한다.
  이는 upstream binary 내부 기능 삭제가 아니라 현재 서비스 경계에서의 도달 불가능성 보장이다.
- 복원된 인스턴스는 새 owner bootstrap 뒤에도 모든 dispatch가 차단된 `restored_review`로 열린다.
  새 owner가 connection/service client를 다시 만들고 exact environment를 검토·활성화해야 하며,
  과거 credential handle/session/challenge를 재사용하지 않는다.
- 복원한 진행 요청은 원격 생존/결과 확인 필요다. 연결 키는 새로 제공/확인하고, 과거 승인 기록을 다른 버전·현재 외부 행동의 신규 권한으로 쓰지 않는다. 미지원 구버전 schema는 조용히 누락해서 열지 않고 지원 실패로 표시한다.

## 6. 런타임·업데이트·장애 복구

control-plane의 worker coordinator는 배포가 시작한 장기 실행 서비스와 authenticated handshake해
논리 instance ID·lease·dispatch/cancel·terminal 상태를 관리한다. container/image/volume을 시작·
종료·교체하지 않으며 같은 socket/이름의 다른 peer를 자기 worker로 간주하지 않는다. 실제 container
restart는 배포 runtime/authority가 맡고, coordinator는 새 peer identity를 검증한 뒤 저장된 요청/
terminal 상태·외부 효과를 재조정한다. 브라우저 재접속/새로고침은 작업을 재발행하지 않는다. API
요청 timeout, 논리 cancel, worker process 종료와 원격 provider 종료 확인은 각각 별개다.

`UpdatePlan = {plan_id, current_release, target_release, component_manifest_ref, signature_evidence_ref, schema_from, schema_to, backup_ref?, migration_id?, downtime_notice, rollback_conditions}`를 사전 보존한다. 기본 수동 업데이트 확인은 배포 manifest만 조회하며 업무/사용 로그를 보내지 않는다. 자동 확인은 별도 설정이고 자동 설치와 구분한다.

업데이트 흐름은 제품 안의 `available → request_prepared → waiting_safe_point → backup_verified`
뒤 외부 운영면의 `operator_applying → receipt_ready`, 새 배포의 `receipt_verified → migrating →
postcheck → activated`로 구분한다. image download/verification/container replacement를 제품 단계로
허위 표시하지 않는다. 활성 외부 쓰기·승인/적용 중에는 안전한 중지점까지 대기한다. 실패 시 새
실행을 열지 않고 이전 server/worker release와 검증된 이전 data backup의 호환성을 확인한 exact
rollback request를 만든다. 실제 rollback effect는 배포 authority가 수행한다. 구버전 server를 새
schema에 억지로 연결하거나 upgrade 후 생성한 사용자 자료를 몰래 없애지 않는다. 이전 버전 복원·
새 데이터 별도 보존/내보내기를 웹 관리 화면과 운영면 양쪽에 같은 request ID로 안내한다.

스키마 마이그레이션, worker 크래시, 비밀 잠김, 손상·용량 부족, 갑작스런 종료는 서로 다른 오류 코드와 복구 동작을 가진다. 모든 경우 재평가의 best/progress reference/patience·소비 예산, 승인한 정확한 버전, 외부 쓰기 idempotency를 유지한다. 제품 조기 종료를 복구·개발 종료 정책으로 전용하지 않는다.

## 7. 선택적 로그 추출과 redaction

`기록 내보내기`는 어느 업무에서든 환경/기간/업무/실험/사건 범위를 선택하고 관련 계보를 제안한다. 기본 metadata-only에는 내용·사용자 파일명·계정·원문 URL을 넣지 않는다. 기본값이 적어 진단에 부족하면 필요한 자료와 이유를 제안하되 자동 포함하지 않는다. 사용자가 원본/모델 최종 응답/도구 관찰/대안/평가 근거를 선택적으로 포함할 수 있다. 숨은 사고과정·자격증명은 선택 가능한 항목이 아니다.

### 7.1 추출 파일 계약

| 레코드/파일 | 필수 필드·내용 | 경계 |
| --- | --- | --- |
| `ExportRequest` | `request_id`, `scope`, `selected_categories`, `include_raw_refs[]`, `redaction_policy_ref`, `author_consent_ref`, `created_at` | 실제 포함 원본을 명시하며 설정 저장만으로 export 생성/전송하지 않음 |
| `ExportManifest` | `schema_version`, `bundle_id`, `created_at`, `app_release`, `scope`, `export_policy_ref`, `pseudonym_map_scope`, `items[]`, `missing_evidence[]`, `redaction_summary`, `reproduction_limits[]`, `checksum_algorithm` | 원 source hash와 추출 bytes hash를 구별. manifest에서 본문·실제 경로·키를 재노출하지 않음 |
| `items[]` | `export_id`, `kind`, `relative_path`, `media_type`, `size_bytes`, `export_sha256`, `linked_export_ids[]`, `content_mode`(raw/redacted/metadata_only), `source_hash_included`, `source_sha256?`, `license_or_share_basis?` | source_sha256은 명시 포함일 때만 존재. 제한된 상대경로만 사용. 비밀·archive path traversal·symlink·자동 실행 hook/실행 권한 없음 |
| `missing_evidence[]` | `export_ref`, `reason`(not_selected/redacted/deleted/unavailable/not_recorded/access_denied/rights_restricted), `affected_claims[]`, `recoverable_by_user` | 가림·사용자 미선택·실제 기록 결손을 같은 오류로 합치지 않음 |
| `ExportReceipt` | `bundle_id`, `manifest_sha256`, `bundle_sha256`, `size_bytes`, `completed_at`, `artifact_ref` | 완성 archive 밖의 확인 레코드. manifest 안에 archive 자신의 해시를 넣는 순환 해시 구조를 만들지 않음 |
| `events.jsonl` | 선택한 EventEnvelope의 내보내기 전용 허용목록, bundle 내부 가명 ID/참조 | 로컬 internal/private ID·OS 경로를 그대로 복사하지 않음. 사건의 실제 존재/순서는 유지 |
| `README` | 포함 범위·원문/가림·빠진 근거·재현 한계·사용자 선택 의견 | 제작자 평가/학습 동의나 실행 스크립트를 자동 삽입하지 않음 |

export는 별도 staging에서 선택 범위의 snapshot으로 만든다. `selecting → preview_ready → generating → validating → ready`를 구분하며 중간 실패 파일을 완료 결과로 주지 않는다. 마지막 검사는 항목 목록·해시·연결·크기·secret canary/탐지·금지 파일·원문 포함 동의와 일치해야 한다. 내용이 preview 뒤 바뀌면 기존 snapshot을 유지하거나 새 preview를 요구한다.

외부 export-sink가 관여하면 `ExportSnapshotV1.artifact_input_bindings`는 그 동결 snapshot의
정확한 순서·내용을 이루는 1–256개 항목이며 모두 `role=export_payload`, `selector=null`, 허용
media type과 byte 한도를 만족한다. `prepare`는 이 목록의 실제 bytes를 T018의 digest/chunk/
receiver-credit bounded stream으로 받아 같은 목록·target·aggregate digest의
`PreparedDeliveryV1`을 봉인한다. `transmit`도 그 prepared record의 정확히 같은 목록과 target을
같은 bounded stream으로 다시 받는다. Artifact ref만 전달하거나 shared-store/host mount를
열어 주거나 preview 뒤 변경된 내용을 보내는 것은 전송이 아니다.

redaction은 추출 복사본에 적용하고 원본을 덮지 않는다. 자동 탐지는 완전하지 않으므로 실제 포함될 텍스트·페이지/이미지·표와 사용자 검토를 제공한다. PDF의 검은 도형 overlay나 HTML 숨김처럼 원 데이터가 남는 가림은 불합격이다. 안전하게 재인코딩/metadata 제거·재검증하지 못한 형식은 raw 포함을 명시 선택하거나 제외한다. 가림으로 변한 자료는 원본과 동일/완전 재현 가능으로 표시하지 않는다.

추출은 네트워크 전송이 아니다. 웹 제품 내 보내기 기능을 추가할 때에는 실제 수신자·범위·파일·전송 경로를 다시 확인하며 링크 공유·자동 업로드를 기본값으로 두지 않는다. 취소는 원 기록을 삭제하지 않는다. 외부로 이미 전달한 파일의 회수/삭제를 보장하지 않는다. 제작자에게 보내지 않아도 업무 수행·성장·승격을 완료할 수 있다.

## 8. 뷰어·도구·인젝션·확장 보안

모든 업로드·웹페이지·도구 결과·문서 내부 지시는 신뢰하지 않는 업무 데이터다. 사용자 허용 범위·시스템 정책·모델/도구 목록·평가 기준·승인 권한으로 승격하지 않는다. 새 파일·링크/메모리·렌즈 출처가 실행 지시를 포함해도 같은 경계를 적용한다. 모델 프롬프트의 경고문만으로 이 격리를 달성했다고 하지 않는다.

- 에이전트용 자동화 브라우저는 worker 소유 격리 프로필이며 사용자의 DeepTwin 브라우저나 일반 브라우저 쿠키·기록·클립보드·확장기능을 자동 가져오지 않는다. 기본 공개 웹 읽기는 제품 UI/API origin·loopback·사설망·클라우드 metadata·호스트 파일/권한 밖 목적지를 차단한다. 실제 대상 URL의 redirect·해석 결과도 검증한다. 필요한 인증 사이트/추가 범위는 명시 grant와 독립 세션으로 확장한다.
- 모델은 도구 ID와 타입이 정해진 인자를 제안할 수 있지만 실행 직전에 host가 권한·현재 버전·목적지·입력/출력 크기·시간·예산을 검사한다. 임의 command 문자열이나 다운로드 코드를 그대로 실행하지 않는다. PDF/표 렌더링은 검증된 문서/데이터 스키마를 입력으로 받는다.
- HTML/Markdown/SVG는 script·이벤트 handler·외부 리소스·위험 URL을 제거/차단한 별도 표시물로 렌더링한다. 다운로드 원본의 바이트와 파생 미리보기를 구별한다. 렌더러는 업무 vault 전체·비밀·네트워크에 접근하지 못하는 제한 프로세스/출처에서 실행한다.
- PDF/DOCX/이미지 parser와 변환기는 고정 버전, 입력 크기/시간/메모리 제한, 인스턴스 소유 임시경로, archive 확장 한도·경로 검사로 보호한다. 원본 링크/매크로·첨부 실행·수식 외부 연결은 허용하지 않는다. 제한만으로 parser 취약점 전체를 막았다고 주장하지 않는다.
- 미리보기 실패는 원형 파일과 읽기 한계를 남기며 자동 텍스트 평탄화로 성공 처리하지 않는다. 다운로드·원본 열기에도 객체 권한과 안전한 attachment 처리를 적용한다.
- 확장은 네 trust tier로 나눈다. (A) 저장소/비밀 저장소는 배포 운영자만 고정·교체하는
  `deployment_trusted` 핵심 어댑터, (B) 제공자/모델 런타임/도구/산출물 코덱/실행형 평가자/
  내보내기 connector는 broker 격리·capability 기반 `runtime_worker`, (C) 실행 코드를 포함하지
  않는 렌즈/평가 definition은 schema 검증형 `definition_package`, (D) 공식 구독 인증 상태와 전용
  provider egress를 소유하는 built-in provider extension은 `managed_provider_runner`다. D는 자체
  auth volume만 가지며 Docker/배포 권한, DeepTwin credential vault, work DB/artifact mount가 없고
  일반 runtime extension보다 넓은 ambient 권한을 얻지 않는다.
- 공통 worker envelope는 인증·크기·deadline·cancel·참조를 운반할 뿐 의미 SPI가 아니다.
  data-model §3.1과 runtime-v1 §6의 닫힌 kind/artifact/port/trust/staging 행렬, 코어 소유 base
  operation/schema/effect/idempotency/outcome/artifact 의미와 `extension-ports-v1`의 44개
  config/request/result/error schema가 우선한다. SDK는 manifest/refinement만 저작하며 코어 포트를
  저작하지 않는다. 확장 schema가 required field/enum/bound 또는 이 의미·authority를 바꾸면 검증 실패다.
- 실행형 확장은 배포 운영자가 exact `ExtensionServiceDescriptor`의 OCI service로 staging한다.
  제품은 immutable request를 내고 signed receipt와 실제 handshake/qualification을 검증할 수만
  있으며 image/code download, Docker socket, container lifecycle, host-path·post-start·unmanifested
  mount, core image rebuild를 수행하지 않는다. descriptor/request에 고정된 전용 socket/named-
  volume mount의 service 생성은 외부 운영자만 수행한다. code-free definition만 authenticated owner가 제한된 크기/schema로 가져올 수
  있다. 인터넷에서 받은 SKILL.md/플러그인 코드/업로드 문서를 자동 설치·활성화하지 않는다.
  개발 도구에 설치된 스킬과 최종 제품 확장은 별개다.
- verified installation은 qualification/binding과 별도다. 만료·runtime/framework/platform/API/
  schema/port/capability 변화는 해당 qualification과 binding만 중지하고 동일 verified bytes의 새
  qualification을 허용한다. 설치/qualification/binding head·history·public event는 DB/CAS에
  원자 보존하고 startup reconcile 전 dispatch하지 않는다. installation head는 extension identity,
  qualification head는 installation digest+qualification-context fingerprint, binding head는 exact
  five-field `BindingSlotKeyV1`와 그 canonical digest로 각각 key한다. Config/record/head/command/
  result/event가 같은 object+digest를 사용하며 다른 port version/slot/selector는 공존하고 exact
  동일 key의 후보만 경쟁한다.
  binding supersession/disable/rollback은 exact key와 expected head를 요구하고 이전 계보를 남기며
  현재 자격·grant·service reachability를 재검사한다. Supersession/disable은 displaced
  target의 rollback-retention head를 원자 생성하고, rollback은 retained head를 원자
  consume한다. Owner는 exact-head release로 이력을 유지한 채 rollback 적격성만
  해제할 수 있으며, released target은 rollback이 거절된다.
- 제품 `/extensions` API와 `설정 > 확장`은 code-free import, 상태/근거 조회, 이미 staged+qualified
  된 runtime adapter의 scope binding/disable/rollback만 허용한다. `deployment_trusted` port와
  executable staging은 operator-only다. export sink는 정확한 대상에 대한 별도 전송 승인을
  요구하고, prepare/transmit의 동결 artifact 목록 bytes는 shared store 없이 bounded broker
  stream으로만 전달한다. 같은 포트/scope/purpose의 행도 logical slot/selector별로 분리하여 공존/경쟁 상태와
  old/new candidate를 보여 준다.
- 사용자 대안·진단·미승격 지식·철학 해석·봉인 평가 자료는 운영 에이전트의 검색/도구 projection에서 제외한다. UI가 같은 화면에서 연결해 보여 주는 것과 모델이 읽을 수 있는 것은 다르다.

## 9. 첫 웹 릴리스 증거와 공급망 한계

로컬 개발 서버, 재현 가능한 소스/서버/worker 배포물, 실제 빈 호스트 배포, 브라우저 호환,
artifact 체크섬·SBOM·provenance/서명, 실제 모델/도구 실행, 사용자 수용, DeepTwin 효과를 각각
보고한다. 어느 하나의 통과를 나머지 완료로 승계하지 않는다. 과거 macOS 앱 서명/공증 연구는
ADR-009 이전의 역사 자료이며 웹 릴리스 합격 증거가 아니다.

외부 artifact/image 서명 권한이 없으면 체크섬·SBOM·재현 시험까지 구별해 보고한다. 이를 공개
배포 적격성으로 표시하거나 검증을 끈 개발 설정으로 시험을 통과시키지 않는다. 새 registry,
서명 서비스, 유료 계정, 공개 다운로드/푸시는 기존 개발 자동화 권한으로 추정하지 않는다.

| OPS 수용 ID | 실제로 확보할 증거 | 명세/기존 수용 연결 |
| --- | --- | --- |
| OPS-AC01 | 빈 지원 호스트의 공식 배포→최초 소유자 설정→브라우저 연결/입력, 첫 관찰 사건과 실패·취소·재개. 일반 사용자의 CLI/개발 도구 조작 없음 | FR-001/002/027/030; AC-001/007/008 |
| OPS-AC02 | Claude API와 Codex 구독 각각 전체 여정, 선택 Codex API; credential vault 잠김/키 교체/잔액 미확인/한도에서 유출·자동 과금 전환 없음 | FR-010–012/029; 최신 Claude 정정·AC-020/021/035 |
| OPS-AC03 | 실제 원형 PDF/표/문서/이미지·브라우저 관찰을 생산→전달→소비→부분 대안→재평가까지 연결. 미지원·미리보기 손실 별도 | FR-013–017/022; AC-003/028/036 |
| OPS-AC04 | 각 필수 event 범주·private 근거·권한, 숨은 추론/secret canary 부재. 같은 이름·다른 vault·오래된 ref의 접근 거절 | FR-017/020/027/029; AC-015/021/032 |
| OPS-AC05 | 디스크 부족·DB 쓰기 실패·worker crash·취소/재시작/외부 결과 미확인에서 중복 dispatch/성공 위장 없음, 알려진 결손 보존 | FR-013/014/024/026/030; AC-006/011/037 |
| OPS-AC06 | cache/diagnostics만 설정대로 정리되고 원본·핵심 기록 자동 삭제 없음. 명시 삭제의 범위·tombstone·파생/승인 영향 보고 | FR-027/029/030; AC-007/010/032 |
| OPS-AC07 | 암호화 백업·빈 staging 복원·해시/참조/버전 검사, 키 부재·손상·마이그레이션 실패·새 데이터 생성 후 rollback에서 자료 보존 | FR-024/026/029/030; AC-006/011 |
| OPS-AC08 | 범위 선택→실제 preview→raw/redacted/metadata manifest·결손→검사된 파일. PDF 가림 원문 잔존·archive 경로 이탈·비밀 유출 거절, 전송 0회 | FR-027–029; AC-007/015/032 |
| OPS-AC09 | 악성 HTML/SVG/PDF/DOCX·zip bomb·prompt injection·URL redirect/사설망·임의 command·미승격 자료 접근을 실제 경계에서 차단 | FR-014/017/020/029/032; AC-011/030/037 |
| OPS-AC10 | SBOM/라이선스·고정 해시·provenance/선택 서명·빈 호스트 웹 배포·업데이트/복구 증거. 없거나 실패한 항목을 명시 | FR-001/030–032; SC-001/009/010 |
| OPS-AC11 | 두 빈 호스트에서 out-of-tree tool OCI service를 exact descriptor+signed receipt로 외부 운영자가 staging하고 broker로 실제 호출. 44개 base schema의 52-operation×terminal/result-artifact 행렬과 별도 52-operation request-artifact-input 행렬(11 non-empty-capable/41 exact-empty), exact five-field BindingSlotKeyV1 object+digest roundtrip, 네 deployment arm의 금지 필드·request equality·acyclic digest를 검사. Export prepare/transmit는 각각 exact snapshot/prepared 1–256 `export_payload` 목록 bytes를 bounded broker stream으로 받고 ref-only/shared-store/changed-content 경로를 거절한다. Result role/media/omissions는 operation별 닫혀 있고 codec target-media/output-omissions와 tool output contract가 일치한다. `result.effect`만 효과 정본이며 error 중복 상태 및 표 밖 terminal/effect/outcome 조합, succeeded-external-unknown/unconfirmed, failed-unknown/retryable를 거절한다. Tool `invoke_tool` success output은 exact `{tool_call_ref,result_ref}`이고 output-level `effect_receipt_ref` 또는 alias를 값 일치 여부와 무관하게 거절하며, ToolResult artifact binding은 `result_ref` 아래 그대로 보존한다. Extra/missing/wrong-role/media/selector/hidden ref, frozen/export-list mismatch, codec/storage competing ref, widened/missing ToolDefinition profile와 four-field/cross-port/digest-mismatched slot key를 거절한다. A stage→B replace→owner release of every A rollback-retention head→A superseded-retirement 뒤 B current binding/installation head와 dispatch는 유지되고 A retirement head만 전진하며 A rollback은 거절되어야 한다. Active-environment ref가 없는 conformance slot에서 B disable→B retention release→dependency-zero→current-uninstall→exact tombstone→next-revision C stage→handshake/qualification/binding/dispatch를 완주하고 A/B 부활은 없어야 한다. Non-ancestor, 남은 binding/rollback/environment dependency, stale binding/retention/deployment head, repeated release, released-target rollback, failure/unknown/cancel/replay/crash도 fail closed. Descriptor/request 전용 mount 외 제품 주도 mount/download/Docker/core rebuild 0회; 재시작/requalification/slot 공존·rollback과 Settings 표시, portable HTTPS actual-client parity 및 HTTP loopback bearer non-exposure 일치 | FR-001/030/032; ADR-014; UX-AC11; R16 |

본 계약 교정에서는 제품 배포·credential vault·실계정·유료 호출·artifact 서명·공개·테스트를
실행하지 않았다. 기존 네이티브 구현/시험을 웹 배포 증거로 재분류하지 않는다.
