import { t } from "../../localization.cjs";
import { Check, Eye, Plus, RotateCcw, Trash2 } from "lucide-react";
import { Field, Modal, Section } from "../components";
import { errorText } from "../errors";
import type { Control } from "../types";
import {
  dropMissingElements,
  elementKeys,
  elementKind,
  hiddenThemeField,
  optionLabels,
  themeGroups,
  themeLabels,
} from "./bubbleTheme";
import type { CoreSettingsState } from "./useCoreSettings";
export function BubbleEditorDialog({
  editor,
  snapshot,
  closeEditor,
  resetDraft,
  dirty,
  editorBusy,
  editorStale,
  saveEditor,
  setResetDraft,
  setEditorNotice,
  setDraft,
  draft,
  assetChange,
  command,
  setEditor,
  setEditorError,
  previewSample,
  setPreviewSample,
  stickerSlot,
  setStickerSlot,
  preview,
  editorNotice,
  renderError,
  editorError,
  rebaseEditor,
  reloadSavedTheme,
}: Pick<
  CoreSettingsState,
  | "editor"
  | "snapshot"
  | "closeEditor"
  | "resetDraft"
  | "dirty"
  | "editorBusy"
  | "editorStale"
  | "saveEditor"
  | "setResetDraft"
  | "setEditorNotice"
  | "setDraft"
  | "draft"
  | "assetChange"
  | "command"
  | "setEditor"
  | "setEditorError"
  | "previewSample"
  | "setPreviewSample"
  | "stickerSlot"
  | "setStickerSlot"
  | "preview"
  | "editorNotice"
  | "renderError"
  | "editorError"
  | "rebaseEditor"
  | "reloadSavedTheme"
>) {
  return (
    <>
      {editor && (
        <Modal
          title={t("message.0978", { value0: snapshot.pet.display_name })}
          close={closeEditor}
          footer={
            <>
              <span className="draft-status" aria-live="polite">
                {resetDraft
                  ? t("message.0979")
                  : !dirty
                    ? t("message.0980")
                    : snapshot.pet.bubble_theme_mode !== "custom"
                      ? t("message.0981")
                      : t("message.0982")}
              </span>
              <button
                className="button"
                disabled={editorBusy}
                onClick={closeEditor}
              >
                {t("message.0650")}
              </button>
              <button
                className="button primary"
                disabled={editorBusy || !dirty || editorStale}
                onClick={saveEditor}
              >
                <Check size={14} />
                {t("message.0983")}
              </button>
            </>
          }
        >
          <div className="editor-grid">
            <div className="editor-controls">
              <div className="preset-gallery" aria-label={t("message.0984")}>
                {(editor.presets || []).map((preset) => (
                  <button
                    key={preset.id}
                    className="preset-chip"
                    onClick={() => {
                      setResetDraft(false);
                      setEditorNotice("");
                      setDraft({ ...draft, ...preset.values });
                    }}
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
              {themeGroups.map(([title, keys], groupIndex) => (
                <details
                  className="editor-group"
                  key={title}
                  open={groupIndex === 0}
                >
                  <summary>{title}</summary>
                  {keys
                    .filter(
                      (key) => key in draft && !hiddenThemeField(key, draft),
                    )
                    .map((key) => {
                      const value = draft[key];
                      let options = editor.choices[key]?.map((id) => ({
                        value: id,
                        label:
                          editor.labels?.[key]?.[id] || optionLabels[id] || id,
                      }));
                      if (elementKeys.includes(key))
                        options = [
                          ...(options || [
                            { value: "none", label: t("message.0754") },
                          ]),
                          ...editor.elements
                            .filter(
                              (element) => element.kind === elementKind(key),
                            )
                            .map((element) => ({
                              value: element.id,
                              label: element.name,
                            })),
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
                                    ? "number"
                                    : "color",
                              group: "",
                              options,
                              ...(typeof value === "number"
                                ? editor.limits?.[key]
                                : {}),
                            } as Control
                          }
                          change={(next) => {
                            setResetDraft(false);
                            setEditorNotice("");
                            if (next !== undefined)
                              setDraft({ ...draft, [key]: next });
                          }}
                        />
                      );
                    })}
                </details>
              ))}
              <Section title={t("message.0985")}>
                <div className="card-body">
                  <p className="footnote">{t("message.0986")}</p>
                  <div className="button-row">
                    <button
                      className="button compact"
                      onClick={() => assetChange("pattern")}
                    >
                      <Plus size={13} />
                      {t("message.0987")}
                    </button>
                    <button
                      className="button compact"
                      onClick={() => assetChange("ornament")}
                    >
                      <Plus size={13} />
                      {t("message.0988")}
                    </button>
                    {(
                      [
                        ["photo", t("message.0989")],
                        ["frame", t("message.0990")],
                        ["sticker", t("message.0991")],
                      ] as const
                    ).map(([kind, label]) => (
                      <button
                        className="button compact"
                        key={kind}
                        onClick={() => assetChange(kind)}
                      >
                        <Plus size={13} />
                        {label}
                      </button>
                    ))}
                  </div>
                  {editor.elements.map((element) => (
                    <div className="setting-row" key={element.id}>
                      <span>{element.name}</span>
                      <button
                        className="icon-button"
                        aria-label={t("message.0992", { value0: element.name })}
                        onClick={() => {
                          if (confirm(t("message.0993")))
                            command(
                              "element.delete",
                              { reference: element.id },
                              { inline: true },
                            )
                              .then(async () => {
                                const updated =
                                  await window.settings!.request(
                                    "bubble.editor",
                                  );
                                setEditor((value) =>
                                  value
                                    ? {
                                        ...value,
                                        elements: updated.elements,
                                        revision: updated.revision,
                                      }
                                    : null,
                                );
                                const known = new Set<string>(
                                  updated.elements.map((item) => item.id),
                                );
                                setDraft((value) =>
                                  dropMissingElements(value, known),
                                );
                              })
                              .catch((e) => setEditorError(errorText(e)));
                        }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              </Section>
            </div>
            <div className="editor-preview">
              <div className="preview-heading">
                <Eye size={15} />
                {t("message.0994")}
                <span
                  className="segmented preview-samples"
                  role="group"
                  aria-label={t("message.0995")}
                >
                  {(
                    [
                      ["notice", t("message.0996")],
                      ["project", t("message.0997")],
                    ] as const
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      aria-pressed={previewSample === value}
                      onClick={() => setPreviewSample(value)}
                    >
                      {label}
                    </button>
                  ))}
                </span>
              </div>
              {[1, 2, 3].some(
                (slot) => draft[`sticker_${slot}`] !== "none",
              ) && (
                <label className="sticker-place">
                  {t("message.0998")}
                  <select
                    value={stickerSlot}
                    onChange={(event) =>
                      setStickerSlot(Number(event.target.value))
                    }
                  >
                    {[1, 2, 3]
                      .filter((slot) => draft[`sticker_${slot}`] !== "none")
                      .map((slot) => (
                        <option key={slot} value={slot}>
                          {t("message.1037", { value0: slot })}
                        </option>
                      ))}
                  </select>
                </label>
              )}
              <div className="bubble-scene">
                {preview ? (
                  <img
                    className="bubble-preview-image"
                    src={preview}
                    alt={t("message.1000")}
                    onClick={(event) => {
                      // Clicking the preview places the chosen sticker. The
                      // renderer draws the body inside fixed margins.
                      const key = `sticker_${stickerSlot}`;
                      if (draft[key] === "none") return;
                      const box = event.currentTarget.getBoundingClientRect();
                      const percent = (
                        value: number,
                        start: number,
                        end: number,
                      ) =>
                        Math.round(
                          Math.max(
                            0,
                            Math.min(
                              100,
                              ((value - start) / (end - start)) * 100,
                            ),
                          ),
                        );
                      const x = ((event.clientX - box.left) / box.width) * 600;
                      const y = ((event.clientY - box.top) / box.height) * 260;
                      setResetDraft(false);
                      setDraft({
                        ...draft,
                        [`${key}_x`]: percent(x, 18, 582),
                        [`${key}_y`]: percent(y, 16, 224),
                      });
                    }}
                  />
                ) : (
                  <p>{t("message.1001")}</p>
                )}
              </div>
              <p className="footnote">{t("message.1002")}</p>
              {editorNotice && (
                <p className="editor-notice" role="status">
                  {editorNotice}
                </p>
              )}
              {renderError && (
                <div className="error-banner" role="alert">
                  <span>{renderError}</span>
                </div>
              )}
              {editorError && (
                <div className="error-banner" role="alert">
                  <span>{editorError}</span>
                  {editorStale && (
                    <button className="button compact" onClick={rebaseEditor}>
                      <RotateCcw size={13} />
                      {t("message.1003")}
                    </button>
                  )}
                </div>
              )}
              <div className="button-row">
                <button
                  className="button compact"
                  onClick={() => {
                    setResetDraft(true);
                    setDraft({ ...editor.packageTheme });
                  }}
                >
                  <RotateCcw size={13} />
                  {t("message.0558")}
                </button>
                <button className="button compact" onClick={reloadSavedTheme}>
                  {t("message.1004")}
                </button>
              </div>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
