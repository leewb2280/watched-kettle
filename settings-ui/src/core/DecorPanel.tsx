import { t } from "../../localization.cjs";
import {
  ArrowDown,
  ArrowUp,
  Copy,
  Eye,
  EyeOff,
  FlipHorizontal2,
  FlipVertical2,
  Lock,
  LockOpen,
  Plus,
  RotateCcw,
  Trash2,
} from "lucide-react";
import type { ReactNode } from "react";
import { Field, NumberInput, Section, Switch } from "../components";
import type {
  BubbleBox,
  BubbleDecorLayer,
  Control,
  Element,
  Scalar,
} from "../types";
import { naturalHeight } from "./bubbleBackground";
import {
  DECOR_LIMITS,
  DECOR_PERCENT,
  MAX_DECOR_LAYERS,
  REPEAT_ANCHORS,
  clampLayer,
  imageName,
  layerPercent,
  mirroredCopy,
  newLayer,
  placeLayerAtPercent,
  uniqueId,
} from "./bubbleDecor";

const THEME_TINTS = ["border", "background", "text", "shadow"];
const anchorLabels: Record<string, string> = {
  "top-left": t("bubble.editor.anchor.top-left"),
  "top-center": t("bubble.editor.anchor.top-center"),
  "top-right": t("bubble.editor.anchor.top-right"),
  "center-left": t("bubble.editor.anchor.center-left"),
  "center-right": t("bubble.editor.anchor.center-right"),
  "bottom-left": t("bubble.editor.anchor.bottom-left"),
  "bottom-center": t("bubble.editor.anchor.bottom-center"),
  "bottom-right": t("bubble.editor.anchor.bottom-right"),
  "arc-top-left": t("bubble.editor.anchor.arc-top-left"),
};
const fieldLabels: Record<string, string> = {
  image: t("bubble.editor.field.image"),
  placement: t("bubble.editor.field.placement"),
  anchor: t("bubble.editor.field.anchor"),
  position_x: t("bubble.editor.field.position_x"),
  position_y: t("bubble.editor.field.position_y"),
  width: t("bubble.editor.field.width"),
  height: t("bubble.editor.field.height"),
  rotation: t("bubble.editor.field.rotation"),
  alpha: t("bubble.editor.field.alpha"),
  tint: t("bubble.editor.field.tint"),
  mirror: t("bubble.editor.field.mirror"),
  flip_y: t("bubble.editor.field.flip_y"),
  repeat: t("bubble.editor.field.repeat"),
  repeat_gap: t("bubble.editor.field.repeat_gap"),
  repeat_inset: t("bubble.editor.field.repeat_inset"),
};
const tintLabels: Record<string, string> = {
  border: t("bubble.editor.tint.border"),
  background: t("bubble.editor.tint.background"),
  text: t("bubble.editor.tint.text"),
  shadow: t("bubble.editor.tint.shadow"),
};
const repeatLabels: Record<string, string> = {
  none: t("bubble.editor.repeat.none"),
  x: t("bubble.editor.repeat.x"),
  y: t("bubble.editor.repeat.y"),
};

/** Decoration layers of the draft: list, add, order and per-layer settings. */
export function DecorPanel({
  layers,
  change,
  preview,
  selected,
  select,
  locked,
  toggleLock,
  images,
  packageImages,
  ornaments,
  petLayers,
  adopt,
  adopted,
  framed,
  packageLayers,
  frameField,
  importImages,
  body,
  radius,
}: {
  layers: BubbleDecorLayer[];
  change: (
    layers: BubbleDecorLayer[],
    selected?: string | null,
    extra?: { package_layers?: boolean },
  ) => void;
  /** Layers drawn while a slider moves, before `change` saves them. */
  preview: (layers: BubbleDecorLayer[]) => void;
  selected: string | null;
  select: (id: string | null) => void;
  locked: Set<string>;
  toggleLock: (id: string) => void;
  images: Element[];
  packageImages: Element[];
  /** Built-in ornaments, drawn in the theme's colors. */
  ornaments: Element[];
  /** Pet frame layers that pressing copies into the user's own layers. */
  petLayers: BubbleDecorLayer[];
  adopt: (id: string) => void;
  /** The pet frame was copied into the layers and its own is off. */
  adopted: boolean;
  framed: boolean;
  packageLayers: boolean;
  /** The pet frame field, shown with the pet layer switch. */
  frameField: ReactNode;
  importImages: () => void;
  body: BubbleBox | null;
  radius: number;
}) {
  const all = [...packageImages, ...images, ...ornaments];
  const full = layers.length >= MAX_DECOR_LAYERS;
  const layer = layers.find((item) => item.id === selected) || null;
  const add = (image: Element | undefined) => {
    if (!image || full) return;
    const created = newLayer(image, layers);
    change([...layers, created], created.id);
  };
  // An ornament starts in the middle like a background pattern, to be moved.
  const addOrnament = (image: Element | undefined) => {
    if (!image || full) return;
    let created = newLayer(image, layers);
    if (body) created = placeLayerAtPercent(created, body, radius, 50, 50);
    change([...layers, clampLayer(created)], created.id);
  };
  const replaced = (next: BubbleDecorLayer) =>
    layers.map((item) => (item.id === next.id ? clampLayer(next) : item));
  const update = (next: BubbleDecorLayer) => change(replaced(next));
  // Rows read top to bottom like the bubble: front layers above the body.
  const rows = [
    ...layers.filter((item) => item.placement !== "back").reverse(),
    null,
    ...layers.filter((item) => item.placement === "back").reverse(),
  ];
  const reorder = (item: BubbleDecorLayer, forward: boolean) => {
    const peers = layers.filter((other) => other.placement === item.placement);
    const index = peers.indexOf(item);
    const target = peers[index + (forward ? 1 : -1)];
    if (!target) return;
    const next = [...layers];
    const a = next.indexOf(item);
    const b = next.indexOf(target);
    [next[a], next[b]] = [next[b], next[a]];
    change(next);
  };
  const label = (item: BubbleDecorLayer) =>
    item.name || imageName(item.image, all) || t("bubble.editor.layer");
  return (
    <>
      <Section title={t("bubble.editor.layers")}>
        <div className="card-body decor-panel">
          {frameField}
          {framed && (
            <div className="setting-row">
              <label htmlFor="decor-package-layers">
                {t("bubble.editor.package_layers")}
              </label>
              <div className="row-control">
                <Switch
                  id="decor-package-layers"
                  label={t("bubble.editor.package_layers")}
                  value={packageLayers}
                  change={(value) =>
                    change(layers, undefined, {
                      package_layers: Boolean(value),
                    })
                  }
                />
              </div>
            </div>
          )}
          {adopted && (
            <p className="footnote">{t("bubble.editor.pet_layers_adopted")}</p>
          )}
          <div className="button-row decor-add-row">
            <button
              className="button compact"
              disabled={full}
              onClick={importImages}
            >
              <Plus size={13} />
              {t("bubble.editor.add_image")}
            </button>
            <select
              className="button compact"
              aria-label={t("bubble.editor.add_from_library")}
              disabled={full || all.length === 0}
              value=""
              onChange={(event) =>
                add(all.find((image) => image.id === event.target.value))
              }
            >
              <option value="">{t("bubble.editor.my_images")}</option>
              {packageImages.length > 0 && (
                <optgroup label={t("bubble.editor.pet_images")}>
                  {packageImages.map((image) => (
                    <option key={image.id} value={image.id}>
                      {image.name}
                    </option>
                  ))}
                </optgroup>
              )}
              {images.length > 0 && (
                <optgroup label={t("bubble.editor.my_images")}>
                  {images.map((image) => (
                    <option key={image.id} value={image.id}>
                      {image.name}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
            <select
              className="button compact"
              aria-label={t("bubble.editor.add_ornament")}
              disabled={full || ornaments.length === 0}
              value=""
              onChange={(event) =>
                addOrnament(
                  ornaments.find((image) => image.id === event.target.value),
                )
              }
            >
              <option value="">{t("bubble.editor.group.builtin")}</option>
              {ornaments.map((image) => (
                <option key={image.id} value={image.id}>
                  {image.name}
                </option>
              ))}
            </select>
          </div>
          {full && (
            <p className="footnote">
              {t("bubble.editor.layer_limit", { count: MAX_DECOR_LAYERS })}
            </p>
          )}
          {petLayers.length > 0 && (
            <ul
              className="layer-list pet-layer-list"
              aria-label={t("bubble.editor.pet_layer_tag")}
            >
              {petLayers.map((item) => (
                <li key={`@pet:${item.id}`} className="layer-row is-pet">
                  <button
                    className="layer-select"
                    title={t("bubble.editor.pet_layers_hint")}
                    onClick={() => adopt(item.id)}
                  >
                    <img
                      src={
                        all.find((image) => image.id === item.image)?.thumbnail
                      }
                      alt=""
                    />
                    <span>{label(item)}</span>
                    <span className="layer-tag">
                      {t("bubble.editor.pet_layer_tag")}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {layers.length === 0 ? (
            petLayers.length === 0 && (
              <p className="footnote">{t("bubble.editor.empty_layers")}</p>
            )
          ) : (
            <ul className="layer-list" aria-label={t("bubble.editor.layers")}>
              {rows.map((item) =>
                item === null ? (
                  <li key="body" className="layer-body-marker">
                    {t("bubble.editor.body_marker")}
                  </li>
                ) : (
                  <li
                    key={item.id}
                    className={`layer-row${item.id === selected ? " is-selected" : ""}`}
                  >
                    <button
                      className="layer-select"
                      aria-pressed={item.id === selected}
                      onClick={() => select(item.id)}
                    >
                      <img
                        src={
                          all.find((image) => image.id === item.image)
                            ?.thumbnail
                        }
                        alt=""
                      />
                      <span data-user-text>{label(item)}</span>
                    </button>
                    <button
                      className="icon-button"
                      aria-label={t(
                        item.hidden
                          ? "bubble.editor.show_layer"
                          : "bubble.editor.hide_layer",
                        { name: label(item) },
                      )}
                      onClick={() => update({ ...item, hidden: !item.hidden })}
                    >
                      {item.hidden ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                    <button
                      className="icon-button"
                      aria-label={t(
                        locked.has(item.id)
                          ? "bubble.editor.unlock_layer"
                          : "bubble.editor.lock_layer",
                        { name: label(item) },
                      )}
                      onClick={() => toggleLock(item.id)}
                    >
                      {locked.has(item.id) ? (
                        <Lock size={14} />
                      ) : (
                        <LockOpen size={14} />
                      )}
                    </button>
                    <button
                      className="icon-button"
                      aria-label={t("bubble.editor.raise", {
                        name: label(item),
                      })}
                      onClick={() => reorder(item, true)}
                    >
                      <ArrowUp size={14} />
                    </button>
                    <button
                      className="icon-button"
                      aria-label={t("bubble.editor.lower", {
                        name: label(item),
                      })}
                      onClick={() => reorder(item, false)}
                    >
                      <ArrowDown size={14} />
                    </button>
                  </li>
                ),
              )}
            </ul>
          )}
        </div>
      </Section>
      {layer ? (
        <LayerInspector
          key={layer.id}
          layer={layer}
          images={all}
          packageImages={packageImages}
          libraryImages={images}
          ornaments={ornaments}
          body={body}
          radius={radius}
          update={update}
          preview={(next) => preview(replaced(next))}
          duplicate={() => {
            if (full) return;
            const copy = {
              ...layer,
              id: uniqueId(layers, layer.id.replace(/-\d+$/, "") || "layer"),
              x: layer.x + 8,
              y: layer.y + 8,
            };
            change([...layers, clampLayer(copy)], copy.id);
          }}
          mirror={
            body && !full
              ? () => {
                  const copy = mirroredCopy(layer, layers, body, radius);
                  change([...layers, clampLayer(copy)], copy.id);
                }
              : undefined
          }
          remove={() =>
            change(
              layers.filter((item) => item.id !== layer.id),
              null,
            )
          }
        />
      ) : (
        layers.length > 0 && (
          <p className="footnote decor-hint">
            {t("bubble.editor.selected_none")}
          </p>
        )
      )}
    </>
  );
}

function LayerInspector({
  layer,
  images,
  packageImages,
  libraryImages,
  ornaments,
  body,
  radius,
  update,
  preview,
  duplicate,
  mirror,
  remove,
}: {
  layer: BubbleDecorLayer;
  images: Element[];
  packageImages: Element[];
  libraryImages: Element[];
  ornaments: Element[];
  body: BubbleBox | null;
  radius: number;
  update: (layer: BubbleDecorLayer) => void;
  preview: (layer: BubbleDecorLayer) => void;
  duplicate: () => void;
  mirror?: () => void;
  remove: () => void;
}) {
  const set = (values: Partial<BubbleDecorLayer>) =>
    update({ ...layer, ...values });
  const field = (
    key: string,
    control: Partial<Control> & Pick<Control, "kind">,
    value: Scalar,
    onChange: (value: Scalar) => void,
    stored?: (value: number) => Partial<BubbleDecorLayer>,
  ) => (
    <Field
      key={key}
      field={
        {
          key: `decor_${key}`,
          label: fieldLabels[key],
          group: "",
          value,
          ...control,
        } as Control
      }
      // A slider redraws the preview as it moves and saves once on release.
      preview={stored && ((shown) => preview({ ...layer, ...stored(shown) }))}
      change={(next) => next !== undefined && onChange(next)}
    />
  );
  const slider = (key: keyof typeof DECOR_LIMITS, unit = "px") =>
    field(
      key,
      {
        kind: "range",
        min: DECOR_LIMITS[key][0],
        max: DECOR_LIMITS[key][1],
        step: 1,
        unit,
      },
      layer[key],
      (value) => set({ [key]: Number(value) }),
      (value) => ({ [key]: value }),
    );
  // Sizes stay typed: they are sized with the handles on the preview.
  const size = (key: "width" | "height") => (
    <label className="decor-size-part">
      <span>{fieldLabels[key]}</span>
      <NumberInput
        field={
          {
            key: `decor_${key}`,
            label: fieldLabels[key],
            group: "",
            kind: "number",
            value: layer[key],
            min: DECOR_LIMITS[key][0],
            max: DECOR_LIMITS[key][1],
            step: 1,
            unit: "px",
          } as Control
        }
        change={(value) => set({ [key]: value })}
      />
    </label>
  );
  // The position is shown like the background photo's: the center as percent
  // of the body. It is saved as the nearest anchor and a distance, as a drag
  // on the preview saves it, so the layer stays by that edge in any length.
  const position = (axis: "x" | "y") => {
    if (!body) return null;
    const percent = layerPercent(layer, body, radius);
    const at = (value: number) =>
      placeLayerAtPercent(
        layer,
        body,
        radius,
        axis === "x" ? value : percent.x,
        axis === "y" ? value : percent.y,
      );
    return field(
      `position_${axis}`,
      {
        kind: "range",
        min: DECOR_PERCENT[0],
        max: DECOR_PERCENT[1],
        step: 0.1,
        unit: "%",
      },
      percent[axis],
      (value) => update(at(Number(value))),
      at,
    );
  };
  const flip = (key: "mirror" | "flip_y", Icon: typeof FlipHorizontal2) => (
    <button
      className="icon-button decor-toggle"
      aria-label={fieldLabels[key]}
      title={fieldLabels[key]}
      aria-pressed={layer[key]}
      onClick={() => set({ [key]: !layer[key] })}
    >
      <Icon size={15} />
    </button>
  );
  const alpha = (percent: number) => ({
    alpha: Math.round((percent / 100) * 255),
  });
  const imageOptions = [...packageImages, ...libraryImages, ...ornaments].map(
    (image) => ({ value: image.id, label: image.name }),
  );
  if (!images.some((image) => image.id === layer.image))
    imageOptions.unshift({
      value: layer.image,
      label: imageName(layer.image, images),
    });
  const tintChoice = !layer.tint
    ? ""
    : THEME_TINTS.includes(layer.tint)
      ? layer.tint
      : "custom";
  const repeatAnchors = REPEAT_ANCHORS[layer.repeat];
  return (
    <Section title={layer.name || imageName(layer.image, images)}>
      <div className="card-body decor-inspector">
        <div className="button-row">
          <button className="button compact" onClick={duplicate}>
            <Copy size={13} />
            {t("bubble.editor.duplicate")}
          </button>
          {mirror && (
            <button className="button compact" onClick={mirror}>
              <FlipHorizontal2 size={13} />
              {t("bubble.editor.mirror_copy")}
            </button>
          )}
          <button className="button compact danger" onClick={remove}>
            <Trash2 size={13} />
            {t("bubble.editor.delete_layer")}
          </button>
        </div>
        {field(
          "placement",
          {
            kind: "select",
            options: [
              { value: "front", label: t("bubble.editor.placement.front") },
              { value: "back", label: t("bubble.editor.placement.back") },
            ],
          },
          layer.placement,
          (value) => set({ placement: String(value) }),
        )}
        <h3 className="inspector-heading">
          {t("bubble.editor.layer_group.position")}
        </h3>
        {position("x")}
        {position("y")}
        <div className="setting-row decor-size-row">
          <span className="field-label-text">
            {t("bubble.editor.field.size")}
          </span>
          <div className="row-control">
            {size("width")}
            <span aria-hidden="true">×</span>
            {size("height")}
            <button
              className="icon-button"
              aria-label={t("bubble.editor.background_ratio")}
              title={t("bubble.editor.background_ratio")}
              onClick={() =>
                set({
                  height: naturalHeight(
                    layer.image,
                    layer.width,
                    images,
                    DECOR_LIMITS.height,
                  ),
                })
              }
            >
              <RotateCcw size={14} />
            </button>
          </div>
        </div>
        {slider("rotation", "°")}
        <h3 className="inspector-heading">
          {t("bubble.editor.layer_group.look")}
        </h3>
        {field(
          "alpha",
          { kind: "range", min: 0, max: 100, step: 1, unit: "%" },
          Math.round((layer.alpha / 255) * 100),
          (value) => set(alpha(Number(value))),
          alpha,
        )}
        {field(
          "tint",
          {
            kind: "select",
            options: [
              { value: "", label: t("bubble.editor.tint.none") },
              ...THEME_TINTS.map((tint) => ({
                value: tint,
                label: tintLabels[tint],
              })),
              { value: "custom", label: t("bubble.editor.tint.custom") },
            ],
          },
          tintChoice,
          (value) =>
            set({ tint: value === "custom" ? "#4f7a5c" : String(value) }),
        )}
        {tintChoice === "custom" &&
          field("tint", { kind: "color" }, layer.tint, (value) =>
            set({ tint: String(value) }),
          )}
        <div className="setting-row">
          <span className="field-label-text">
            {t("bubble.editor.field.flip")}
          </span>
          <div className="row-control">
            {flip("mirror", FlipHorizontal2)}
            {flip("flip_y", FlipVertical2)}
          </div>
        </div>
        <h3 className="inspector-heading">
          {t("bubble.editor.layer_group.repeat")}
        </h3>
        {field(
          "repeat",
          {
            kind: "select",
            options: ["none", "x", "y"].map((value) => ({
              value,
              label: repeatLabels[value],
            })),
          },
          layer.repeat,
          (value) => {
            const repeat = String(value);
            const allowed = REPEAT_ANCHORS[repeat];
            set({
              repeat,
              // Repeats run along an edge; pick an anchor that supports it.
              anchor:
                !allowed || allowed.includes(layer.anchor)
                  ? layer.anchor
                  : allowed[0],
            });
          },
        )}
        {/* Only a repeat needs its edge picked; other layers find their
            anchor from where they are placed. */}
        {repeatAnchors &&
          field(
            "anchor",
            {
              kind: "select",
              options: repeatAnchors.map((anchor) => ({
                value: anchor,
                label: anchorLabels[anchor],
              })),
            },
            layer.anchor,
            (value) => set({ anchor: String(value) }),
          )}
        {layer.repeat !== "none" && slider("repeat_gap")}
        {layer.repeat !== "none" && slider("repeat_inset")}
        {/* Swapping the image or renaming is rare; it waits behind "More". */}
        <details className="decor-more">
          <summary>{t("bubble.editor.layer_more")}</summary>
          {field(
            "image",
            { kind: "select", options: imageOptions },
            layer.image,
            (value) => set({ image: String(value) }),
          )}
          <div className="setting-row">
            <label htmlFor="decor-name">{t("bubble.editor.field.name")}</label>
            <div className="row-control">
              <input
                id="decor-name"
                type="text"
                maxLength={60}
                value={layer.name}
                data-user-text
                onChange={(event) => set({ name: event.target.value })}
              />
            </div>
          </div>
        </details>
      </div>
    </Section>
  );
}
