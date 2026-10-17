# 아키텍처

## 동결된 대화·작업 경계 (2026-09-14)

이 절은 18단계 재검수 전까지 동결된 소스의 보존 경계다. 두 설치 구성에서 시작·노출하지 않는다.
현재 사용량 기록의 프로젝트·대화·작업 조회와 구분하며 [유지보수 경계](maintenance-boundaries.md)를 따른다.

`TasksViewModel`은 프로젝트·페이지·필터·선택 ID와 가능한 조작을 계산한다.
`TasksPage`는 화면을 표시하고 `TaskService`에 명령을 보낸다. 서비스가 소유한 작업 스레드의
`TaskWorker`에서 조회·후보 분석·암호화 저장·실행을 처리한다.

`ConversationCatalog`는 목록을, `HistoryReader`는 직렬 페이지 조회와 원본 해시를 담당한다.
`CandidateAccumulator`는 원문 전체를 보관하지 않고 명시적 후보만 누적한다. 미등록 후보의
보관 범위는 프로젝트별 최근 10개와 현재 과거 페이지이며, 열려 있는 검토의 원본 식별자도 유지한다.
`QueueRepository`는 DB v7에서 후보 연결 키와 암호화된 완료 최소 요약을 관리한다.

`QueueExecutor`는 조회용 서버와 별개인 `DesktopExecutionAdapter`의 실행 연결을 사용한다.
`ExecutionCapabilities`는 조회·전체 관측·기존 대화 실행·승인·소유 작업 중단을 구분하고,
`ExecutionSnapshot`은 계정·연결 세대·관측 시각·실행 대화·충돌 경로를 전달한다.
현재 Desktop 공유 연결 계약은 검증되지 않아 자동 실행은 비활성화한다.
독립 조회 서버의 로드 목록이나 JSONL 활동 추정으로 이 검증을 대체하지 않는다.

승인 요청은 작업 상세와 `TaskNotificationBridge`를 거쳐 기존 알림·이동 처리기로 연결한다.
해결된 요청이나 연결 세대가 지난 요청은 대화상자와 알림의 동작 대상에서 함께 만료한다.

## 목표

외부 연동 실패가 펫 자체를 중단시키지 않고, 개인정보가 포함된 원문을 상태 표시나
저장소로 전달하지 않는 것을 핵심 경계로 둡니다.

## 10단계 설치 구성 경계

`pet-only` 진입점은 `PetRuntime`과 펫 UI만 조립한다. `pet-assistant` 진입점은
기존 `ApplicationRuntime`을 조립하지만 대화 후보·대기열 서비스는 첫 공개에서 시작하지
않는다. 두 Public 번들은 같은 소스와 펫 자산을 사용하며 설치기는 선택한 번들만
별도 런타임 폴더에 둔다. 펫 단독 번들에서 비서 모듈·Codex 보조 실행 모드·DB 초기화는
허용하지 않는다.

기본 `PetBubbleController`와 `ui/bubble_models.py`는 펫 UI의 디자인 미리보기를
담당한다. 비서 구성은 `ActionableBubbleController`를 주입해 상태·알림을 연결한다.
상태 의미와 기한의 책임은 [말풍선 구조 규칙](bubble-architecture.md)에 따른다.

```text
Codex hook / JSONL / 로컬 알림
              ↓
     integrations 어댑터
              ↓
   기능 서비스와 불변 snapshot
              ↓
        AppCoordinator
       ┌──────┼────────┐
Assistant Center  Pet Overlay  System Tray
```

## 책임

- `application`: 객체 조립, 시작·종료 순서와 기능 간 신호 연결
- `features`: 알림·사용량·펫·설정의 서비스와 ViewModel
- `integrations`: Codex app-server, hook, JSONL, IPC와 Windows 기능
- `state`: 외부 이벤트 정규화, 세션 집계와 표시 정책
- `storage`: SQLite 연결, migration과 repository 구현
- `pet`: 펫 패키지, 렌더링, 입력, 행동과 화면 배치
- `ui`: 트레이, 말풍선, 사용량 위젯과 그리기. 설정과 비서 화면은 `application/settings_ui`가 띄우는 Electron 설정창이 맡는다.

## 의존성 원칙

- 상태 모델과 저장 계약은 UI를 import하지 않습니다.
- UI는 ViewModel과 불변 snapshot을 통해 상태를 읽고 명령을 호출합니다.
- 외부 시스템은 integrations 어댑터 안에서 실패를 격리합니다.
- `ApplicationRuntime`만 구체 구현을 조립합니다.
- 데이터베이스 연결은 `DatabaseManager` 하나가 소유합니다.

## 수명주기

앱 시작 시 단일 인스턴스를 확인하고 펫을 복구 가능한 방식으로 로드한 뒤 runtime을
조립합니다. runtime은 로그 모니터, IPC 서버와 사용량 서비스를 순서대로 시작합니다.
종료는 UI, 서비스, 외부 연결, 데이터베이스의 역방향으로 실행하며 모든 close 작업은
멱등이어야 합니다.


## 사용량·저장소 실행 경계

GUI의 `UsageWorkerService`는 제한된 명령 큐와 불변 스냅샷만 제공한다. 전용 QThread 안에서
`CodexUsageService`, App Server QProcess와 SQLite 연결을 생성·사용·종료한다. QSettings는
GUI가 소유하고 작업 스레드에는 필요한 설정 값만 복사한다. 진단 화면의 저장소 참조는
상태 전용이며 DB 연결을 노출하지 않는다. 기록 삭제는 요청 당시 계정·세대를 대조한 뒤 처리한다.

`ThreadedCodexLogMonitor`는 별도 스레드에서 파일 탐색·tail·정제를 수행하고 허용된 이벤트와
상태 사본만 GUI에 전달한다. 회차별 1MiB/200개/20ms 한도와 파일별 이어읽기를 사용한다.
원문은 로그 작업 스레드의 제한된 파서 버퍼에만 존재한다. 실제 단일 디스크 접근의 지연은
이 시간 한도로 보장할 수 없다.

## 계정·기기 분리와 로그 읽기 기준

계정과 기기 관측을 분리하고 UI shell과 작업 흐름을 분리한다. 설치 의존성의 기준은 `requirements*.txt`이며 pyproject의 프로젝트 정보는 wheel 배포 계약이 아니다. JSONL의 활성/보관 로그는 공통 제한 tail 커서로 읽고 시작 replay는 알림을 억제한다. heartbeat는 활동 상태 유지에만 사용한다.
