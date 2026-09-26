# 인스턴스 운영자 배포·백업 안내 (초안)

작성일: 2026-09-23 · 갱신: 2026-09-25 · 대상: DeepTwin 인스턴스를 배포·유지하는 운영자 · 상태:
**초안, 배포 적격 아님**

이 문서는 인스턴스 운영자를 위한 것이다. 일반 사용자의 업무는 브라우저 UI에서만 이뤄지며
([브라우저 사용 안내](browser-user-guide.md)), 여기 나오는 Docker/Compose/Portainer 조작과
`python -m app.…` 운영 도구는 사용자 제품 흐름이 아니다. 정본 계약은
`specs/001-autonomous-release/contracts/operations.md`(OPS-002)와 `contracts/api.md`다. 이 문서와
계약이 다르면 계약이 우선한다.

> 현재 상태: `deploy/compose.yaml`은 `"status": "candidate_not_runtime_qualified"`인
> **골격(skeleton)** 이다. 모든 이미지 변수는 T081이 만들 정확한 `@sha256:` 참조를 요구하는데
> 그 최종 이미지는 아직 없다. 따라서 이 저장소만으로 실행 가능한 배포를 할 수는 없다. 두 지원
> 프로필(`local-no-terminal-v1`, `portable-compose-v1`)의 새 호스트 시험(T083)도 아직 수행되지
> 않았다. 아래에 적힌 운영 도구와 worker 프로세스의 근거는 모두 시험이 소유한 임시 인스턴스에서의
> 합성 근거이며, 실제 Compose·Portainer·HTTPS 배포에서 실행된 적은 없다.

## 1. 배포 권한의 경계

DeepTwin 제품(웹 control-plane)은 **컨테이너·이미지·볼륨·Docker socket을 제어하지 않는다.**

- 어떤 DeepTwin 컨테이너에도 Docker socket을 mount하지 않는다.
- 제품은 image/code/model을 내려받거나 설치하지 않는다. 필요한 구성요소가 빠져 있으면 제품은
  정확한 배포 요청(`DeploymentRequest`)을 만들고, 외부 운영면이 수행한 뒤 서명된 receipt를
  돌려준다. 제품은 그 receipt와 실제 handshake를 **검증할 뿐** 다운로드·교체를 자기가 했다고
  표시하지 않는다(`operations.md` §2, `api.md` deployment routes).
- worker coordinator는 이미 배포된 장기 실행 서비스와 인증 handshake만 한다. 컨테이너 재시작은
  배포 runtime/운영자의 몫이다(`operations.md` §6).
- Portainer는 Docker Engine 전체를 관리하는 **호스트 관리자 권한**이다. DeepTwin보다 낮은
  권한의 플러그인처럼 다루지 않는다.
- 실행형 제3자 확장은 운영자가 정확한 `ExtensionServiceDescriptor`의 OCI service로 외부에서
  staging한다. 자세한 경계는 [surface-boundaries.md](surface-boundaries.md) §C를 본다.

제품 API에서 운영자와 연결되는 부분은 다음뿐이며, 모두 브라우저 소유자 세션을 요구한다.

- `deployment-prepare-v1`: 배포 요청과 제공자 배포 요청의 준비·취소·조회, receipt 가져오기, 소비
  (`deployment.manage`/`deployment.read`).
- `platform-update-v1`: `GET|HEAD /api/v1/platform/update`, 업데이트 상태의 **읽기 전용** 안내
  (`deployment.read`). 업데이트나 소유자 복구 receipt를 브라우저에서 받는 경로는 없다(§7).

## 2. 두 배포 프로필 (계약상 목표)

| 프로필 | 호스트 | 진입점 | 상태 |
| --- | --- | --- | --- |
| `local-no-terminal-v1` | macOS arm64, Docker Desktop + Portainer CE | loopback HTTP, 생성된 인스턴스 전용 origin/base path | 미시험 |
| `portable-compose-v1` | Linux x86_64, Docker Engine/Compose | release-pinned edge가 운영자 TLS secret으로 HTTPS 종료 | 미시험 |

두 프로필은 같은 서비스·볼륨·네트워크·Compose schema를 쓰고 edge 프로필은 정확히 하나만
선택해야 한다. Compose profiles만으로는 둘 다 선택하는 것을 막지 못하므로 배포 검증이 이를
거절해야 한다는 점이 골격의 `open_gates`에 열린 과제로 적혀 있다.

### 2.1 최초 소유자 설정 준비 도우미

`deploy/bootstrap/index.html`은 네트워크에 연결하지 않는 정적 보조 페이지다. 배포 유형(로컬 /
HTTPS 서버)과 주소를 확인하고, 브라우저 안에서 최초 설정 값을 만든다. 결과는 두 가지다.

- 배포 설정 블록(비밀이 아닌 verifier 포함): 배포 구성에 넣는다.
- 일회용 capability: **한 번만 표시**되며, 배포 구성에 넣지 말고 같은 주소의 DeepTwin 시작
  화면에 직접 입력한다.

소유자 복구(§6)에서도 운영자는 이 도우미로 새 capability를 오프라인에서 만들고, 그 verifier만
복구 도구에 넘긴다. 이 도우미는 `deploy/tests/bootstrap-helper.test.mjs`로 시험되지만 새 호스트
배포 적격성은 검증되지 않았다.

### 2.2 control-plane 입력

서버 main(`python -m app.server`)의 **필수** 운영 입력은 `--data-dir`, `--deployment-config`
(`origin_profile`, `verifier_b64u`, `recovery_epoch`를 담은 8 KiB 이하 JSON),
`--session-root-dir`, `--expected-uid`, `--expected-gid`다. 구성이나 root가 없으면 시작 자체가
실패한다. 선택 입력은 각 격리 worker의 attachment 구성과 복구 trust set이다.

| 옵션 | 내용 |
| --- | --- |
| `--recovery-trust-set` | 소유자 복구 뒤 첫 시작에 쓰는 공개 `deployment-public-trust-set-v2` (§6) |
| `--credential-gateway-config` | `deeptwin-credential-gateway-attachment-v1` (자격증명 게이트웨이, §4) |
| `--document-worker-config` | `deeptwin-document-worker-attachment-v1` (문서 worker) |
| `--backup-worker-config` | `deeptwin-backup-crypto-attachment-v1` (backup-crypto worker) |
| `--browser-worker-config` | `deeptwin-browser-control-attachment-v1` (browser worker와 fetch 서비스) |

선택 입력을 주지 않으면 해당 기능은 브라우저에서 "연결되어 있지 않음"으로 정직하게 표시된다
(예: 백업은 `not_configured`, PDF/DOCX는 `codec_required`).

내부 listener는 `0.0.0.0:8080`, worker 1개, reload 끔, proxy header 신뢰 안 함, access log
끔으로 고정된다. `Forwarded`/`X-Forwarded-*` 헤더가 있는 요청은 거절된다.

**직접 연결(direct-adapter) Claude 프로필.** 현재 main은 코드 소유 실행기
(`ClaudeRunExecutor`)를 연결한다. 소유자가 브라우저의 "Claude 연결"에 입력한 API 키는
**control-plane 프로세스의 메모리에만** 있고, 모델 호출도 같은 프로세스에서 공식 SDK adapter로
나간다. 운영자는 비밀이 아닌 한도만 환경 변수로 정한다: `DEEPTWIN_LIVE_MAX_MODEL_CALLS`(기본 10),
`DEEPTWIN_LIVE_MAX_OUTPUT_TOKENS`(기본 512). 이것은 소유자가 승인한 개발 단계 프로필이며 릴리스
격리 경계가 아니다(`evidence/claude-direct-live-path-2026-09-24.md`). 릴리스 경로인 자격증명
게이트웨이 경유 전송(T090/T087)은 아직 실행에 쓰이지 않는다.

## 3. 초기화 작업(init job)의 규칙

root/key를 만드는 작업은 장기 실행 서비스와 분리된 일회성 작업이며 배포 권한만 실행한다.
`*-root-init` 계열(`session-root-init`, `vault-init`, `backup-key-init`,
`deployment-receipt-root-init` 등)은 공통으로 다음 세 경우만 가진다(`operations.md` §2).

| 대상 상태 | 동작 |
| --- | --- |
| **없음(absent)** 또는 빈 소유 디렉터리 | 값을 검증한 뒤 `O_EXCL`로 파일을 만들고 파일과 디렉터리를 `fsync` |
| **정확히 유효한 기존 상태** | 읽고 검증만 하는 no-op. 쓰기 0회, 생성기 호출 없음 |
| **그 밖의 모든 상태**(부분 쌍, 손상·외부 manifest, 해시 불일치, 느슨한 권한, symlink/hardlink, 잘못된 소유권) | **아무것도 바꾸지 않고 실패** |

이 규칙 때문에 stack 갱신으로 init 작업이 다시 돌아도 키가 바뀌지 않는다. 손상된 상태를 자동
"복구"하지 않는 것은 의도된 동작이다. 조용히 새 키를 만들면 이전 키로 암호화된 모든 백업이
고아가 되기 때문이다. 이런 실패는 운영자가 원인을 확인하고 별도 절차로 다뤄야 한다.

구현 위치:

- `app/operations/session_root.py` `initialize_session_root`: `root.key`(32바이트, 0400)와
  `manifest.json`(0400). 소유자 복구는 `advance_session_root`로 새 세대를 옆에 추가한다(§6).
- `app/operations/credential_root_init.py` `initialize_credential_root`: credential root와
  records 디렉터리를 쌍으로 초기화. 게이트웨이 프로세스는 vault를 만들거나 고치지 않는다.
- `app/operations/backup_key.py` `initialize_backup_key`: `identity.age`(0600)와
  `manifest.json`(`key_mode: instance_backup_key`, `encryption_profile_ref: age-x25519-v1`,
  public recipient, identity SHA-256). secret identity는 결과·오류·로그에 나오지 않는다.
- 배포 요청·receipt·제공자 소스·설치 릴리스 소스의 UID0 일회성 초기화:
  `deployment_prepare_init.py`, `deployment_receipt_public_init.py`,
  `deployment_provider_source_init.py`, `installation_release_init.py`.
- IPC pair root: `app/workers/ipc_root.py` `initialize_pair_root`(root 소유 IPC 초기화기만
  generation을 만들고 교체한다. 응답자 프로세스는 만들지 못한다).

주의: 현재 Compose 골격에는 `state-root-init`와 `ipc-root-init` 두 작업만 선언되어 있다.
`ipc-root-init`의 IPC boot secret은 위 규칙과 달리 **부팅마다 새로 만들거나 덮어쓰는**
(`generate_or_overwrite_per_boot`, `deploy/security/service-ids.json`) 값이다. `backup-key-init`,
`session-root-init`, `vault-init`은 코드와 시험은 있으나 골격에 서비스로 아직 선언되어 있지 않다.

## 4. 격리 worker 프로세스

아래 프로세스는 각자 고정된 신원으로 실행되고, control-plane과는 pair마다 따로 있는 IPC root
(`/run/deeptwin/ipc/<pair>`) 위의 검증된 UDS·`SO_PEERCRED`·boot-secret HMAC handshake·frame별
MAC으로만 대화한다. 한 연결에 요청 하나, 양방향 모두 크기가 제한된다. 신원과 pair 값은
`deploy/security/service-ids.json`에 있다.

| 프로세스 | 신원 | pair (group) | argv | 네트워크 |
| --- | --- | --- | --- | --- |
| `python -m app.workers.credential_gateway_main` | `provider` 20103 | `cp-provider` (21101) | `--service-config=` (`deeptwin-credential-gateway-service-v1`: `vault_id`, `root_directory`, `records_directory`), `--attachment-config=` | Compose상 `provider-egress` |
| `python -m app.workers.document_worker_main` | `document` 20106 | `cp-document` (21105) | `--attachment-config=` | `network_mode: none` |
| `python -m app.workers.backup_crypto_main` | `backup` 20111 | `cp-backup` (21109) | `--service-config=` (`deeptwin-backup-crypto-service-v1`: `key_root`, `age_root`), `--attachment-config=` | 프로세스 자체가 AF_UNIX 외 소켓을 거절 |
| `python -m app.workers.browser_worker_main` | `browser` 20105 | `cp-browser` (21104, 응답자), `browser-fetch` (21110, 요청자) | `--attachment-config=` | loopback 외 인터페이스가 있으면 시작 거절(`network_present`) |
| `python -m app.workers.fetch_worker_main` | `fetch` 20104 | `cp-fetch` (21102), `browser-fetch` (21110) | `--attachment-config=` | egress broker를 돌리는 유일한 프로세스(`fetch-egress`) |

공통 동작: argv나 구성이 정확한 모양이 아니면 종료 코드 2, listener를 열지 못하면 1, 요청된
정지 뒤 0이다. generation이 바뀌거나 listener 무결성이 깨지면 종료 코드 1로 끝나 supervisor가
재시작하게 한다. 로그는 stderr의 한 줄 JSON이며 닫힌 어휘만 쓰고 문서 바이트·URL·본문·ID·비밀을
담지 않는다.

- **자격증명 게이트웨이**는 암호화된 vault를 열고, 소유자의 키 저장·교체·삭제, 모델 목록 새로 고침,
  모델 선택을 처리한다. 제공자 전송 매니페스트의 검증(qualification)을 채택하기 전에는 저장된 키로
  어떤 요청도 보내지 않는다(`transport_unqualified`).
- **문서 worker**는 PDF/DOCX 읽기(자료 읽기), 산출물 미리보기(PDF 쪽 이미지, DOCX 텍스트), 내보내기의
  PDF 비밀 검사를 맡는다. parser는 listener를 연 뒤 이 프로세스 안에서만 import된다.
- **browser worker**는 요청마다 새 Chromium 세션을 쓰며 JavaScript는 항상 꺼져 있다. 바깥으로 나가는
  유일한 길은 `browser-fetch`를 통한 fetch 서비스이고, fetch 서비스는 소유자가 설정 화면에서 만든
  브라우저 접근 허가의 주소·수신 호스트·값 투영만 허용한다. 다만 지원 서버의 제품 실행기는 아직
  브라우저 도구 정의를 등록하지 않으므로, 소유자의 실행이 브라우저 도구를 쓰는 제품 경로는 아직 없다
  (controlled E2E만 있다, `evidence/browser-grants-t043-2026-09-25.md`).
- **backup-crypto worker**는 §5.6을 본다.

이 프로세스들을 Compose 서비스로 연결하는 일(이미지, `command`, 볼륨 mount, attachment 파일)은
아직 되어 있지 않다(T081). 골격의 해당 서비스에는 `command`가 없다.

## 5. 백업과 복원 (age 1.3.2)

### 5.1 암호화 도구

백업 암호화는 age 1.3.2의 `age`/`age-keygen`만 사용한다. 정확한 archive·member digest,
Sigsum 증명과 license 입력은 `deploy/manifests/age-1.3.2.json`과
`deploy/manifests/age-1.3.2-runtime-licenses.json`에 고정되어 있다. 실행 시
`app/workers/backup_crypto.py`의 `AgeRuntime.open`이 두 실행 파일의 member digest와 `v1.3.2`
버전 출력을 확인한다.

- native X25519 recipient(`age1…`)와 identity(`AGE-SECRET-KEY-1…`)만 허용한다. SSH 키,
  plugin/PQ/tag 값, 대문자·짧은 키, flag 모양 값, 주석 줄은 실행 전에 거절한다.
- argv는 고정이고 환경 변수는 비어 있다(PATH 없음, plugin 탐색 없음).
- identity는 소유한 pipe descriptor로만 전달되고 argv·파일·환경에 나타나지 않는다.
- 이것은 upstream 바이너리의 기능 제거가 아니라 **현재 서비스 경계에서의 도달 불가능성**
  보장이다.

### 5.2 키 모드

| 모드 | recipient | host/볼륨 상실 후 복원 |
| --- | --- | --- |
| `instance_backup_key` | `backup-key-init`이 만든 별도 `backup-key` 볼륨의 키 | **불가** (receipt에 `recoverable_after_host_or_volume_loss=false`) |
| `portable_recovery` | 사용자가 따로 보관하는 recipient + 한 번만 쓰고 지우는 `OneShotIdentity` | 가능 (복구 비밀을 사용자가 보관할 때) |

`backup-key` 볼륨에만 있는 키를 host/볼륨 상실 대비 수단으로 안내하지 않는다. 복구 비밀은
백업 안에 넣거나 로그로 남기지 않는다.

### 5.3 백업 과정

`app/operations/backup.py`는 `backup_pending → snapshotting → encrypting → verify_restore →
ready`(실패 시 `failed`와 이유)로 진행한다. SQLite online backup으로 snapshot을 뜨고, 그 snapshot이
등록한 모든 원본 바이트(`domain-cas`의 content-addressed 파일)를 digest·크기 검증 후 각각 archive
member로 담으며(원본이 없거나 digest가 다르면 백업 전체 거절), 모든 테이블을 포함/제외 범주로 닫힌
분류에 따라 처리한다(분류되지 않은 테이블이 있으면 백업 전체 거절). 인증 세션, 대기 중인 대화 확인
요청(challenge), provider 연결, 배포 receipt 비공개 상태(업데이트 lifecycle 포함) 같은 권한 자료는
제외된다. 소유자가 지운 원본과 그 원본에서 읽은 글자는 이후 백업에 없다. 암호화한 뒤 **전체를 다시
복호화해 검증**한 다음에야 `ready`가 된다. 외부 `BackupReceipt`는 암호문 SHA-256/크기와 복원 검증
참조를 담으며, 내부 manifest는 자기 해시를 담지 않는다.

### 5.4 복원과 `restored_review`

- 복원 대상은 **비어 있는 staging 디렉터리**여야 한다. 활성 vault나 사용 중인 디렉터리로의 복원은
  거절한다.
- 복호화 전에 암호문이 외부 receipt와 일치해야 한다. 이후 age 인증, archive member와 크기, 원본
  바이트의 content address와 등록 목록의 정확한 일치, manifest 해시, schema 버전, 제외 범주 부재,
  vault identity, 모든 기록의 계보를 확인한다.
- 성공하면 `restored_review.json` 표시를 남긴다. 복원된 인스턴스는 새 owner bootstrap 뒤에도
  **모든 dispatch가 차단된 `restored_review`** 로 열리며, 새 소유자가 연결·service client를
  다시 만들고 정확한 환경을 검토·활성화해야 한다. 과거 credential/session/challenge는 재사용하지
  않는다.
- 실패하면 staging 디렉터리는 비어 있는 채로 남는다.

### 5.5 근거

`evidence/backup-age-t070-2026-09-23.md`: 검증된 age 디렉터리를 가리키는
`DEEPTWIN_AGE_RUNTIME_ROOT`와 함께 `app/tests/test_backup.py` 통과(Linux x86_64). 그 변수가 없으면
실행 파일이 필요한 경우는 이유를 밝히고 건너뛴다. CI에는 age 바이너리 공급이 없어 그곳에서는
건너뛴다. `deploy/tests/age_runtime_canary.py`는 uid 65534, 네트워크 namespace 안에서 통과했다.

### 5.6 backup-crypto worker와 control-plane의 분리

- age를 부르는 쪽은 **별도 프로세스** `python -m app.workers.backup_crypto_main`이다(§4의 표).
- worker는 네트워크 소켓을 열지 않는다. 시작하자마자 audit hook이 AF_UNIX 외 소켓 생성·bind·
  connect·이름 조회와, 잠긴 `age`/`age-keygen` 외의 실행을 거절한다. Compose의 `network_mode: none`과
  별개로 프로세스 자체에서 성립한다.
- `key_root`는 `backup-key-init`이 만든 `identity.age`와 `manifest.json` **두 파일만** 있어야 하며,
  읽기 전용 mount이거나 쓰기 권한이 전혀 없는 디렉터리(0500)여야 한다. 그 밖의 내용(예: provider
  credential root나 records)이 있거나 쓸 수 있으면 시작을 거절한다(종료 코드 2). 볼륨이 없으면
  시작은 하되 키가 필요한 모든 요청에 `key_unavailable`로 답한다.
- control-plane(`app.server --backup-worker-config=<attachment>`)은 snapshot·미리보기·archive·
  복원 검증만 하고, archive/암호문을 **typed stream**(요청, 32 KiB 이하 chunk, 크기·SHA-256을 묶는 end
  frame)으로 주고받는다. 키 핸들이나 키 경로를 받지 않으며, 키 볼륨은 control 신원이 읽을 수 없다.
- 브라우저의 설정 화면(백업·보존)에서 소유자는 `instance_backup_key` 백업을 만들고(실제 포함 내용 미리보기와 그
  digest에 묶인 동의), 암호화된 백업과 외부 영수증을 내려받고, 영수증+백업을 올려 `restored_review`
  스테이징 복원을 할 수 있다. 복원은 두 키 모드를 모두 받으며, `portable_recovery`는 소유자가 따로
  보관한 identity를 한 번만 받아 worker가 쓰고 지운다. 업로드는 64 MiB까지다. 브라우저에서
  `portable_recovery` 백업을 **만드는** 경로는 없다.
- 보존 화면에서 소유자는 미리보기와 동의를 거쳐 오래된 백업(가장 최근 것은 항상 남김)과 스테이징된
  복원본을 정리할 수 있다. 자동 삭제는 없다.

## 6. 소유자 복구 (control-plane 정지 상태에서만)

소유자가 비밀번호를 잃는 등 브라우저에서 계속할 수 없을 때, 운영자는 control-plane을 **멈춘 상태에서**
`python -m app.operations.deployment_control`을 쓴다. 이 도구는 data 디렉터리의 serving lock을 잡으므로
서버가 돌고 있으면 `busy`로 거절한다.

공통 옵션: `--data-dir`, `--session-root-dir`, `--deployment-config`, `--work-dir`,
`--expected-uid`, `--expected-gid`.

1. 새 일회용 capability를 오프라인에서 만든다(§2.1). 도구에는 **비밀이 아닌 verifier만** 넘긴다.
2. `prepare --new-verifier V [--ttl-seconds S]`: 현재 epoch N(구성·session root·DB가 모두 같아야 함)을
   읽고 새 nonce로 `owner_recovery` 요청을 봉인해 `W/requests/<request_id>.json`에 쓴다.
3. 복구 trust set을 가진 쪽이 이 요청에 서명한다. **서명은 이 도구 밖의 일이며**, 실제 키로 서명하는
   운영자 recovery adapter는 아직 없다(시험에는 시험용 서명기만 있다).
4. `import --receipt R --trust-set T`: receipt를 요청과 `deployment-public-trust-set-v2`로 검증하고,
   session root를 N+1로 올리고, 배포 구성을 epoch N+1과 새 verifier로 다시 쓴다. 같은 receipt로 다시
   실행하면 중간에 끊긴 import를 마친다.
5. control-plane을 `--recovery-trust-set`과 함께 시작한다. 제한된 시작이 한 트랜잭션으로 정리한다:
   모든 인증 수단·브라우저 세션·서비스 클라이언트를 끝내고, 쓰지 않은 대화 확인 요청과 결정되지 않은
   게이트 승인을 만료시키고, 열린 실행 동의를 철회한다. 이전 기록과 소유자 actor는 그대로 남는다.
6. 소유자는 시작 화면의 "소유자 다시 설정"에서 새 capability로 다시 설정한다.

`status`는 현재 epoch를 읽고, `cancel`은 아직 import하지 않은 요청을 끝낸다. 모든 거절은 비밀 없는
닫힌 코드의 한 줄 JSON이며 종료 코드 2다. 근거: `evidence/owner-recovery-reconcile-t025-2026-09-25.md`
(시험 소유 인스턴스, 실제 배포 복구 없음).

`python -m app.operations.recovery import-owner-recovery`는 같은 import를 운영자 입력 검사(아래 §7)와
함께 감싼 것이며, 업데이트가 `migrating`인 동안에는 거절한다.

## 7. 웹 릴리스 업데이트 (control-plane 정지 상태에서만)

`python -m app.operations.updates`는 업데이트의 제품 쪽 절반이다: 정확한 digest에 묶인 요청을 봉인하고
돌아온 receipt를 검증한다. 이미지를 받고 컨테이너를 교체하는 권한 있는 일은 운영자/Portainer 몫이다.
이 도구는 아무것도 내려받거나 설치하지 않고, 패키지 관리자나 Docker를 부르지 않는다. 공통 옵션은 §6과
같다.

| 하위 명령 | 하는 일 |
| --- | --- |
| `status` | 업데이트 안내(현재 릴리스, 진행 중인 요청, 게이트 백업, 최근 거절, 다음 단계)를 출력 |
| `prepare --target-manifest M --image-lock L [--ttl-seconds S]` | 대상 웹 릴리스 매니페스트와 그것이 이름 짓는 이미지 잠금 목록에 묶인 `release_update` 요청을 봉인 |
| `backup --backup-worker-config C` | backup-crypto 포트로 **게이트 백업**을 만들고, receipt와 암호문을 대조하고, 다시 복호화해 보관된 DB의 상태 digest가 지금과 같을 때만 `backup_verified`로 기록 |
| `cancel` | `prepared`/`backup_verified` 요청을 끝냄 |
| `migrate --receipt R --trust-set T [--backup-worker-config C]` | 서명된 `deployment-update-receipt-v1`을 검증하고, 게이트·구성 요소 handshake·epoch를 다시 확인한 뒤 한 트랜잭션으로 코드 소유 migration을 적용 |

- lifecycle은 `prepared → backup_verified → migrating → completed`(취소 `cancelled`, 실패 `failed`)이며
  vault DB 안의 revision CAS로 기록된다. 이 lifecycle은 백업에 담기지 않는다.
- 백업 뒤에 새 자료가 기록되면 `backup_stale`로 거절하고 새 게이트 백업을 요구한다(백업과 migrate 사이에
  서버를 다시 시작해도 그렇게 된다). 게이트 암호문이 없거나 바뀌면 `backup_missing`, 필요한 구성 요소가
  응답하지 않거나 버전이 다르면 `component_unavailable`/`component_version_mismatch`로 아무것도 바꾸지
  않는다. migration 단계가 실패하면 되돌리고 `failed`로 끝난다(자료는 백업 시점 그대로).
- 업데이트가 `migrating`인 동안에는 control-plane 시작이 거절되며, 같은 receipt의 `migrate`만 이를 마친다.
- 모든 receipt·trust set·매니페스트·이미지 잠금 입력은 **data 디렉터리와 session root 밖**의, 운영자
  소유이고 그룹/전체 쓰기 권한이 없는 일반 파일이어야 한다(symlink 거절). 브라우저가 올린 파일은 모두
  data 디렉터리 안에 떨어지므로 배포 권한이 될 수 없다.
- `python -m app.operations.recovery guidance`는 같은 안내를 출력하고,
  `restore-update-backup --staging-dir S --backup-worker-config C [--request-id I]
  [--acknowledge-new-data-after-backup DIGEST]`는 게이트 백업을 빈 staging 디렉터리에
  `restored_review`로 복원한다. 활성 vault에 백업 뒤 자료가 있으면, 버려질 지금 상태의 digest를 운영자가
  정확히 적지 않는 한 거절한다.
- 소유자는 설정 화면의 "업데이트·복구"에서 같은 안내를 읽기만 한다.

근거: `evidence/update-recovery-t072-2026-09-25.md` (시험 소유 입력, 실제 age 1.3.2). 업데이트할
**실제 웹 릴리스는 아직 없다**: 매니페스트·이미지 잠금 형식은 정의·검사되지만 T081이 만들 릴리스가 아직
그것을 게시하지 않는다.

## 8. 아직 연결되지 않은 것

- **Compose 배포 연결.** worker 프로세스와 채널은 구현·시험되었지만(§4), Compose 골격의 해당 서비스에는
  이미지·명령이 없고 `backup-key` 볼륨의 읽기 전용 mount, attachment/서비스 구성 파일, 자격증명 vault
  볼륨도 연결되지 않았다(T081). browser worker 이미지 잠금(Node + `playwright-core`)과 이 worker가 쓰는
  Python + chromium-headless-shell 구성도 아직 맞춰지지 않았다(T081/T089).
- 최종 이미지, 두 프로필의 새 호스트 시험, TLS edge, Linux UID/network·seccomp·read-only root 자격
  검증(T079/T081/T083).
- 스테이징된 `restored_review` vault를 새 인스턴스로 여는 과정(새 소유자 설정, 연결 재생성, 환경
  재활성화)은 화면에서 필요한 단계로 **표시만** 하며, 활성 vault를 바꾸는 기능은 없다.
- 소유자 복구의 실제 서명 adapter와 업데이트 receipt의 전용 계약·schema, trust set을
  `deployment-verify-public` 볼륨에 고정하는 배선(T025/T072/T081).
- 예약 백업.
- 관리형 Codex 실행기(T088)와 음성 worker(T024)는 지원 서버에 연결되어 있지 않다.
- 보존 정책상 원본·핵심 기록은 자동 삭제하지 않으며, 백업도 자동 삭제하지 않는다. 사용자가 업무 화면에서
  지운 원본은 tombstone으로 남고 이후 백업에 포함되지 않지만, **삭제 전에 만든 백업에는 그 바이트가 남아
  있다**. 원본 외 기록의 삭제 화면은 아직 없다.
