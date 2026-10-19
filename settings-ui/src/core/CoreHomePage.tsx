import { t } from "../../localization.cjs";
import { PawPrint } from "lucide-react";
import { Section } from "../components";
import { doubleClickOptions } from "./doubleClick";
import type { CoreSettingsState } from "./useCoreSettings";

export function CoreHomePage({
  snapshot,
  previewImage,
  shell,
}: Pick<CoreSettingsState, "snapshot" | "previewImage" | "shell">) {
  const action = doubleClickOptions().find(
    (option) => option.value === snapshot.doubleClickAction,
  );
  return (
    <Section title={t("home.my_pet")}>
      <div className="pet-home-summary">
        {previewImage ? (
          <img src={previewImage} alt={snapshot.pet.display_name} />
        ) : (
          <PawPrint size={64} aria-hidden="true" />
        )}
        <div>
          <h3 data-user-text>{snapshot.pet.display_name}</h3>
          <p>
            {snapshot.doubleClickAction !== "wave_only" && action
              ? t("home.double_click_with_action", { action: action.label })
              : t("home.double_click_wave")}
          </p>
        </div>
      </div>
      <div className="pet-home-links">
        <button className="button" onClick={() => shell.navigate("pet")}>
          {t("home.customize_pet")}
        </button>
        <button className="button" onClick={() => shell.navigate("bubble")}>
          {t("message.1100")}
        </button>
        <button className="button" onClick={() => shell.navigate("app")}>
          {t("message.0595")}
        </button>
      </div>
    </Section>
  );
}
