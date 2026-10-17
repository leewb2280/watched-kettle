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
import { petTabs } from "./petCatalog";
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
      <Heading
        title="펫"
        subtitle="표시할 펫을 고르고 크기와 동작을 설정합니다."
      />
      <div className="pet-grid">
        <section className="pet-stage card">
          <div className="stage-top">
            <span className="pill">
              <span className="small-dot" />
              {snapshot.pet.visible
                ? `화면 속 펫 · ${currentAnimationLabel}`
                : "화면에서 숨김"}
            </span>
            <button
              className="icon-button"
              aria-label="펫 폴더 다시 읽기"
              title="펫 폴더 다시 읽기"
              onClick={() =>
                Promise.all([
                  loadCatalog(),
                  loadPetPreview(snapshot.pet.pet_id),
                ])
                  .then(() => notify("펫 목록을 다시 읽었어요."))
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
            다른 펫 선택
            <ChevronRight size={14} />
          </button>
          <div className="stage-footer">
            <span className="stage-visibility">
              <span>
                {snapshot.pet.visible ? "화면에 표시 중" : "숨김 상태"}
              </span>
              <button
                className="text-button"
                onClick={() => call("pet.action", { action: "visibility" })}
              >
                {snapshot.pet.visible ? "펫 숨기기" : "펫 다시 표시"}
              </button>
            </span>
            <span>{displaySizeLabel}</span>
          </div>
        </section>
        <div className="pet-controls">
          <div
            className="tabs"
            role="tablist"
            aria-label="펫 설정 영역"
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
                {label}
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
              controls={snapshot.controls.filter((c) => c.group === petTab)}
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
                          지금 이 화면으로 옮기기
                          <ChevronRight size={13} />
                        </button>
                      ),
                    }
                  : undefined
              }
              groupRows={{
                "동작·화면": (
                  <div className="setting-row recover-row">
                    <div>
                      <h3>펫이 안 보이나요?</h3>
                      <p>화면 밖으로 나갔거나 찾기 어려울 때 데려와요.</p>
                    </div>
                    <button
                      className="button"
                      onClick={() => call("pet.action", { action: "recenter" })}
                    >
                      <Monitor size={14} />
                      화면 가운데로 불러오기
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
                  <strong>펫 가져오기</strong>
                  <small>다운로드한 펫 스프라이트를 추가합니다.</small>
                </span>
                <ChevronRight size={16} />
              </button>
              <button
                className="link-card"
                aria-label="펫 관리"
                onClick={openCatalogManager}
              >
                <LayoutGrid size={19} />
                <span>
                  <strong>펫 관리</strong>
                  <small>펫을 추가하고 표시·순서·휴지통을 관리합니다.</small>
                </span>
                <ChevronRight size={16} />
              </button>
              <button
                className="link-card"
                onClick={() => shell.navigate("bubble")}
              >
                <Palette size={19} />
                <span>
                  <strong>말풍선 꾸미기</strong>
                  <small>색과 모양, 장식을 바꿉니다.</small>
                </span>
                <ChevronRight size={16} />
              </button>
              <div className="pet-utility-actions" aria-label="펫 보조 기능">
                <button
                  className="text-button"
                  onClick={() => call("pet.action", { action: "folder" })}
                >
                  <Folder size={14} />펫 폴더 열기
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
                      <strong>동작 미리보기</strong>
                      <small>화면 위의 펫에서 바로 확인합니다.</small>
                    </span>
                  </span>
                  <span className="animation-current" aria-live="polite">
                    현재 동작: {currentAnimationLabel}
                  </span>
                  <ChevronRight
                    className="animation-disclosure-chevron"
                    size={16}
                  />
                </summary>
                <div className="animation-panel-body">
                  <div className="walk-test">
                    <span>
                      <strong>걷기 테스트</strong>
                      <small>
                        선택한 이동 디스플레이에서 잠깐 실제로 걸어요. 걷기를 꺼
                        두어도 한 번 실행돼요.
                      </small>
                    </span>
                    <button
                      className="button compact"
                      onClick={() =>
                        call("pet.action", { action: "movement_test" })
                      }
                    >
                      실제로 걸어보기
                    </button>
                  </div>
                  <h3 className="animation-group-title">제자리 동작</h3>
                  {!snapshot.pet.visible && (
                    <p className="animation-hidden-note" role="status">
                      펫이 숨겨져 있어 제자리 동작은 보이지 않아요. 펫을 다시
                      표시하면 확인할 수 있어요.
                    </p>
                  )}
                  <div
                    className="animation-actions"
                    role="group"
                    aria-label="펫 동작 선택"
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
                      실제 상태로 돌아가기
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
