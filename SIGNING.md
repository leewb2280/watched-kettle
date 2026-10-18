# Windows 코드 서명 절차

현재 공개 산출물은 미서명입니다. 빌드 스크립트에는 서명 단계가 들어 있지만 인증서를 지정하지 않으면 건너뛰고 지금과 같은 `-unsigned` 산출물을 만듭니다.

## 서명 범위

인증서를 지정하면 다음을 Authenticode(SHA-256 파일 다이제스트, RFC 3161 SHA-256 타임스탬프)로 서명합니다. 공통 함수는 `scripts/code_signing.ps1`에 있습니다.

| 단계 | 서명 대상 |
|---|---|
| `build_windows.ps1` | 번들의 미서명 `.exe`·`.dll`·`.pyd`·`.node`. 앱·hook 브리지·설정창 실행 파일과 서명 없이 배포된 라이브러리가 포함된다. 이미 서명된 라이브러리는 그대로 둔다 |
| `build_installer.ps1` | 실행기 `WatchedKettle.exe`, 통합 설치기, 구성별 업데이트 설치기, 그 안의 제거 프로그램 |

- 번들 서명은 스모크 검사와 파일 목록(manifest) 생성 전에 한다. 그래서 검사와 부분 업데이트 해시가 서명된 파일을 기준으로 한다.
- 서명된 설치기는 이름에서 `-unsigned`를 뺀다(`WatchedKettle-<v>-public-setup.exe`). 앱의 업데이트 선택 규칙은 두 이름을 모두 받는다.
- 설치기 서명은 Inno Setup의 명령행 옵션(`/S`, `/J`, `/F`)으로 넣는다. 그래서 `packaging/windows-installer.iss`와 설치기 개정 번호는 서명 여부와 관계없이 같다.
- 설치기 서명을 켜면 두 번들의 `WatchedKettle.exe`도 같은 인증서로 서명돼 있어야 한다. 아니면 빌드를 멈춘다.
- `-WithPrivatePets` 지인용 설치기와 비공개 콘텐츠 팩은 오픈소스 프로젝트 밖의 자산을 담으므로 서명하지 않는다. 안의 Public 번들과 실행기는 서명될 수 있다.

## 서명 캐시

타임스탬프 때문에 같은 파일도 서명할 때마다 바이트가 달라진다. 그러면 바뀌지 않은 Electron 실행 파일까지 매 릴리스 부분 업데이트에 실린다. 이를 막으려고 번들 서명은 서명 전 SHA-256과 인증서 지문을 키로 서명된 사본을 보관하고, 같은 입력이면 다시 서명하지 않고 사본을 쓴다.

- 기본 위치는 `%LOCALAPPDATA%\WatchedKettleBuild\signing-cache\<지문>\`이다. `WATCHED_KETTLE_SIGNING_CACHE`로 바꿀 수 있다.
- 인증서를 갱신하면 지문이 바뀌므로 그 릴리스는 모든 대상을 다시 서명한다. 그 버전의 부분 업데이트는 평소보다 커진다.
- 캐시를 지워도 결과의 유효성에는 영향이 없다. 다음 빌드가 다시 서명할 뿐이다. 캐시 사본의 서명이 맞지 않으면 빌드가 멈추므로 해당 폴더를 지우고 다시 빌드한다.

## 설정

| 항목 | 지정 방법 | 기본값 |
|---|---|---|
| 인증서 지문(SHA-1, 40자리 16진수) | `-SigningCertificateThumbprint` 또는 `WATCHED_KETTLE_SIGNING_THUMBPRINT` | 없음(서명 안 함) |
| 타임스탬프 서버 | `WATCHED_KETTLE_SIGNING_TIMESTAMP_URL` | `http://time.certum.pl` |
| signtool | `WATCHED_KETTLE_SIGNTOOL` | 최신 Windows SDK의 x64 `signtool.exe` |

인증서는 현재 사용자 인증서 저장소(`Cert:\CurrentUser\My`)에서 찾는다. 클라우드 서명(예: Certum SimplySign Desktop)은 연결돼 있는 동안 인증서를 이 저장소에 보인다. 빌드는 시작할 때 인증서가 있는지, 코드 서명 용도인지, 만료되지 않았는지를 먼저 확인한다. 개인 키와 비밀번호는 저장소·빌드 로그·설치 파일에 넣지 않는다.

## 릴리스 절차

1. 공개 게시자와 인증서의 주체가 일치하는지 확인한다.
2. 서명 서비스를 연결하고, 같은 PowerShell 창에서 지문을 지정한다.

   ```powershell
   $env:WATCHED_KETTLE_SIGNING_THUMBPRINT = '<인증서 지문>'
   ```

3. 평소 릴리스 명령대로 두 구성 번들, 설치기, 업데이트 자산을 순서대로 만든다. 업데이트 자산은 서명된 설치기와 번들에서 만들어야 하므로 서명 전 체크섬과 목록을 재사용하지 않는다.
4. Windows SDK `signtool verify /pa /all /v`로 앱·hook 브리지·설정창·실행기·설치기를 확인하고 게시자·체인·타임스탬프·만료 시각을 기록한다.
5. 깨끗한 Windows 계정에서 설치·업데이트·취소·제거·데이터 보존을 다시 검수한 뒤 게시한다. SmartScreen과 Smart App Control 동작은 실제 내려받은 파일로 확인하며, 자동 검사 통과로 기록하지 않는다.

명령 옵션 기준: [Microsoft SignTool 문서](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool).
