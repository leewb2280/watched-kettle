# ADR 0007: 앱 안 업데이트는 바뀐 파일만 받는다

- 상태: 승인 — 2026-10-16, 0.15.3 첫 공개 직후
- 관련: 릴리스 계획 4절 사용자 요청 업데이트, [ADR 0006](0006-tool-activation-single-bundle.md)
- 후속: 0.15.5부터 아래 파일은 별도 공개 저장소의 Release에 올리고, 본 저장소 Release에는 통합 설치기와 `.sha256`만 둔다([ADR 0008](0008-update-repository.md))

## 배경

앱 안 업데이트는 매번 Public 통합 설치기 전체를 받았다. 0.15.2 기준 307MB이고 펫만·펫 + 비서 두 구성이 모두 들어 있었다. 설치 단계만 21~23초 걸렸다(설치기 로그 기준). 압축이 하나의 덩어리(`SolidCompression=yes`)라서 건너뛰는 구성도 풀어야 했다.

0.15.2→0.15.3의 실제 차이는 펫 + 비서 번들 272개 파일 중 12개, 13.5MB(2.8%)였다. Electron 설정창(327MB)과 PySide6(102MB)는 바뀌지 않았다. 공개된 앱의 업데이트 코드가 어떤 Release 파일을 고르는지는 사용자 PC에 고정되므로, 공개 사용자가 늘기 전에 정한다.

## 결정

Release마다 통합 설치기와 함께 다음을 만든다. 이름의 `<kind>`는 공개판 `public`, 시험 채널 `public-update-test`다.

| 파일 | 내용 |
|---|---|
| `WatchedKettle-<v>-<kind>-unsigned-setup.exe` | 새 설치·구성 전환용 통합 설치기. 0.15.x 클라이언트도 이것을 받는다 |
| `WatchedKettle-<v>-<kind>-<edition>-update-unsigned-setup.exe` | 구성별 업데이트 설치기. 같은 구성 설치판만 업데이트한다 |
| `WatchedKettle-<v>-<kind>-<edition>-files.json` | 번들의 `PACKAGE_MANIFEST.sha256.json`. 다음 릴리스의 변경분 기준이며 앱은 받지 않는다. 0.15.4부터 Release에 올리지 않고 빌드 쪽에 보관한다 |
| `WatchedKettle-<v>-<kind>-<edition>-from-<u>.zip` | 직전 최대 3개 버전 `<u>` 대비 바뀌거나 새로 생긴 파일과 새 manifest |
| `WatchedKettle-<v>-update.json` + `.sha256` | 위 파일들의 이름·크기·SHA-256과 설치기 개정 번호를 담은 색인 |

앱은 확인할 때 색인을 받아 다음 순서로 고른다.

1. 자기 버전에서 오는 변경분 zip. 단, 색인과 자기 번들의 설치기 개정 번호(`BUILD_PROFILE.txt`의 `installer_revision`)가 같아야 한다.
2. 자기 구성의 업데이트 설치기.
3. 통합 설치기. 색인이 없는 릴리스나 색인을 읽지 못했을 때다.

변경분을 받으면 다음 순서로 적용한다.

1. 백그라운드 스레드에서 `{app}\runtime\<edition>.next`를 만든다. zip의 파일은 풀고 SHA-256을 확인한다. 나머지는 현재 runtime에서 하드링크(실패하면 복사)하고 해시를 다시 확인한다. 하나라도 맞지 않거나 manifest 밖 경로가 있으면 지우고 구성별 업데이트 설치기로 바꿔 받는다.
2. 마지막에 `.ready` 표식을 쓴다.
3. 펫이 곧 다시 켜진다고 알린 뒤 `{app}\WatchedKettle.exe --apply-staged-update`를 띄우고 종료한다.
4. 실행기(`packaging/launcher`)가 현재 runtime 폴더 이름을 `.old`로 바꾸고 `.next`를 그 자리로 옮긴다. 폴더 안 파일이 열려 있으면 이름 바꾸기가 실패하므로 최대 30초 재시도하며 앱·설정창·hook 브리지 종료를 기다린다. 실패하면 되돌리고 `runtime\update-result.txt`에 남긴다.
5. 새 앱이 시작하면 결과를 읽고 남은 `.next`·`.old`와 받은 파일을 지운다. 설치판(패키지 실행)이면 Windows `설치된 앱`의 버전 표시(`DisplayVersion`)를 고친다.

일반 시작도 실행기가 준비된 폴더를 한 번 시도한다. 앱이 이미 실행 중이면 기다리지 않는다.

## 설치기 개정 번호

변경분은 runtime 폴더만 바꾼다. 실행기·설치기 로직이 바뀐 릴리스는 전체 설치기로만 업데이트해야 한다. `packaging/installer-revision.json`의 `sha256`은 `.iss`와 실행기 소스의 해시다. `scripts.validate_project`가 다르면 실패시키므로 두 파일을 바꾸면 번호를 올려야 한다. `build_windows.ps1`이 번호를 `BUILD_PROFILE.txt`에 쓴다. `scripts/build_update_assets.py`는 같은 번호의 이전 릴리스로만 변경분을 만든다. 번호는 공개 전 변경에도 그대로 올린다. 값 자체는 같고 다름만 비교한다.

## 그 밖의 결정

- 통합 설치기의 구성별 runtime 항목에 `solidbreak`를 넣는다. 그래서 건너뛰는 구성의 압축은 풀지 않는다.
- 제거기는 `{app}\runtime`을 통째로 지운다(`[UninstallDelete]`). 변경분이 만든 경로는 Inno 기록에 없기 때문이다.
- 내려받기·준비 시간과 크기를 `application.update` 로그(`download_finished`, `staging_finished`, `fallback`)에 남긴다.

## 신뢰 범위와 한계

- 체크섬은 같은 Release에서 받는다. 파일 손상과 잘린 내려받기는 막지만, Release를 올릴 권한을 빼앗긴 경우까지는 막지 못한다. 기존 설치기 경로와 같다. 코드 서명을 정하면 서명 확인을 더한다.
- 하드링크한 파일은 `.old`와 새 폴더가 잠시 같은 내용을 가리킨다. `.old`는 다음 시작에 지운다.
- 폴더를 바꾸는 짧은 순간의 hook 호출은 실행 파일을 찾지 못할 수 있다. 실패는 fail-open이다([ADR 0003](0003-fail-open-integrations.md)).
- 0.15.3(공개판)까지의 설치판은 이 규칙 이전의 앱이라 다음 업데이트를 통합 설치기로 받는다. 그래서 다음 릴리스도 통합 설치기를 같은 이름 규칙(`WatchedKettle-<v>-public(-unsigned)-setup.exe`와 `.sha256`)으로 계속 올린다. 이 기능이 들어간 버전부터 변경분을 쓴다.
- 직전 3개 버전보다 오래된 설치나 개정 번호가 다른 설치는 구성별 업데이트 설치기를 받는다.
