# macOS Chromium worker egress 강제 수단 조사

> **2026-09-08 superseded by ADR-009.** 이 문서는 이전 `.app`/XPC/App Sandbox 경계의 역사적
> 조사다. 현재 웹 배포 worker의 격리 증거가 아니며, 네트워크 차단·typed broker라는 요구만
> 새 서버/worker 환경에서 별도로 재검증한다.

조사일: 2026-09-07. 범위: macOS 26.5.1 arm64, standalone py2app 제품, GUI-only 설치, 관리자 권한·보안 비활성화·사용자 CLI 설정 없음. **실제 sandbox/Chromium 실행과 정책 컴파일은 하지 않았다.** 변경은 이 조사 문서뿐이다.

## 1. 결론: network 없는 App Sandbox worker + host fetch를 기본 설계로 선택

**구현·검증할 기본 아키텍처는 공식 App Sandbox가 적용된 독립 XPC worker + host-side egress broker fetch + Playwright route.fulfill로 선택한다. 실제 동작 검증 완료는 아니다.** worker에는 network client/server entitlement를 주지 않아 broker loopback port 연결조차 필요 없게 한다. Chromium은 실제 JS/DOM/렌더링을 수행하고, 필요한 HTTP(S) 응답은 sandbox 밖 trusted broker가 검증하여 가져온 뒤 제어 채널로 전달한다. request interception이 놓친 통신은 허용하는 대신 OS network deny에 막혀야 한다.

변경 이력(동일 조사일): 최초의 ‘worker가 특정 proxy TCP port에 직접 연결’ 제약으로는 검증된 수단이 미결이었고 outer sandbox-exec를 실험 후보로 좁혔다. 이후 root가 제안한 **network 없는 worker/control-pipe 중계** 구조를 추가 검토하여 이 구조를 기본 설계로 선택했다. 이는 egress 강제 요구 완화가 아니라 worker의 직접 network 권한을 더 줄이는 변경이다. sandbox-exec/SBPL은 deprecated/지원 위험 때문에 기본안과 자동 fallback에서 제외한다. Chromium의 App Sandbox 호환성, 파일·Keychain 비밀 분리, 아래 실기 게이트가 실패하면 RC는 차단된다.

## 2. 현재 호스트에서 실제 읽기 전용으로 확인한 것

| 검사 | 관측 결과 | 증명하지 않는 것 |
| --- | --- | --- |
| `sw_vers`, `uname -m` | macOS 26.5.1, build 25F80, arm64 | 다른 OS/build의 호환성 |
| `/usr/bin/sandbox-exec` 존재 확인 | executable 존재, 크기 102560 bytes | profile가 적용되는지, Chromium이 실행되는지 |
| `/usr/bin/sandbox-exec -h` | 도움말 전용 flag는 아니어서 exit 64, usage 출력. `-f/-n/-p`, `-D` 지원 표시 | sandbox 적용 또는 child 실행 — command 인수는 전달하지 않음 |
| 현재 `man sandbox-exec` | DEPRECATED, App Sandbox 권고 | third-party SBPL 안정성 |
| 현재 `man sandbox_init` | API 및 사전 정의 profile도 DEPRECATED | 특정 포트 허용 syntax의 공개 계약 |
| 현재 `man sandbox` | child가 부모 sandbox를 상속. 제한은 일반적으로 자원 획득 시점에 적용, 기존 열린 descriptor는 사용할 수 있음 | 모든 inherited FD/Mach capability가 자동 무효화되는 것 |

위 로컬 man은 이번 대상 OS가 제공한 1차 자료다. 현재 binary 존재와 deprecated 상태를 함께 기록한다. Apple DTS의 원문도 SBPL이 third-party 사용을 위해 문서화되지 않았고 이를 바탕으로 제품을 만드는 것은 권하지 않는다고 설명한다. Chromium이 SBPL을 사용하는 사실이 Apple의 지원 정책을 바꾸지는 않는다. [Apple DTS 설명](https://developer.apple.com/forums/thread/661939)

## 3. 최초 포트 제약의 한계와 변경된 공식 지원 경로

App Sandbox는 공식 kernel-enforced 격리이고 별도 XPC/helper app으로 권한 분리는 가능하다. 그러나 `com.apple.security.network.client`는 같은 기기의 서버까지 포함하는 outgoing connection 허용 Boolean이지 목적지 host/port allowlist가 아니다. 이를 켜서 broker 연결을 허용하면 해당 entitlement만으로 다른 목적지를 금지하지 못하고, 끄면 broker TCP 연결도 허용되지 않는다. TCP/UDP의 entitlement 동작도 다르다. [Apple network.client](https://developer.apple.com/documentation/BundleResources/Entitlements/com.apple.security.network.client), [helper 권한 분리](https://developer.apple.com/documentation/security/discovering-and-diagnosing-app-sandbox-violations)

**추가 확인한 지원 경로:** Apple은 XPC service마다 독립 sandbox를 둘 수 있고, 외부 build tool을 sandboxed helper로 동봉하는 절차가 Developer ID 독립 배포에도 적용된다고 명시한다. 따라서 별도의 native XPC worker가 network 없는 sandbox의 시작점이 되고, 그 안에서 Playwright driver/Chromium을 상속 실행하게 하는 구조를 권고한다. 기존 unsandboxed py2app host가 Chromium을 spawn한 뒤 `inherit`만 붙이는 것으로 같은 격리가 생긴다고 추정하지 않는다. [XPC privilege separation](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingXPCServices.html), [Apple helper 동봉·외부 배포](https://developer.apple.com/documentation/xcode/embedding-a-helper-tool-in-a-sandboxed-app)

Playwright의 `route.fulfill`은 status/headers/body를 제공하는 공식 API이다. 이 연결점을 사용하면 Chromium 자체의 HTTP 요청은 실제 socket에 진행시키지 않고 trusted host가 받은 응답으로 완료할 수 있다는 설계 추론이 가능하다. network entitlement가 없는 실제 signed Chromium에서 모든 필요한 navigation/subresource/JS 기능이 유지되는 것은 아직 실증하지 않았다. [Playwright Route](https://playwright.dev/python/docs/api/class-route#route-fulfill)

## 4. Chromium의 실제 원본이 보여 주는 주의점

Chromium 공식 `network.sb`는 network service에 remote TCP/UDP, mDNSResponder socket, DNS 설정·Mach 서비스, 사용자 및 시스템 Keychains 읽기를 허용한다. 따라서 Chromium 자체 sandbox 또는 `chromium_sandbox=True`는 DeepTwin 전용 egress/file 정책을 대체하지 않는다. 이 원본을 그대로 복사하여 worker profile로 사용하면 요구와 모순된다. [Chromium network.sb](https://raw.githubusercontent.com/chromium/chromium/main/sandbox/policy/mac/network.sb)

`common.sb`에는 framework·bundle 읽기, MachPort rendezvous, logging/IPC 등 child 실행에 필요한 규칙이 있다. Mac sandbox 설계는 system framework 자원이 OS마다 바뀌며 지나치게 넓은 허용과 호환성 사이의 tradeoff가 있음을 설명한다. 이것을 바탕으로 DeepTwin의 별도 App Sandbox 안에서도 기존 Chromium 내부 sandbox가 모두 동작한다고 추정할 수는 없다. nesting과 GPU/renderer/network helper를 실험하고, 새 구조에서는 TLS 검증을 담당하는 trusted broker도 별도로 검증한다. [common.sb](https://raw.githubusercontent.com/chromium/chromium/main/sandbox/policy/mac/common.sb), [Mac sandbox 설계](https://raw.githubusercontent.com/chromium/chromium/main/sandbox/mac/seatbelt_sandbox_design.md)

Chromium proxy 설정에는 localhost/link-local implicit bypass와 DIRECT fallback 개념이 있으며 SOCKSv5도 TCP URL 요청만 처리하고 UDP를 relay하지 않는다. manual proxy의 bypass를 조정하고 DIRECT fallback을 없애는 것은 필요한 방어적 설정일 수 있으나 OS 차단의 대체가 아니다. QUIC/WebRTC/DNS가 proxy 설정을 따른다고 추정하지 않는다. [Chromium proxy 문서](https://chromium.googlesource.com/chromium/src/+/main/net/docs/proxy.md)

## 5. 선택한 기본 아키텍처의 정확한 경계

다음은 코드가 아닌 **구현·검증할 정책 명세**다. 서명된 XPC worker/Chromium 구성, IPC, broker를 새로 구현해야 하며 이미 확보한 기능으로 표시하지 않는다.

- py2app host의 제공자 호출·Keychain·SQLite는 trusted host에 남긴다. 별도 bundle ID의 signed XPC service가 App Sandbox를 적용하고 network client/server, user-selected files/Downloads, camera/mic, 앱 데이터 공유 권한을 부여하지 않은 채 driver/Chromium을 시작한다. XPC service는 main app과 독립 권한을 가진다. Node/Chromium 및 모든 child의 실제 inheritance·entitlement 조합을 inspect한다. Apple 문서상 inheriting tool의 App Sandbox entitlement는 app-sandbox와 inherit 두 개이며 다른 App Sandbox entitlement는 오류를 일으킬 수 있다. [상속 규칙](https://developer.apple.com/library/archive/documentation/Miscellaneous/Reference/EntitlementKeyReference/Chapters/EnablingAppSandbox.html#//apple_ref/doc/uid/TP40011195-CH4-SW3)
- Playwright↔Chromium은 worker 내부 remote-debugging pipe로만 통신한다. host↔worker는 앱에 동봉된 XPC service의 검증된 typed message로 요청/바이트를 중계한다. proxy/CDP HTTP server를 열지 않는다. XPC 상대·세대·요청 ID·메시지 크기를 검증하고 범용 Python/shell/파일/credential 명령을 허용하지 않는다. 비신뢰 worker가 broker를 confused deputy로 사용할 수 있음을 전제로 한다.
- 최초 page 이전 context route 등록, SW 차단, 모든 지원 HTTP(S) request의 method/URL/headers/body를 제한된 broker 요청으로 변환한다. `route.continue_`/자동 fallback으로 worker socket을 열지 않는다. trusted host가 직접 fetch하고 검증한 status/headers/body만 route.fulfill한다. worker 쪽 `route.fetch`/APIRequestContext가 실수로 쓰여도 OS network deny를 우회할 수 없어야 한다.
- broker는 실제 connect 시 DNS/IP, host/port/URL allowlist, redirect 매 hop, TLS certificate/SNI, method·body·응답 byte·시간·동시성 상한을 검증한다. UI localhost, private/link-local/metadata 목적지와 인증정보 포함 URL을 차단한다. system proxy/netrc/환경의 자격정보를 묵시적으로 상속하지 않는다. 응답은 fake 페이지가 아니라 broker가 받은 실제 public HTTPS bytes이며 origin·CORS/CSP·쿠키·redirect·압축 header·중복 Set-Cookie 의미를 보존하는 기능 검증이 필요하다.
- WS/SW/WebRTC/QUIC·무한 스트림 등 아직 broker가 지원하지 않는 기능은 명시적 unsupported/abort로 종료한다. full-fidelity 일반 브라우징을 주장하지 않는다. 필수 사용자 시나리오가 그 기능을 요구하면 RC 기능 게이트가 실패한 것이며 network entitlement를 켜서 넘어가지 않는다. interception 사각지대는 가용성 실패일 수 있지만 직접 egress 허용이어서는 안 된다.
- worker에는 비밀 없는 전용 container/profile/staging만 사용한다. App Sandbox가 모든 시스템 파일을 숨기거나 `지정 container 외 파일은 무조건 0개`를 뜻하지는 않는다. 앱/OS runtime 자원 접근과 보호 대상 사용자 home/DeepTwin DB/인증 데이터 접근을 구분한다. sandbox extension/bookmark/App Group으로 host 데이터 전체를 공유하지 않는다.
- DeepTwin API 비밀은 data-protection Keychain에 저장하고 worker와 다른 access group으로 제한한다. worker에 host의 keychain/app group을 부여하지 않는다. **App Sandbox만으로 모든 legacy macOS Keychain API 접근이 차단된다고 주장하지 않는다.** legacy file-based Keychain은 별도 ACL 모델이므로 API·file 접근과 무허가 prompt를 dummy fixture로 확인해야 한다. 엄격한 개인 Keychain 비밀 차단이 증명되지 않으면 보호 경계는 미충족이다. [data-protection Keychain](https://developer.apple.com/documentation/security/ksecusedataprotectionkeychain), [access group](https://developer.apple.com/documentation/Security/kSecAttrAccessGroup), [legacy ACL](https://developer.apple.com/documentation/security/access-control-lists)
- 상속 FD는 필요한 익명 control/log pipe만 명시적으로 전달한다. 연결된 socket, 열린 DB/secret file, 임의 directory FD, 자격정보 capability를 전달하지 않는다. XPC로 보내는 file handle도 같은 규칙을 적용한다. 실제 pipe 번호를 임의 가정하지 않는다. Chromium 내부 sandbox는 유지하고 GPU·network child·Mach rendezvous와 App Sandbox nesting을 검증한다.
- network 없는 worker에서도 DNS service를 통한 대행, Unix/Mach network proxy, inherited connection, child 탈출을 시험한다. API 키를 읽는 parent 기능은 browser broker IPC로 호출할 수 없게 한다. service 시작/서명/sandbox/handshake 오류나 host broker 종료 시 fail-closed로 worker 작업을 중단한다. root helper·SBPL·`--no-sandbox`·전체 권한 허용 fallback은 없다.

기존 열린 FD가 경계를 우회할 수 있다는 경고는 추측만이 아니다. 현재 macOS man에 명시되어 있고 Chromium 자체 test도 deny-default 이후 상속된 writable FD로 쓰기/ftruncate가 가능함을 확인하는 내용을 담는다. [Chromium seatbelt tests](https://raw.githubusercontent.com/chromium/chromium/main/sandbox/mac/seatbelt_unittest.cc)

## 6. 채택 전에 필요한 empirical gate — 모두 미실행

| ID | 허용된 별도 실험에서 확인할 것 | 합격 기준 |
| --- | --- | --- |
| SB-01 | 먼저 작은 signed App Sandbox XPC fixture로 모든 IPv4/IPv6 TCP/UDP deny + host typed fetch/fulfill 경로 | worker 직접 sink 수신 0, host broker의 허용 fetch만 성공. syscall와 sink 증거 병행 |
| SB-02 | DNS/DoH/QUIC/STUN, mDNSResponder 및 DNS 대행 서비스, proxy 비활성/우회 시도 | worker 직접 통신 0. broker가 허용한 요청만 성공. 실제 metadata/사용자 LAN probing 금지 |
| SB-03 | temp secret/DB/keychain 전용 test fixture와 file/FD/Mach 접근 | worker의 비허용 내용 획득 0. 사용자 실제 비밀은 테스트에 쓰지 않음 |
| SB-04 | App Sandbox worker에서 pinned Chromium pipe/child, 실제 HTTPS broker body로 JS/DOM/screenshot | 필수 기능·origin/cookie/CORS/redirect 의미 보존, 내부 sandbox 유지. 모든 child의 적용 확인 |
| SB-05 | broker/XPC 시작 실패/종료/상대 위조, entitlement 오류, OS mismatch, worker crash/cancel | 직접 연결 fallback 0, 신규 작업 차단, 실제 확인 전 completed 보고 0 |
| SB-06 | signed/notarized py2app 설치본을 해당 OS의 깨끗한 비관리자 계정에서 실행 | GUI-only, root/보안 설정 변경 0, 자식도 같은 제한. 서명·공증 자체가 정책 증명은 아님 |
| SB-07 | pinned macOS/Chromium revision 변경 전 위 행렬 재실행 | 지원 matrix와 결과 hash 고정. 미검증 OS/새 binary는 보호 없이 실행하지 않음 |

최종 인계: [패키징 조사](packaging-research.md)의 강한 network enforcement를 구현할 **기본 설계는 network 없는 공식 App Sandbox XPC worker + host fetch/route.fulfill로 확정 권고**한다. native helper·서명·실제 Chromium 호환성과 비밀 격리 검증은 남는다. loopback proxy-only SBPL 방식은 기본안에서 제외했다. 이 조사로 실제 통신/Keychain 차단이나 RC 적합성이 입증되었다고 쓰지 않는다.
