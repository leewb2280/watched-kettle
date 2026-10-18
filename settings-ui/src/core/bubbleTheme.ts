import { t } from "../../localization.cjs";
import type { Scalar, SpeechBubbleTheme } from "../types";
export const themeLabels: Record<string, string> = {
  background: t("message.0488"),
  border: t("message.1005"),
  text: t("message.1006"),
  shadow: t("message.1007"),
  shadow_alpha: t("message.1008"),
  radius: t("message.1009"),
  border_width: t("message.1010"),
  shape: t("message.1011"),
  tail: t("message.1012"),
  gradient: t("message.1013"),
  fill_end: t("message.1014"),
  border_style: t("message.1015"),
  header_style: t("message.1016"),
  pattern: t("message.1017"),
  ornament_left: t("message.1018"),
  ornament_right: t("message.1019"),
  ornament_scale: t("message.1020"),
  glow: t("message.1021"),
  frame_style: t("message.1022"),
  fill_opacity: t("message.1023"),
  minimum_width: t("message.1024"),
  maximum_width: t("message.1025"),
  horizontal_padding: t("message.1026"),
  stack_alignment: t("message.1027"),
  text_alignment: t("message.1028"),
  text_bold: t("message.1029"),
  background_image: t("message.1030"),
  background_opacity: t("message.1031"),
  background_focus_x: t("message.1032"),
  background_focus_y: t("message.1033"),
  background_zoom: t("message.1034"),
  frame_image: t("message.1035"),
  frame_slice: t("message.1036"),
  ...Object.fromEntries(
    [1, 2, 3].flatMap((slot) => [
      [`sticker_${slot}`, t("message.1037", { value0: slot })],
      [`sticker_${slot}_x`, t("message.1038", { value0: slot })],
      [`sticker_${slot}_y`, t("message.1039", { value0: slot })],
      [`sticker_${slot}_size`, t("message.1040", { value0: slot })],
    ]),
  ),
};
export const optionLabels: Record<string, string> = {
  rounded: t("message.1041"),
  cloud: t("message.1042"),
  jelly: t("message.1043"),
  comic: t("message.1044"),
  tech: t("message.1045"),
  none: t("message.0754"),
  triangle: t("message.1046"),
  curved: t("message.1047"),
  stub: t("message.1048"),
  angular: t("message.1049"),
  droplet: t("message.1050"),
  solid: t("message.0502"),
  vertical: t("message.1051"),
  horizontal: t("message.1052"),
  single: t("message.1053"),
  double: t("message.1054"),
  accent: t("message.1055"),
  capsule: t("message.1056"),
  tab: t("message.1057"),
  ribbon: t("message.1058"),
  panel: t("message.1059"),
  standard: t("message.0279"),
  dots: t("message.1060"),
  stars: t("message.1061"),
  grid: t("message.1062"),
  center: t("message.1063"),
  left: t("message.1064"),
  // Built-in ornaments, matching the Qt customizer's ORNAMENT_OPTIONS.
  "cat-ear": t("message.1065"),
  "small-wing": t("message.1066"),
  horn: t("message.1067"),
  "bat-wing": t("message.1068"),
  star: t("message.1061"),
  sparkle: t("message.1069"),
  goggles: t("message.1070"),
  magnet: t("message.1071"),
};
export const elementKeys = [
  "pattern",
  "ornament_left",
  "ornament_right",
  "background_image",
  "frame_image",
  "sticker_1",
  "sticker_2",
  "sticker_3",
];
// Which kind of user image each element field lists.
export const elementKind = (key: string) =>
  key === "pattern"
    ? "pattern"
    : key === "background_image"
      ? "photo"
      : key === "frame_image"
        ? "frame"
        : key.startsWith("sticker_")
          ? "sticker"
          : "ornament";
export const stickerFields = [1, 2, 3].flatMap((slot) =>
  ["", "_x", "_y", "_size"].map((suffix) => `sticker_${slot}${suffix}`),
);
export const themeGroups: [string, string[]][] = [
  [
    t("message.0487"),
    ["background", "gradient", "fill_end", "fill_opacity", "text", "text_bold"],
  ],
  [
    t("message.1072"),
    [
      "shape",
      "tail",
      "radius",
      "border",
      "border_width",
      "border_style",
      "frame_style",
      "header_style",
      "shadow",
      "shadow_alpha",
      "glow",
    ],
  ],
  [
    t("message.1073"),
    ["pattern", "ornament_left", "ornament_right", "ornament_scale"],
  ],
  [
    t("message.1074"),
    [
      "background_image",
      "background_opacity",
      "background_focus_x",
      "background_focus_y",
      "background_zoom",
      "frame_image",
      "frame_slice",
      ...stickerFields,
    ],
  ],
  [
    t("message.1075"),
    [
      "minimum_width",
      "maximum_width",
      "horizontal_padding",
      "stack_alignment",
      "text_alignment",
    ],
  ],
];
// Settings of an image stay hidden until that image is chosen.
export function hiddenThemeField(key: string, theme: ThemeValues) {
  if (key.startsWith("background_") && key !== "background_image")
    return theme.background_image === "none";
  if (key === "frame_slice") return theme.frame_image === "none";
  const sticker = key.match(/^(sticker_[123])_/);
  return !!sticker && theme[sticker[1]] === "none";
}
// A draft may still point at a user image deleted meanwhile; fall back to none.
export function dropMissingElements(theme: ThemeValues, known: Set<string>) {
  const next = { ...theme };
  for (const key of elementKeys)
    if (String(next[key]).startsWith("user:") && !known.has(String(next[key])))
      next[key] = "none";
  return next;
}
export type ThemeValues = SpeechBubbleTheme & Record<string, Scalar>;
