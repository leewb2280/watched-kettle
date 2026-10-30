import { t } from "../../localization.cjs";
import type { BubbleDecorLayer, Scalar, SpeechBubbleTheme } from "../types";
export const themeLabels: Record<string, string> = {
  // Named in the pet package export notice of left-out items.
  decor_ornaments: t("bubble.editor.ornament_layers"),
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
  frame_style: t("bubble.editor.field.frame_style"),
  fill_opacity: t("message.1023"),
  minimum_width: t("message.1024"),
  maximum_width: t("message.1025"),
  horizontal_padding: t("message.1026"),
  stack_alignment: t("message.1027"),
  text_alignment: t("message.1028"),
  text_bold: t("message.1029"),
  background_image: t("message.1030"),
  background_opacity: t("message.1031"),
  background_focus_x: t("bubble.editor.background_focus_x"),
  background_focus_y: t("bubble.editor.background_focus_y"),
  background_zoom: t("message.1034"),
  frame_image: t("message.1035"),
  frame_slice: t("message.1036"),
  gradient_angle: t("bubble.editor.gradient_angle"),
  pattern_tile_size: t("bubble.editor.pattern_tile_size"),
  pattern_opacity: t("bubble.editor.pattern_opacity"),
  background_fit: t("bubble.editor.background_fit"),
  background_tile_size: t("bubble.editor.background_tile_size"),
  background_blur: t("bubble.editor.background_blur"),
  background_overlay: t("bubble.editor.background_overlay"),
  // The photo's own box when it is placed freely.
  background_x: t("message.1032"),
  background_y: t("message.1033"),
  background_width: t("bubble.editor.background_width"),
  background_height: t("bubble.editor.background_height"),
  inner_border_custom: t("bubble.editor.field.inner_border_custom"),
  inner_border_color: t("bubble.editor.field.inner_border_color"),
  inner_border_alpha: t("bubble.editor.field.inner_border_alpha"),
  halo_custom: t("bubble.editor.field.halo_custom"),
  halo_color: t("bubble.editor.field.halo_color"),
  halo_alpha: t("bubble.editor.field.halo_alpha"),
  halo_width: t("bubble.editor.field.halo_width"),
  halo_offset_y: t("bubble.editor.field.halo_offset_y"),
  halo_grow: t("bubble.editor.field.halo_grow"),
  content_custom: t("bubble.editor.field.content_custom"),
  content_top: t("bubble.editor.field.content_top"),
  content_bottom: t("bubble.editor.field.content_bottom"),
  content_left: t("bubble.editor.field.content_left"),
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
  angle: t("bubble.editor.gradient.angle"),
  cover: t("bubble.editor.fit.cover"),
  contain: t("bubble.editor.fit.contain"),
  stretch: t("bubble.editor.fit.stretch"),
  tile: t("bubble.editor.fit.tile"),
  free: t("bubble.editor.fit.free"),
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
  dot: t("bubble.editor.ornament.dot"),
};
export const elementKeys = [
  "pattern",
  "ornament_left",
  "ornament_right",
  "background_image",
  "frame_image",
];
// Which kind of user image each element field lists.
export const elementKind = (key: string) =>
  key === "pattern"
    ? "pattern"
    : key === "background_image"
      ? "photo"
      : key === "frame_image"
        ? "frame"
        : "ornament";
// Alphas stored as 0-255 but shown in percent like the other opacities.
export const percentKeys = ["fill_opacity", "inner_border_alpha", "halo_alpha"];
// Switches that make a theme set a pet frame value itself, and the fields
// each one opens.
export const frameGroups: Record<string, string[]> = {
  inner_border_custom: ["inner_border_color", "inner_border_alpha"],
  halo_custom: [
    "halo_color",
    "halo_alpha",
    "halo_width",
    "halo_offset_y",
    "halo_grow",
  ],
  content_custom: ["content_top", "content_bottom", "content_left"],
};
// Where a switched-on group starts: the pet frame's own values, else what
// the bubble draws without one.
export function frameStart(
  key: string,
  theme: ThemeValues,
  frameValues: Record<string, Scalar>,
) {
  const fallback: Record<string, Scalar> = {
    inner_border_color: theme.border,
    inner_border_alpha: 115,
    halo_color: theme.shadow,
    halo_alpha: 90,
    halo_width: 3,
    halo_offset_y: 0,
    halo_grow: 0,
    content_top: 12,
    content_bottom: 14,
    content_left: 0,
  };
  return Object.fromEntries(
    (frameGroups[key] ?? []).map((field) => [
      field,
      frameValues[field] ?? fallback[field],
    ]),
  );
}
// Theme numbers are sliders except these: the free photo's width and height
// have a wide range in pixels, and the preview handles size them.
export const typedKeys = ["background_width", "background_height"];
// Field groups per editor tab; the decoration tab also has the layer panel.
export const editorTabs: [string, string, [string, string[]][]][] = [
  [
    "background",
    t("bubble.editor.tab.background"),
    [
      [
        t("message.0487"),
        [
          "background",
          "gradient",
          "gradient_angle",
          "fill_end",
          "fill_opacity",
        ],
      ],
      [t("message.1017"), ["pattern", "pattern_tile_size", "pattern_opacity"]],
      // The image, then the fields of its fill, then looks every fill shares.
      [t("message.1074"), ["background_image", "background_fit"]],
      [
        t("bubble.editor.group.placement"),
        [
          "background_focus_x",
          "background_focus_y",
          "background_zoom",
          "background_x",
          "background_y",
          "background_width",
          "background_height",
          "background_tile_size",
        ],
      ],
      [
        t("bubble.editor.group.image_effects"),
        ["background_opacity", "background_blur", "background_overlay"],
      ],
    ],
  ],
  [
    "border",
    t("bubble.editor.tab.border_shape"),
    [
      [t("bubble.editor.group.border_basic"), ["border", "border_width"]],
      [
        t("bubble.editor.group.border_style"),
        [
          "border_style",
          "inner_border_custom",
          "inner_border_color",
          "inner_border_alpha",
          "frame_image",
          "frame_slice",
        ],
      ],
      [t("bubble.editor.group.box"), ["shape", "radius"]],
      [t("message.1012"), ["tail"]],
      [t("bubble.editor.group.effects"), ["shadow", "shadow_alpha", "glow"]],
      [
        t("bubble.editor.group.halo"),
        ["halo_custom", ...frameGroups.halo_custom],
      ],
    ],
  ],
  [
    "decor",
    t("message.1073"),
    [
      // The pet frame sits in the layer card; the old corner ornaments show
      // here only while a theme still uses them.
      [
        t("bubble.editor.group.legacy_ornaments"),
        ["ornament_left", "ornament_right", "ornament_scale"],
      ],
    ],
  ],
  [
    "layout",
    t("bubble.editor.tab.layout"),
    [
      [
        t("bubble.editor.group.text"),
        ["text", "text_bold", "text_alignment", "header_style"],
      ],
      [
        t("bubble.editor.group.size"),
        [
          "minimum_width",
          "maximum_width",
          "horizontal_padding",
          "stack_alignment",
        ],
      ],
      [
        t("bubble.editor.group.content"),
        ["content_custom", ...frameGroups.content_custom],
      ],
    ],
  ],
  // Saved designs and theme files; the tab has no theme fields.
  ["themes", t("bubble.theme.tab"), []],
];
// Settings of an image stay hidden until that image is chosen. The old
// pattern field is left only for themes that still use one; background
// images now hold the built-in pattern tiles.
export function hiddenThemeField(key: string, theme: ThemeValues) {
  if (key === "pattern") return theme.pattern === "none";
  // The inner line is only drawn by the double border.
  if (key.startsWith("inner_border_") && theme.border_style !== "double")
    return true;
  for (const [toggle, fields] of Object.entries(frameGroups))
    if (fields.includes(key)) return !theme[toggle];
  // Ornaments are added as layers now; the old corner slots show while used.
  if (key === "ornament_left" || key === "ornament_right")
    return theme[key] === "none";
  if (key === "ornament_scale")
    return theme.ornament_left === "none" && theme.ornament_right === "none";
  if (key.startsWith("background_") && key !== "background_image") {
    if (theme.background_image === "none") return true;
    const fit = theme.background_fit;
    if (key === "background_tile_size") return fit !== "tile";
    if (
      ["background_focus_x", "background_focus_y", "background_zoom"].includes(
        key,
      )
    )
      return fit === "tile" || fit === "stretch" || fit === "free";
    if (
      [
        "background_x",
        "background_y",
        "background_width",
        "background_height",
      ].includes(key)
    )
      return fit !== "free";
    return false;
  }
  if (key === "gradient_angle") return theme.gradient !== "angle";
  if (key.startsWith("pattern_")) return !theme.pattern.startsWith("user:");
  return key === "frame_slice" && theme.frame_image === "none";
}
// A draft may still point at a user image deleted meanwhile; fall back to none.
export function dropMissingElements(theme: ThemeValues, known: Set<string>) {
  const next = { ...theme };
  for (const key of elementKeys)
    if (String(next[key]).startsWith("user:") && !known.has(String(next[key])))
      next[key] = "none";
  next.decor = next.decor.filter(
    (layer) => !layer.image.startsWith("user:") || known.has(layer.image),
  );
  return next;
}
// Compares values, not key order: drafts mix server data and local edits.
function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.keys(value)
      .sort()
      .map(
        (key) =>
          `${JSON.stringify(key)}:${stable((value as Record<string, unknown>)[key])}`,
      )
      .join(",")}}`;
  return JSON.stringify(value);
}
export function sameTheme(a: ThemeValues, b: ThemeValues) {
  return stable(a) === stable(b);
}
export type ThemeValues = SpeechBubbleTheme &
  Record<string, Scalar | BubbleDecorLayer[]>;
