import { t } from "../../localization.cjs";
import { useEffect, useRef, useState } from "react";
import type {
  Args,
  PetCatalog as Catalog,
  Page,
  PetPreview,
  RendererCommand,
  Scalar,
  SettingRequest,
  Shell,
} from "../types";
import { petTabs } from "./petCatalog";
import { useBubbleEditor } from "./useBubbleEditor";
/** Keeps state alive across page changes; the shell remains mounted. */
export function useCoreSettings(shell: Shell, page: Page) {
  const { snapshot, command, notify } = shell;

  const [catalog, setCatalog] = useState<Catalog | null>(null);

  const [manager, setManager] = useState(false);

  const [petPreview, setPetPreview] = useState<PetPreview | null>(null);

  const [picker, setPicker] = useState(false);

  const [importPet, setImportPet] = useState(false);

  useEffect(() => {
    if (!shell.visible || page !== "pet") {
      setImportPet(false);
      setManager(false);
    }
  }, [shell.visible, page]);

  const [pickerError, setPickerError] = useState("");

  const [petTab, setPetTab] = useState(petTabs[0]);

  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const {
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
  } = useBubbleEditor(shell);

  const petPreviewSequence = useRef(0);

  const current = catalog?.entries.find(
    (entry) => entry.id === snapshot.pet.pet_id,
  );

  const widthControl = snapshot.controls.find(
    (control) => control.key === "width",
  );

  const selectedWidth = snapshot.pet.pet_width;

  const selectedHeight = Math.round((selectedWidth * 208) / 192);

  const selectedWidthLabel =
    widthControl?.options?.find((option) => option.value === selectedWidth)
      ?.label ?? `${selectedWidth}px`;

  const selectedWidthMeaning = selectedWidthLabel.split(" · ")[1];

  const displaySizeLabel = t("message.1150", {
    value0: selectedWidth,
    value1: selectedHeight,
    value2: selectedWidthMeaning ? ` · ${selectedWidthMeaning}` : "",
  });

  const currentAnimationLabel =
    snapshot.animations.find(
      (animation) => animation.value === snapshot.pet.visual_state,
    )?.label ?? t("message.0279");

  const durationOverrides = snapshot.bubbleControls.filter((control) =>
    control.key.startsWith("duration:"),
  );

  const hasDurationOverrides = durationOverrides.some(
    (control) => control.value !== null,
  );

  const movementScreen = snapshot.controls.find(
    (control) => control.key === "screen",
  )?.value;

  const themeControl = snapshot.bubbleControls.find(
    (control) => control.key === "bubble_theme",
  );

  const currentPreview =
    petPreview?.petId === snapshot.pet.pet_id ? petPreview : null;

  const previewImage = currentPreview?.image || current?.thumbnail;

  // Errors go to the page banner once; toasts are reserved for success.
  const fail = shell.reportError;

  const call = <M extends RendererCommand>(
    method: M,
    ...params: {} extends Args<M> ? [args?: Args<M>] : [args: Args<M>]
  ) => command(method, (params[0] ?? {}) as Args<M>).catch(fail);

  const loadCatalog = async () => {
    const next = await window.settings!.request("pet.catalog");
    setCatalog(next);
    return next;
  };

  const openCatalogManager = () => setManager(true);

  const selectTab = (index: number) => {
    const next = (index + petTabs.length) % petTabs.length;
    setPetTab(petTabs[next]);
    tabRefs.current[next]?.focus();
  };

  const loadPetPreview = async (petId: string) => {
    const sequence = ++petPreviewSequence.current;
    setPetPreview(null);
    try {
      const next = await window.settings!.request("pet.preview", {
        petId,
      });
      if (sequence === petPreviewSequence.current && next.petId === petId) {
        setPetPreview(next);
      }
      return next;
    } catch (error) {
      if (sequence === petPreviewSequence.current) setPetPreview(null);
      throw error;
    }
  };

  useEffect(() => {
    if (shell.visible && page === "pet") {
      let cancelled = false;
      const petId = snapshot.pet.pet_id;
      const sequence = ++petPreviewSequence.current;
      setPetPreview(null);
      window
        .settings!.request("pet.catalog")
        .then((value) => {
          if (!cancelled) setCatalog(value);
        })
        .catch(fail);
      window
        .settings!.request("pet.preview", { petId })
        .then((value) => {
          const next = value;
          if (
            !cancelled &&
            sequence === petPreviewSequence.current &&
            next.petId === petId
          ) {
            setPetPreview(next);
          }
        })
        .catch((error) => {
          if (!cancelled && sequence === petPreviewSequence.current) {
            setPetPreview(null);
            fail(error);
          }
        });
      return () => {
        cancelled = true;
        ++petPreviewSequence.current;
      };
    }
  }, [snapshot.pet.pet_id, shell.visible, page]);

  // Dynamic controls come from the validated Python snapshot.
  const change = (key: string, value: Scalar | undefined) =>
    call("settings.set", { key, value } as SettingRequest);

  const appearanceChange = (key: string, value: Scalar | undefined) =>
    change("appearance:" + key, value);
  return {
    snapshot,
    currentAnimationLabel,
    loadCatalog,
    loadPetPreview,
    notify,
    fail,
    previewImage,
    currentPreview,
    current,
    setPickerError,
    setPicker,
    call,
    displaySizeLabel,
    petTab,
    selectTab,
    tabRefs,
    setPetTab,
    change,
    movementScreen,
    setImportPet,
    openCatalogManager,
    shell,
    openEditor,
    themeControl,
    hasDurationOverrides,
    appearanceChange,
    importPet,
    picker,
    catalog,
    pickerError,
    command,
    manager,
    setManager,
    editor,
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
  };
}
export type CoreSettingsState = ReturnType<typeof useCoreSettings>;
