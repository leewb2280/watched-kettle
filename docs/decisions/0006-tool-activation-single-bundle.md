# ADR 0006: 비서 번들은 하나로 두고 도구마다 사용 스위치를 둔다

- 상태: 승인 — 2026-10-16, 0.15.3 첫 공개 직후
- 관련: 로드맵 13단계(Claude Code를 연동 제공자로 추가), 15단계 설치 구성, [말풍선 구조](../bubble-architecture.md) 2절

## 배경

펫 + 비서를 설치하며 Codex만 골라도 Claude Code가 화면에 나오고 대화 기록을 읽는 경우가 있었다. 원인은 번들이 아니라 설정이었다.

- 한 도구에 스위치가 둘이었다. 연결·진단의 hook 연결 스위치와 사용량 화면의 사용량 스위치가 따로 움직였다.
- Claude Code 사용량 스위치는 값이 없으면 Codex 값을 물려받았고, 첫 실행에 그 값이 저장됐다. 예전 설치기·무인 업데이트·소스 실행에서 그대로 남았다.
- Claude Code를 끌 때 관리 status line은 남았다. 설치기는 그 표식을 보고 다음 업그레이드에서 Claude Code를 "연결됨"으로 미리 체크했다.
- 무인 새 설치는 `~/.claude`가 있으면 Claude Code hook을 설치했다.
- 꺼진 도구도 계속 읽혔다. Codex는 로그 tail·계정 확인·대화 메타데이터 worker가, Claude Code는 `settings.json` 상태 확인이 스위치와 관계없이 돌았다. 남은 hook의 이벤트도 출처와 관계없이 펫에 닿았다.

## 검토한 방법

| 항목 | 번들 하나 + 동작 차단 | Claude Code 별도 구성 분리 |
|---|---|---|
| 줄어드는 크기 | 없음 | Claude 전용 모듈 9개, 소스 약 107KB. 번들 479MB의 0.1% 미만 |
| 코드 변경 | 스위치·차단 지점 | 위에 더해 Claude Code를 참조하는 모듈 28개(약 280곳)의 import 경계, 훅 브리지, 설정창 분기 |
| 구성 수 | 2(펫만, 펫 + 비서) | 4(펫만, 펫 + Codex, 펫 + Claude Code, 펫 + 둘 다) |
| 새 설치 파일 | 약 307MB | 약 600MB로 추정(구성마다 압축 후 약 150MB) |
| 구성 전환 검수 | 2가지 | 12가지 |
| 나중에 다른 도구 켜기 | 설정창 스위치 | 구성 전환 재설치 |

13단계는 Claude Code를 "새 설치 구성이 아닌 비서 확장팩의 연동 제공자"로 정했다. 훅 브리지·출처별 세션 집계·DB migration·위젯이 두 출처를 함께 다룬다. 분리는 이 결정을 뒤집고, 앞으로 선택 기능마다 구성이 두 배씩 늘어난다. 16~19단계(펫 이동·듀얼 펫·대화 재검수·일정 알림)도 분리로 얻는 것이 없다.

## 결정

비서 번들은 하나로 둔다. 도구(Codex, Claude Code)마다 **사용 스위치 하나**를 둔다.

- 켜면 그 도구의 관리 hook 설치와 사용량 수집을 함께 켠다. hook이 막혀도 스위치는 켜고 경고만 보인다. Codex는 hook 없이도 로그로 활동을 받는다.
- 끄면 관리 hook과 Claude Code 관리 status line을 지운다. 파일 변경이 막혀도 스위치는 끈다. 그 도구의 파일 읽기·프로세스 실행·이벤트 수신을 멈추고, 펫 세션과 프로젝트 카드를 지운다. 홈·사용량·기록·추세·트레이·위젯에서 숨긴다. 저장된 기록은 지우지 않는다.
- 스위치는 연결·진단 화면에만 둔다. 꺼진 도구는 스위치와 짧은 설명만 보인다.
- 저장 키는 기존 `usage/enabled`(Codex)와 `usage/claude_code_enabled`(Claude Code)를 그대로 쓴다. Claude Code는 값이 없으면 꺼짐이다.
- 처음 실행할 때 한 번(`internal/toolActivation`) Claude Code 스위치를 이 앱의 관리 hook·status line 유무로 다시 정한다. Codex 값은 그대로 둔다.
- 설치기는 업그레이드할 때 앱의 스위치를 처음 선택으로 보여 준다. 무인 새 설치는 `/CLAUDECODE=on`이 없으면 Claude Code를 끈다.

구현은 `watched_kettle/features/integrations/activation.py`(미리보기·적용·이전), `application/runtime.py`(서비스 시작·중지와 정리), `integrations/codex_ipc.py`(꺼진 출처의 이벤트 차단), `application/integration_setup.py`(설치기 경로)다.

## 결과

- Codex만 고른 PC는 Claude Code 파일을 읽지 않는다. 연결·진단 화면이 `~/.claude` 폴더가 있는지만 본다.
- 이전 버전에서 Claude Code를 hook 없이 사용량만 켜 둔 사용자는 이전 때 꺼진다. 연결·진단에서 다시 켜면 hook도 함께 설치된다.
- hook과 사용량을 따로 켜고 끄던 조합(예: 사용량만 끄고 펫 활동은 유지)은 더 지원하지 않는다.
- 디스크에서 Claude Code 코드를 아예 빼야 하는 요구가 생기면 이 ADR을 다시 검토한다.
