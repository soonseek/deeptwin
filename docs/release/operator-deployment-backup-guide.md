# 인스턴스 운영자 배포·백업 안내 (초안)

작성일: 2026-09-23 · 대상: DeepTwin 인스턴스를 배포·유지하는 운영자 · 상태: **초안, 배포
적격 아님**

이 문서는 인스턴스 운영자를 위한 것이다. 일반 사용자의 업무는 브라우저 UI에서만 이뤄지며
([브라우저 사용 안내](browser-user-guide.md)), 여기 나오는 Docker/Compose/Portainer 조작은
사용자 제품 흐름이 아니다. 정본 계약은 `specs/001-autonomous-release/contracts/operations.md`
(OPS-002)와 `contracts/api.md`다. 이 문서와 계약이 다르면 계약이 우선한다.

> 현재 상태: `deploy/compose.yaml`은 `"status": "candidate_not_runtime_qualified"`인
> **골격(skeleton)** 이다. 모든 이미지 변수는 T081이 만들 정확한 `@sha256:` 참조를 요구하는데
> 그 최종 이미지는 아직 없다. 따라서 이 저장소만으로 실행 가능한 배포를 할 수는 없다. 두 지원
> 프로필(`local-no-terminal-v1`, `portable-compose-v1`)의 새 호스트 시험(T083)도 아직 수행되지
> 않았다.

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
  staging한다. 자세한 경계는 [surface-boundaries.md](surface-boundaries.md) §3을 본다.

제품 API에서 운영자와 연결되는 부분은 `deployment-prepare-v1` 경로(요청 준비·취소·조회,
receipt 가져오기, 소비)뿐이며 모두 브라우저 소유자 세션과 `deployment.manage`/
`deployment.read` 범위를 요구한다(`app/api/route_contributions/deployment-prepare-v1.json`).

## 2. 두 배포 프로필 (계약상 목표)

| 프로필 | 호스트 | 진입점 | 상태 |
| --- | --- | --- | --- |
| `local-no-terminal-v1` | macOS arm64, Docker Desktop + Portainer CE | loopback HTTP, 생성된 인스턴스 전용 origin/base path | 미시험 |
| `portable-compose-v1` | Linux x86_64, Docker Engine/Compose | release-pinned edge가 운영자 TLS secret으로 HTTPS 종료 | 미시험 |

두 프로필은 같은 서비스·볼륨·네트워크·Compose schema를 쓰고 edge 프로필은 정확히 하나만
선택해야 한다. Compose profiles만으로는 둘 다 선택하는 것을 막지 못하므로 배포 검증이 이를
거절해야 한다는 점이 골격에 열린 과제로 적혀 있다.

### 2.1 최초 소유자 설정 준비 도우미

`deploy/bootstrap/index.html`은 네트워크에 연결하지 않는 정적 보조 페이지다. 배포 유형(로컬 /
HTTPS 서버)과 주소를 확인하고, 브라우저 안에서 최초 설정 값을 만든다. 결과는 두 가지다.

- 배포 설정 블록: 배포 구성에 넣는다.
- 일회용 capability: **한 번만 표시**되며, 배포 구성에 넣지 말고 같은 주소의 DeepTwin 시작
  화면에 직접 입력한다.

이 도우미는 `deploy/tests/bootstrap-helper.test.mjs`로 시험되지만 새 호스트 배포 적격성은
검증되지 않았다.

### 2.2 control-plane 입력

서버 main(`python -m app.server`)은 `--data-dir`, `--deployment-config`,
`--session-root-dir`, `--expected-uid`, `--expected-gid`를 모두 요구하는 **운영 입력**이다.
내부 listener는 `0.0.0.0:8080`, worker 1개, reload 끔, proxy header 신뢰 안 함, access log
끔으로 고정된다. `Forwarded`/`X-Forwarded-*` 헤더가 있는 요청은 거절된다. 구성이나 root가
없으면 시작 자체가 실패한다.

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
  `manifest.json`(0400).
- `app/operations/credential_root_init.py` `initialize_credential_root`: credential root와
  records 디렉터리를 쌍으로 초기화.
- `app/operations/backup_key.py` `initialize_backup_key`: `identity.age`(0600)와
  `manifest.json`(`key_mode: instance_backup_key`, `encryption_profile_ref: age-x25519-v1`,
  public recipient, identity SHA-256). secret identity는 결과·오류·로그에 나오지 않는다.

주의: 현재 Compose 골격에는 `state-root-init`와 `ipc-root-init` 두 작업만 선언되어 있다.
`ipc-root-init`의 IPC boot secret은 위 규칙과 달리 **부팅마다 새로 만들거나 덮어쓰는**
(`generate-or-overwrite-per-boot`) 값이다. `backup-key-init`, `session-root-init`,
`vault-init`은 코드와 시험은 있으나 골격에 서비스로 아직 선언되어 있지 않다.

## 4. 백업과 복원 (age 1.3.2)

### 4.1 암호화 도구

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

### 4.2 키 모드

| 모드 | recipient | host/볼륨 상실 후 복원 |
| --- | --- | --- |
| `instance_backup_key` | `backup-key-init`이 만든 별도 `backup-key` 볼륨의 키 | **불가** (receipt에 `recoverable_after_host_or_volume_loss=false`) |
| `portable_recovery` | 사용자가 따로 보관하는 recipient + 한 번만 쓰고 지우는 `OneShotIdentity` | 가능 (복구 비밀을 사용자가 보관할 때) |

`backup-key` 볼륨에만 있는 키를 host/볼륨 상실 대비 수단으로 안내하지 않는다. 복구 비밀은
백업 안에 넣거나 로그로 남기지 않는다.

### 4.3 백업 과정

`app/operations/backup.py`는 `backup_pending → snapshotting → encrypting → verify_restore →
ready`(실패 시 `failed`와 이유)로 진행한다. SQLite online backup으로 snapshot을 뜨고, 그 snapshot이 등록한 모든 원본 바이트(`domain-cas`의 content-addressed 파일)를 digest·크기 검증 후 각각 archive member로 담으며(원본이 없거나 digest가 다르면 백업 전체 거절), 모든
테이블을 포함/제외 범주로 닫힌 분류에 따라 처리한다(분류되지 않은 테이블이 있으면 백업 전체
거절). 인증 세션, challenge, provider 연결 같은 권한 자료는 제외된다. 암호화한 뒤 **전체를 다시
복호화해 검증**한 다음에야 `ready`가 된다. 외부 `BackupReceipt`는 암호문 SHA-256/크기와
복원 검증 참조를 담으며, 내부 manifest는 자기 해시를 담지 않는다.

### 4.4 복원과 `restored_review`

- 복원 대상은 **비어 있는 staging 디렉터리**여야 한다. 활성 vault나 사용 중인 디렉터리로의 복원은
  거절한다.
- 복호화 전에 암호문이 외부 receipt와 일치해야 한다. 이후 age 인증, archive member와 크기, 원본 바이트의 content address와 등록 목록의 정확한 일치,
  manifest 해시, schema 버전, 제외 범주 부재, vault identity, 모든 기록의 계보를 확인한다.
- 성공하면 `restored_review.json` 표시를 남긴다. 복원된 인스턴스는 새 owner bootstrap 뒤에도
  **모든 dispatch가 차단된 `restored_review`** 로 열리며, 새 소유자가 연결·service client를
  다시 만들고 정확한 환경을 검토·활성화해야 한다. 과거 credential/session/challenge는 재사용하지
  않는다.
- 실패하면 staging 디렉터리는 비어 있는 채로 남는다.

### 4.5 근거

`evidence/backup-age-t070-2026-09-23.md`: 검증된 age 디렉터리를 가리키는
`DEEPTWIN_AGE_RUNTIME_ROOT`와 함께 `app/tests/test_backup.py` 12개 통과(Linux x86_64). 그 변수가
없으면 실행 파일이 필요한 8개는 이유를 밝히고 건너뛴다. CI에는 age 바이너리 공급이 없어 그곳에서는
건너뛴다. `deploy/tests/age_runtime_canary.py`는 uid 65534, 네트워크 namespace 안에서 통과했다.

## 5. 아직 연결되지 않은 것

- **networkless backup-crypto worker는 아직 별도로 배포된 서비스가 아니다.** 계약은
  control-plane이 typed archive stream만 보내고 worker만 `backup-key`를 읽기 전용으로 mount하도록
  나누지만, 지금은 `create_backup`이 두 절반을 **한 프로세스에서** 실행한다. Compose 골격의
  `backup` 서비스는 `network_mode: none` 자리표시자일 뿐이며 이미지가 없다.
- 브라우저에서 백업 만들기·복원, 포함 내용 미리보기·동의 화면이 없다(기록 화면은 미연결 상태를
  알려 줄 뿐이다).
- 마이그레이션 전 백업 게이트(T072), 예약 백업, 업데이트 흐름이 구현되지 않았다.
- 최종 이미지, 두 프로필의 새 호스트 시험, TLS edge, Linux UID/network 자격 검증(T079/T081/T083)이
  남아 있다.
- 보존 정책상 원본·핵심 기록은 자동 삭제하지 않으며, 백업도 자동 삭제하지 않는다. 삭제 화면은
  아직 없다.
