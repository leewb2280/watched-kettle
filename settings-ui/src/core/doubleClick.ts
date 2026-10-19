import { t } from "../../localization.cjs";
import type { Option } from "../types";

// Built on use so the labels follow the active language pack.
export function doubleClickOptions(): Option[] {
  return [
    { value: "settings_home", label: t("double_click.settings_home") },
    { value: "codex", label: t("double_click.codex") },
    { value: "claude", label: t("double_click.claude") },
    { value: "wave_only", label: t("double_click.wave_only") },
  ];
}
