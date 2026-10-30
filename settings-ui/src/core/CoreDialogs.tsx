import { t } from "../../localization.cjs";
import { Modal } from "../components";
import { errorText } from "../errors";
import { PetImportDialog } from "../PetImportDialog";
import { PetLinkDialog } from "../PetLinkDialog";
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
    | "linkPet"
    | "setLinkPet"
    | "shell"
    | "importPet"
    | "picker"
    | "catalog"
    | "pickerError"
    | "command"
    | "manager"
    | "setManager"
    | "bubbleEditor"
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
    linkPet,
    setLinkPet,
    shell,
    importPet,
    picker,
    catalog,
    pickerError,
    command,
    manager,
    setManager,
    bubbleEditor,
  } = props;
  return (
    <>
      {importPet && (
        <PetImportDialog shell={shell} close={() => setImportPet(false)} />
      )}
      {linkPet && (
        <PetLinkDialog
          shell={shell}
          close={() => {
            setLinkPet(false);
            loadCatalog().catch(fail);
          }}
        />
      )}
      {picker && catalog && (
        <Modal
          title={t("message.1111")}
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
      <BubbleEditorDialog
        bubble={bubbleEditor}
        snapshot={snapshot}
        command={command}
      />
    </>
  );
}
