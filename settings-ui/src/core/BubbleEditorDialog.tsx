import { t } from "../../localization.cjs";
import type { KeyboardEvent } from "react";
import {
  Check,
  Eye,
  FolderOpen,
  Plus,
  Redo2,
  RotateCcw,
  Trash2,
  Undo2,
} from "lucide-react";
import { Field, Modal, Section, TabList } from "../components";
import { errorText } from "../errors";
import type {
  BubbleDecorLayer,
  Control,
  Element,
  ElementKind,
  Scalar,
  SettingsSnapshot,
} from "../types";
import { BubbleCanvas } from "./BubbleCanvas";
import {
  backgroundBox,
  freeBackground,
  freeBox,
  naturalHeight,
} from "./bubbleBackground";
import {
  dropMissingElements,
  editorTabs,
  elementKeys,
  elementKind,
  frameGroups,
  frameStart,
  hiddenThemeField,
  optionLabels,
  percentKeys,
  themeLabels,
  ThemeValues,
  typedKeys,
} from "./bubbleTheme";
import {
  Box,
  MAX_DECOR_LAYERS,
  adoptPetDecor,
  adoptablePetLayers,
  clampLayer,
  newLayer,
  placeLayer,
  uniqueId,
} from "./bubbleDecor";
import { DecorPanel } from "./DecorPanel";
import { ThemeLibrary } from "./ThemeLibrary";
import type { CoreSettingsState } from "./useCoreSettings";
import type {
  EditorTab,
  PreviewSample,
  useBubbleEditor,
} from "./useBubbleEditor";

const ARROWS: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

export function BubbleEditorDialog({
  bubble,
  snapshot,
  command,
}: {
  bubble: ReturnType<typeof useBubbleEditor>;
  snapshot: SettingsSnapshot;
  command: CoreSettingsState["command"];
}) {
  const {
    editor,
    draft,
    changeDraft,
    setEditorError,
    selectedLayer,
    setSelectedLayer,
    geometry,
  } = bubble;
  if (!editor) return null;
  const layers: BubbleDecorLayer[] = draft.decor ?? [];
  const setLayers = (
    next: BubbleDecorLayer[],
    selected?: string | null,
    extra: Partial<ThemeValues> = {},
  ) => {
    // A layer slider ends its preview here with the value it saves.
    if (bubble.previewOverride?.decor) bubble.setPreviewOverride(null);
    changeDraft({ ...draft, ...extra, decor: next });
    if (selected !== undefined) setSelectedLayer(selected);
  };
  const selected = layers.find((layer) => layer.id === selectedLayer) || null;
  // Pet frame layers become the user's own the moment one is pressed.
  const petLayers = adoptablePetLayers(
    draft,
    editor.packageDecor,
    editor.petId,
  );
  const adopted =
    !draft.package_layers &&
    layers.some((layer) => layer.image.startsWith(`pkg:${editor.petId}/`));
  const adopt = (id: string) => {
    const next = adoptPetDecor(layers, editor.packageDecor, id);
    setLayers(next.layers, next.selected?.id ?? null, {
      package_layers: false,
    });
    bubble.setBackgroundSelected(false);
    bubble.setEditorTab("decor");
    return next.selected;
  };
  // On the background tab the photo is a layer of its own on the preview.
  // A freely placed photo's box follows the draft at once, so a second drag
  // or repeated arrow keys never start from a preview still being drawn.
  const photoBox =
    bubble.editorTab !== "background" ||
    draft.background_image === "none" ||
    !geometry?.background
      ? null
      : draft.background_fit === "free"
        ? freeBox(draft, geometry.body)
        : backgroundBox(geometry);
  const placePhoto = (box: Box) => {
    if (geometry)
      changeDraft({ ...draft, ...freeBackground(box, geometry.body) });
  };
  /** A layer per imported image, centred on a body point when one is given. */
  const addLayers = (images: Element[], point?: { x: number; y: number }) => {
    const next = [...layers];
    let last: string | null = null;
    for (const image of images) {
      if (next.length >= MAX_DECOR_LAYERS) break;
      let created = newLayer(image, next);
      if (point && geometry)
        created = placeLayer(
          created,
          geometry.body,
          draft.radius,
          point.x - created.width / 2,
          point.y - created.height / 2,
        );
      next.push(clampLayer(created));
      last = created.id;
    }
    if (last === null) return;
    setLayers(next, last);
    bubble.setEditorTab("decor");
  };
  const editing = (event: { target: EventTarget }) =>
    ["INPUT", "SELECT", "TEXTAREA"].includes(
      (event.target as HTMLElement).tagName,
    );
  const onKeyDown = (event: KeyboardEvent) => {
    if (editing(event)) return;
    const key = event.key.toLowerCase();
    if (event.ctrlKey || event.metaKey) {
      if (key === "z" && !event.shiftKey) bubble.undo();
      else if (key === "y" || (key === "z" && event.shiftKey)) bubble.redo();
      else if (key === "d" && selected) {
        const copy = clampLayer({
          ...selected,
          id: uniqueId(layers, selected.id.replace(/-\d+$/, "") || "layer"),
          x: selected.x + 8,
          y: selected.y + 8,
        });
        setLayers([...layers, copy], copy.id);
      } else return;
      event.preventDefault();
      return;
    }
    if (!selected && bubble.backgroundSelected && photoBox) {
      const arrow = ARROWS[event.key];
      if (arrow) {
        const step = event.shiftKey ? 10 : 1;
        placePhoto({
          ...photoBox,
          x: photoBox.x + arrow[0] * step,
          y: photoBox.y + arrow[1] * step,
        });
      } else if (event.key === "Escape") {
        event.stopPropagation();
        bubble.setBackgroundSelected(false);
      } else return;
      event.preventDefault();
      return;
    }
    if (!selected || bubble.lockedLayers.has(selected.id)) {
      if (event.key === "Escape" && selected) {
        event.stopPropagation();
        setSelectedLayer(null);
      }
      return;
    }
    const arrow = ARROWS[event.key];
    if (arrow) {
      const step = event.shiftKey ? 10 : 1;
      setLayers(
        layers.map((layer) =>
          layer.id === selected.id
            ? clampLayer({
                ...layer,
                x: layer.x + arrow[0] * step,
                y: layer.y + arrow[1] * step,
              })
            : layer,
        ),
      );
    } else if (event.key === "Delete" || event.key === "Backspace") {
      setLayers(
        layers.filter((layer) => layer.id !== selected.id),
        null,
      );
    } else if (event.key === "Escape") {
      event.stopPropagation();
      setSelectedLayer(null);
    } else return;
    event.preventDefault();
  };
  const tabs = editorTabs.map(([id, label]) => [id, label] as [string, string]);
  // Built-in ornaments as layer images, under the names the fields use.
  const ornaments = editor.ornaments.map((item) => ({
    ...item,
    name: optionLabels[item.id.replace(/^ornament:/, "")] || item.name,
  }));
  const groups = editorTabs.find(([id]) => id === bubble.editorTab)?.[2] ?? [];
  const field = (key: string) => {
    const percent = percentKeys.includes(key);
    const toStored = (shown: Scalar) =>
      percent ? Math.round((Number(shown) * 255) / 100) : Number(shown);
    const stored = draft[key] as Scalar;
    const slider = typeof stored === "number" && !typedKeys.includes(key);
    const value = percent ? Math.round((Number(stored) * 100) / 255) : stored;
    let options = editor.choices[key]?.map((id) => ({
      value: id,
      label: editor.labels?.[key]?.[id] || optionLabels[id] || id,
    }));
    if (elementKeys.includes(key))
      options = [
        ...(options || [{ value: "none", label: t("message.0754") }]),
        ...[...editor.elements]
          .sort(
            (a, b) =>
              Number(b.kind === elementKind(key)) -
              Number(a.kind === elementKind(key)),
          )
          .map((element) => ({ value: element.id, label: element.name })),
      ];
    return (
      <Field
        key={key}
        field={
          {
            key,
            label: themeLabels[key] || key,
            value,
            kind: options
              ? "select"
              : typeof value === "boolean"
                ? "bool"
                : typeof value === "number"
                  ? slider
                    ? "range"
                    : "number"
                  : "color",
            group: "",
            options,
            ...(typeof value === "number" ? editor.limits?.[key] : {}),
            ...(percent ? { min: 0, max: 100, step: 1, unit: "%" } : {}),
          } as Control
        }
        // A slider redraws the preview as it moves and saves once on release.
        preview={
          slider
            ? (shown) => bubble.setPreviewOverride({ [key]: toStored(shown) })
            : undefined
        }
        change={(next) => {
          if (next === undefined) return;
          if (slider) bubble.setPreviewOverride(null);
          if (percent) changeDraft({ ...draft, [key]: toStored(next) });
          else if (key in frameGroups && next === true)
            // Start from what the bubble draws now, then change it.
            changeDraft({
              ...draft,
              [key]: true,
              ...frameStart(key, draft, editor.frameValues),
            });
          else if (key === "background_fit" && next === "free" && geometry) {
            // Start from where the photo is drawn now, so nothing jumps.
            if (photoBox) placePhoto(photoBox);
            else {
              const width = Math.round(geometry.body.width / 2);
              changeDraft({
                ...draft,
                background_fit: "free",
                background_x: 50,
                background_y: 50,
                background_width: width,
                background_height: naturalHeight(
                  draft.background_image,
                  width,
                  editor.elements,
                ),
              });
            }
          } else if (
            key === "background_image" &&
            String(next).startsWith("builtin:") &&
            draft.background_fit !== "free"
          ) {
            // A pattern tile is placed like an attached image, one copy in
            // the middle, ready to move and resize.
            const size = Math.round(
              Math.min(96, (geometry?.body.width ?? 192) / 2),
            );
            changeDraft({
              ...draft,
              [key]: String(next),
              background_fit: "free",
              background_x: 50,
              background_y: 50,
              background_width: size,
              background_height: size,
            });
          } else if (
            key === "background_image" &&
            String(next).startsWith("user:") &&
            draft.background_fit === "tile"
          )
            // A tiled photo has no box to pick on the preview; fill instead.
            changeDraft({
              ...draft,
              [key]: String(next),
              background_fit: "cover",
            });
          else changeDraft({ ...draft, [key]: next });
        }}
      />
    );
  };
  // Import buttons under the image fields; the new image is chosen at once.
  const imageImports: Record<
    string,
    [ElementKind, string, Record<string, Scalar>]
  > = {
    background_image: [
      "photo",
      t("bubble.editor.add_background_image"),
      { background_fit: "cover" },
    ],
    frame_image: ["frame", t("message.0990"), {}],
  };
  const chosenImage = (key: string) =>
    editor.elements.find((element) => element.id === draft[key]);
  const importInto = (key: string) => {
    const [kind, , extra] = imageImports[key];
    bubble.assetChange(kind).then((images) => {
      if (images.length)
        changeDraft({ ...draft, ...extra, [key]: images[0].id });
    });
  };
  // Presets and resets: under the preview, or above the tabs in a narrow
  // window where only the drawing stays pinned.
  const designTools = (where: "preview" | "controls") => (
    <div className={`design-tools design-tools-${where}`}>
      <div className="preset-section">
        <h3 id={`bubble-presets-${where}`} className="preset-heading">
          {t("message.0984")}
        </h3>
        <div
          className="preset-gallery"
          role="group"
          aria-labelledby={`bubble-presets-${where}`}
        >
          {(editor.presets || []).map((preset) => (
            <button
              key={preset.id}
              className="preset-chip"
              onClick={() => changeDraft({ ...draft, ...preset.values })}
            >
              <span
                className="preset-swatch"
                style={{
                  background: preset.values.background,
                  borderColor: preset.values.border,
                }}
              />
              {preset.label}
            </button>
          ))}
        </div>
      </div>
      <div className="button-row">
        <button
          className="button compact"
          onClick={() => {
            changeDraft({ ...editor.packageTheme } as ThemeValues);
            bubble.setResetDraft(true);
            setSelectedLayer(null);
          }}
        >
          <RotateCcw size={13} />
          {t("message.0558")}
        </button>
        <button className="button compact" onClick={bubble.reloadSavedTheme}>
          {t("message.1004")}
        </button>
      </div>
    </div>
  );
  return (
    <Modal
      className="bubble-editor-modal"
      title={t("message.0978", { value0: snapshot.pet.display_name })}
      close={bubble.closeEditor}
      footer={
        <>
          <span className="draft-status" aria-live="polite">
            {bubble.resetDraft
              ? t("message.0979")
              : !bubble.dirty
                ? t("message.0980")
                : snapshot.pet.bubble_theme_mode !== "custom"
                  ? t("message.0981")
                  : t("message.0982")}
          </span>
          <button
            className="button"
            disabled={bubble.editorBusy}
            onClick={bubble.closeEditor}
          >
            {t("message.0650")}
          </button>
          <button
            className="button primary"
            disabled={bubble.editorBusy || !bubble.dirty || bubble.editorStale}
            onClick={bubble.saveEditor}
          >
            <Check size={14} />
            {t("message.0983")}
          </button>
        </>
      }
    >
      <div
        className="editor-grid"
        onKeyDown={onKeyDown}
        onPaste={(event) => {
          // Text fields keep their own paste; elsewhere an image becomes a layer.
          const image = Array.from(event.clipboardData.files).find((file) =>
            file.type.startsWith("image/"),
          );
          if (editing(event) || !image) return;
          event.preventDefault();
          bubble.pasteImage(image).then((images) => addLayers(images));
        }}
      >
        <div className="editor-controls">
          {designTools("controls")}
          <TabList
            id="bubble-editor"
            label={t("bubble.editor.tabs")}
            tabs={tabs}
            value={bubble.editorTab}
            select={(key) => bubble.setEditorTab(key as EditorTab)}
          />
          <div
            id="bubble-editor-panel"
            role="tabpanel"
            aria-labelledby={`bubble-editor-tab-${bubble.editorTab}`}
            className="editor-tab-panel"
          >
            {bubble.editorTab === "themes" && <ThemeLibrary bubble={bubble} />}
            {bubble.editorTab === "decor" && (
              <DecorPanel
                layers={layers}
                change={setLayers}
                preview={(next) => bubble.setPreviewOverride({ decor: next })}
                selected={selectedLayer}
                select={setSelectedLayer}
                locked={bubble.lockedLayers}
                toggleLock={bubble.toggleLock}
                images={editor.elements}
                packageImages={editor.packageImages}
                ornaments={ornaments}
                petLayers={petLayers}
                adopt={adopt}
                adopted={adopted}
                framed={draft.frame_style !== "standard"}
                packageLayers={draft.package_layers}
                frameField={field("frame_style")}
                importImages={() =>
                  bubble
                    .assetChange("sticker")
                    .then((images) => addLayers(images))
                }
                body={geometry?.body ?? null}
                radius={draft.radius}
              />
            )}
            {groups.map(([title, keys]) => {
              const shown = keys.filter(
                (key) => key in draft && !hiddenThemeField(key, draft),
              );
              return (
                shown.length > 0 && (
                  <Section title={title} key={title}>
                    <div className="card-body editor-fields-list">
                      {shown.map((key) => [
                        field(key),
                        // Adding an image sits right under the field it fills.
                        key in imageImports && (
                          <div className="button-row" key={`${key}-import`}>
                            <button
                              className="button compact"
                              disabled={bubble.editorBusy}
                              onClick={() => importInto(key)}
                            >
                              <Plus size={13} />
                              {imageImports[key][1]}
                            </button>
                            <button
                              className="button compact"
                              onClick={() => openImageFolder(setEditorError)}
                            >
                              <FolderOpen size={13} />
                              {t("bubble.editor.open_folder")}
                            </button>
                            {/* Only the user's own images can be deleted. */}
                            {chosenImage(key) && (
                              <button
                                className="button compact danger"
                                disabled={bubble.editorBusy}
                                onClick={() =>
                                  deleteImage(
                                    chosenImage(key)!,
                                    bubble,
                                    command,
                                  )
                                }
                              >
                                <Trash2 size={13} />
                                {t("bubble.editor.delete_image")}
                              </button>
                            )}
                          </div>
                        ),
                      ])}
                      {shown.includes("background_height") && (
                        <div className="button-row">
                          <button
                            className="button compact"
                            onClick={() =>
                              changeDraft({
                                ...draft,
                                background_height: naturalHeight(
                                  draft.background_image,
                                  draft.background_width,
                                  editor.elements,
                                ),
                              })
                            }
                          >
                            <RotateCcw size={13} />
                            {t("bubble.editor.background_ratio")}
                          </button>
                        </div>
                      )}
                    </div>
                  </Section>
                )
              );
            })}
            {bubble.editorTab === "decor" ? (
              <ImageLibrary
                bubble={bubble}
                command={command}
                setEditorError={setEditorError}
              />
            ) : null}
          </div>
        </div>
        <div className="editor-preview">
          <div className="preview-heading">
            <Eye size={15} />
            {t("message.0994")}
            <span className="preview-tools">
              <button
                className="icon-button"
                aria-label={t("bubble.editor.undo")}
                title={t("bubble.editor.undo")}
                disabled={!bubble.canUndo}
                onClick={bubble.undo}
              >
                <Undo2 size={14} />
              </button>
              <button
                className="icon-button"
                aria-label={t("bubble.editor.redo")}
                title={t("bubble.editor.redo")}
                disabled={!bubble.canRedo}
                onClick={bubble.redo}
              >
                <Redo2 size={14} />
              </button>
            </span>
          </div>
          <div className="preview-options">
            <span
              className="segmented preview-samples"
              role="group"
              aria-label={t("message.0995")}
            >
              {(
                [
                  ["notice", t("message.0996")],
                  ["long", t("bubble.editor.long")],
                  ["project", t("message.0997")],
                ] as [PreviewSample, string][]
              ).map(([value, label]) => (
                <button
                  key={value}
                  aria-pressed={bubble.previewSample === value}
                  onClick={() => bubble.setPreviewSample(value)}
                >
                  {label}
                </button>
              ))}
            </span>
            <span
              className="segmented"
              role="group"
              aria-label={t("bubble.editor.zoom")}
            >
              {[1, 2].map((value) => (
                <button
                  key={value}
                  aria-pressed={bubble.zoom === value}
                  onClick={() => bubble.setZoom(value)}
                >
                  {value * 100}%
                </button>
              ))}
            </span>
          </div>
          <div className="bubble-scene">
            {bubble.preview && geometry ? (
              <BubbleCanvas
                preview={bubble.preview}
                geometry={geometry}
                zoom={bubble.zoom}
                layers={layers}
                radius={draft.radius}
                selected={selectedLayer}
                locked={bubble.lockedLayers}
                images={[
                  ...editor.packageImages,
                  ...editor.elements,
                  ...ornaments,
                ]}
                select={(id) => {
                  setSelectedLayer(id);
                  if (!id) return;
                  bubble.setBackgroundSelected(false);
                  bubble.setEditorTab("decor");
                }}
                dragging={bubble.setDraggedLayer}
                petLayers={petLayers}
                adopt={adopt}
                dropFiles={(files, point) =>
                  bubble
                    .dropImages(files)
                    .then((images) => addLayers(images, point))
                }
                commit={(layer) =>
                  setLayers(
                    layers.map((item) =>
                      item.id === layer.id ? clampLayer(layer) : item,
                    ),
                  )
                }
                background={
                  photoBox && {
                    box: photoBox,
                    selected: bubble.backgroundSelected,
                    select: bubble.setBackgroundSelected,
                    preview: bubble.setPreviewOverride,
                    commit: bubble.commitPreviewOverride,
                    cancel: () => bubble.setPreviewOverride(null),
                  }
                }
              />
            ) : (
              <p>{t("message.1001")}</p>
            )}
          </div>
          <p className="footnote">
            {photoBox
              ? t("bubble.editor.background_hint")
              : petLayers.length > 0
                ? t("bubble.editor.pet_layers_hint")
                : layers.length > 0
                  ? t("bubble.editor.canvas_hint")
                  : t("message.1002")}
          </p>
          {bubble.editorNotice && (
            <p className="editor-notice" role="status">
              {bubble.editorNotice}
            </p>
          )}
          {bubble.renderError && (
            <div className="error-banner" role="alert">
              <span>{bubble.renderError}</span>
            </div>
          )}
          {bubble.editorError && (
            <div className="error-banner" role="alert">
              <span>{bubble.editorError}</span>
              {bubble.editorStale && (
                <button
                  className="button compact"
                  onClick={bubble.rebaseEditor}
                >
                  <RotateCcw size={13} />
                  {t("message.1003")}
                </button>
              )}
            </div>
          )}
          {designTools("preview")}
        </div>
      </div>
    </Modal>
  );
}

/** Show the image library folder in Explorer; its path stays in Python. */
function openImageFolder(fail: (text: string) => void) {
  window
    .settings!.request("element.open_folder")
    .catch((error) => fail(errorText(error)));
}

/**
 * Delete a library image after confirming, naming saved pet designs that use
 * it. The library refreshes and the draft stops using the image.
 */
async function deleteImage(
  element: Element,
  bubble: ReturnType<typeof useBubbleEditor>,
  command: CoreSettingsState["command"],
) {
  const usage = await window
    .settings!.request("element.usage", { reference: element.id })
    .catch(() => ({ pets: [] as string[], designs: [] as string[] }));
  const pets = usage.pets.join(", ");
  const designs = usage.designs.join(", ");
  const question =
    pets && designs
      ? t("bubble.editor.delete_used_both", { pets, designs })
      : pets
        ? t("bubble.editor.delete_used", { pets })
        : designs
          ? t("bubble.editor.delete_used_designs", { designs })
          : t("message.0993");
  if (!confirm(question)) return;
  command("element.delete", { reference: element.id }, { inline: true })
    .then(async () => {
      const updated = await window.settings!.request("bubble.editor");
      bubble.setEditor((value) =>
        value
          ? {
              ...value,
              elements: updated.elements,
              revision: updated.revision,
            }
          : null,
      );
      const known = new Set<string>(updated.elements.map((item) => item.id));
      bubble.setDraft((value) => dropMissingElements(value, known));
    })
    .catch((error) => bubble.setEditorError(errorText(error)));
}

/**
 * The user's images, folded away by default. Import and delete apply right
 * away; files dropped on it, open or folded, are imported too.
 */
function ImageLibrary({
  bubble,
  command,
  setEditorError,
}: {
  bubble: ReturnType<typeof useBubbleEditor>;
  command: CoreSettingsState["command"];
  setEditorError: (value: string) => void;
}) {
  const editor = bubble.editor!;
  return (
    <section
      className="section library-section"
      title={t("bubble.editor.library_hint")}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) event.preventDefault();
      }}
      onDrop={(event) => {
        if (!event.dataTransfer.files.length) return;
        event.preventDefault();
        bubble.dropImages(event.dataTransfer.files);
      }}
    >
      <details className="library-details">
        <summary className="section-heading">
          <h2>
            {t("bubble.editor.library_title", {
              count: editor.elements.length,
            })}
          </h2>
        </summary>
        <div className="card">
          <div className="card-body">
            <p className="footnote">{t("message.0986")}</p>
            <div className="import-options">
              <label>
                <input
                  type="checkbox"
                  checked={bubble.importOptions.trim === true}
                  onChange={(event) =>
                    bubble.setImportOptions({
                      ...bubble.importOptions,
                      trim: event.target.checked,
                    })
                  }
                />
                {t("bubble.editor.import_trim")}
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={bubble.importOptions.clearWhite === true}
                  onChange={(event) =>
                    bubble.setImportOptions({
                      ...bubble.importOptions,
                      clearWhite: event.target.checked,
                    })
                  }
                />
                {t("bubble.editor.import_clear_white")}
              </label>
            </div>
            <div className="button-row">
              {/* Any image goes anywhere, so one import serves every use. */}
              <button
                className="button compact"
                disabled={bubble.editorBusy}
                onClick={() => bubble.assetChange("sticker")}
              >
                <Plus size={13} />
                {t("bubble.editor.add_image")}
              </button>
              <button
                className="button compact"
                onClick={() => openImageFolder(setEditorError)}
              >
                <FolderOpen size={13} />
                {t("bubble.editor.open_folder")}
              </button>
            </div>
            <ul className="library-grid">
              {editor.elements.map((element) => (
                <li
                  className="library-item"
                  key={element.id}
                  title={element.name}
                >
                  <img src={element.thumbnail} alt={element.name} />
                  <button
                    className="icon-button"
                    aria-label={t("message.0992", { value0: element.name })}
                    onClick={() => deleteImage(element, bubble, command)}
                  >
                    <Trash2 size={13} />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </details>
    </section>
  );
}
