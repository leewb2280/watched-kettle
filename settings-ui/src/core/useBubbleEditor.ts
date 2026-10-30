import { t } from "../../localization.cjs";
import { useEffect, useRef, useState } from "react";
import { errorText, isStaleError } from "../errors";
import type {
  BubbleEditor as Editor,
  BubbleGeometry,
  Cancelled,
  Element,
  ElementImported,
  ElementKind,
  ImportOptions,
  Shell,
} from "../types";
import { dropMissingElements, sameTheme, ThemeValues } from "./bubbleTheme";

export type PreviewSample = "notice" | "long" | "project";
export type EditorTab =
  | "background"
  | "border"
  | "decor"
  | "layout"
  | "themes";
// Enough to back out of a dragging session without keeping every keystroke.
const HISTORY_LIMIT = 50;

/** Owns editor draft and preview generation for the mounted settings shell. */
export function useBubbleEditor(
  shell: Pick<
    Shell,
    "snapshot" | "command" | "refresh" | "visible" | "reportError"
  >,
) {
  const { command } = shell;
  const fail = shell.reportError;

  const [editor, setEditor] = useState<Editor | null>(null);

  const [draft, setDraft] = useState<ThemeValues>({} as ThemeValues);

  const [resetDraft, setResetDraft] = useState(false);

  const [preview, setPreview] = useState("");

  const [geometry, setGeometry] = useState<BubbleGeometry | null>(null);

  const [previewSample, setPreviewSample] = useState<PreviewSample>("notice");

  const [zoom, setZoom] = useState(1);

  // The tab survives navigation and hiding, like the draft; opening starts over.
  const [editorTab, setEditorTab] = useState<EditorTab>("background");

  const [selectedLayer, setSelectedLayer] = useState<string | null>(null);
  // The background photo picked on the preview to move or resize.
  const [backgroundSelected, setBackgroundSelected] = useState(false);

  // Locks only protect layers from accidental drags in this editing session.
  const [lockedLayers, setLockedLayers] = useState<Set<string>>(new Set());

  // While a layer is dragged, the preview draws it transparent: hiding it
  // would change the canvas margins it reserves and move the bubble.
  const [draggedLayer, setDraggedLayer] = useState<string | null>(null);
  // Values a preview gesture is changing; drawn at once, saved on release.
  const [previewOverride, setOverrideState] =
    useState<Partial<ThemeValues> | null>(null);
  const overrideRef = useRef<Partial<ThemeValues> | null>(null);
  const setPreviewOverride = (value: Partial<ThemeValues> | null) => {
    overrideRef.current = value;
    setOverrideState(value);
  };

  const past = useRef<ThemeValues[]>([]);
  const future = useRef<ThemeValues[]>([]);
  const [historyVersion, setHistoryVersion] = useState(0);

  // How new images are cleaned up on import; kept for the whole session.
  const [importOptions, setImportOptions] = useState<ImportOptions>({
    trim: true,
    clearWhite: false,
  });

  const [editorBusy, setEditorBusy] = useState(false);

  const [editorError, setEditorError] = useState("");

  const [editorStale, setEditorStale] = useState(false);

  // Preview failures are separate so a late preview cannot clear a save error.
  const [renderError, setRenderError] = useState("");

  const [editorNotice, setEditorNotice] = useState("");

  const previewSequence = useRef(0);

  /** A user edit: remembered for undo, and it is no longer a reset. */
  const changeDraft = (next: ThemeValues) => {
    if (sameTheme(next, draft)) return;
    past.current = [...past.current, draft].slice(-HISTORY_LIMIT);
    future.current = [];
    setHistoryVersion((value) => value + 1);
    setResetDraft(false);
    setEditorNotice("");
    setDraft(next);
  };
  const clearHistory = () => {
    past.current = [];
    future.current = [];
    setHistoryVersion((value) => value + 1);
  };
  /** End a preview gesture as one undo step, with its last values if given. */
  const commitPreviewOverride = (last?: Partial<ThemeValues>) => {
    const value = last ?? overrideRef.current;
    setPreviewOverride(null);
    if (value) changeDraft({ ...draft, ...value } as ThemeValues);
  };
  const undo = () => {
    const previous = past.current.at(-1);
    if (!previous) return;
    past.current = past.current.slice(0, -1);
    future.current = [draft, ...future.current];
    setHistoryVersion((value) => value + 1);
    setDraft(previous);
  };
  const redo = () => {
    const next = future.current[0];
    if (!next) return;
    future.current = future.current.slice(1);
    past.current = [...past.current, draft];
    setHistoryVersion((value) => value + 1);
    setDraft(next);
  };

  useEffect(() => {
    if (!editor || !shell.visible) return;
    const sequence = ++previewSequence.current;
    const shown = { ...draft, ...previewOverride } as ThemeValues;
    const theme =
      draggedLayer === null
        ? shown
        : {
            ...shown,
            decor: shown.decor.map((layer) =>
              layer.id === draggedLayer ? { ...layer, alpha: 0 } : layer,
            ),
          };
    const live = draggedLayer !== null || previewOverride !== null;
    const timer = setTimeout(
      () =>
        window
          .settings!.request("bubble.render", {
            theme,
            sample: previewSample,
          })
          .then((value) => {
            if (sequence === previewSequence.current) {
              setPreview(value.image);
              setGeometry(value.geometry);
              setRenderError("");
              if (live) return;
              // Python clamps cross-field values (e.g. max width below min
              // width); mirror the normalized theme so fields match the preview.
              const normalized: ThemeValues = value.theme;
              if (!sameTheme(draft, normalized)) {
                setDraft(normalized);
                setEditorNotice(t("message.1146"));
              }
            }
          })
          .catch((error) => {
            if (sequence === previewSequence.current)
              setRenderError(errorText(error));
          }),
      live ? 0 : 160,
    );
    return () => {
      clearTimeout(timer);
      ++previewSequence.current;
    };
  }, [
    draft,
    !!editor,
    shell.visible,
    previewSample,
    draggedLayer,
    previewOverride,
  ]);
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
      setGeometry(null);
      setSelectedLayer(null);
      setBackgroundSelected(false);
      setLockedLayers(new Set());
      setEditorTab("background");
      clearHistory();
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
        setSelectedLayer(null);
        clearHistory();
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
    !!editor && (resetDraft || !sameTheme(editor.theme as ThemeValues, draft));

  const closeEditor = () => {
    if (!dirty || confirm(t("message.1149"))) {
      setEditor(null);
      setPreview("");
      setGeometry(null);
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

  /** Import one image; returns its library entry, or null when cancelled. */
  /** Bring imported images into the editor; returns them in import order. */
  const imported = async (
    result: ElementImported | Cancelled,
  ): Promise<Element[]> => {
    if ("cancelled" in result) return [];
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
    return (result.ids ?? [result.id]).flatMap(
      (id) => updated.elements.find((element) => element.id === id) ?? [],
    );
  };
  const importing = async (
    action: () => Promise<ElementImported | Cancelled>,
  ) => {
    try {
      return await imported(await action());
    } catch (e) {
      setEditorError(errorText(e));
      return [];
    }
  };
  // Pick one or more files; each becomes a library image.
  const assetChange = (kind: ElementKind) =>
    importing(() => window.settings!.file("import", kind, importOptions));
  const dropImages = (
    files: FileList | File[],
    kind: ElementKind = "sticker",
  ) => importing(() => window.settings!.dropImages(files, kind, importOptions));
  const pasteImage = (file: File, kind: ElementKind = "sticker") =>
    importing(() => window.settings!.pasteImage(file, kind, importOptions));

  const toggleLock = (id: string) =>
    setLockedLayers((value) => {
      const next = new Set(value);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  return {
    editor,
    setEditor,
    draft,
    setDraft,
    changeDraft,
    undo,
    redo,
    // historyVersion re-renders when these refs change.
    canUndo: past.current.length > 0,
    canRedo: future.current.length > 0,
    historyVersion,
    resetDraft,
    setResetDraft,
    preview,
    setPreview,
    geometry,
    previewSample,
    setPreviewSample,
    zoom,
    setZoom,
    editorTab,
    setEditorTab,
    selectedLayer,
    setSelectedLayer,
    backgroundSelected,
    setBackgroundSelected,
    lockedLayers,
    toggleLock,
    setDraggedLayer,
    previewOverride,
    setPreviewOverride,
    commitPreviewOverride,
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
    dropImages,
    pasteImage,
    importOptions,
    setImportOptions,
  };
}
