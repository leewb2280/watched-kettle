# 유지보수 경계와 분리 기준

## 책임을 나누는 기준

입력 검증, 흐름 조정, 규칙·계산, 외부 작업, 화면 표시를 구분한다. 역할마다 파일이나
클래스를 만들지는 않는다. 먼저 같은 파일의 비공개 함수로 추출하고 독립된 책임이
확인되면 모듈로 옮긴다. 줄 수는 검토 신호이며 강제 분리 기준이 아니다.

변경하는 경계는 아래 다섯 항목으로 설명할 수 있어야 한다.

| 항목 | 기록할 내용 |
|---|---|
| 책임 | 어떤 요구·정책이 바뀔 때 수정하는가 |
| 입출력 | 허용한 입력, 반환 값과 실패 |
| 상태 소유자 | 누가 상태를 보관하고 변경하는가 |
| 부수효과 | 저장·신호·IPC·프로세스 작업을 누가 수행하는가 |
| 수명 | 생성·초기화·취소·종료 조건 |

같은 변경 이유를 가진 코드만 공통화한다. 비슷한 모양을 이유로 범용 처리기나
기반 클래스를 만들지 않는다. 조회와 변경을 구분하고 저장·revision·변경 신호를
모든 명령에 무조건 적용하지 않는다. 전체 runtime을 새 객체로 넘겨 결합을 숨기지 않는다.
검사는 내부 함수명·파일 크기보다 동작과 경계를 검증한다.

## 설정과 화면의 적용 기준

설정 진입점은 구성·실행 가능 여부를 확인하고 기능별 처리를 선택한다. 개별 작업의
검증 순서, 부분 실패와 저장·신호 책임은 명시적으로 유지한다. App이 설정 snapshot과
명령 큐를 소유한다. 기능별 훅은 조회·구독·취소·늦은 응답 폐기와 편집 상태를 담당하고,
화면은 표시 값과 콜백을 받는다. 훅 추출은 공유 상태 생성이나 초기화 시점 변경이 아니다.
화면 전환만으로 초안·필터·선택·대화상자를 초기화하지 않는다.

### 현재 설정 구현의 책임 표

| 경계 | 입출력·상태·부수효과·수명 |
|---|---|
| `settings_protocol.py`와 생성기 | Qt 독립 DTO·명령 노출 명세에서 TS 타입·Electron 목록을 생성한다. 제품 상태를 소유하지 않는다. 생성물 최신성은 계약 검사에서 대조한다. |
| `CoreSettingsAdapter.execute` | 구성·일괄 작업 제한과 명령 선택을 소유한다. 펫·일반 설정·테마 처리를 비공개 메서드에 위임하고, 기존의 조회·변경·부분 실패별 저장·revision·신호 순서를 유지한다. |
| `AssistantSettingsAdapter.execute` | 계정 epoch 확인과 비서 명령 선택을 소유한다. 조회·탐색·변경 처리를 위임하고 기존 usage/activity 신호를 전달한다. |
| 펫·위젯 고정 단축키 | `application/click_through.py`가 두 runtime에서 한 번 만들어져 전역 단축키(`integrations/windows_hotkeys.py`)를 등록·해제하고, 눌리면 펫·위젯의 고정을 토글한다. 위젯 단축키는 비서 runtime만 연결한다. runtime 종료 때 UI보다 먼저 해제한다. |
| 공통 더블클릭 조정 | `application/pet_actions.py`가 설정 조회·홈/앱 열기만 수행한다. 앱 열기는 `integrations/windows_apps.py`의 공통 창 활성화를 Codex·VS Code launcher가 함께 쓴다. 두 runtime이 펫 신호를 한 번 연결하고 종료 때 해제한다. 수집 스위치와 독립적인 사용자 동작이며 활동 상태·큐를 소유하지 않는다. |
| 공통 홈 | App이 공통 페이지 컨테이너를 유지하고 공통 펫 영역·선택적 비서 영역을 합성한다. 기존 상위 훅·snapshot·명령 큐를 재생성하지 않는다. |
| `App` | 공통 설정 snapshot·계정 문맥·직렬 명령 큐의 유일한 소유자다. 화면 분리로 큐를 추가하지 않는다. |
| `core/useCoreSettings` | 펫 목록·미리보기 요청 세대와 선택 화면 상태를 소유한다. 페이지·표시 여부 변화의 기존 취소 조건을 유지한다. |
| `core/useBubbleEditor` | 초안·원본 revision·미리보기 요청 세대·편집 오류를 소유한다. 명시적 적용 때만 저장 명령을 보내고, 충돌 후 재불러오기 정책을 유지한다. 화면 전환에도 같은 상위 훅 인스턴스를 사용한다. |
| `assistant/useAssistantSnapshots` | 표시 중인 페이지에 필요한 조회와 오래된 응답 폐기를 소유한다. 계정·서비스 상태를 직접 바꾸지 않는다. |
| `assistant/useUsageHistory` | 출처·필터·정렬·선택·작업 기록 대화상자와 탐색 명령을 소유한다. 동결된 작업 대기열과 별개인 현재 사용량 기록이다. |
| `assistant/useNavigationAck` | 실제 화면·알림 표시를 기다리는 ACK 전송만 담당한다. 최종 확인·기한·계정 유효성은 Python host가 판단한다. |
| `core/*Page`, `assistant/*Page`와 대화상자 | 값과 콜백을 받아 기존 DOM을 표시한다. 페이지별 표시 컴포넌트에 공통 상태·큐·서비스 연결을 새로 만들지 않는다. |

명령의 wire 이름·version 1·오류 코드·기존 검증을 유지한다. renderer 공개 목록과
Electron main 전용 파일·창 명령을 분리한다. 동적 진단 값은 JSON 값/unknown으로 한정하고,
정적 타입을 맞추려고 외부 입력 검증이나 개인정보 정제를 제거하지 않는다.
`asdict`·진단 정제처럼 Python이 필드 정보를 잃는 지점의 제한된 타입 단언은 실제 응답
계약 검사로 대조한다. 전체 응답을 단언해 타입 검사를 우회하지 않는다.

## 언어팩 표시 경계

번역 사전의 발견·검증·활성 실행 수명과 설정 저장·화면 표시 책임은
[언어팩 구조](localization-architecture.md)를 따른다. 설정 DTO와 노출 목록은 기존 생성기로 갱신한다.

## 동결 기능

후보 분석·검토·작업 대기열·자동 실행과 전용 연결·저장소는 **18단계 재검수 전까지 동결**한다.
현재 제품의 프로젝트·대화·작업별 사용량 기록은 동결 대상이 아니다.
기존 DB migration·암호화·데이터 보존과 배포·실행 경계 검사는 유지한다.
동결 중 수정은 보안 문제, 현재 제품에 영향을 주는 결함, 공용 경계의 호환성 보수로 제한한다.
재개는 Desktop 공유 실행 계약의 실환경 확인과 재도입 범위 결정 이후에 한다.

| 검사 분류 | 대표 범위 | 유지 정책 |
|---|---|---|
| 출시 기능 | usage, settings_bridge, pet, notifications, project_activity 관련 검사 | 일반 회귀 검사 |
| 데이터·경계 호환성 | structured_storage, task_repository의 migration·암호화·계정 분리, edition 경계 | 동결 중에도 보존 |
| 동결 기능 전용 | task_candidates/catalog/completion/connection/discovery/execution/flow/history/transport, execution_connection/history_flow | 삭제·자동 skip 없이 보존, 실행 정책은 CI 작업에서 별도 결정 |

위 분류는 테스트 실행 범위를 바꾸지 않는다. `test_task_repository`처럼 여러 책임을
검사하는 모듈은 통째로 동결 전용으로 분류하지 않는다.

## 변경 검증

분리와 동작 변경을 같은 단계에서 섞지 않는다. 대표 사례의 회귀 검사를 먼저 확인한 뒤
같은 기준으로 확대한다. 말풍선 관련 작업은 [구조 계약](bubble-architecture.md)의 BA 규칙을 따른다.
빌드 보류 작업에서는 Ruff·타입·문서·계약·빌드 없는 회귀 검사를 개별 실행하고,
UI 빌드가 포함된 전체 check와 Electron·패키지 검증은 미실행으로 명시해 통합 시 수행한다.

### 2026-10-17 적용·검증 기록

기준은 `main`의 `6ed8f7c`, 작업 브랜치는 `codex/maintenance-boundaries`다.
비활성 기능 정책, Qt 독립 설정 DTO와 명령별 생성 타입, 설정 어댑터의 비공개 처리 함수,
페이지별 표시와 계속 마운트되는 기능별 훅을 적용했다. 활동·사용량 서비스 내부의 큰 함수는
이번 범위에 포함하지 않았다. CI workflow·지원 Python 버전·공통 검사 스크립트도 변경하지 않았다.

BA-01·BA-06·BA-07·BA-09·BA-10의 책임 경로를 문서와 검사에 반영했으며 규칙은 변경하지 않았다.
App의 snapshot·명령 큐와 기존 문맥 주입 우선순위, revision·epoch의 런타임 검증을 유지했다.
조회와 저장 후처리는 구분한다. 카탈로그 저장 성공은 동기화·revision 증가·변경 신호가 각각
한 번이며, 실패는 기존 설정 복구와 동기화 재시도 후 한 번만 무효화하는지 회귀 검사한다.

| 실제 실행한 검사 | 결과 |
|---|---|
| `python -m ruff format --check .`, `python -m ruff check .` | 통과, Python 파일 366개 포맷 확인 |
| `python -m mypy watched_kettle/settings_protocol.py scripts/generate_settings_protocol.py watched_kettle/application/settings_ui --follow-imports=silent` | 8개 소스 통과 |
| `node settings-ui/node_modules/typescript/bin/tsc -p settings-ui --noEmit --pretty false` | 통과, 잘못된 인자·응답·내부 명령과 보조 호출 함수의 예상 타입 오류 포함 |
| `python -m scripts.generate_settings_protocol --check` | TS·Electron 생성물 최신성 통과 |
| `python -m scripts.validate_project` | 공개 소스 허용 목록·문서 링크·프로젝트 구조 통과 |
| `node --test settings-ui/scripts/protocol.test.cjs settings-ui/scripts/appearance.test.cjs` | 5개 통과, 실제 IPC 처리기를 VM에서 실행해 송신자·구성·명령 노출 검증 |
| 아래 Python 회귀 모듈 | 255개 중 254개 통과, 기존 Windows 심볼릭 링크 권한 조건으로 1개 skip |

Python 회귀 검사는 `python -m unittest <모듈...> -v`로 다음 모듈을 함께 실행했다.
실제 Qt 어댑터 응답과 데이터가 채워진 Codex·Claude 응답을 DTO에 대조하고, 편집 충돌·
펫 전환·저장 실패·중복 요청·계정 전환·화면 ACK와 동결 기능의 배포 경계를 검사했다.

```text
tests.test_settings_protocol tests.test_settings_bridge
tests.test_pet_batch tests.test_pet_trash tests.test_pet_catalog
tests.test_pet_preferences tests.test_pet_importer
tests.test_bubble_architecture tests.test_bubble_customization
tests.test_bubble_frame tests.test_bubble_timing
tests.test_notification_service tests.test_assistant_notification
tests.test_account_refresh tests.test_user_data_isolation
tests.test_structured_storage tests.test_edition_bundle_files
tests.test_public_export tests.test_public_privacy_scan tests.test_design_tokens
```

skip은 `test_pet_trash.PetTrashTests.test_links_inside_packages_are_not_followed`의
`Windows symlink privilege unavailable`이며 새 skip 정책을 추가하지 않았다.
공개 내보내기 검사는 임시 fixture에서 실행했으며 공개 작업 트리 반영·푸시는 하지 않았다.

**통합 후 필수 확인:** 이번에는 `scripts/check.ps1`과 전체 unittest discovery를 실행하지 않았다.
UI 번들 빌드, 두 구성의 Electron 화면 QA, C# 컴파일을 호출하는 `test_launcher_update`·
`test_private_pack`을 포함한 전체 회귀, 패키지·설치·업데이트 스모크는 보류했다.
새 의존성 설치·업그레이드와 패키지·설치기 생성도 하지 않았다.
화면 QA에서는 페이지 왕복 시 필터·선택·초안·대화상자 수명, 펫·계정 변경과 창 숨김 중 늦은 응답,
충돌 후 재불러오기, 화면 표시 후 ACK를 두 구성에서 확인한다. 빌드 없는 검사 통과가 이 검수를
완료했다는 뜻은 아니다.

### 0.15.5 main 통합

위 표는 개별 브랜치에서 빌드를 보류한 당시 기록이다. Python 3.14·CI 작업과 업데이트
저장소 분리를 main에 병합한 뒤의 정밀 검사·두 구성 Electron QA·남은 검수는
개발 저장소의 0.15.5 비공개 통합 검증 기록을 따른다.
