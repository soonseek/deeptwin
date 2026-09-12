# [HISTORICAL · DO NOT IMPLEMENT] Apple Silicon macOS 로컬 RC 패키징 조사

> **2026-09-08 superseded by ADR-009.** 이 문서는 이전 네이티브 데스크톱 가정 아래 수행한
> 역사적 조사다. 현재 **웹 기반 프레임워크 오픈소스**의 배포 결정·작업·출시 증거로 사용하지
> 않는다. 아래의 `.app`/DMG/WKWebView/네이티브 런처 권고는 모두 폐기되었으며 구현 입력으로
> 인용하거나 승계하지 않는다.
> 재사용 가능한 것은 고정 의존성·라이선스·무결성 검증 원칙뿐이다.

조사일: 2026-09-07. 상태: **설계 권고·공식 문서 조사만 완료**. 설치본 제작, 의존성 설치, 키/계정 접근, 서명, 공증, 실제 마이크·모델·브라우저 실행은 하지 않았다. 아래 검증표는 미실행 인수 조건이지 성공 기록이 아니다.

현재 제품 조건은 비개발자 GUI-only, 기존 Python/Starlette/SQLite 및 웹 frontend 재사용, DeepTwin 소유 Chromium 도구, 로컬 STT, Codex 공식 subprocess이다. 제공자 요구는 사용자 최신 변경에 따라 **Claude API-only + Codex 구독 기본(명시적 API 선택 가능)**이며 Claude 구독 승인 대기는 제외한다. 제공자 경계는 [별도 조사](provider-research.md)를 따른다.

## 1. 폐기된 과거 추천안과 당시 선택 이유

**pywebview의 macOS WKWebView + py2app standalone `.app`, Developer ID 서명·notarization·stapling을 거친 DMG**를 첫 RC 경로로 권고한다. UI는 OS의 WKWebView, 에이전트 브라우저 도구는 별도 DeepTwin 소유 Playwright Chromium 프로세스이다. 두 브라우저의 쿠키·권한·신뢰 영역을 합치지 않는다.

pywebview 공식 freezing 문서는 macOS에 py2app을 지정하고, 엔진 문서는 OS 내장 WKWebView를 명시한다. py2app의 alias 및 semi-standalone 모드는 설치된 Python에 의존하므로 배포에 쓰지 않는다. GUI toolkit과 충돌할 수 있는 argv emulation도 끈다. [pywebview freezing](https://pywebview.flowrl.com/guide/freezing), [엔진](https://pywebview.flowrl.com/guide/web_engine), [py2app 옵션](https://py2app.readthedocs.io/en/latest/options.html)

이 선택은 현재 Python backend와 웹 UI를 보존하면서 Dock/앱 종료/마이크 사용 주체를 하나의 앱으로 만들기 위한 설계 판단이다. launcher `.app` + 사용자의 기본 브라우저는 UI 세션·권한·종료 소유권이 갈라지므로 이번 추천안에서 제외한다. pywebview+PyInstaller를 macOS 공식 권장 조합이라고 표현하지 않는다.

단, **py2app이 이 저장소의 전체 의존성을 자동으로 완벽 수집한다는 증거는 없다.** Playwright 공식 문서는 PyInstaller 브라우저 동봉 예제를 제공할 뿐 py2app 검증을 제공하지 않는다. py2app의 Playwright driver/Node/Chromium 수집, arm64 Mach-O 의존성, STT Metal 자원, nested signing은 실제 빌드로 닫아야 할 우선 게이트다. [Playwright 독립 실행 패키징](https://playwright.dev/python/docs/library)

## 2. 실제로 만들 설치 단위

| 구성 | RC의 소유·배치 방침 | 인수할 증거 |
| --- | --- | --- |
| DeepTwin.app | standalone Python, Starlette backend, 웹 정적 자원, pywebview/PyObjC를 동봉. bundle에는 실행 중 쓰지 않음 | Finder 실행, 개발 Python/Node/Homebrew 없는 기기에서 부팅 |
| Playwright | Python package뿐 아니라 driver/Node와 정확히 일치하는 Chromium revision 동봉 | signed bundle에서 지정 revision 실행, 외부 cache/사용자 Chrome 미사용 |
| STT | 기존 whisper.cpp 계열 arm64 실행 파일·필수 dylib/Metal 자원 동봉. 기본 다국어 모델도 license/hash 확인 후 동봉을 우선 | 네트워크 없이 한국어 녹음→전사, 외부 바이너리 PATH 의존 없음 |
| Codex | 공식 arm64 배포물의 특정 버전과 생성 protocol schema를 고정하여 동봉. 제3자 notices 및 helper signing 검토 후 확정 | 공식 stdio subprocess initialize/종료·GUI 로그인 경로. 실제 구독 호출은 별도 승인된 인수 |
| 상태 | 앱 전용 Application Support에 SQLite/설정/모델, 앱 전용 Caches에 제한된 임시 파일. bundle 밖으로 분리 | 재시작·업데이트 후 상태 보존, 앱 bundle signature 불변 |
| 비밀 | DeepTwin API 키는 Keychain, SQLite에는 opaque credential reference만 | DB/로그/argv/웹 storage/진단 export에 canary 키 없음 |

Playwright 버전마다 필요한 브라우저 binary가 다르며 기본 macOS cache는 사용자 공용 위치다. **빌드 단계에서** matching Chromium을 수집하고 앱 실행 시 전용 bundle 경로를 지정한다. 사용자의 cache를 빌드 재료로 묵시적으로 복사하거나 공용 cache GC/삭제를 호출하지 않는다. 개발자가 브라우저를 설치하는 과정과 최종 사용자의 설치 과정을 구분한다. [공식 브라우저 관리](https://playwright.dev/python/docs/browsers)

다운로드 정책: 첫 RC의 Chromium은 DMG에 포함하여 첫 실행 다운로드를 없애는 것이 기본이다. STT 모델을 크기 때문에 분리해야 한다면 GUI에 공급자·용량·저장 위치·license·진행률·취소·재시도·offline 상태를 제공한다. HTTPS URL/redirect origin allowlist, 사전에 신뢰한 서명된 manifest의 크기/SHA-256, 임시 파일→검증→원자적 활성화를 적용한다. 다운로드 서버가 함께 준 미검증 hash만으로 신뢰를 만들지 않는다. 모델은 데이터이며 다운로드한 임의 설치 스크립트를 실행하지 않는다. 바이너리 수리·업데이트는 서명된 앱 릴리스로 한다.

현재 개발 기기의 whisper.cpp 1.8.7/base 기록은 [기존 조사](../../docs/ui/2026-09-07-model-control-and-voice.md)에 있을 뿐 새 설치본 증거가 아니다. RC 최소 macOS 버전은 고정한 Python/PyObjC/Playwright/Chromium/STT의 지원 범위 교집합과 실기 결과로 정한다. Apple Silicon-only가 모든 macOS 버전 지원이나 Rosetta 필요 없음의 검증 결과를 뜻하지 않는다.

## 3. 비개발자의 처음 실행과 마이크

최종 사용 흐름은 DMG 열기 → Applications로 복사 → Finder/Dock에서 실행 → GUI 준비 상태 → 제공자 연결 → 작업이다. Terminal, pip/npm, Homebrew, Xcode, 환경변수 편집, 개발자 모드는 요구하지 않는다. 부족한 disk/미지원 OS/손상된 helper/오프라인은 앱 안에서 원인과 재시도·공식 재다운로드를 안내하며 조용히 다른 제공자나 유료 API로 전환하지 않는다.

마이크는 사용자 녹음 시작 뒤에만 요청한다. `NSMicrophoneUsageDescription`에 로컬 전사 목적을 명시하고 hardened runtime의 audio-input entitlement를 검토한다. WKWebView에는 origin/frame/type별 media capture permission delegate가 있으며 기본 동작은 prompt다. 이는 실제 pywebview의 pinned delegate가 올바르게 동작한다는 증거가 아니다. [Apple microphone purpose](https://developer.apple.com/documentation/BundleResources/Information-Property-List/NSMicrophoneUsageDescription), [audio-input](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.device.audio-input), [WKUIDelegate](https://developer.apple.com/documentation/webkit/wkuidelegate/webview%28_%3Arequestmediacapturepermissionfor%3Ainitiatedbyframe%3Atype%3Adecisionhandler%3A%29)

WKWebView의 신뢰한 앱 origin에서 getUserMedia→기존 PCM 전사 흐름을 우선 검증한다. 권한 거부·회수, 녹음 중 작업 전환/취소, 한국어 IME 병행, interim/final, 장치 분리, 재실행을 확인한다. 녹음 표시와 stop은 실제 capture 수명주기에 연결한다. 기본값은 원음 미보존·외부 전송 없음이다. 패키징 후 WK capture가 불가능하면 동일 앱 안의 AVFoundation capture bridge를 별도 구현·검증해야 하며, 웹 permission prompt가 보인 것만으로 음성 기능 완료를 선언하지 않는다.

UI의 마이크 권한을 에이전트 Chromium에 전달하지 않는다. 카메라·화면 녹화·Accessibility·Full Disk Access를 일반 설치 조건으로 요구하지 않는다. OS 설정 변경이 필요한 거부 상태는 사용자에게 안내만 하고 TCC DB 수정/권한 초기화 명령을 실행하지 않는다.

## 4. 서명·공증·라이선스 출시 경계

배포 담당자가 Developer ID Application 인증서로 모든 배포 실행물의 유효한 서명을 확보하고 hardened runtime·timestamp를 적용한 뒤 notarytool 제출, accepted 결과와 경고 로그 확인, ticket stapling, 최종 DMG 검증을 수행해야 한다. Apple은 notarization이 App Review가 아니며 성공 후에도 실제 배포 테스트가 필요하다고 설명한다. [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution), [배포 검증](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution)

Chromium/Node/Codex/Python/STT nested 실행물은 각각 실제 서명 상태와 필요한 entitlement를 검사하여 안쪽부터 처리한다. 임의의 모든 entitlement 활성화나 `--deep` 재서명을 만능 수정으로 쓰지 않는다. JIT/라이브러리 검증 예외는 해당 helper에 필요한 최소 범위만 실험으로 입증한다. hardened runtime과 App Sandbox는 다른 기능이며, 이 외부 배포 `.app`가 OS sandbox에 의해 모든 파일·네트워크를 격리한다고 주장하지 않는다. [Apple 배포 설정](https://developer.apple.com/documentation/Xcode/preparing-your-app-for-distribution), [hardened runtime](https://developer.apple.com/documentation/Security/hardened-runtime)

다운로드되어 quarantine 속성이 있는 **다른 깨끗한 Mac/사용자**에서 정상 Gatekeeper 확인창을 통한 실행을 시험한다. 정상 최초 Open 확인은 사용자 동작이다. unsigned 경고의 Open Anyway, quarantine 제거, Gatekeeper 비활성화, SIP 변경은 RC 통과 조건이나 설치 안내로 허용하지 않는다. 조직 관리 정책에 막히면 해당 상태를 보고하고 사용자/관리자 결정에 맡긴다. 지금 인증서 보유·서명·공증 완료를 가정하지 않는다. [Apple 안전한 앱 실행 안내](https://support.apple.com/en-us/102445)

라이선스는 다음이 **후보 확인**이며 실제 릴리스 artifact의 dependency/SBOM/notices 검토가 남는다. 소프트웨어 배포 허용과 제공자 계정·서비스 사용 권한은 별개다.

| 구성 | 확인한 원본 | 배포에 남는 의무/확인 |
| --- | --- | --- |
| pywebview | [BSD-3-Clause license](https://github.com/r0x0r/pywebview/blob/master/LICENSE) | copyright/조건/disclaimer, 비보증·비후원 고지 보존 |
| py2app | [MIT 또는 PSF 조건](https://raw.githubusercontent.com/ronaldoussoren/py2app/main/LICENSE.txt) | 선택한 실제 버전 고지 포함 |
| Playwright Python | [Apache-2.0](https://raw.githubusercontent.com/microsoft/playwright-python/main/LICENSE) | LICENSE/관련 NOTICE, 변경 사항 및 포함 dependency 고지 확인 |
| Chromium | [BSD 계열 원본](https://raw.githubusercontent.com/chromium/chromium/main/LICENSE) | Chromium 최상위 license만으로 동봉 third_party 전체가 처리되지 않음. matching build의 notices/추가 의무 확인 |
| whisper.cpp | [MIT](https://raw.githubusercontent.com/ggml-org/whisper.cpp/master/LICENSE) | 엔진과 모델 weights의 출처·license를 별도 검증. 엔진 MIT를 모든 모델에 전이하지 않음 |
| Python/PyObjC/SQLite/Node/Codex 등 | 선택한 binary/package의 공식 release와 license 파일 | 정확한 포함 파일·버전·notice·재배포 조건 확인 전 배포 완료 아님. Codex desktop 내부 자산을 임의 복사하지 않음 |

## 5. 비밀·로컬 서버·Codex 경계

API 키는 macOS Keychain에 앱 고유 service/account 항목으로 저장하고 오류/잠금/사용자 거부를 처리한다. UI는 저장 성공 여부와 masked label만 받아야 한다. 암호화 저장이 실행 중 악성 코드에 대한 완전 방어는 아니다. Codex 인증은 공식 로그인 흐름/저장 동작에 맡기고 DeepTwin이 기존 인증 파일을 읽어 다른 위치에 복사하거나 토큰을 추출하지 않는다. 종료는 로그아웃이 아니며 연결 해제·비밀 삭제는 별도 명시적 동작이다. [Apple Keychain](https://developer.apple.com/documentation/security/keychain-services)

Starlette는 고정 공개 포트가 아닌 `127.0.0.1`의 앱 전용 ephemeral port에 bind한다. session-unique secret으로 HTTP/WebSocket을 인증하고 Host/Origin/CSRF/CORS를 검증한다. token은 URL query/로그에 넣지 않는다. pywebview도 REST API의 CSRF와 session token을 설명하지만 기존 Starlette 서버를 자동 보안 처리해 주지는 않는다. UI origin만 bridge를 허용하고 외부 링크는 별도 기본 브라우저에 열며 외부 페이지를 privileged WKWebView로 navigate하지 못하게 한다. [pywebview 보안](https://pywebview.flowrl.com/guide/security)

Codex는 absolute bundled executable + argv 배열 + 앱 소유 stdio subprocess로 실행한다. shell/profile/PATH의 사용자 프로그램을 묵시적으로 실행하지 않는다. 공식 app-server는 JSONL stdio와 initialize/initialized, thread/turn 및 interrupt 수명주기를 문서화한다. 다만 현재 문서에는 app-server command와 WebSocket의 experimental/production unsupported 설명도 있다. **공식 문서화된 RC 통합 경로이지 안정된 production API 계약 보장은 아니다.** pinned 0.144.4의 기존 확인과 최신 문서를 혼동하지 말고 동봉 버전 schema/기능 검사를 인수한다. [Codex app-server](https://learn.chatgpt.com/docs/app-server)

## 6. Playwright 최소 통제와 SSRF 보증의 한계

Playwright는 페이지 자동화 API이며 URL allowlist를 제공하는 보안 sandbox 자체가 아니다. 공식 문서상 page.route는 redirect의 첫 URL에만 handler가 호출되고, popup 최초 요청은 context.route가 필요하다. context.route도 service worker가 처리한 요청을 intercept하지 않으므로 `service_workers="block"`이 권장된다. 따라서 request 이벤트를 사후 관찰하거나 최초 URL을 검사한 것만으로 redirect/SSRF 차단을 선언하지 않는다. [Page route](https://playwright.dev/python/docs/api/class-page#page-route), [Context route](https://playwright.dev/python/docs/api/class-browsercontext#browser-context-route)

최소 구현 제안:

1. 앱 소유 Chromium과 새 non-persistent context만 생성한다. 사용자 Chrome/profile/CDP 세션에 붙지 않는다. `chromium_sandbox=True`를 명시한다. 문서의 기본값은 false다. 임의 launch args, `--no-sandbox`, 무검증 TLS 우회, extension 설치를 모델에 노출하지 않는다. [BrowserType](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch)
2. 첫 page 생성 전에 context route를 등록하고 service worker를 block한다. permissions는 부여하지 않고 TLS 검증은 켠다. 다운로드는 기본 거절(`accept_downloads=False`), 시간·응답 바이트·동시 page·작업당 요청 수에 상한을 둔다. 이를 가용성·노출 축소 설정으로 보며 OS 강제 격리와 동일시하지 않는다.
3. `navigate/click/fill/upload/download` 같은 좁은 tool schema와 작업별 정책을 둔다. 모델이 raw Python/Playwright 객체, 임의 filesystem API, context.request나 새로운 브라우저를 만들어 우회하지 못하게 한다. WebSocket은 별도 route/차단 정책을 두고 frame·worker·subresource·popup도 같은 origin 정책으로 다룬다. [Playwright 네트워크](https://playwright.dev/python/docs/network)
4. URL은 parser로 정규화하고 scheme/host/port를 정확히 allowlist한다. userinfo·난독화 IP·IPv4-mapped IPv6·loopback/private/link-local/metadata 주소·로컬 DeepTwin port는 거절한다. `file:`과 임의 `data:`, `javascript:`, `blob:` navigation을 모델 입력으로 허용하지 않는다. 내부 초기 blank와 페이지 생성 blob의 필요한 사용은 별도 좁은 정책이다.
5. **DNS 사전 조회+route만으로 rebinding/redirect 연결을 강제 통제할 수 없다.** 민감한 로컬 네트워크에 대한 강한 방어가 요구되면 실제 connect 시점 DNS/IP와 모든 redirect hop을 검사하는 egress proxy 및 proxy 우회를 막는 별도 네트워크 enforcement가 필요하다. proxy 설정 하나만으로 WebRTC/UDP/기타 채널까지 모두 차단됐다고 주장하지 않는다. 이 enforcement가 없으면 잔여 위험을 명시하고 승인된 제한 origin 작업만 허용한다. 임의 인터넷 안전 자동화의 합격으로 대체하지 않는다.
6. upload는 사용자 승인 artifact handle→허용 root 아래 검증된 파일로만 변환한다. symlink/경로 traversal/검사 후 교체도 시험한다. 다운로드는 승인된 작업별 context에서만 허용하여 private staging에 저장하고 크기/type/hash/목적지를 검사한다. 서버 filename을 경로로 신뢰하지 않고 자동 실행·덮어쓰기는 금지한다. 취소/실패 시 부분 파일이 정상 artifact가 되지 않아야 한다.

이 설정과 테스트는 위험을 줄이고 구체적 우회를 검출하는 제안이다. 임의 웹 콘텐츠·악성 browser exploit·동일 사용자 권한 악성 프로세스에 대한 완전 격리 증명은 아니다. 특히 allowlist origin 자체의 공격성, 허용 사이트로의 민감 입력 전송, model이 다른 tool로 동일 요청을 수행하는 우회도 전체 runtime 정책이 맡아야 한다.

## 7. 종료와 업데이트

App lifecycle owner가 모든 자식의 시작·ready·실패·PID/세대·소유권을 관리한다. Quit에서는 신규 dispatch 차단 → 녹음 중단 → 진행 작업 취소/감사 기록 → context/browser 정상 close 및 Codex interrupt/종료 → SQLite 안전 종료 순서를 둔다. 시간 초과는 자신이 시작한 자식 process group만 정리하고, 완료가 확인되지 않은 작업을 completed로 만들지 않는다. `pkill`로 사용자의 Chrome/Codex를 종료하지 않는다. 창 닫기와 Cmd-Q의 차이, 다중 실행, crash 후 stale lock/port/미완료 작업 복구를 정의한다.

Playwright 공식 Python guide는 진행 중인 API 호출 task의 cancellation을 unsupported로 설명한다. 무차별 asyncio task cancel만으로 안전 종료를 보장하지 말고 소유 task/정상 close/한정된 child 종료로 설계하고 시험한다. [공식 library guide](https://playwright.dev/python/docs/library)

첫 RC 업데이트는 **GUI에서 새 서명·공증 DMG 안내 후 앱을 종료하고 교체하는 방식**으로 한정한다. self-modifying bundle, runtime pip/npm upgrade, 실행 중 Chromium/Codex 교체는 하지 않는다. SQLite migration은 backup/transaction/version gate와 실패 복구를 갖추고 구버전 실행이 새 schema를 손상시키지 않게 막는다. 앱 삭제와 사용자 데이터·Keychain 삭제를 분리하여 기본 삭제가 작업 기록을 임의 소거하지 않도록 안내한다. 자동 업데이트 엔진은 이번 추천안의 완료 항목이 아니다.

## 8. RC 전에 실제로 실행할 검증

| ID | 실험 | 통과 증거 / 실패하면 남는 경계 |
| --- | --- | --- |
| PK-01 | 최소 지원 macOS 및 최신 지원 macOS의 깨끗한 Apple Silicon 기기에서 다운로드 DMG→Finder 설치 | Terminal 0회, 개발 runtime 0개, offline UI/로컬 STT 동작. 기기/OS/build hash 기록 |
| PK-02 | Mach-O/dylib/driver/모델/웹 assets closure 검사, readonly bundle 실행 | arm64 및 실제 필요한 slice, 외부 개발 경로 0개, 모든 필요한 notices. py2app 수집 가능성 확정 |
| PK-03 | nested codesign·notary accepted/log·staple·Gatekeeper online/offline 첫 실행 | 정상 시스템 확인만 필요. 서명 예외·우회 명령이 필요하면 RC 실패 |
| PK-04 | WKWebView 마이크 첫 허용/거부/회수/장치 분리·취소·한국어 IME·전사 | 앱 이름으로 권한, 실제 capture 중단, 원음/외부 전송 기본 0, packaged latency 측정 |
| PK-05 | 번들 Chromium revision/driver 일치, UI와 agent context 분리, sandbox 설정 | 사용자 browser/profile 변경 0, actual process/config 증거, agent mic/camera 접근 거절 |
| PK-06 | controlled servers로 30x→loopback/private/IPv6, DNS rebinding, iframe/fetch/worker/SW/popup/WS/다운로드 검사 | 거절 응답뿐 아니라 금지 목적지 server의 요청 수 0 확인. 실제 provider/metadata endpoint에 probing하지 않음 |
| PK-07 | egress 정책 밖 연결 및 proxy bypass 경로 검사 | 연결 시점 차단 증거. route-only라면 강한 SSRF isolation 미충족으로 보고 |
| PK-08 | traversal/symlink/파일 교체/upload/download 초과·취소 fixture | 허용 root 밖 읽기·쓰기 0, 실행 0, 부분 artifact 정상 노출 0 |
| PK-09 | dummy API key와 전용 임시 계정 fixture로 Keychain/로그/DB/argv/export 검사 | secret 유출 0, locked/denied 처리. 실제 사용자 keychain/auth 파일은 조사 대상 아님 |
| PK-10 | Codex 고정 binary/schema handshake, GUI 로그인 취소/연결 해제, child crash | 기본 stdio 소유권/오류 분리. 실모델 시험은 별도 명시적 비용 승인·최소 한도로 수행 |
| PK-11 | 녹음/브라우저/모델 작업 중 Cmd-Q, crash, double launch, 재시작 | 소유 자식 누수 0, 사용자 프로세스 영향 0, 미확인 결과는 미완료로 복구 |
| PK-12 | signed RC N→N+1 교체, DB migration 실패/rollback, disk 부족·중단 다운로드 | 구버전/새버전·backup 보존, 서명 bundle 불변, GUI만으로 복구 가능 |

권고는 한 가지로 좁혔지만 출시를 보증하지 않는다. 가장 먼저 닫을 empirical gate는 **py2app 전체 bundle closure + signed WKWebView 마이크 + nested Chromium/Codex/STT 실행·종료**다. 재배포 고지, 서명 자격, 강한 network enforcement, 실제 기기 결과가 없으면 이를 문서만으로 완료 처리하지 않는다.
