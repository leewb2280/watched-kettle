import { t } from "../../localization.cjs";
import { useEffect, useRef, useState } from "react";
import { errorText, isStaleError } from "../errors";
import type { BubbleEditor as Editor, ElementKind, Shell } from "../types";
import { dropMissingElements, ThemeValues } from "./bubbleTheme";
/** Owns editor draft and preview generation for the mounted settings shell. */
export function useBubbleEditor(
  shell: Pick<
    Shell,
    "snapshot" | "command" | "refresh" | "visible" | "reportError"
  >,
) {
  const { snapshot, command } = shell;
  const fail = shell.reportError;

  const [editor, setEditor] = useState<Editor | null>(null);

  const [draft, setDraft] = useState<ThemeValues>({} as ThemeValues);

  const [resetDraft, setResetDraft] = useState(false);

  const [preview, setPreview] = useState("");

  const [previewSample, setPreviewSample] = useState<"notice" | "project">(
    "notice",
  );

  const [stickerSlot, setStickerSlot] = useState(1);

  const [editorBusy, setEditorBusy] = useState(false);

  const [editorError, setEditorError] = useState("");

  const [editorStale, setEditorStale] = useState(false);

  // Preview failures are separate so a late preview cannot clear a save error.
  const [renderError, setRenderError] = useState("");

  const [editorNotice, setEditorNotice] = useState("");

  const previewSequence = useRef(0);

  useEffect(() => {
    if (!editor || !shell.visible) return;
    const sequence = ++previewSequence.current;
    const timer = setTimeout(
      () =>
        window
          .settings!.request("bubble.render", {
            theme: draft,
            sample: previewSample,
          })
          .then((value) => {
            if (sequence === previewSequence.current) {
              setPreview(value.image);
              setRenderError("");
              // Python clamps cross-field values (e.g. max width below min
              // width); mirror the normalized theme so fields match the preview.
              const normalized: ThemeValues = value.theme;
              if (
                Object.keys(draft).some((key) => draft[key] !== normalized[key])
              ) {
                setDraft(normalized);
                setEditorNotice(t("message.1146"));
              }
            }
          })
          .catch((error) => {
            if (sequence === previewSequence.current)
              setRenderError(errorText(error));
          }),
      160,
    );
    return () => {
      clearTimeout(timer);
      ++previewSequence.current;
    };
  }, [draft, !!editor, shell.visible, previewSample]);
  const openEditor = async () => {
    try {
      const value = await window.settings!.request("bubble.editor");
      setEditor(value);
      setDraft(value.theme);
      setResetDraft(false);
      setEditorError("");
      setEditorStale(false);
      setEditorNotice("");
      setRenderError("");
      setPreview("");
    } catch (e) {
      fail(e);
    }
  };

  const reloadSavedTheme = () => {
    if (!dirty || confirm(t("message.1147"))) openEditor();
  };

  // After a conflict: adopt the latest revision but keep the user's draft.
  // Nothing is sent until 적용 again. A different pet means a different theme,
  // so that case loads the new pet's design instead.
  const rebaseEditor = async () => {
    if (!editor) return;
    try {
      const latest = await window.settings!.request("bubble.editor");
      if (latest.petId !== editor.petId) {
        setDraft(latest.theme);
        setResetDraft(false);
        setEditorNotice(t("message.1148"));
      } else {
        const known = new Set(latest.elements.map((element) => element.id));
        setDraft((value) => dropMissingElements(value, known));
      }
      setEditor(latest);
      setEditorStale(false);
      setEditorError("");
    } catch (e) {
      setEditorError(errorText(e));
    }
  };

  const dirty =
    !!editor &&
    (resetDraft || JSON.stringify(editor.theme) !== JSON.stringify(draft));

  const closeEditor = () => {
    if (!dirty || confirm(t("message.1149"))) {
      setEditor(null);
      setPreview("");
    }
  };

  const saveEditor = async () => {
    if (!editor) return;
    setEditorBusy(true);
    try {
      await command(
        resetDraft ? "bubble.reset" : "bubble.save",
        {
          theme: draft,
          revision: editor.revision,
          petId: editor.petId,
        },
        { inline: true },
      );
      setEditor(null);
    } catch (e) {
      setEditorStale(isStaleError(e));
      setEditorError(errorText(e));
    } finally {
      setEditorBusy(false);
    }
  };

  const assetChange = async (kind: ElementKind) => {
    try {
      const result = await window.settings!.file("import", kind);
      if (!("cancelled" in result)) {
        const updated = await window.settings!.request("bubble.editor");
        setEditor((value) =>
          value
            ? {
                ...value,
                elements: updated.elements,
                revision: updated.revision,
              }
            : null,
        );
        await shell.refresh();
      }
    } catch (e) {
      setEditorError(errorText(e));
    }
  };
  return {
    editor,
    setEditor,
    draft,
    setDraft,
    resetDraft,
    setResetDraft,
    preview,
    setPreview,
    previewSample,
    setPreviewSample,
    stickerSlot,
    setStickerSlot,
    editorBusy,
    setEditorBusy,
    editorError,
    setEditorError,
    editorStale,
    setEditorStale,
    renderError,
    setRenderError,
    editorNotice,
    setEditorNotice,
    openEditor,
    reloadSavedTheme,
    rebaseEditor,
    dirty,
    closeEditor,
    saveEditor,
    assetChange,
  };
}
