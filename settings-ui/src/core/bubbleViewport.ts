/** Display-only transforms. Theme coordinates always remain logical pixels. */
export type Point = { x: number; y: number };
export type Size = { width: number; height: number };
export type View = Point & { zoom: number; fit: boolean };
export const VIEW_PAD = 28;
export const INITIAL_VIEW: View = { x: 0, y: 0, zoom: 1, fit: true };
export const clampZoom = (zoom: number) => Math.max(0.01, Math.min(4, zoom));

export function clampView(view: View, image: Size, viewport: Size): View {
  const axis = (origin: number, extent: number, available: number) =>
    extent + VIEW_PAD * 2 <= available
      ? (available - extent) / 2
      : Math.max(available - VIEW_PAD - extent, Math.min(VIEW_PAD, origin));
  const zoom = clampZoom(view.zoom);
  return {
    ...view,
    zoom,
    x: axis(view.x, image.width * zoom, viewport.width),
    y: axis(view.y, image.height * zoom, viewport.height),
  };
}

export function fitView(image: Size, viewport: Size): View {
  return clampView(
    {
      ...INITIAL_VIEW,
      zoom: clampZoom(
        Math.min(
          (viewport.width - VIEW_PAD * 2) / image.width,
          (viewport.height - VIEW_PAD * 2) / image.height,
        ),
      ),
    },
    image,
    viewport,
  );
}

export function imagePoint(point: Point, view: View): Point {
  return {
    x: (point.x - view.x) / view.zoom,
    y: (point.y - view.y) / view.zoom,
  };
}
export function displayPoint(point: Point, view: View): Point {
  return { x: view.x + point.x * view.zoom, y: view.y + point.y * view.zoom };
}
export function zoomView(
  view: View,
  zoom: number,
  anchor: Point,
  image: Size,
  viewport: Size,
): View {
  const point = imagePoint(anchor, view);
  zoom = clampZoom(zoom);
  return clampView(
    {
      fit: false,
      zoom,
      x: anchor.x - point.x * zoom,
      y: anchor.y - point.y * zoom,
    },
    image,
    viewport,
  );
}
