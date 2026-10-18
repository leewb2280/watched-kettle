import { t } from "../../localization.cjs";
import {
  ChevronRight,
  Folder,
  LayoutGrid,
  Monitor,
  Palette,
  Play,
  Plus,
  RotateCcw,
} from "lucide-react";
import { Fields, Heading } from "../components";
import { petTabs, petTabLabels } from "./petCatalog";
import type { CoreSettingsState } from "./useCoreSettings";
export function CorePetPage({
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
}: Pick<
  CoreSettingsState,
  | "snapshot"
  | "currentAnimationLabel"
  | "loadCatalog"
  | "loadPetPreview"
  | "notify"
  | "fail"
  | "previewImage"
  | "currentPreview"
  | "current"
  | "setPickerError"
  | "setPicker"
  | "call"
  | "displaySizeLabel"
  | "petTab"
  | "selectTab"
  | "tabRefs"
  | "setPetTab"
  | "change"
  | "movementScreen"
  | "setImportPet"
  | "openCatalogManager"
  | "shell"
>) {
  return (
    <div className="page">
      <Heading title={t("message.0591")} subtitle={t("message.1112")} />
      <div className="pet-grid">
        <section className="pet-stage card">
          <div className="stage-top">
            <span className="pill">
              <span className="small-dot" />
              {snapshot.pet.visible
                ? t("message.1113", { value0: currentAnimationLabel })
                : t("message.1114")}
            </span>
            <button
              className="icon-button"
              aria-label={t("message.1115")}
              title={t("message.1115")}
              onClick={() =>
                Promise.all([
                  loadCatalog(),
                  loadPetPreview(snapshot.pet.pet_id),
                ])
                  .then(() => notify(t("message.1116")))
                  .catch(fail)
              }
            >
              <RotateCcw size={14} />
            </button>
          </div>
          <div className="pet-scene">
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <span className="scene-spark spark-one">✧</span>
            <span className="scene-spark spark-two">+</span>
            <div className="sprite-floor" />
            {previewImage && (
              <img
                className="pet-image"
                src={previewImage}
                alt={snapshot.pet.display_name}
                data-preview-source={
                  currentPreview ? "original-cell" : "catalog-thumbnail"
                }
              />
            )}
          </div>
          <div className="pet-caption">
            <h2>{snapshot.pet.display_name}</h2>
            <p>{current?.description}</p>
          </div>
          <button
            className="button stage-picker"
            onClick={() => {
              loadCatalog()
                .then(() => {
                  setPickerError("");
                  setPicker(true);
                })
                .catch(fail);
            }}
          >
            <LayoutGrid size={15} />
            {t("message.1117")}
            <ChevronRight size={14} />
          </button>
          <div className="stage-footer">
            <span className="stage-visibility">
              <span>
                {snapshot.pet.visible ? t("message.1118") : t("message.1119")}
              </span>
              <button
                className="text-button"
                onClick={() => call("pet.action", { action: "visibility" })}
              >
                {snapshot.pet.visible ? t("message.0224") : t("message.1120")}
              </button>
            </span>
            <span>{displaySizeLabel}</span>
          </div>
        </section>
        <div className="pet-controls">
          <div
            className="tabs"
            role="tablist"
            aria-label={t("message.1121")}
            onKeyDown={(event) => {
              const index = petTabs.indexOf(petTab);
              const target = {
                ArrowRight: index + 1,
                ArrowLeft: index - 1,
                Home: 0,
                End: petTabs.length - 1,
              }[event.key];
              if (target === undefined) return;
              event.preventDefault();
              selectTab(target);
            }}
          >
            {petTabs.map((label, index) => (
              <button
                key={label}
                ref={(element) => {
                  tabRefs.current[index] = element;
                }}
                id={`pet-tab-${index}`}
                role="tab"
                aria-selected={petTab === label}
                aria-controls="pet-tabpanel"
                tabIndex={petTab === label ? 0 : -1}
                onClick={() => setPetTab(label)}
              >
                {petTabLabels[label]}
              </button>
            ))}
          </div>
          <div
            role="tabpanel"
            id="pet-tabpanel"
            aria-labelledby={`pet-tab-${petTabs.indexOf(petTab)}`}
          >
            <Fields
              key={snapshot.pet.pet_id}
              controls={snapshot.controls.filter((c) => c.groupId === petTab)}
              change={change}
              hideTitles
              fieldExtras={
                movementScreen && movementScreen !== "current"
                  ? {
                      screen: (
                        <button
                          className="text-button field-extra"
                          onClick={() =>
                            call("pet.action", { action: "recall" })
                          }
                        >
                          {t("message.1122")}
                          <ChevronRight size={13} />
                        </button>
                      ),
                    }
                  : undefined
              }
              groupRows={{
                pet_behavior: (
                  <div className="setting-row recover-row">
                    <div>
                      <h3>{t("message.1123")}</h3>
                      <p>{t("message.1124")}</p>
                    </div>
                    <button
                      className="button"
                      onClick={() => call("pet.action", { action: "recenter" })}
                    >
                      <Monitor size={14} />
                      {t("message.1125")}
                    </button>
                  </div>
                ),
              }}
            />
          </div>
          {petTab === petTabs[0] ? (
            <>
              <button className="link-card" onClick={() => setImportPet(true)}>
                <Plus size={19} />
                <span>
                  <strong>{t("message.1126")}</strong>
                  <small>{t("message.1127")}</small>
                </span>
                <ChevronRight size={16} />
              </button>
              <button
                className="link-card"
                aria-label={t("message.1128")}
                onClick={openCatalogManager}
              >
                <LayoutGrid size={19} />
                <span>
                  <strong>{t("message.1128")}</strong>
                  <small>{t("message.1129")}</small>
                </span>
                <ChevronRight size={16} />
              </button>
              <button
                className="link-card"
                onClick={() => shell.navigate("bubble")}
              >
                <Palette size={19} />
                <span>
                  <strong>{t("message.1100")}</strong>
                  <small>{t("message.1130")}</small>
                </span>
                <ChevronRight size={16} />
              </button>
              <div
                className="pet-utility-actions"
                aria-label={t("message.1131")}
              >
                <button
                  className="text-button"
                  onClick={() => call("pet.action", { action: "folder" })}
                >
                  <Folder size={14} />
                  {t("message.1132")}
                </button>
              </div>
            </>
          ) : (
            <>
              <details className="animation-panel card">
                <summary>
                  <span className="animation-summary-copy">
                    <span className="animation-summary-icon">
                      <Play size={18} />
                    </span>
                    <span>
                      <strong>{t("message.1133")}</strong>
                      <small>{t("message.1134")}</small>
                    </span>
                  </span>
                  <span className="animation-current" aria-live="polite">
                    {t("message.1135")}
                    {currentAnimationLabel}
                  </span>
                  <ChevronRight
                    className="animation-disclosure-chevron"
                    size={16}
                  />
                </summary>
                <div className="animation-panel-body">
                  <div className="walk-test">
                    <span>
                      <strong>{t("message.1136")}</strong>
                      <small>{t("message.1137")}</small>
                    </span>
                    <button
                      className="button compact"
                      onClick={() =>
                        call("pet.action", { action: "movement_test" })
                      }
                    >
                      {t("message.1138")}
                    </button>
                  </div>
                  <h3 className="animation-group-title">{t("message.1139")}</h3>
                  {!snapshot.pet.visible && (
                    <p className="animation-hidden-note" role="status">
                      {t("message.1140")}
                    </p>
                  )}
                  <div
                    className="animation-actions"
                    role="group"
                    aria-label={t("message.1141")}
                  >
                    {snapshot.animations.map((item) => (
                      <button
                        className="button compact"
                        key={item.value}
                        aria-pressed={snapshot.pet.visual_state === item.value}
                        onClick={() =>
                          call("pet.action", {
                            action: "animation",
                            state: item.value,
                          })
                        }
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                  <div className="animation-panel-footer">
                    <button
                      className="text-button"
                      onClick={() => call("pet.action", { action: "restore" })}
                    >
                      {t("message.1142")}
                    </button>
                  </div>
                </div>
              </details>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
