# 펫 패키지 규격

펫 하나는 독립된 디렉터리이며 최소한 `pet.json`과 `spritesheet.webp`를 포함합니다.
`spritesheetPath`는 보안을 위해 펫 디렉터리 밖을 가리킬 수 없습니다.

## 스프라이트

- V1: 1536×1872, 8열×9행
- V2: 1536×2288, 8열×11행
- 원본 프레임: 192×208
- 기본 9개 상태: idle, running-left, running-right, waving, jumping, failed,
  waiting, running, review
- V2의 마지막 두 행은 16방향 바라보기 프레임입니다.

## 주요 매니페스트 필드

설정의 **펫 가져오기**는 다운로드한 정지 PNG/WebP(20MiB 이하)를 검증하고 로컬 패키지로
만듭니다. 기본 9개 상태의 필수 셀과 V2의 마지막 두 행 전체에 그림과 투명 배경이 필요합니다.
정규화한 RGBA 크기·픽셀의 SHA-256으로 `imported-<해시>` ID를 만들고, metadata를 제거한
무손실 `spritesheet.webp`와 `distribution: private` 매니페스트를 저장합니다. 크기는 바꾸지 않습니다.
같은 픽셀인 이미지는 기존 패키지를 재사용하며 덮어쓰지 않습니다. 준비 데이터는 최대 한 건·10분간
메모리에만 두고 취소·재선택·설정창 숨김·연결 종료 시 폐기합니다. 완성한 디렉터리만 목록에 게시하고
웹 metadata나 장식을 추측해 만들지 않습니다.

- `id`: 안정적인 펫 식별자
- `displayName`: 사용자에게 표시할 이름
- `description`: 선택적 한 줄 설명. 아래 언어별 설명이 없을 때 쓴다
- `localizedDescriptions`: 선택적 언어별 설명. `{"en": "...", "en-GB": "..."}`처럼 언어 코드를
  키로 둔다. 현재 언어팩의 언어 코드와 정확히 같은 키, 같은 언어(`en`) 키, `description` 순서로 고른다
- `spritesheetPath`: 패키지 내부 스프라이트 경로
- `spriteVersionNumber`: 1 또는 2
- `distribution`: public 또는 private
- `defaultWidth`, `defaultLookRange`: 선택적 기본 표시 설정
- `idleActivities`: 선택적 자동 행동 목록
- `bubbleTheme`: 선택적 말풍선 테마. 배경 사진·테두리 이미지·스티커 항목은 사용자가 가져온 이미지(`user:` 요소)만 가리킨다. 패키지 이미지는 아래 `frame`으로만 쓴다

## 말풍선 바깥 장식 (`bubbleTheme.frame`)

펫 고유의 말풍선 장식은 `bubbleTheme.frame`에 데이터로 선언합니다. 장식이 있는 패키지의 테마는
`frame_style`이 `pet:<id>`가 되고, 펫을 불러올 때 앱이 장식을 등록합니다. 사용자 펫 폴더에 복사한
패키지도 같은 장식을 씁니다. 수치는 100% 배율 기준 픽셀이며 말풍선 배율에 맞춰 커집니다.

| 필드 | 뜻 |
|---|---|
| `insets` | `[왼쪽, 위, 오른쪽, 아래]` 말풍선 본문 바깥에 확보할 여백(0~120) |
| `contentPadding` | `[위, 아래, 왼쪽 추가]` 본문 안쪽 여백 |
| `innerBorder` | 이중 테두리 안쪽 선의 `color`·`alpha` |
| `halo` | 본문 둘레 후광. `color`, `alpha`, `width`, `minWidth`, `offsetY`, `grow`, `radiusDelta` |
| `backdrop` | 말풍선 표면 아래에 그릴 층 목록(최대 8개) |
| `overlay` | 말풍선 표면 위에 그릴 층 목록(최대 8개) |

층은 `anchor`(본문의 `top-left`·`top-center`·`top-right`·`center-left`·`center-right`·`bottom-left`·
`bottom-center`·`bottom-right`, 또는 왼쪽 위 둥근 모서리의 45° 지점 `arc-top-left`)에서 `x`·`y`만큼
떨어진 곳에 그립니다. 이미지 층은 `image`(패키지 내부 PNG·WebP, 4MB 이하), `width`, `height`를 쓰고,
`mirror`로 좌우를 뒤집을 수 있습니다. `tint`를 주면 이미지를 모양 마스크로 보고 그 색으로 채웁니다.
점 층은 `circle: {"radius", "color"}`입니다. 색은 `#rrggbb` 또는 테마 색 이름(`border`, `shadow`,
`background`, `text`)이며, 테마 색 이름을 쓰면 사용자가 말풍선 색을 바꿀 때 장식 색도 따라갑니다.
`alpha`는 0~255입니다. 실행 중에는 형식이 틀린 층을 그리지 않고 수치는 허용 범위로 맞춥니다.
이미지가 패키지 밖을 가리키거나 없으면 Windows 빌드가 실패합니다.

새 형식을 추가할 때는 기존 버전을 자동 감지하고 잘못된 필드가 안전한 기본값으로
대체되거나 명확한 로드 오류가 되도록 해야 합니다. Public 빌드는 `distribution=public`
자산만 포함합니다.

## 사용자 폴더에서 설치

완성된 펫 디렉터리를 사용자 펫 폴더에 복사하면 기존 로더가 `pet.json`과 스프라이트,
`bubbleTheme.frame`에 선언한 장식 이미지를 읽습니다. 폴더 전체를 준비한 뒤 목록을
새로고침하거나 앱을 다시 실행하세요. PNG/WebP 한 장을 가져오는 기능과 구분됩니다.
