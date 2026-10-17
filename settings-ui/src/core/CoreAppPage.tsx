import { Fields, Heading, Section, Switch } from "../components";
import { UpdateRow } from "./UpdateRow";

import type { CoreSettingsState } from "./useCoreSettings";
export function CoreAppPage({
  snapshot,
  change,
  appearanceChange,
  call,
}: Pick<
  CoreSettingsState,
  "snapshot" | "change" | "appearanceChange" | "call"
>) {
  return (
    <div className="page">
      <Heading
        title="앱 설정"
        subtitle="시작, 화면 테마와 업데이트를 설정합니다."
      />
      <Section title="앱 시작">
        <div className="setting-row">
          <div>
            <h3>Windows와 함께 시작</h3>
            <p>
              {snapshot.startup.matches_current_app
                ? "현재 실행 파일과 연결되어 있어요."
                : "설정 변경 시 현재 실행 경로로 등록합니다."}
            </p>
          </div>
          <Switch
            label="Windows와 함께 시작"
            value={snapshot.startup.enabled}
            disabled={!snapshot.startup.supported}
            change={(value) => change("startup", value)}
          />
        </div>
      </Section>
      <Fields
        controls={[
          {
            key: "theme",
            label: "테마",
            kind: "select",
            value: snapshot.appearance.theme,
            options: [
              { value: "system", label: "시스템 설정에 맞춤" },
              { value: "light", label: "포슬린 · 라이트" },
              { value: "dark", label: "그라파이트 · 다크" },
            ],
            group: "화면과 색상",
          },
          {
            key: "material",
            label: "창 배경 재질",
            kind: "select",
            value: snapshot.appearance.material,
            options: [
              { value: "acrylic", label: "아크릴" },
              { value: "mica", label: "미카" },
              { value: "none", label: "단색" },
            ],
            group: "화면과 색상",
          },
          {
            key: "lightOpacity",
            label: "라이트 배경 농도",
            kind: "range",
            value: snapshot.appearance.lightOpacity,
            min: 0,
            max: 100,
            group: "화면과 색상",
          },
          {
            key: "darkOpacity",
            label: "다크 배경 농도",
            kind: "range",
            value: snapshot.appearance.darkOpacity,
            min: 0,
            max: 100,
            group: "화면과 색상",
          },
          {
            key: "reduceMotion",
            label: "움직임 줄이기",
            kind: "bool",
            value: snapshot.appearance.reduceMotion,
            group: "화면과 색상",
          },
        ]}
        change={appearanceChange}
      />
      <p className="footnote">
        배경 재질과 농도는 상단·사이드바에 적용되며 본문은 불투명하게
        유지됩니다. 고대비·투명 효과 끄기에서는 단색을 사용합니다. OS의 움직임
        줄이기도 반영됩니다.
      </p>
      <Section title="버전과 업데이트">
        <UpdateRow
          version={snapshot.version}
          update={snapshot.update}
          call={call}
        />
        <div className="setting-row">
          <div>
            <h3>업데이트 자동 확인</h3>
            <p>
              하루에 한 번 새 버전이 있는지 확인하고, 있으면 펫이 알려 줘요.
              설치는 직접 누를 때만 합니다.
            </p>
          </div>
          <Switch
            label="업데이트 자동 확인"
            value={snapshot.update.auto_check}
            change={(value) => change("update_auto_check", value)}
          />
        </div>
      </Section>
    </div>
  );
}
