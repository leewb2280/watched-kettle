import type { Scalar, SpeechBubbleTheme } from "../types";
export const themeLabels: Record<string, string> = {
  background: "배경색",
  border: "테두리 색",
  text: "글자색",
  shadow: "그림자 색",
  shadow_alpha: "그림자 농도",
  radius: "모서리 곡률",
  border_width: "테두리 두께",
  shape: "모양",
  tail: "꼬리",
  gradient: "그라데이션",
  fill_end: "끝 색상",
  border_style: "테두리 스타일",
  header_style: "출처 이름 모양",
  pattern: "배경 무늬",
  ornament_left: "왼쪽 장식",
  ornament_right: "오른쪽 장식",
  ornament_scale: "장식 크기",
  glow: "은은한 빛",
  frame_style: "프레임",
  fill_opacity: "채우기 농도",
  minimum_width: "최소 너비",
  maximum_width: "최대 너비",
  horizontal_padding: "좌우 여백",
  stack_alignment: "카드 정렬",
  text_alignment: "글자 정렬",
  text_bold: "굵은 글씨",
  background_image: "배경 사진",
  background_opacity: "사진 진하기",
  background_focus_x: "사진 가로 위치",
  background_focus_y: "사진 세로 위치",
  background_zoom: "사진 확대",
  frame_image: "테두리 이미지",
  frame_slice: "테두리 모서리 크기",
  ...Object.fromEntries(
    [1, 2, 3].flatMap((slot) => [
      [`sticker_${slot}`, `스티커 ${slot}`],
      [`sticker_${slot}_x`, `스티커 ${slot} 가로 위치`],
      [`sticker_${slot}_y`, `스티커 ${slot} 세로 위치`],
      [`sticker_${slot}_size`, `스티커 ${slot} 크기`],
    ]),
  ),
};
export const optionLabels: Record<string, string> = {
  rounded: "둥근형",
  cloud: "구름형",
  jelly: "젤리형",
  comic: "만화형",
  tech: "기계형",
  none: "없음",
  triangle: "삼각형",
  curved: "곡선형",
  stub: "통통한 형",
  angular: "각진 형",
  droplet: "물방울형",
  solid: "단색",
  vertical: "세로",
  horizontal: "가로",
  single: "기본선",
  double: "이중선",
  accent: "포인트선",
  capsule: "캡슐",
  tab: "상단 탭",
  ribbon: "리본",
  panel: "기계 패널",
  standard: "기본",
  dots: "점",
  stars: "별",
  grid: "격자",
  center: "가운데",
  left: "왼쪽",
  // Built-in ornaments, matching the Qt customizer's ORNAMENT_OPTIONS.
  "cat-ear": "고양이 귀",
  "small-wing": "작은 날개",
  horn: "뿔",
  "bat-wing": "박쥐 날개",
  star: "별",
  sparkle: "반짝임",
  goggles: "고글",
  magnet: "자석",
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
    "색",
    ["background", "gradient", "fill_end", "fill_opacity", "text", "text_bold"],
  ],
  [
    "모양·테두리",
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
  ["장식", ["pattern", "ornament_left", "ornament_right", "ornament_scale"]],
  [
    "사진·이미지",
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
    "글자·여백",
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
