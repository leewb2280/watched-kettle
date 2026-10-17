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
          title={`${snapshot.pet.display_name} · 말풍선 꾸미기`}
          close={closeEditor}
          footer={
            <>
              <span className="draft-status" aria-live="polite">
                {resetDraft
                  ? "적용하면 펫 기본 디자인으로 돌아갑니다."
                  : !dirty
                    ? "변경 사항 없음"
                    : snapshot.pet.bubble_theme_mode !== "custom"
                      ? "적용하면 테마가 '내가 꾸민 디자인'으로 바뀝니다."
                      : "적용하지 않은 변경이 있어요."}
              </span>
              <button
                className="button"
                disabled={editorBusy}
                onClick={closeEditor}
              >
                취소
              </button>
              <button
                className="button primary"
                disabled={editorBusy || !dirty || editorStale}
                onClick={saveEditor}
              >
                <Check size={14} />
                적용
              </button>
            </>
          }
        >
          <div className="editor-grid">
            <div className="editor-controls">
              <div className="preset-gallery" aria-label="디자인 프리셋">
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
                          ...(options || [{ value: "none", label: "없음" }]),
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
              <Section title="사용자 장식 이미지">
                <div className="card-body">
                  <p className="footnote">
                    이미지 추가·삭제는 즉시 반영되며 디자인 취소로 되돌아가지
                    않습니다.
                  </p>
                  <div className="button-row">
                    <button
                      className="button compact"
                      onClick={() => assetChange("pattern")}
                    >
                      <Plus size={13} />
                      무늬 추가
                    </button>
                    <button
                      className="button compact"
                      onClick={() => assetChange("ornament")}
                    >
                      <Plus size={13} />
                      장식 추가
                    </button>
                    {(
                      [
                        ["photo", "사진 추가"],
                        ["frame", "테두리 이미지 추가"],
                        ["sticker", "스티커 추가"],
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
                        aria-label={`${element.name} 삭제`}
                        onClick={() => {
                          if (
                            confirm(
                              "다른 펫에서 사용 중인 장식도 사라질 수 있습니다. 삭제할까요?",
                            )
                          )
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
                실제 그리기로 미리보기
                <span
                  className="segmented preview-samples"
                  role="group"
                  aria-label="미리보기 종류"
                >
                  {(
                    [
                      ["notice", "짧은 알림"],
                      ["project", "프로젝트 카드"],
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
                  미리보기를 눌러 놓을 스티커
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
                          스티커 {slot}
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
                    alt="현재 말풍선 디자인 미리보기"
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
                  <p>미리보기를 만드는 중…</p>
                )}
              </div>
              <p className="footnote">
                실사용 알림과 상태를 바꾸지 않는 독립 미리보기입니다.
              </p>
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
                      최신 상태 다시 불러오기
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
                  <RotateCcw size={13} />펫 기본 디자인
                </button>
                <button className="button compact" onClick={reloadSavedTheme}>
                  저장된 값 다시 불러오기
                </button>
              </div>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
