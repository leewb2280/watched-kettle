import type { BubbleBox, BubbleGeometry, Element } from "../types";
import type { Box } from "./bubbleDecor";

// Mirrors BUBBLE_THEME_LIMITS for the "free" photo box in pet/bubble_theme.py.
export const BACKGROUND_SIZE: readonly [number, number] = [8, 960];
export const BACKGROUND_HANDLES = [
  "nw",
  "n",
  "ne",
  "e",
  "se",
  "s",
  "sw",
  "w",
] as const;
export type BackgroundHandle = (typeof BACKGROUND_HANDLES)[number];
export type FreeBackground = {
  background_fit: "free";
  background_x: number;
  background_y: number;
  background_width: number;
  background_height: number;
};

const clamp = (value: number, low: number, high: number) =>
  Math.min(high, Math.max(low, value));

/** The drawn photo's box relative to the body, or null when there is none. */
export function backgroundBox(geometry: BubbleGeometry | null): Box | null {
  const box = geometry?.background;
  if (!geometry || !box) return null;
  return {
    x: box.x - geometry.body.x,
    y: box.y - geometry.body.y,
    width: box.width,
    height: box.height,
  };
}

/** Theme values that draw the photo in this body-relative box. */
export function freeBackground(box: Box, body: BubbleBox): FreeBackground {
  const percent = (value: number, span: number) =>
    Math.round(clamp((value / Math.max(span, 1)) * 100, 0, 100) * 10) / 10;
  return {
    background_fit: "free",
    background_x: percent(box.x + box.width / 2, body.width),
    background_y: percent(box.y + box.height / 2, body.height),
    background_width: Math.round(clamp(box.width, ...BACKGROUND_SIZE)),
    background_height: Math.round(clamp(box.height, ...BACKGROUND_SIZE)),
  };
}

/** The body-relative box that "free" theme values draw the photo in. */
export function freeBox(
  values: Omit<FreeBackground, "background_fit">,
  body: BubbleBox,
): Box {
  return {
    x: (body.width * values.background_x) / 100 - values.background_width / 2,
    y: (body.height * values.background_y) / 100 - values.background_height / 2,
    width: values.background_width,
    height: values.background_height,
  };
}

/**
 * Drag a handle by (dx, dy). Corners keep the box's shape unless `free`;
 * side handles stretch one way only. The opposite edge stays put.
 */
export function resizeBackground(
  start: Box,
  handle: BackgroundHandle,
  dx: number,
  dy: number,
  free: boolean,
): Box {
  const [low, high] = BACKGROUND_SIZE;
  const sx = handle.includes("e") ? 1 : handle.includes("w") ? -1 : 0;
  const sy = handle.includes("s") ? 1 : handle.startsWith("n") ? -1 : 0;
  let width = sx ? clamp(start.width + sx * dx, low, high) : start.width;
  let height = sy ? clamp(start.height + sy * dy, low, high) : start.height;
  if (sx && sy && !free) {
    const ratio = start.height / start.width;
    if (Math.abs(dx) >= Math.abs(dy)) height = width * ratio;
    else width = height / ratio;
    // Keep the shape within the size limits.
    const fit = Math.min(1, high / width, high / height);
    const grow = Math.max(1, low / width, low / height);
    width *= fit * grow;
    height *= fit * grow;
  }
  return {
    x: sx < 0 ? start.x + start.width - width : start.x,
    y: sy < 0 ? start.y + start.height - height : start.y,
    width,
    height,
  };
}

/** Height that gives the chosen image its own shape at this width. */
export function naturalHeight(
  image: string,
  width: number,
  images: Element[],
  limits: readonly [number, number] = BACKGROUND_SIZE,
): number {
  const element = images.find((item) => item.id === image);
  // Built-in pattern tiles are square.
  const ratio =
    element && element.width > 0 ? element.height / element.width : 1;
  return Math.round(clamp(width * ratio, ...limits));
}
