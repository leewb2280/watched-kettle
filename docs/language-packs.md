# Language packs / 언어팩

Watched Kettle includes Korean and English. Open **App settings → Language** to choose
a pack, then click **Restart app** at the end of the button row. The app restarts and reopens
App settings in the selected language. The first choice follows the installer language;
an explicit app choice takes priority.

한국어와 영어를 기본 제공합니다. **앱 설정 → 언어**에서 고른 뒤 버튼 줄 오른쪽의
**앱 다시 시작**을 누르면 선택한 언어로 앱 설정이 다시 열립니다. 처음에는 설치 언어를
따르고, 앱에서 저장한 선택이 우선합니다.

## Edit the app's text / 앱 문구 직접 고치기

1. Select the language to start from and click **Copy as editable pack / 편집용 팩으로 복사**.
   The app writes a new pack (ID `custom.<locale>.<n>`) with every message, selects it
   and opens its folder. Existing packs are never changed.
2. Edit `value` in `messages.json`. `reference.json` lists each message's Korean source,
   official English, the text shown when copied, the screen that shows it, variables
   and plural forms. The app does not load `reference.json`.
3. Click **Reload language packs / 언어팩 다시 읽기** to check the pack, then **Restart app / 앱 다시 시작** at the end of the button row.

Entries that cannot be used (wrong variables, invalid plural forms, unknown keys, ...)
are listed under the selected pack with their key and reason; those messages keep
showing fallback text until fixed. File paths and file contents are not shown.

설정창에서 고칠 언어를 고른 뒤 **편집용 팩으로 복사**를 누르면 전체 문구가 담긴 새
팩을 만들고 선택한 뒤 폴더를 엽니다. `messages.json`의 `value`를 고치고 **언어팩 다시
읽기**로 문제를 확인한 다음 버튼 줄 오른쪽의 **앱 다시 시작**을 누르세요. 잘못 고친 항목은 키와 사유가 언어
설정에 표시되고, 고치기 전까지 대체 문구로 보입니다. 복사본은 원본 팩의 검토 필요
표시를 그대로 유지합니다. 다른 언어의 공식 팩으로 보완되던 항목은 복사본에서 빈
값(미번역)으로 남습니다.

## Install a community pack / 사용자 팩 설치

1. Use **Open language pack folder / 언어팩 폴더 열기**.
2. Copy one folder containing `manifest.json` and `messages.json` into it.
3. Click **Reload language packs / 언어팩 다시 읽기**, select the pack and restart.

The folder is under `%LOCALAPPDATA%\WatchedKettle\language-packs`.
Updates and uninstall's **Keep data / Delete history only** preserve it. **Delete all**
removes it. Packs are local text data; they cannot run scripts or load fonts/images.
Folders whose names start with `.` are ignored.
Missing or invalid messages in a pack use the official pack of the same language,
otherwise English, and finally Korean. A pack can therefore change only a few
messages. If the selected pack disappears or becomes unreadable, the app starts in
Korean and preserves the saved selection so it can be repaired.

사용자 팩에 빠지거나 잘못된 문구는 같은 언어의 공식 팩(한국어·영어), 그 밖의 언어는
영어, 마지막으로 한국어로 보완합니다. 예를 들어 `en-GB` 팩은 고친 문구만 담아도
나머지는 공식 영어로 보입니다.

같은 언어의 여러 제작자 팩을 설치할 수 있습니다. 팩 ID가 중복되면 그 사용자 팩들은
선택할 수 없습니다. 설치된 팩은 자동 다운로드·업데이트하지 않습니다.
현재는 왼쪽에서 오른쪽으로 배치하는 언어만 지원합니다.

## Format / 형식

`manifest.json`:

```json
{
  "schemaVersion": 1,
  "id": "community.example",
  "locale": "en-US",
  "name": "Example English",
  "author": "Translator",
  "version": "1",
  "catalogVersion": 1
}
```

`messages.json`:

```json
{
  "language.title": {
    "sourceRevision": 1,
    "value": "Language"
  },
  "bubble.more_projects": {
    "sourceRevision": 1,
    "value": {
      "one": "{count} more project",
      "other": "{count} more projects"
    }
  }
}
```

Keep IDs and variable names unchanged. Variables can be reordered within a complete
sentence. Formatting expressions, attribute access, HTML and control codes are not
supported. Plural messages use the catalog's numeric variable and the locale's CLDR
categories; `other` is required. Use a concrete BCP 47 code from
`watched_kettle/localization/resources/locales.json`, the supported intersection of
Babel and the pinned Electron runtime. ICU modifiers, `root` and `und` are rejected.
`official.*` IDs are reserved for bundled packs.

문구 ID는 문장을 다듬어도 유지합니다. `sourceRevision`은 번역한 원문의 revision입니다.
오래된 revision의 유효한 번역은 계속 쓰되 검토 필요로 표시합니다. 변수 이름이나
필수 변수가 틀리면 해당 항목만 위 순서로 보완합니다. 알려지지 않은 키는 무시합니다.
번역률은 유효한 번역 항목 수이며 번역 품질의 보증이 아닙니다.

## Translator tools / 번역자 도구

Installed apps only need the copy button above. These tools are for a source checkout
with its development dependencies (empty templates, checks and catalog updates):

```powershell
python -m scripts.language_pack template --id community.example --locale en-US --output build/example-pack
python -m scripts.language_pack check build/example-pack
python -m scripts.language_pack update build/example-pack --id community.example --locale en-US --output build/example-pack-updated
```

Templates contain empty values and a `reference.json` with Korean source text,
official English, screens, variables, contexts and revisions. The reference file is for translators, not loaded
by the app. A check reports untranslated, invalid, unknown and outdated entries.
Update writes a **new** folder, preserves the pack name, author, version and existing
translations (including entries needing repair), and reports added,
removed and review-needed keys. It never overwrites the original pack.

템플릿은 새 폴더에 생성합니다. `reference.json`을 참고하여 `messages.json`의
`value`를 번역하세요. 기준 카탈로그가 바뀌면 새 폴더로 갱신하고 변경 목록을 검토합니다.
공식 영어팩은 모든 키·변수·revision 검사를 통과해야 합니다.

User names, project/conversation titles, pet package names/descriptions and external
error details are preserved as received. A pet package may ship per-language descriptions
in `localizedDescriptions` ([pet package format](pet-package-format.md)); language packs
do not translate them. OS-owned dialog controls follow Windows.
The installer, launcher recovery messages and private content-pack installer have
their own language handling. Historical release notes describe their original version.

언어 호환 검사는 Babel과 고정 Electron의 지원 여부에 더해 정수 경계·소수의 복수형 결과를
대조합니다. 차이가 확인된 코드는 **excludedPluralLocales**에 기록하며 선택할 수 없습니다.
해당 팩을 저장해 둔 경우 기존의 사용 불가 팩 복구 절차로 한국어를 표시합니다.
현재 **kok** 계열과 **pt-AO** 같은 일부 포르투갈어 지역 코드가 여기에 해당하며,
**pt-PT**와 **pt-BR**은 계속 사용할 수 있습니다.
