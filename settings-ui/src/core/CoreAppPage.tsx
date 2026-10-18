import { t } from "../../localization.cjs";
import { Fields, Heading, Section, Switch } from "../components";
import { UpdateRow } from "./UpdateRow";
import { LanguageSettings } from "./LanguageSettings";

import type { CoreSettingsState } from "./useCoreSettings";
export function CoreAppPage({
  snapshot,
  shell,
  change,
  appearanceChange,
  call,
}: Pick<
  CoreSettingsState,
  "snapshot" | "shell" | "change" | "appearanceChange" | "call"
>) {
  return (
    <div className="page">
      <Heading title={t("message.0595")} subtitle={t("message.1076")} />
      <LanguageSettings shell={shell} />
      <Section title={t("message.1077")}>
        <div className="setting-row">
          <div>
            <h3>{t("message.1078")}</h3>
            <p>
              {snapshot.startup.matches_current_app
                ? t("message.1079")
                : t("message.1080")}
            </p>
          </div>
          <Switch
            label={t("message.1078")}
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
            label: t("message.1081"),
            kind: "select",
            value: snapshot.appearance.theme,
            options: [
              { value: "system", label: t("message.1082") },
              { value: "light", label: t("message.1083") },
              { value: "dark", label: t("message.1084") },
            ],
            groupId: "app_appearance",
            group: t("message.1085"),
          },
          {
            key: "material",
            label: t("message.1086"),
            kind: "select",
            value: snapshot.appearance.material,
            options: [
              { value: "acrylic", label: t("message.0503") },
              { value: "mica", label: t("message.1087") },
              { value: "none", label: t("message.0502") },
            ],
            groupId: "app_appearance",
            group: t("message.1085"),
          },
          {
            key: "lightOpacity",
            label: t("message.1088"),
            kind: "range",
            value: snapshot.appearance.lightOpacity,
            min: 0,
            max: 100,
            groupId: "app_appearance",
            group: t("message.1085"),
          },
          {
            key: "darkOpacity",
            label: t("message.1089"),
            kind: "range",
            value: snapshot.appearance.darkOpacity,
            min: 0,
            max: 100,
            groupId: "app_appearance",
            group: t("message.1085"),
          },
          {
            key: "reduceMotion",
            label: t("message.1090"),
            kind: "bool",
            value: snapshot.appearance.reduceMotion,
            groupId: "app_appearance",
            group: t("message.1085"),
          },
        ]}
        change={appearanceChange}
      />
      <p className="footnote">{t("message.1091")}</p>
      <Section title={t("message.1092")}>
        <UpdateRow
          version={snapshot.version}
          update={snapshot.update}
          call={call}
        />
        <div className="setting-row">
          <div>
            <h3>{t("message.1093")}</h3>
            <p>{t("message.1094")}</p>
          </div>
          <Switch
            label={t("message.1093")}
            value={snapshot.update.auto_check}
            change={(value) => change("update_auto_check", value)}
          />
        </div>
      </Section>
    </div>
  );
}
