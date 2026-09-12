# DeepTwin

DeepTwin은 **자체 호스팅 가능한 웹 기반 오픈소스 멀티에이전트 프레임워크**로 공개하는 것을
목표로 개발 중이다. 현재 저장소에는 프로젝트 라이선스가 아직 추가되지 않아 공개·재배포 가능한
오픈소스 릴리스 상태가 아니다. 릴리스에서 지원할 **공식 최종사용자 제품·관제면은 브라우저
UI**이며, 이 UI가 재사용 가능한 프레임워크 코어의 첫 번째 공식 참조 구현이다. 사용자는 이 화면에서 업무 설명과 자료·음성을 입력하고,
멀티에이전트 그래프를 비교·실행하며, 형식별 산출물과 DeepTwin 개선·재평가·사람 승격
과정을 다룬다.

## 제품 경계

Docker Engine, Docker Desktop, Compose와 Portainer 같은 배포 콘솔·도구는 인스턴스를
배포·운영하기 위한 외부 권한면이지 DeepTwin 제품 UI가 아니다. 서버 내부의 Codex CLI,
모델·브라우저·문서·음성 worker와
개발 명령도 구현 수단이며 사용자가 DeepTwin을 조작하는 제품 표면이 아니다. 네이티브
데스크톱 래퍼, 내장 WebView, macOS 앱 번들·DMG와 제품 런처는 현재 릴리스 경계에 포함되지
않는다.

Claude는 사용자가 명시적으로 연결한 API 경로만 지원한다. Codex 구독은 DeepTwin 서버가
소유·격리하는 어댑터와 관리형 실행기를 통해 사용하며, Codex API는 별도로 선택하는 경로다.
어느 경우에도 사용자가 제공자 앱이나 CLI 안에서 DeepTwin을 사용할 필요가 없다. 에이전트의
브라우저 조회·외부 도구 호출·PDF를 포함한 다양한 형식의 산출물 생성도 프레임워크가 권한과
계보를 통제하는 서버 측 실행 기능이며, 브라우저 UI에서 구성·관제·검토한다.

재사용 가능한 코어는 브라우저/API 구현과 분리된 graph·authority·artifact·evidence·growth
계약을 제공한다. 확장은 공통 메시지 하나가 아니라 종류별 코어 소유 semantic port에 묶이며,
실행형 제3자 확장은 외부 운영자가 digest-pinned OCI service/descriptor와 signed receipt로
staging한다. 제품은 Docker socket·runtime code download·container lifecycle 권한을 갖지 않는다.
공식 브라우저의 `설정 > 확장`은 이미 staging·qualification된 binding을 관찰·통제하고,
향후 별도 설치 가능한 extension-author SDK와 HTTP/OpenAPI client가 같은 계약을 사용한다.
이 ADR-014 경계는 설계 보정 상태이며 T086 독립 재검토와 T087 구현이 아직 열려 있다.

## 현재 상태

현재 저장소는 개발 중이며 릴리스 적격 배포물이 아니다. `app/`의 브라우저 기반 개발
슬라이스와 `control-prototype/`의 합성 관제 시제품을 최종 배포·전체 엔진·실사용 효과의
증거로 해석하지 않는다. `packaging/macos/`와 관련 증거는 ADR-009 이전 네이티브 가정의
역사적 실험으로만 보존한다.

현재 정본은 다음 문서다.

- [헌법](.specify/memory/constitution.md)
- [제품 명세](specs/001-autonomous-release/spec.md)
- [설계 결정](specs/001-autonomous-release/decisions.md)
- [구현 계획](specs/001-autonomous-release/plan.md)
- [작업 목록](specs/001-autonomous-release/tasks.md)
- [ADR-014 보정 근거](specs/001-autonomous-release/evidence/extension-framework-design-remediation.md)

저장소에 적힌 셸 명령은 개발·검증용이다. 최종사용자에게 CLI 사용을 요구하는 제품
사용법이나 설치 흐름이 아니다.
