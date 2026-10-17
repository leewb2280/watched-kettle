import { Modal } from "../components";
import { errorText } from "../errors";
import { PetImportDialog } from "../PetImportDialog";
import { PetManagerDialog } from "../PetManagerDialog";
import { BubbleEditorDialog } from "./BubbleEditorDialog";
import { orderedCatalog } from "./petCatalog";
import type { CoreSettingsState } from "./useCoreSettings";
export function CoreDialogs(
  props: Pick<
    CoreSettingsState,
    | "snapshot"
    | "loadCatalog"
    | "fail"
    | "setPickerError"
    | "setPicker"
    | "change"
    | "setImportPet"
    | "shell"
    | "importPet"
    | "picker"
    | "catalog"
    | "pickerError"
    | "command"
    | "manager"
    | "setManager"
    | "editor"
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
  >,
) {
  const {
    snapshot,
    loadCatalog,
    fail,
    setPickerError,
    setPicker,
    change,
    setImportPet,
    shell,
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
  } = props;
  return (
    <>
      {importPet && (
        <PetImportDialog shell={shell} close={() => setImportPet(false)} />
      )}
      {picker && catalog && (
        <Modal
          title="펫 선택"
          close={() => setPicker(false)}
          error={pickerError || undefined}
        >
          <div className="pet-picker">
            {orderedCatalog(catalog.entries, catalog.sort, catalog.order)
              .filter((entry) => !catalog.hidden.includes(entry.id))
              .map((entry) => (
                <button
                  className={`pet-choice ${entry.id === snapshot.pet.pet_id ? "selected" : ""}`}
                  key={entry.id}
                  onClick={() => {
                    setPickerError("");
                    command("pet.select", { id: entry.id }, { inline: true })
                      .then(() => setPicker(false))
                      .catch((error) => setPickerError(errorText(error)));
                  }}
                >
                  <img src={entry.thumbnail} alt="" />
                  <strong>{entry.name}</strong>
                  <span>{entry.description}</span>
                </button>
              ))}
          </div>
        </Modal>
      )}
      {manager && (
        <PetManagerDialog
          shell={shell}
          close={() => {
            setManager(false);
            loadCatalog().catch(fail);
          }}
        />
      )}
      <BubbleEditorDialog {...props} />
    </>
  );
}
