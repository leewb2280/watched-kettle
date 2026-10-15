import { useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowDownToLine,
  ArrowUp,
  ArrowUpToLine,
  Check,
  ChevronRight,
  Download,
  Eye,
  Folder,
  GripVertical,
  LayoutGrid,
  Monitor,
  Palette,
  Play,
  Plus,
  RotateCcw,
  Sparkles,
  Trash2,
} from "lucide-react";
import type { Control, Page, Shell, UpdateState, Values } from "./types";
import { Field, Fields, Heading, Modal, Section, Switch } from "./components";
import { errorText, isStaleError } from "./errors";
import { PetImportDialog } from "./PetImportDialog";

const petTabs = ["외형·표시", "동작·화면"];

function megabytes(bytes: number) {
  return (bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0);
}

// One row whose text and button follow UpdateService's state. Python owns the
// messages; this picks the action for each state.
function UpdateRow({
  version,
  update,
  call,
}: {
  version: string;
  update: UpdateState;
  call: (method: string) => unknown;
}) {
  const { state } = update;
  const percent =
    update.total > 0
      ? Math.min(100, Math.floor((update.received / update.total) * 100))
      : 0;
  const showPage =
    update.page_url !== "" &&
    (state === "available" || state === "downloading" || state === "error");
  let action = null;
  if (state === "available" && update.can_install) {
    action = (
      <button
        className="button primary"
        onClick={() => call("update.download")}
      >
        <Download size={14} />
        업데이트
      </button>
    );
  } else if (state === "downloading") {
    action = (
      <button className="button" onClick={() => call("update.cancel")}>
        취소
      </button>
    );
  } else if (state === "error") {
    action = (
      <button
        className="button"
        onClick={() =>
          call(update.retry === "download" ? "update.download" : "update.check")
        }
      >
        <RotateCcw size={14} />
        다시 시도
      </button>
    );
  } else if (state !== "installing") {
    action = (
      <button
        className="button"
        disabled={state === "checking"}
        onClick={() => call("update.check")}
      >
        <RotateCcw size={14} />
        업데이트 확인
      </button>
    );
  }
  return (
    <div className="setting-row update-row">
      <div className="update-summary">
        <h3>Watched Kettle {version}</h3>
        <p aria-live="polite">
          {state === "current" && <Check size={12} className="update-ok" />}
          {update.message}
          {showPage && (
            <>
              {" · "}
              <button
                className="text-button inline"
                onClick={() => call("update.open")}
              >
                변경 사항 보기
              </button>
            </>
          )}
        </p>
        {(state === "downloading" || state === "installing") && (
          <div className="update-progress">
            <div
              className="progress-track"
              role="progressbar"
              aria-label="업데이트 내려받기"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={percent}
            >
              <span style={{ width: `${percent}%` }} />
            </div>
            <output>
              {megabytes(update.received)} / {megabytes(update.total)}MB
            </output>
          </div>
        )}
      </div>
      {action}
    </div>
  );
}

// Mirrors watched_kettle.pet.catalog.order_pet_entries: entries arrive in name
// order, ranked IDs come first in custom mode and the rest keep name order.
function orderedCatalog(entries: Values[], sort: string, order: string[]) {
  if (sort !== "custom") return entries;
  const rank = new Map(order.map((id, index) => [id, index]));
  return [
    ...entries
      .filter((entry) => rank.has(entry.id))
      .sort((a, b) => rank.get(a.id)! - rank.get(b.id)!),
    ...entries.filter((entry) => !rank.has(entry.id)),
  ];
}

const themeLabels: Record<string, string> = {
  background: "배경색",
  border: "테두리 색",
  text: "글자색",
  shadow: "그림자 색",
  shadow_alpha: "그림자 농도",
  radius: "모서리 곡률",
  border_width: "테두리 두께",
  shape: "모양",
  tail: "꼬리",
  gradient: "그라데이션",
  fill_end: "끝 색상",
  border_style: "테두리 스타일",
  header_style: "출처 이름 모양",
  pattern: "배경 무늬",
  ornament_left: "왼쪽 장식",
  ornament_right: "오른쪽 장식",
  ornament_scale: "장식 크기",
  glow: "은은한 빛",
  frame_style: "프레임",
  fill_opacity: "채우기 농도",
  minimum_width: "최소 너비",
  maximum_width: "최대 너비",
  horizontal_padding: "좌우 여백",
  stack_alignment: "카드 정렬",
  text_alignment: "글자 정렬",
  text_bold: "굵은 글씨",
  background_image: "배경 사진",
  background_opacity: "사진 진하기",
  background_focus_x: "사진 가로 위치",
  background_focus_y: "사진 세로 위치",
  background_zoom: "사진 확대",
  frame_image: "테두리 이미지",
  frame_slice: "테두리 모서리 크기",
  ...Object.fromEntries(
    [1, 2, 3].flatMap((slot) => [
      [`sticker_${slot}`, `스티커 ${slot}`],
      [`sticker_${slot}_x`, `스티커 ${slot} 가로 위치`],
      [`sticker_${slot}_y`, `스티커 ${slot} 세로 위치`],
      [`sticker_${slot}_size`, `스티커 ${slot} 크기`],
    ]),
  ),
};
const optionLabels: Record<string, string> = {
  rounded: "둥근형",
  cloud: "구름형",
  jelly: "젤리형",
  comic: "만화형",
  tech: "기계형",
  none: "없음",
  triangle: "삼각형",
  curved: "곡선형",
  stub: "통통한 형",
  angular: "각진 형",
  droplet: "물방울형",
  solid: "단색",
  vertical: "세로",
  horizontal: "가로",
  single: "기본선",
  double: "이중선",
  accent: "포인트선",
  capsule: "캡슐",
  tab: "상단 탭",
  ribbon: "리본",
  panel: "기계 패널",
  standard: "기본",
  dots: "점",
  stars: "별",
  grid: "격자",
  center: "가운데",
  left: "왼쪽",
  // Built-in ornaments, matching the Qt customizer's ORNAMENT_OPTIONS.
  "cat-ear": "고양이 귀",
  "small-wing": "작은 날개",
  horn: "뿔",
  "bat-wing": "박쥐 날개",
  star: "별",
  sparkle: "반짝임",
  goggles: "고글",
  magnet: "자석",
};
const elementKeys = [
  "pattern",
  "ornament_left",
  "ornament_right",
  "background_image",
  "frame_image",
  "sticker_1",
  "sticker_2",
  "sticker_3",
];
// Which kind of user image each element field lists.
const elementKind = (key: string) =>
  key === "pattern"
    ? "pattern"
    : key === "background_image"
      ? "photo"
      : key === "frame_image"
        ? "frame"
        : key.startsWith("sticker_")
          ? "sticker"
          : "ornament";
const stickerFields = [1, 2, 3].flatMap((slot) =>
  ["", "_x", "_y", "_size"].map((suffix) => `sticker_${slot}${suffix}`),
);
const themeGroups: [string, string[]][] = [
  [
    "색",
    ["background", "gradient", "fill_end", "fill_opacity", "text", "text_bold"],
  ],
  [
    "모양·테두리",
    [
      "shape",
      "tail",
      "radius",
      "border",
      "border_width",
      "border_style",
      "frame_style",
      "header_style",
      "shadow",
      "shadow_alpha",
      "glow",
    ],
  ],
  ["장식", ["pattern", "ornament_left", "ornament_right", "ornament_scale"]],
  [
    "사진·이미지",
    [
      "background_image",
      "background_opacity",
      "background_focus_x",
      "background_focus_y",
      "background_zoom",
      "frame_image",
      "frame_slice",
      ...stickerFields,
    ],
  ],
  [
    "글자·여백",
    [
      "minimum_width",
      "maximum_width",
      "horizontal_padding",
      "stack_alignment",
      "text_alignment",
    ],
  ],
];
// Settings of an image stay hidden until that image is chosen.
function hiddenThemeField(key: string, theme: Values) {
  if (key.startsWith("background_") && key !== "background_image")
    return theme.background_image === "none";
  if (key === "frame_slice") return theme.frame_image === "none";
  const sticker = key.match(/^(sticker_[123])_/);
  return !!sticker && theme[sticker[1]] === "none";
}
// A draft may still point at a user image deleted meanwhile; fall back to none.
function dropMissingElements(theme: Values, known: Set<string>) {
  const next = { ...theme };
  for (const key of elementKeys)
    if (String(next[key]).startsWith("user:") && !known.has(next[key]))
      next[key] = "none";
  return next;
}
type Catalog = {
  entries: Values[];
  order: string[];
  hidden: string[];
  sort: string;
  revision: number;
  petId: string;
};
type PetPreview = {
  petId: string;
  revision: number;
  image: string;
  sourceSize: { width: number; height: number };
  contentBounds: { x: number; y: number; width: number; height: number };
  cropBounds: { x: number; y: number; width: number; height: number };
};
type Editor = {
  theme: Values;
  packageTheme: Values;
  revision: number;
  petId: string;
  elements: Values[];
  choices: Record<string, string[]>;
  limits: Record<
    string,
    { min: number; max: number; step: number; unit: string }
  >;
  labels: Record<string, Record<string, string>>;
  presets?: { id: string; label: string; values: Values }[];
};

export function CorePages({ shell, page }: { shell: Shell; page: Page }) {
  const { snapshot, command, notify } = shell;
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogDraft, setCatalogDraft] = useState<Catalog | null>(null);
  const [petPreview, setPetPreview] = useState<PetPreview | null>(null);
  const [picker, setPicker] = useState(false);
  const [importPet, setImportPet] = useState(false);
  useEffect(() => {
    if (!shell.visible || page !== "pet") setImportPet(false);
  }, [shell.visible, page]);
  const [pickerError, setPickerError] = useState("");
  const [catalogError, setCatalogError] = useState<unknown>(null);
  // The pet being dragged in the catalog manager and the gap it would drop
  // into (0 is above the first row, rows.length below the last).
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropAt, setDropAt] = useState<number | null>(null);
  const [petTab, setPetTab] = useState(petTabs[0]);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [draft, setDraft] = useState<Values>({});
  const [resetDraft, setResetDraft] = useState(false);
  const [preview, setPreview] = useState("");
  const [previewSample, setPreviewSample] = useState("notice");
  const [stickerSlot, setStickerSlot] = useState(1);
  const [editorBusy, setEditorBusy] = useState(false);
  const [editorError, setEditorError] = useState("");
  const [editorStale, setEditorStale] = useState(false);
  // Preview failures are separate so a late preview cannot clear a save error.
  const [renderError, setRenderError] = useState("");
  const [editorNotice, setEditorNotice] = useState("");
  const previewSequence = useRef(0);
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
  const displaySizeLabel = `실제 표시: ${selectedWidth}×${selectedHeight}px${
    selectedWidthMeaning ? ` · ${selectedWidthMeaning}` : ""
  }`;
  const currentAnimationLabel =
    snapshot.animations.find(
      (animation) => animation.value === snapshot.pet.visual_state,
    )?.label ?? "기본";
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
  const call = (method: string, args: Values = {}) =>
    command(method, args).catch(fail);
  const loadCatalog = async () => {
    const next = await window.settings!.request("pet.catalog");
    setCatalog(next);
    return next as Catalog;
  };
  const openCatalogManager = async () => {
    try {
      const value = await loadCatalog();
      setCatalogError(null);
      setCatalogDraft({
        ...value,
        order: [...value.order],
        hidden: [...value.hidden],
      });
    } catch (error) {
      fail(error);
    }
  };
  // A user-requested refresh after a conflict: take the latest revision and
  // entries but keep the user's choices. Nothing is sent until 적용 again.
  const rebaseCatalogDraft = async () => {
    if (!catalogDraft) return;
    try {
      const latest = await loadCatalog();
      const known = new Set(latest.entries.map((entry) => entry.id));
      setCatalogDraft({
        ...latest,
        sort: catalogDraft.sort,
        order: catalogDraft.order.filter((id) => known.has(id)),
        hidden: catalogDraft.hidden.filter(
          (id) => known.has(id) && id !== latest.petId,
        ),
      });
      setCatalogError(null);
    } catch (error) {
      setCatalogError(error);
    }
  };
  const saveCatalogDraft = async () => {
    if (!catalogDraft) return;
    const known = new Set(catalogDraft.entries.map((entry) => entry.id));
    const displayed = orderedCatalog(
      catalogDraft.entries,
      catalogDraft.sort,
      catalogDraft.order,
    ).map((entry) => entry.id);
    try {
      await command(
        "pet.catalog.save",
        {
          petId: catalogDraft.petId,
          revision: catalogDraft.revision,
          sort: catalogDraft.sort,
          order:
            catalogDraft.sort === "custom"
              ? displayed
              : catalogDraft.order.filter((id) => known.has(id)),
          hidden: catalogDraft.hidden.filter(
            (id) => known.has(id) && id !== catalogDraft.petId,
          ),
        },
        { inline: true },
      );
      setCatalogDraft(null);
      await loadCatalog();
    } catch (error) {
      setCatalogError(error);
    }
  };
  const selectTab = (index: number) => {
    const next = (index + petTabs.length) % petTabs.length;
    setPetTab(petTabs[next]);
    tabRefs.current[next]?.focus();
  };
  const loadPetPreview = async (petId: string) => {
    const sequence = ++petPreviewSequence.current;
    setPetPreview(null);
    try {
      const next = (await window.settings!.request("pet.preview", {
        petId,
      })) as PetPreview;
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
          const next = value as PetPreview;
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
              const normalized = value.theme as Values;
              if (
                Object.keys(draft).some((key) => draft[key] !== normalized[key])
              ) {
                setDraft(normalized);
                setEditorNotice("허용 범위에 맞게 일부 값을 조정했어요.");
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
    if (!dirty || confirm("편집 중인 값을 버리고 저장된 값을 불러올까요?"))
      openEditor();
  };
  // After a conflict: adopt the latest revision but keep the user's draft.
  // Nothing is sent until 적용 again. A different pet means a different theme,
  // so that case loads the new pet's design instead.
  const rebaseEditor = async () => {
    if (!editor) return;
    try {
      const latest = (await window.settings!.request(
        "bubble.editor",
      )) as Editor;
      if (latest.petId !== editor.petId) {
        setDraft(latest.theme);
        setResetDraft(false);
        setEditorNotice("펫이 바뀌어 새 펫의 디자인을 불러왔어요.");
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
    if (!dirty || confirm("적용하지 않은 디자인 변경을 버릴까요?")) {
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
  const assetChange = async (kind: string) => {
    try {
      const result = await window.settings!.file("import", kind);
      if (!result.cancelled) {
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
  const change = (key: string, value: any) =>
    call("settings.set", { key, value });
  const appearanceChange = (key: string, value: any) =>
    change("appearance:" + key, value);
  return (
    <>
      {page === "pet" && (
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
                          onClick={() =>
                            call("pet.action", { action: "recenter" })
                          }
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
                  <button
                    className="link-card"
                    onClick={() => setImportPet(true)}
                  >
                    <Plus size={19} />
                    <span>
                      <strong>펫 가져오기</strong>
                      <small>다운로드한 펫 스프라이트를 추가합니다.</small>
                    </span>
                    <ChevronRight size={16} />
                  </button>
                  <button className="link-card" onClick={openCatalogManager}>
                    <LayoutGrid size={19} />
                    <span>
                      <strong>펫 목록 관리</strong>
                      <small>목록 순서와 표시할 펫을 정합니다.</small>
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
                  <div
                    className="pet-utility-actions"
                    aria-label="펫 보조 기능"
                  >
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
                            선택한 이동 디스플레이에서 잠깐 실제로 걸어요.
                            걷기를 꺼 두어도 한 번 실행돼요.
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
                          펫이 숨겨져 있어 제자리 동작은 보이지 않아요. 펫을
                          다시 표시하면 확인할 수 있어요.
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
                            aria-pressed={
                              snapshot.pet.visual_state === item.value
                            }
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
                          onClick={() =>
                            call("pet.action", { action: "restore" })
                          }
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
      )}
      {page === "bubble" && (
        <div className="page">
          <Heading
            title="말풍선"
            subtitle="말풍선 디자인과 표시 방식, 표시 시간을 설정합니다."
          />
          <div className="bubble-intro-card card">
            <div className="bubble-intro">
              <span className="large-icon">
                <Palette size={30} />
              </span>
              <div className="bubble-intro-copy">
                <h2>말풍선 디자인</h2>
                <p>
                  색, 모양, 장식부터 글자와 여백까지.
                  <br />
                  미리보기로 확인하고 마음에 들 때 적용하세요.
                </p>
              </div>
              <div className="bubble-intro-actions">
                <button
                  className="button"
                  onClick={() => call("pet.action", { action: "preview" })}
                >
                  <Eye size={15} />
                  펫에서 미리보기
                </button>
                <button className="button primary" onClick={openEditor}>
                  <Sparkles size={15} />
                  말풍선 꾸미기
                </button>
              </div>
            </div>
            {themeControl && (
              <Field
                key={snapshot.pet.pet_id}
                field={themeControl}
                change={(value) => change(themeControl.key, value)}
              />
            )}
          </div>
          <Fields
            key={snapshot.pet.pet_id}
            controls={snapshot.bubbleControls.filter(
              (control) => control !== themeControl,
            )}
            change={change}
            groupFooters={
              snapshot.edition === "pet-assistant"
                ? {
                    "표시 시간": (
                      <button
                        className="text-button"
                        disabled={!hasDurationOverrides}
                        onClick={() =>
                          call("pet.action", {
                            action: "duration_overrides_reset",
                          })
                        }
                      >
                        종류별 시간을 기본값으로
                      </button>
                    ),
                  }
                : undefined
            }
          />
          {snapshot.edition === "pet-assistant" && (
            <Section title="알림 잠시 쉬기">
              <div className="snooze-card">
                <div className="snooze-copy">
                  {!snapshot.pet.bubbles_enabled ? (
                    <>
                      <strong>말풍선 알림이 꺼져 있습니다</strong>
                      <p>알림을 켜면 잠시 쉬는 시간을 선택할 수 있어요.</p>
                    </>
                  ) : snapshot.pet.bubbles_snoozed ? (
                    <>
                      <strong>알림 쉬는 중</strong>
                      <p>
                        약 {snapshot.pet.bubble_snooze_remaining_minutes}분 남음
                      </p>
                    </>
                  ) : (
                    <>
                      <strong>필요할 때 잠시 조용하게</strong>
                      <p>
                        선택한 시간 동안 말풍선을 모두 숨깁니다. 그동안 온
                        일반·일정 알림은 나중에 다시 띄우지 않고, 아직 진행 중인
                        작업은 다시 나타나요.
                      </p>
                    </>
                  )}
                </div>
                <div className="snooze-actions">
                  {snapshot.pet.bubbles_snoozed &&
                  snapshot.pet.bubbles_enabled ? (
                    <button
                      className="button"
                      onClick={() => call("pet.action", { action: "resume" })}
                    >
                      지금 다시 표시
                    </button>
                  ) : (
                    [15, 30, 60].map((minutes) => (
                      <button
                        className="button"
                        key={minutes}
                        disabled={!snapshot.pet.bubbles_enabled}
                        onClick={() =>
                          call("pet.action", { action: "snooze", minutes })
                        }
                      >
                        {minutes}분
                      </button>
                    ))
                  )}
                </div>
              </div>
            </Section>
          )}
          {snapshot.edition === "pet-only" && (
            <p className="footnote">
              펫만 구성에서는 디자인과 미리보기를 제공합니다. 비서 알림은
              생성하지 않습니다.
            </p>
          )}
        </div>
      )}
      {page === "app" && (
        <div className="page">
          <Heading
            title="앱 설정"
            subtitle="시작, 화면 테마와 업데이트를 설정합니다."
          />
          <Section title="앱 시작">
            <div className="setting-row">
              <div>
                <h3>Windows와 함께 시작</h3>
                <p>
                  {snapshot.startup.matches_current_app
                    ? "현재 실행 파일과 연결되어 있어요."
                    : "설정 변경 시 현재 실행 경로로 등록합니다."}
                </p>
              </div>
              <Switch
                label="Windows와 함께 시작"
                value={snapshot.startup.enabled}
                disabled={!snapshot.startup.supported}
                change={(value) => change("startup", value)}
              />
            </div>
          </Section>
          <Fields
            controls={[
              {
                key: "theme",
                label: "테마",
                kind: "select",
                value: snapshot.appearance.theme,
                options: [
                  { value: "system", label: "시스템 설정에 맞춤" },
                  { value: "light", label: "포슬린 · 라이트" },
                  { value: "dark", label: "그라파이트 · 다크" },
                ],
                group: "화면과 색상",
              },
              {
                key: "material",
                label: "창 배경 재질",
                kind: "select",
                value: snapshot.appearance.material,
                options: [
                  { value: "acrylic", label: "아크릴" },
                  { value: "mica", label: "미카" },
                  { value: "none", label: "단색" },
                ],
                group: "화면과 색상",
              },
              {
                key: "lightOpacity",
                label: "라이트 배경 농도",
                kind: "range",
                value: snapshot.appearance.lightOpacity,
                min: 0,
                max: 100,
                group: "화면과 색상",
              },
              {
                key: "darkOpacity",
                label: "다크 배경 농도",
                kind: "range",
                value: snapshot.appearance.darkOpacity,
                min: 0,
                max: 100,
                group: "화면과 색상",
              },
              {
                key: "reduceMotion",
                label: "움직임 줄이기",
                kind: "bool",
                value: snapshot.appearance.reduceMotion,
                group: "화면과 색상",
              },
            ]}
            change={appearanceChange}
          />
          <p className="footnote">
            배경 재질과 농도는 상단·사이드바에 적용되며 본문은 불투명하게
            유지됩니다. 고대비·투명 효과 끄기에서는 단색을 사용합니다. OS의
            움직임 줄이기도 반영됩니다.
          </p>
          <Section title="버전과 업데이트">
            <UpdateRow
              version={snapshot.version}
              update={snapshot.update}
              call={call}
            />
          </Section>
        </div>
      )}
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
      {catalogDraft &&
        (() => {
          const custom = catalogDraft.sort === "custom";
          const rows = orderedCatalog(
            catalogDraft.entries,
            catalogDraft.sort,
            catalogDraft.order,
          );
          const hiddenCount = rows.filter((entry) =>
            catalogDraft.hidden.includes(entry.id),
          ).length;
          const move = (from: number, to: number) => {
            const order = rows.map((entry) => entry.id);
            const [id] = order.splice(from, 1);
            order.splice(Math.max(0, Math.min(to, order.length)), 0, id);
            setCatalogDraft({ ...catalogDraft, order });
          };
          const endDrag = () => {
            setDragId(null);
            setDropAt(null);
          };
          return (
            <Modal
              title="펫 목록 관리"
              close={() => setCatalogDraft(null)}
              error={
                catalogError ? (
                  <>
                    <span>{errorText(catalogError)}</span>
                    {isStaleError(catalogError) && (
                      <button
                        className="button compact"
                        onClick={rebaseCatalogDraft}
                      >
                        <RotateCcw size={13} />
                        최신 상태 다시 불러오기
                      </button>
                    )}
                  </>
                ) : undefined
              }
              footer={
                <>
                  <button
                    className="button"
                    onClick={() => setCatalogDraft(null)}
                  >
                    취소
                  </button>
                  <button
                    className="button primary"
                    disabled={!!catalogError && isStaleError(catalogError)}
                    onClick={saveCatalogDraft}
                  >
                    적용
                  </button>
                </>
              }
            >
              <Field
                field={{
                  key: "sort",
                  label: "정렬 방식",
                  kind: "select",
                  group: "",
                  value: catalogDraft.sort,
                  options: [
                    { value: "name", label: "이름순" },
                    { value: "custom", label: "직접 정렬" },
                  ],
                }}
                change={(sort) => setCatalogDraft({ ...catalogDraft, sort })}
              />
              <p className="catalog-status" aria-live="polite">
                표시 {rows.length - hiddenCount}개 · 숨김 {hiddenCount}개 ·{" "}
                {custom
                  ? "끌어서 옮기거나 화살표로 순서를 바꿀 수 있습니다."
                  : "이름이 바뀌거나 펫이 추가되면 자동으로 다시 정렬됩니다."}
              </p>
              <p className="catalog-hint">
                체크한 펫만 선택 창과 트레이 메뉴에 표시됩니다.
              </p>
              {rows.map((entry, index) => {
                const isCurrent = entry.id === snapshot.pet.pet_id;
                const dropClass =
                  dragId === null
                    ? ""
                    : dropAt === index
                      ? " drop-before"
                      : dropAt === index + 1 && index === rows.length - 1
                        ? " drop-after"
                        : "";
                return (
                  <div
                    className={`catalog-row${dragId === entry.id ? " dragging" : ""}${dropClass}`}
                    key={entry.id}
                    onDragOver={
                      custom && dragId !== null
                        ? (event) => {
                            event.preventDefault();
                            event.dataTransfer.dropEffect = "move";
                            const box =
                              event.currentTarget.getBoundingClientRect();
                            setDropAt(
                              event.clientY < box.top + box.height / 2
                                ? index
                                : index + 1,
                            );
                          }
                        : undefined
                    }
                    onDrop={
                      custom && dragId !== null
                        ? (event) => {
                            event.preventDefault();
                            const from = rows.findIndex(
                              (row) => row.id === dragId,
                            );
                            if (from >= 0 && dropAt !== null)
                              move(from, dropAt > from ? dropAt - 1 : dropAt);
                            endDrag();
                          }
                        : undefined
                    }
                  >
                    {custom && (
                      // Dragging starts only from the handle so the checkbox
                      // and label keep their clicks; the buttons cover the
                      // keyboard.
                      <span
                        className="drag-handle"
                        draggable
                        aria-hidden="true"
                        title="끌어서 순서 바꾸기"
                        onDragStart={(event) => {
                          event.dataTransfer.effectAllowed = "move";
                          event.dataTransfer.setData("text/plain", entry.id);
                          const row = event.currentTarget.parentElement;
                          if (row) event.dataTransfer.setDragImage(row, 20, 20);
                          setDragId(entry.id);
                        }}
                        onDragEnd={endDrag}
                      >
                        <GripVertical size={15} />
                      </span>
                    )}
                    <img src={entry.thumbnail} alt="" />
                    <label
                      title={
                        isCurrent
                          ? "현재 사용 중인 펫은 숨길 수 없습니다."
                          : undefined
                      }
                    >
                      <input
                        type="checkbox"
                        aria-label={`${entry.name} 표시`}
                        checked={!catalogDraft.hidden.includes(entry.id)}
                        disabled={isCurrent}
                        onChange={(event) =>
                          setCatalogDraft({
                            ...catalogDraft,
                            hidden: event.target.checked
                              ? catalogDraft.hidden.filter(
                                  (item) => item !== entry.id,
                                )
                              : [...catalogDraft.hidden, entry.id],
                          })
                        }
                      />
                      {entry.name}
                      {isCurrent && (
                        <span className="current-badge">현재 사용 중</span>
                      )}
                    </label>
                    {custom && (
                      <>
                        <button
                          className="icon-button"
                          aria-label={`${entry.name} 맨 위로`}
                          title="맨 위로"
                          disabled={index === 0}
                          onClick={() => move(index, 0)}
                        >
                          <ArrowUpToLine size={15} />
                        </button>
                        <button
                          className="icon-button"
                          aria-label={`${entry.name} 위로`}
                          title="위로"
                          disabled={index === 0}
                          onClick={() => move(index, index - 1)}
                        >
                          <ArrowUp size={15} />
                        </button>
                        <button
                          className="icon-button"
                          aria-label={`${entry.name} 아래로`}
                          title="아래로"
                          disabled={index === rows.length - 1}
                          onClick={() => move(index, index + 1)}
                        >
                          <ArrowDown size={15} />
                        </button>
                        <button
                          className="icon-button"
                          aria-label={`${entry.name} 맨 아래로`}
                          title="맨 아래로"
                          disabled={index === rows.length - 1}
                          onClick={() => move(index, rows.length - 1)}
                        >
                          <ArrowDownToLine size={15} />
                        </button>
                      </>
                    )}
                  </div>
                );
              })}
            </Modal>
          );
        })()}
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
                {(editor.presets || []).map((preset: Values) => (
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
                          field={{
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
                          }}
                          change={(next) => {
                            setResetDraft(false);
                            setEditorNotice("");
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
                                  updated.elements.map(
                                    (item: Values) => item.id,
                                  ),
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
