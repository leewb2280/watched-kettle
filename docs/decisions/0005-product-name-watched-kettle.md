# ADR 0005: 제품명을 Watched Kettle로 변경

- 상태: 승인 — 2026-10-02, 13단계 착수 전
- 관련: 로드맵 13단계 제품명, 15단계 설치 식별자 고정

## 배경

`Codex Desktop Pets`는 Codex 전용을 전제로 한 이름이다. 13단계에서 Claude Code를 연동 제공자로 추가하고, 15단계 첫 공개 뒤에는
설치 식별자를 바꾸지 않는다. 또한 Claude Code hook 설정에 실행 파일 경로가 처음 기록되는 시점이 13단계이므로, 그 전에 이름과 식별자를 정리해야
이전 작업을 한 번으로 끝낼 수 있다. 다른 회사의 상표(Codex, Claude)를 제품명에 넣으면 15단계의 비공식 관계 고지와도 어긋난다.

## 결정

제품명은 **Watched Kettle**이다. 속담 "A watched pot never boils"에서 따왔으며, 펫이 에이전트 작업이라는 주전자를 대신 지켜본다는 뜻이다.
이름에서 파생한 식별자를 아래처럼 한 번에 바꾼다.

| 구분 | 이전 | 이후 |
| --- | --- | --- |
| 표시명 | `Codex Desktop Pets`, `Codex Pets` | `Watched Kettle` |
| 사용자 데이터 | `%LOCALAPPDATA%\CodexDesktopPets` | `%LOCALAPPDATA%\WatchedKettle` |
| 설치 폴더(새 설치) | `%LOCALAPPDATA%\Programs\CodexDesktopPets` | `%LOCALAPPDATA%\Programs\WatchedKettle` |
| 실행 파일 | `CodexDesktopPets.exe`, `CodexPetsSettings.exe`, `CodexPetsHookBridge.exe` | `WatchedKettle.exe`, `WatchedKettleSettings.exe`, `WatchedKettleHookBridge.exe` |
| 시작 프로그램 값·Qt 조직명 | `CodexDesktopPets` | `WatchedKettle` |
| pipe | `codex-desktop-pets-instance-v1`, `codex-desktop-pets-agent-v1`, `codex-pets-settings-*` | `watched-kettle-instance-v1`, `watched-kettle-agent-v1`, `watched-kettle-settings-*` |
| 관리 hook 표식 | `codex-desktop-pets-managed-v1` | `watched-kettle-managed-v1` |
| Python 패키지·배포 이름 | `codex_pets`, `codex-desktop-pets` | `watched_kettle`, `watched-kettle` |
| 환경 변수 | `CODEX_PETS_*`, `CODEX_PET_*` | `WATCHED_KETTLE_*` |
| npm 패키지·PyInstaller spec | `codex-pets-settings`, `CodexDesktopPets.spec` | `watched-kettle-settings`, `WatchedKettle.spec` |
| GitHub 저장소 | 공개 전 비공개 저장소의 이전 이름 | `leewb2280/watched-kettle` |

다음은 바꾸지 않는다.

- **설치기 AppId GUID.** 이름이 아니라 업그레이드 식별자다. 유지하면 Private Beta 설치 위에 그대로 업그레이드된다.
- **작업 키 DPAPI 보조 엔트로피 `codex-pets/task-key/v1`.** 바꾸면 기존에 암호화한 작업 키를 풀 수 없다.
- **실제 Codex 연동을 뜻하는 이름.** `integrations/codex_*`, `--codex-hook-bridge`, 화면의 "Codex 비서" 같은 문구는 Codex 제공자를 가리킨다.
  제공자 일반화는 13단계 범위다.
- 기본 펫 이름 Mori Bot, 과거 CHANGELOG 항목과 생성물 경로 같은 이력 기록.

## 기존 Private Beta 데이터 이전

- 앱 시작 때 새 데이터 폴더가 없고 이전 폴더가 있으면 이전 폴더를 새 이름으로 옮긴다(같은 볼륨 안의 이름 변경). 이전 폴더가
  reparse point이면 옮기지 않는다. 다른 프로세스가 파일을 잡고 있어 옮기지 못하면, 그 실행 동안에는 이전 폴더를 그대로 쓰고 다음 시작에서 다시 시도한다.
- 시작 프로그램에 이전 값이 있으면 새 값으로 바꿔 등록하고 이전 값을 지운다.
- 이전 관리 hook 표식(`LEGACY_MANAGED_MARKERS`)도 계속 관리 항목으로 인식한다. ZIP으로 쓰던 Private Beta에서는 연동 화면에 "경로 변경"으로 보이며,
  복구하면 새 표식과 새 실행 파일로 바뀐다. 앱은 실행 중에 사용자 Codex 설정을 스스로 고치지 않는다.
- 설치기로 펫+비서 구성을 업그레이드하면 설치기가 `--migrate-legacy-hook`으로 이전 표식의 관리 hook만 새 실행 파일로 바꾸고(백업 포함,
  `config.toml`과 다른 hook은 그대로) 이전 실행 파일을 지운다. 옮기지 못하면 연동 설정에서 복구하라고 안내한다. 펫만으로 바꾸거나 제거할 때는
  새 표식과 이전 표식의 관리 hook을 모두 지운다.
- 설치기의 완전 제거는 새 데이터 폴더와 이전 데이터 폴더를 모두 처리한다. 이미 설치된 Private Beta는 기존 설치 폴더(`Programs\CodexDesktopPets`)에
  그대로 업그레이드된다.
- 오래된 레지스트리 설정(`HKCU\Software\CodexDesktopPets\DesktopPet`)을 `settings.ini`로 옮기는 기존 처리는 그대로 둔다.

## 이름을 정한 과정

- 짧은 조어 후보는 같은 분야에 이미 있었다. Deskling과 Perch는 Claude Code를 지켜보는 데스크톱 펫이 같은 이름을 쓰고,
  Sidepaw는 같은 이름의 Electron 데스크톱 동반자 앱이 있으며, Nudgeling은 같은 이름의 소프트웨어 회사가 있다.
- 2026-10-02 웹 검색 기준으로 "Watched Kettle"이라는 앱·회사·브랜드는 찾지 못했다. PyPI·npm 이름과 `.app`·`.dev`·`.io` 도메인은 비어 있다.
  같은 이름의 GitHub 계정과 `.com` 도메인은 이미 다른 사람이 쓰고 있어 쓰지 않는다.
- 상표 DB(KIPRIS·USPTO) 조회는 하지 않았다. 수익 목적이 아니어서 이 상태로 진행하며, 15단계 공개 전에 다시 확인한다.

## 위험과 후속

- 이전 폴더를 옮기기 전에 이전 버전 hook 실행 파일이 이벤트를 쓰면 이전 폴더 아래 `runtime`이 다시 생길 수 있다. 이 이벤트는 60초 뒤 폐기되는
  일회성 데이터이므로 옮기지 않는다.
- 단일 실행 pipe 이름이 바뀌어 이전 버전과 새 버전이 동시에 실행될 수 있다. 설치기는 업그레이드 전에 두 버전의 실행 파일을 모두 닫는다.
- 15단계 첫 공개 뒤에는 위 표의 식별자를 바꾸지 않는다.
