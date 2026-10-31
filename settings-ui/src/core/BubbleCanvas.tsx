import { t } from "../../localization.cjs";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { BubbleDecorLayer, BubbleGeometry, Element } from "../types";
import {
  BACKGROUND_HANDLES,
  BackgroundHandle,
  FreeBackground,
  freeBackground,
  resizeBackground,
} from "./bubbleBackground";
import { Box, layerBox, placeLayer, snapBox } from "./bubbleDecor";
import {
  clampView,
  imagePoint,
  VIEW_PAD as PAD,
  type View,
} from "./bubbleViewport";
import type { useBubbleEditor } from "./useBubbleEditor";

// Room around the image so handles of layers at the edge stay reachable.
const CORNERS = ["nw", "ne", "sw", "se"] as const;
type Corner = (typeof CORNERS)[number];
type Action = {
  mode: "move" | "resize" | "rotate";
  layer: BubbleDecorLayer;
  corner?: Corner;
  pointer: { x: number; y: number };
  start: Box;
  moved: boolean;
};
type Live = {
  id: string;
  box: Box;
  rotation: number;
  guides: { axis: "x" | "y"; at: number }[];
};
// The live box of the background photo uses this id; layer ids never start with @.
const BACKGROUND_ID = "@background";
// Python redraws the photo at most this often while it is dragged.
const LIVE_INTERVAL = 40;
type BackgroundAction = {
  // null moves the photo.
  handle: BackgroundHandle | null;
  pointer: { x: number; y: number };
  start: Box;
  moved: boolean;
  sent: number;
};
/** The background photo as a layer of its own, on the background tab. */
export type BackgroundControl = {
  // Relative to the body, like layer boxes.
  box: Box;
  selected: boolean;
  select: (selected: boolean) => void;
  // Drawn while dragging, then saved as one undo step or dropped.
  preview: (values: FreeBackground) => void;
  commit: (values: FreeBackground) => void;
  cancel: () => void;
};

/** The preview image with selectable, draggable decoration layers on top. */
export function BubbleCanvas({
  preview,
  geometry,
  zoom,
  layers,
  radius,
  selected,
  locked,
  images,
  select,
  dragging,
  commit,
  dropFiles,
  background,
  petLayers = [],
  adopt,
  viewport,
}: {
  preview: string;
  geometry: BubbleGeometry;
  zoom: number;
  layers: BubbleDecorLayer[];
  radius: number;
  selected: string | null;
  locked: Set<string>;
  images: Element[];
  select: (id: string | null) => void;
  dragging: (id: string | null) => void;
  commit: (layer: BubbleDecorLayer) => void;
  // Image files dropped on the canvas, with the body point they landed on.
  dropFiles: (files: FileList, point: { x: number; y: number }) => void;
  background?: BackgroundControl | null;
  // The pet frame's layers, drawn in the preview image, that pressing copies
  // into the user's own layers; adopt returns the copy of the pressed one.
  petLayers?: BubbleDecorLayer[];
  adopt?: (id: string) => BubbleDecorLayer | null;
  viewport: ReturnType<typeof useBubbleEditor>;
}) {
  const surface = useRef<HTMLDivElement>(null);
  const space = useRef(false);
  const hovering = useRef(false);
  const pan = useRef<{ x: number; y: number; view: View } | null>(null);
  const capture = useRef<{ element: HTMLElement; id: number } | null>(null);
  const view = viewport.view;
  const stage = useRef<HTMLDivElement>(null);
  const action = useRef<Action | null>(null);
  const backgroundAction = useRef<BackgroundAction | null>(null);
  const liveRef = useRef<Live | null>(null);
  const [live, setLiveState] = useState<Live | null>(null);
  const setLive = (value: Live | null) => {
    liveRef.current = value;
    setLiveState(value);
  };
  const body = geometry.body;
  const thumbnails = new Map(
    images.map((image) => [image.id, image.thumbnail]),
  );
  const release = () => {
    const held = capture.current;
    capture.current = null;
    if (held?.element.hasPointerCapture(held.id))
      held.element.releasePointerCapture(held.id);
  };
  const capturePointer = (
    event: ReactPointerEvent<HTMLElement>,
    element = event.currentTarget,
  ) => {
    release();
    element.setPointerCapture(event.pointerId);
    capture.current = { element, id: event.pointerId };
    viewport.beginInteraction();
  };
  const cancel = () => {
    const active = !!(
      action.current ||
      backgroundAction.current ||
      pan.current
    );
    if (pan.current) viewport.setViewState(pan.current.view);
    pan.current = null;
    action.current = null;
    backgroundAction.current = null;
    setLive(null);
    dragging(null);
    background?.cancel();
    viewport.setInteracting(false);
    release();
    return active;
  };
  const latest = useRef({ cancel, viewport });
  latest.current = { cancel, viewport };
  viewport.interactionCancel.current = cancel;
  useLayoutEffect(() => {
    const element = surface.current!;
    const observer = new ResizeObserver(() => {
      latest.current.cancel();
      latest.current.viewport.setViewportSize({
        width: element.clientWidth,
        height: element.clientHeight,
      });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const element = surface.current!;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      event.stopPropagation();
      const rect = element.getBoundingClientRect();
      const current = latest.current.viewport;
      current.setZoom(
        current.zoom *
          Math.exp(
            -Math.max(
              -240,
              Math.min(
                240,
                event.deltaY *
                  (event.deltaMode === 1
                    ? 16
                    : event.deltaMode === 2
                      ? element.clientHeight
                      : 1),
              ),
            ) * 0.002,
          ),
        { x: event.clientX - rect.left, y: event.clientY - rect.top },
      );
    };
    const blur = () => {
      space.current = false;
      latest.current.cancel();
    };
    const hidden = () => {
      if (document.hidden) blur();
    };
    const keyDown = (event: KeyboardEvent) => {
      if (
        event.code !== "Space" ||
        !hovering.current ||
        (event.target as HTMLElement).closest(
          "input, select, textarea, button, a, summary, [contenteditable=true]",
        )
      )
        return;
      space.current = true;
      event.preventDefault();
    };
    const keyUp = (event: KeyboardEvent) => {
      if (event.code === "Space") space.current = false;
    };
    element.addEventListener("wheel", wheel, { passive: false });
    window.addEventListener("keydown", keyDown);
    window.addEventListener("keyup", keyUp);
    window.addEventListener("blur", blur);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      element.removeEventListener("wheel", wheel);
      window.removeEventListener("keydown", keyDown);
      window.removeEventListener("keyup", keyUp);
      window.removeEventListener("blur", blur);
      document.removeEventListener("visibilitychange", hidden);
      latest.current.cancel();
      latest.current.viewport.interactionCancel.current = null;
    };
  }, []);

  // Body-relative 100% pixels of a pointer position.
  const bodyPoint = (event: { clientX: number; clientY: number }) => {
    const rect = surface.current!.getBoundingClientRect();
    const point = imagePoint(
      { x: event.clientX - rect.left, y: event.clientY - rect.top },
      view,
    );
    return {
      x: point.x - body.x,
      y: point.y - body.y,
    };
  };

  const begin =
    (layer: BubbleDecorLayer, mode: Action["mode"], corner?: Corner) =>
    (event: ReactPointerEvent<HTMLElement>) => {
      if (event.button !== 0) return;
      event.stopPropagation();
      select(layer.id);
      // Keyboard nudges and shortcuts follow the canvas focus.
      stage.current?.focus({ preventScroll: true });
      if (locked.has(layer.id)) return;
      event.preventDefault();
      capturePointer(event);
      action.current = {
        mode,
        layer,
        corner,
        pointer: { x: event.clientX, y: event.clientY },
        start: layerBox(layer, body, radius),
        moved: false,
      };
    };

  // Pressing a pet layer copies the frame and drags the copy at once. The
  // pressed box goes away with the copy, so the stage holds the pointer.
  const adoptAndMove =
    (petLayer: BubbleDecorLayer) => (event: ReactPointerEvent<HTMLElement>) => {
      if (event.button !== 0 || !adopt) return;
      event.stopPropagation();
      event.preventDefault();
      const copy = adopt(petLayer.id);
      if (!copy) return;
      stage.current?.focus({ preventScroll: true });
      capturePointer(event, stage.current!);
      action.current = {
        mode: "move",
        layer: copy,
        pointer: { x: event.clientX, y: event.clientY },
        start: layerBox(copy, body, radius),
        moved: false,
      };
    };
  // Events of a layer box bubble up to the stage; only its own are handled.
  const onStage =
    (handler: (event: ReactPointerEvent<HTMLElement>) => void) =>
    (event: ReactPointerEvent<HTMLElement>) => {
      if (event.target === event.currentTarget) handler(event);
    };

  const move = (event: ReactPointerEvent<HTMLElement>) => {
    const current = action.current;
    if (!current) return;
    const dx = (event.clientX - current.pointer.x) / zoom;
    const dy = (event.clientY - current.pointer.y) / zoom;
    if (!current.moved) {
      if (Math.hypot(dx, dy) * zoom < 3) return;
      current.moved = true;
      dragging(current.layer.id);
    }
    const start = current.start;
    if (current.mode === "move") {
      const moved = { ...start, x: start.x + dx, y: start.y + dy };
      // Alt places freely, like most editors.
      const snapped = event.altKey
        ? { box: moved, guides: [] }
        : snapBox(moved, body, 4 / zoom);
      setLive({
        id: current.layer.id,
        box: snapped.box,
        rotation: current.layer.rotation,
        guides: snapped.guides,
      });
    } else if (current.mode === "resize") {
      const corner = current.corner!;
      const sx = corner.includes("e") ? 1 : -1;
      const sy = corner.includes("s") ? 1 : -1;
      let width = Math.max(4, start.width + sx * dx);
      let height = Math.max(4, start.height + sy * dy);
      // The image keeps its shape by default; Shift resizes the box freely.
      if (!event.shiftKey) {
        const ratio = start.height / start.width;
        if (Math.abs(dx) >= Math.abs(dy)) height = width * ratio;
        else width = height / ratio;
      }
      width = Math.min(320, width);
      height = Math.min(320, height);
      setLive({
        id: current.layer.id,
        box: {
          x: sx > 0 ? start.x : start.x + start.width - width,
          y: sy > 0 ? start.y : start.y + start.height - height,
          width,
          height,
        },
        rotation: current.layer.rotation,
        guides: [],
      });
    } else {
      const point = bodyPoint(event);
      const cx = start.x + start.width / 2;
      const cy = start.y + start.height / 2;
      let angle = (Math.atan2(point.y - cy, point.x - cx) * 180) / Math.PI + 90;
      if (angle > 180) angle -= 360;
      // Shift turns in 15 degree steps.
      if (event.shiftKey) angle = Math.round(angle / 15) * 15;
      setLive({
        id: current.layer.id,
        box: start,
        rotation: Math.round(angle),
        guides: [],
      });
    }
  };

  const end = () => {
    const current = action.current;
    const result = liveRef.current;
    action.current = null;
    viewport.setInteracting(false);
    release();
    setLive(null);
    if (!current?.moved) return;
    dragging(null);
    if (!result) return;
    const layer = current.layer;
    if (current.mode === "move")
      commit(placeLayer(layer, body, radius, result.box.x, result.box.y));
    else if (current.mode === "resize")
      commit(
        placeLayer(
          {
            ...layer,
            width: Math.round(result.box.width * 10) / 10,
            height: Math.round(result.box.height * 10) / 10,
          },
          body,
          radius,
          result.box.x,
          result.box.y,
          true,
        ),
      );
    else commit({ ...layer, rotation: result.rotation });
  };

  const beginBackground =
    (handle: BackgroundHandle | null) =>
    (event: ReactPointerEvent<HTMLElement>) => {
      if (event.button !== 0 || !background) return;
      event.stopPropagation();
      event.preventDefault();
      select(null);
      background.select(true);
      stage.current?.focus({ preventScroll: true });
      capturePointer(event);
      backgroundAction.current = {
        handle,
        pointer: { x: event.clientX, y: event.clientY },
        start: background.box,
        moved: false,
        sent: 0,
      };
    };

  const moveBackground = (event: ReactPointerEvent<HTMLElement>) => {
    const current = backgroundAction.current;
    if (!current || !background) return;
    const dx = (event.clientX - current.pointer.x) / zoom;
    const dy = (event.clientY - current.pointer.y) / zoom;
    if (!current.moved) {
      if (Math.hypot(dx, dy) * zoom < 3) return;
      current.moved = true;
    }
    const start = current.start;
    let next = { box: start, guides: [] as Live["guides"] };
    if (current.handle)
      // Shift lets the corners change the photo's shape too.
      next.box = resizeBackground(
        start,
        current.handle,
        dx,
        dy,
        event.shiftKey,
      );
    else {
      const moved = { ...start, x: start.x + dx, y: start.y + dy };
      next = event.altKey
        ? { box: moved, guides: [] }
        : snapBox(moved, body, 4 / zoom);
    }
    setLive({ id: BACKGROUND_ID, rotation: 0, ...next });
    const now = performance.now();
    if (now - current.sent >= LIVE_INTERVAL) {
      current.sent = now;
      background.preview(freeBackground(next.box, body));
    }
  };

  const endBackground = () => {
    const current = backgroundAction.current;
    const result = liveRef.current;
    backgroundAction.current = null;
    viewport.setInteracting(false);
    release();
    setLive(null);
    if (!current?.moved || !result || !background) return;
    background.commit(freeBackground(result.box, body));
  };

  const px = (value: number) => `${value * zoom}px`;
  const backgroundShown =
    background && (live?.id === BACKGROUND_ID ? live.box : background.box);
  const ordered = [
    ...layers.filter((layer) => layer.placement === "back"),
    ...layers.filter((layer) => layer.placement !== "back"),
  ].filter((layer) => !layer.hidden);
  return (
    <div
      ref={surface}
      className="bubble-viewport"
      data-zoom={zoom}
      data-body-width={body.width}
      onPointerEnter={() => {
        hovering.current = true;
      }}
      onPointerLeave={() => {
        hovering.current = false;
      }}
      onPointerDownCapture={(event) => {
        if (event.button !== 1 && !(event.button === 0 && space.current))
          return;
        event.preventDefault();
        event.stopPropagation();
        if (viewport.interacting) return;
        stage.current?.focus({ preventScroll: true });
        pan.current = { x: event.clientX, y: event.clientY, view };
        capturePointer(event);
      }}
      onPointerMoveCapture={(event) => {
        if (!pan.current) return;
        event.stopPropagation();
        const start = pan.current;
        viewport.setViewState(
          clampView(
            {
              ...start.view,
              fit: false,
              x: start.view.x + event.clientX - start.x,
              y: start.view.y + event.clientY - start.y,
            },
            geometry,
            {
              width: surface.current!.clientWidth,
              height: surface.current!.clientHeight,
            },
          ),
        );
      }}
      onPointerUpCapture={(event) => {
        if (!pan.current) return;
        event.stopPropagation();
        pan.current = null;
        viewport.setInteracting(false);
        release();
      }}
      onPointerCancelCapture={(event) => {
        event.stopPropagation();
        cancel();
      }}
      onLostPointerCapture={() => {
        if (capture.current) cancel();
      }}
      onKeyDownCapture={(event) => {
        if (event.key === "Escape" && cancelActive()) {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
        if (event.code === "Space") {
          space.current = true;
          event.preventDefault();
          event.stopPropagation();
        }
        if (!(event.ctrlKey || event.metaKey)) return;
        if (["+", "=", "-", "0"].includes(event.key)) {
          event.preventDefault();
          event.stopPropagation();
          if (event.key === "0") viewport.fit();
          else viewport.setZoom(zoom * (event.key === "-" ? 1 / 1.25 : 1.25));
        }
      }}
      onKeyUp={(event) => {
        if (event.code === "Space") space.current = false;
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          space.current = false;
          cancel();
        }
      }}
    >
      <div
        ref={stage}
        className="bubble-canvas"
        tabIndex={0}
        aria-label={t("bubble.editor.canvas_hint")}
        style={{
          width: geometry.width * zoom + PAD * 2,
          height: geometry.height * zoom + PAD * 2,
          padding: PAD,
          position: "absolute",
          left: view.x - PAD,
          top: view.y - PAD,
        }}
        onPointerDown={() => {
          stage.current?.focus({ preventScroll: true });
          select(null);
          background?.select(false);
        }}
        onPointerMove={onStage(move)}
        onPointerUp={onStage(end)}
        onPointerCancel={cancel}
        onDragOver={(event) => {
          if (event.dataTransfer.types.includes("Files"))
            event.preventDefault();
        }}
        onDrop={(event) => {
          if (!event.dataTransfer.files.length) return;
          event.preventDefault();
          dropFiles(event.dataTransfer.files, bodyPoint(event));
        }}
      >
        <img
          className="bubble-preview-image"
          src={preview}
          alt={t("message.1000")}
          draggable={false}
          style={{ width: px(geometry.width), height: px(geometry.height) }}
        />
        {background && backgroundShown && (
          <div
            role="button"
            tabIndex={-1}
            aria-label={t("message.1074")}
            aria-pressed={background.selected}
            className={`canvas-layer canvas-background${
              background.selected ? " is-selected" : ""
            }`}
            style={{
              left: PAD + (body.x + backgroundShown.x) * zoom,
              top: PAD + (body.y + backgroundShown.y) * zoom,
              width: px(backgroundShown.width),
              height: px(backgroundShown.height),
            }}
            onPointerDown={beginBackground(null)}
            onPointerMove={moveBackground}
            onPointerUp={endBackground}
            onPointerCancel={cancel}
          >
            {background.selected &&
              BACKGROUND_HANDLES.map((handle) => (
                <span
                  key={handle}
                  className={`canvas-handle canvas-handle-${handle}`}
                  onPointerDown={beginBackground(handle)}
                  onPointerMove={moveBackground}
                  onPointerUp={endBackground}
                  onPointerCancel={cancel}
                />
              ))}
          </div>
        )}
        {live?.guides.map((guide, index) => (
          <span
            key={index}
            className={`canvas-guide canvas-guide-${guide.axis}`}
            style={
              guide.axis === "x"
                ? { left: PAD + (body.x + guide.at) * zoom }
                : { top: PAD + (body.y + guide.at) * zoom }
            }
          />
        ))}
        {[
          ...petLayers.filter((layer) => layer.placement === "back"),
          ...petLayers.filter((layer) => layer.placement !== "back"),
        ].map((layer) => {
          const box = layerBox(layer, body, radius);
          return (
            <div
              key={`@pet:${layer.id}`}
              role="button"
              tabIndex={-1}
              aria-label={layer.name || t("bubble.editor.pet_layer_tag")}
              className="canvas-layer canvas-pet-layer"
              style={{
                left: PAD + (body.x + box.x) * zoom,
                top: PAD + (body.y + box.y) * zoom,
                width: px(box.width),
                height: px(box.height),
                transform: layer.rotation
                  ? `rotate(${layer.rotation}deg)`
                  : undefined,
              }}
              onPointerDown={adoptAndMove(layer)}
            />
          );
        })}
        {ordered.map((layer) => {
          const active = live?.id === layer.id ? live : null;
          const box = active?.box ?? layerBox(layer, body, radius);
          const rotation = active?.rotation ?? layer.rotation;
          const isSelected = layer.id === selected;
          return (
            <div
              key={layer.id}
              role="button"
              tabIndex={-1}
              aria-label={layer.name || t("bubble.editor.layer")}
              aria-pressed={isSelected}
              className={`canvas-layer${isSelected ? " is-selected" : ""}${
                locked.has(layer.id) ? " is-locked" : ""
              }`}
              style={{
                left: PAD + (body.x + box.x) * zoom,
                top: PAD + (body.y + box.y) * zoom,
                width: px(box.width),
                height: px(box.height),
                transform: rotation ? `rotate(${rotation}deg)` : undefined,
              }}
              onPointerDown={begin(layer, "move")}
              onPointerMove={move}
              onPointerUp={end}
              onPointerCancel={cancel}
            >
              {active && thumbnails.get(layer.image) && (
                <img
                  className="canvas-layer-image"
                  src={thumbnails.get(layer.image)}
                  alt=""
                  draggable={false}
                  style={{
                    opacity: layer.alpha / 255,
                    transform: `scale(${layer.mirror ? -1 : 1}, ${
                      layer.flip_y ? -1 : 1
                    })`,
                  }}
                />
              )}
              {isSelected && !locked.has(layer.id) && (
                <>
                  {CORNERS.map((corner) => (
                    <span
                      key={corner}
                      className={`canvas-handle canvas-handle-${corner}`}
                      onPointerDown={begin(layer, "resize", corner)}
                      onPointerMove={move}
                      onPointerUp={end}
                      onPointerCancel={cancel}
                    />
                  ))}
                  <span
                    className="canvas-rotate"
                    title={t("bubble.editor.rotate_hint")}
                    onPointerDown={begin(layer, "rotate")}
                    onPointerMove={move}
                    onPointerUp={end}
                    onPointerCancel={cancel}
                  />
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );

  function cancelActive() {
    return action.current || backgroundAction.current || pan.current
      ? cancel()
      : false;
  }
}
