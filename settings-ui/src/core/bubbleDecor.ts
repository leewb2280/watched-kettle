import type {
  BubbleBox,
  BubbleDecorLayer,
  Element,
  SpeechBubbleTheme,
} from "../types";

// Mirrors pet/bubble_decor.py; Python normalizes again on preview and save.
export const MAX_DECOR_LAYERS = 24;
export const DECOR_ANCHORS = [
  "top-left",
  "top-center",
  "top-right",
  "center-left",
  "center-right",
  "bottom-left",
  "bottom-center",
  "bottom-right",
  "arc-top-left",
] as const;
export const REPEAT_ANCHORS: Record<string, readonly string[]> = {
  y: ["top-left", "top-center", "top-right"],
  x: ["top-left", "center-left", "bottom-left"],
};
export const DECOR_LIMITS = {
  x: [-240, 240],
  y: [-240, 240],
  width: [1, 320],
  height: [1, 320],
  rotation: [-180, 180],
  alpha: [0, 255],
  repeat_gap: [0, 200],
  repeat_inset: [0, 200],
} as const;

export type Point = { x: number; y: number };
export type Box = { x: number; y: number; width: number; height: number };

const clamp = (value: number, [low, high]: readonly [number, number]) =>
  Math.min(high, Math.max(low, value));
const round = (value: number) => Math.round(value * 10) / 10;

/** Anchor position relative to the body's top-left corner. */
export function anchorPoint(
  body: BubbleBox,
  anchor: string,
  radius: number,
): Point {
  if (anchor === "arc-top-left") {
    const corner =
      Math.min(radius, body.height / 2, body.width / 2) * (1 - Math.SQRT1_2);
    return { x: corner, y: corner };
  }
  const [vertical, horizontal] = anchor.split("-");
  return {
    x: { left: 0, center: body.width / 2, right: body.width }[horizontal] ?? 0,
    y: { top: 0, center: body.height / 2, bottom: body.height }[vertical] ?? 0,
  };
}

/** The anchor a box centered at (x, y) of the body should keep its place to. */
export function nearestAnchor(body: BubbleBox, x: number, y: number) {
  const horizontal =
    x < body.width / 3 ? "left" : x > (body.width * 2) / 3 ? "right" : "center";
  let vertical =
    y < body.height / 3
      ? "top"
      : y > (body.height * 2) / 3
        ? "bottom"
        : "center";
  // There is no center-center anchor: use the nearer edge.
  if (horizontal === "center" && vertical === "center")
    vertical = y < body.height / 2 ? "top" : "bottom";
  return `${vertical}-${horizontal}`;
}

/** Move a layer so its box's top-left sits at (left, top) of the body. */
export function placeLayer(
  layer: BubbleDecorLayer,
  body: BubbleBox,
  radius: number,
  left: number,
  top: number,
  keepAnchor = false,
): BubbleDecorLayer {
  let anchor = layer.anchor;
  const repeats = layer.repeat !== "none";
  if (!keepAnchor && !repeats && anchor !== "arc-top-left")
    anchor = nearestAnchor(
      body,
      left + layer.width / 2,
      top + layer.height / 2,
    );
  const point = anchorPoint(body, anchor, radius);
  return {
    ...layer,
    anchor,
    x: round(clamp(left - point.x, DECOR_LIMITS.x)),
    y: round(clamp(top - point.y, DECOR_LIMITS.y)),
  };
}

/** The layer's box relative to the body, before rotation. */
export function layerBox(
  layer: BubbleDecorLayer,
  body: BubbleBox,
  radius: number,
): Box {
  const point = anchorPoint(body, layer.anchor, radius);
  return {
    x: point.x + layer.x,
    y: point.y + layer.y,
    width: layer.width,
    height: layer.height,
  };
}

// Position sliders show a layer's center as percent of the body; decorations
// often sit past its edges, so the range reaches half a body beyond them.
export const DECOR_PERCENT = [-50, 150] as const;

/** The layer's center as percent of the body. */
export function layerPercent(
  layer: BubbleDecorLayer,
  body: BubbleBox,
  radius: number,
): Point {
  const box = layerBox(layer, body, radius);
  return {
    x: round(((box.x + box.width / 2) / body.width) * 100),
    y: round(((box.y + box.height / 2) / body.height) * 100),
  };
}

/** Move a layer so its center sits at percent (x, y) of the body. */
export function placeLayerAtPercent(
  layer: BubbleDecorLayer,
  body: BubbleBox,
  radius: number,
  x: number,
  y: number,
): BubbleDecorLayer {
  return placeLayer(
    layer,
    body,
    radius,
    (x / 100) * body.width - layer.width / 2,
    (y / 100) * body.height - layer.height / 2,
  );
}

export function uniqueId(layers: BubbleDecorLayer[], base = "layer") {
  const ids = new Set(layers.map((layer) => layer.id));
  for (let index = layers.length + 1; ; index++) {
    const id = `${base}-${index}`;
    if (!ids.has(id)) return id;
  }
}

/**
 * The pet frame's layers the preview lets the user pick up: while they are
 * drawn, belong to this pet, have not been copied yet and fit the limit.
 */
export function adoptablePetLayers(
  theme: Pick<SpeechBubbleTheme, "decor" | "package_layers" | "frame_style">,
  packageDecor: BubbleDecorLayer[],
  petId: string,
) {
  if (!theme.package_layers || theme.frame_style !== `pet:${petId}`) return [];
  if (theme.decor.some((layer) => layer.image.startsWith(`pkg:${petId}/`)))
    return [];
  if (theme.decor.length + packageDecor.length > MAX_DECOR_LAYERS) return [];
  return packageDecor;
}

/**
 * Every pet frame layer copied into decor ahead of the user's own, and the
 * copy of the one picked. The caller turns the pet's own layers off, so
 * nothing is drawn twice.
 */
export function adoptPetDecor(
  layers: BubbleDecorLayer[],
  packageDecor: BubbleDecorLayer[],
  picked: string,
) {
  const copies: BubbleDecorLayer[] = [];
  let selected: BubbleDecorLayer | null = null;
  for (const item of packageDecor) {
    const copy = { ...item, id: uniqueId([...layers, ...copies], "pet") };
    copies.push(copy);
    if (item.id === picked) selected = copy;
  }
  return {
    layers: [...copies, ...layers],
    selected: selected ?? copies[0] ?? null,
  };
}

/** A new layer for an image, overlapping the body's top-right corner. */
export function newLayer(
  image: Element,
  layers: BubbleDecorLayer[],
): BubbleDecorLayer {
  const fit = Math.min(1, 40 / Math.max(image.width, image.height, 1));
  const width = round(Math.max(4, image.width * fit));
  const height = round(Math.max(4, image.height * fit));
  return {
    id: uniqueId(layers),
    name: image.name.slice(0, 60),
    image: image.id,
    placement: "front",
    anchor: "top-right",
    x: round(-width * 0.7),
    y: round(-height * 0.5),
    width,
    height,
    rotation: 0,
    mirror: false,
    flip_y: false,
    alpha: 255,
    tint: "",
    repeat: "none",
    repeat_gap: 0,
    repeat_inset: 0,
    hidden: false,
  };
}

/** A copy reflected across the body's vertical center line. */
export function mirroredCopy(
  layer: BubbleDecorLayer,
  layers: BubbleDecorLayer[],
  body: BubbleBox,
  radius: number,
): BubbleDecorLayer {
  const box = layerBox(layer, body, radius);
  const reflected: BubbleDecorLayer = {
    ...layer,
    id: uniqueId(layers, layer.id.replace(/-\d+$/, "") || "layer"),
    anchor:
      layer.anchor === "arc-top-left"
        ? "top-right"
        : layer.anchor.replace(/left|right/, (side) =>
            side === "left" ? "right" : "left",
          ),
    mirror: !layer.mirror,
    rotation: layer.rotation ? -layer.rotation : 0,
  };
  if (reflected.repeat === "x") reflected.repeat = "none";
  return placeLayer(
    reflected,
    body,
    radius,
    body.width - box.x - box.width,
    box.y,
    true,
  );
}

/** Pull a box edge or center to the body's edges or center within reach. */
export function snapBox(box: Box, body: BubbleBox, reach: number) {
  const guides: { axis: "x" | "y"; at: number }[] = [];
  let { x, y } = box;
  const pull = (
    axis: "x" | "y",
    start: number,
    size: number,
    span: number,
  ): number => {
    const targets = [0, span / 2, span];
    let best: { delta: number; at: number } | null = null;
    for (const offset of [0, size / 2, size])
      for (const target of targets) {
        const delta = target - (start + offset);
        if (
          Math.abs(delta) <= reach &&
          (!best || Math.abs(delta) < Math.abs(best.delta))
        )
          best = { delta, at: target };
      }
    if (!best) return start;
    guides.push({ axis, at: best.at });
    return start + best.delta;
  };
  x = pull("x", x, box.width, body.width);
  y = pull("y", y, box.height, body.height);
  return { box: { ...box, x, y }, guides };
}

export function clampLayer(layer: BubbleDecorLayer): BubbleDecorLayer {
  const next = { ...layer };
  for (const key of Object.keys(DECOR_LIMITS) as (keyof typeof DECOR_LIMITS)[])
    next[key] = round(clamp(Number(next[key]) || 0, DECOR_LIMITS[key]));
  next.alpha = Math.round(next.alpha);
  return next;
}

/** Packages ship images by path; show their file name without extension. */
export function imageName(reference: string, images: Element[]) {
  return (
    images.find((image) => image.id === reference)?.name ||
    reference
      .split("/")
      .pop()
      ?.replace(/\.[^.]+$/, "") ||
    reference
  );
}
