import { useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  GripVertical,
  MoreHorizontal,
  Plus,
  RotateCcw,
  Search,
  Trash2,
} from "lucide-react";
import { Modal, Switch } from "./components";
import { errorText } from "./errors";
import { PetImportDialog } from "./PetImportDialog";
import { usePetBatch } from "./usePetBatch";
import type {
  PetBatchAction,
  PetCatalog,
  PetCatalogEntry,
  PetTrashCatalog,
  PetTrashEntry,
  Shell,
  Values,
} from "./types";

function ordered(catalog: PetCatalog) {
  if (catalog.sort === "name") return catalog.entries;
  const ranks = new Map(catalog.order.map((id, index) => [id, index]));
  return [...catalog.entries].sort(
    (a, b) => (ranks.get(a.id) ?? Infinity) - (ranks.get(b.id) ?? Infinity),
  );
}
function size(bytes: number) {
  return bytes < 1024 * 1024
    ? `${Math.ceil(bytes / 1024)} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
type Confirmation =
  | { kind: "move"; entry: PetCatalogEntry }
  | { kind: "delete"; entry: PetTrashEntry }
  | { kind: "empty" }
  | {
      kind: "batch";
      action: "move" | "delete";
      ids: string[];
      names: string[];
      bytes: number;
    };

export function PetManagerDialog({
  shell,
  close,
}: {
  shell: Shell;
  close: () => void;
}) {
  const batch = usePetBatch(shell);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [batchUndo, setBatchUndo] = useState<string[]>([]);
  const handledJob = useRef("");
  const selectAll = useRef<HTMLInputElement>(null);
  const epochRef = useRef(shell.snapshot.epoch);
  epochRef.current = shell.snapshot.epoch;
  const [catalog, setCatalog] = useState<PetCatalog | null>(null);
  const [trash, setTrash] = useState<PetTrashCatalog | null>(null);
  const [view, setView] = useState<"owned" | "trash">("owned");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [editing, setEditing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [saving, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [undo, setUndo] = useState<{ trashId: string; name: string } | null>(
    null,
  );
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [replacement, setReplacement] = useState("");
  const [offset, setOffset] = useState(0);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropAt, setDropAt] = useState<number | null>(null);
  const lock = useRef(false);
  const sequence = useRef(0);
  const feedback = useRef<HTMLDivElement>(null);
  const contextChanged =
    !!catalog &&
    (catalog.petId !== shell.snapshot.pet.pet_id ||
      catalog.revision !== shell.snapshot.revision);
  const busy = saving || loading || contextChanged || batch.busy;
  // Switching views is local. A late invalidate after a change reloads the
  // lists again; disabling here on that reload swallowed an immediate click.
  const navigationBusy = saving || batch.busy;

  const load = async () => {
    const seq = ++sequence.current;
    setLoading(true);
    try {
      // Recovery can finish an interrupted move/restore, so read it first.
      const nextTrash = await window.settings!.request("pet.trash.list", {
        offset,
      });
      const nextCatalog = await window.settings!.request("pet.catalog");
      if (seq === sequence.current) {
        setCatalog(nextCatalog);
        setTrash(nextTrash);
        if (offset && offset >= nextTrash.total)
          setOffset(Math.max(0, offset - 50));
      }
      return {
        catalog: nextCatalog as PetCatalog,
        trash: nextTrash as PetTrashCatalog,
      };
    } finally {
      if (seq === sequence.current) setLoading(false);
    }
  };
  useEffect(() => {
    // A delayed settings notification must not disable a drag already underway.
    // Refresh against the latest revision as soon as the drag ends.
    if (dragId !== null || batch.job?.state === "running") return;
    load().catch((failure) => setError(errorText(failure)));
    return () => {
      ++sequence.current;
    };
  }, [
    dragId,
    batch.job?.state,
    shell.eventVersion,
    shell.snapshot.revision,
    shell.snapshot.pet.pet_id,
    offset,
    importing,
  ]);
  useEffect(() => {
    setConfirmation(null);
    setUndo(null);
    setSelecting(false);
    setSelected([]);
    setBatchUndo([]);
  }, [shell.snapshot.epoch]);

  const run = async (method: string, args: Values, message: string) => {
    if (lock.current || loading || contextChanged || !catalog) return null;
    lock.current = true;
    setBusy(true);
    setError("");
    batch.clearError();
    setBatchUndo([]);
    try {
      const result = await shell.command(
        method,
        { petId: catalog.petId, revision: catalog.revision, ...args },
        { inline: true },
      );
      setNotice(message);
      setConfirmation(null);
      setUndo(
        method === "pet.trash.move"
          ? { trashId: result.trashId, name: result.name }
          : null,
      );
      if (result.failed?.length)
        setError(
          `${result.deleted}개를 삭제했고 ${result.failed.length}개는 삭제하지 못했어요. 남은 항목을 다시 시도하세요.`,
        );
      await load();
      if (
        [
          "pet.trash.move",
          "pet.trash.restore",
          "pet.trash.delete",
          "pet.trash.empty",
        ].includes(method)
      )
        requestAnimationFrame(() => feedback.current?.focus());
      return result;
    } catch (failure) {
      setError(errorText(failure));
      // Includes a lost response: always show the server's actual final state.
      await load().catch(() => {});
      return null;
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  const save = (
    change: Partial<PetCatalog>,
    message = "변경 사항을 저장했어요.",
  ) => {
    if (!catalog) return;
    return run(
      "pet.catalog.save",
      {
        sort: catalog.sort,
        order: catalog.order,
        hidden: catalog.hidden,
        ...change,
      },
      message,
    );
  };
  const rows = catalog ? ordered(catalog) : [];
  const hidden = catalog?.hidden ?? [];
  const counts = {
    all: rows.length,
    shown: rows.filter((entry) => !hidden.includes(entry.id)).length,
    hidden: rows.filter((entry) => hidden.includes(entry.id)).length,
  };
  const shown = rows.filter(
    (entry) =>
      entry.name
        .toLocaleLowerCase()
        .includes(query.trim().toLocaleLowerCase()) &&
      (filter === "all" || (filter === "hidden") === hidden.includes(entry.id)),
  );
  const selectable =
    view === "owned"
      ? shown.filter((entry) => entry.canDelete).map((entry) => entry.id)
      : (trash?.entries ?? [])
          .filter((entry) => ["trashed", "deleting"].includes(entry.state))
          .map((entry) => entry.trashId);
  const selectedEntries =
    view === "owned"
      ? shown.filter((entry) => selected.includes(entry.id))
      : [];
  const selectedTrash = (trash?.entries ?? []).filter((entry) =>
    selected.includes(entry.trashId),
  );
  const canRestore =
    selectedTrash.length > 0 &&
    selectedTrash.every((entry) => entry.state === "trashed");
  useEffect(() => {
    if (selectAll.current)
      selectAll.current.indeterminate =
        selected.length > 0 && selected.length < selectable.length;
  }, [selected, selectable.length, selecting]);
  useEffect(() => {
    if (batch.busy || loading || !selecting) return;
    setSelected((previous) => {
      const next = previous.filter((id) => selectable.includes(id));
      return next.length === previous.length ? previous : next;
    });
  }, [catalog, trash, view, query, filter, batch.busy, loading, selecting]);
  const clearSelection = (announce = true) => {
    setSelected([]);
    if (announce && selecting)
      setNotice("화면 조건이 바뀌어 선택을 해제했어요.");
  };
  const toggleSelected = (id: string) =>
    setSelected((value) =>
      value.includes(id)
        ? value.filter((entry) => entry !== id)
        : [...value, id],
    );
  const startBatch = async (
    action: PetBatchAction,
    ids: string[],
    replacementId = "",
  ) => {
    if (!catalog) return;
    setError("");
    setUndo(null);
    setBatchUndo([]);
    setConfirmation(null);
    await batch.start(
      action,
      [...ids],
      { petId: catalog.petId, revision: catalog.revision },
      replacementId,
    );
  };
  const confirmBatch = (action: "move" | "delete") => {
    setReplacement("");
    setConfirmation({
      kind: "batch",
      action,
      ids: [...selected],
      names:
        action === "move"
          ? selectedEntries.map((entry) => entry.name)
          : selectedTrash.map((entry) => entry.name),
      bytes: selectedTrash.reduce((total, entry) => total + entry.bytes, 0),
    });
  };
  useEffect(() => {
    const job = batch.job;
    if (!job || job.state === "running" || handledJob.current === job.jobId)
      return;
    handledJob.current = job.jobId;
    const epoch = shell.snapshot.epoch;
    setConfirmation(null);
    setNotice(
      `${job.succeeded}개 완료 · ${job.failed}개 실패 · ${job.total - job.processed}개 미처리${job.message ? ` · ${job.message}` : ""}`,
    );
    setBatchUndo(job.action === "move" ? job.undoIds : []);
    load()
      .then((value) => {
        if (!value || epoch !== epochRef.current) return;
        const retry = job.results
          .filter((row) => ["failed", "notStarted"].includes(row.status))
          .map((row) => row.id);
        const owned = value.catalog.entries
          .filter(
            (entry) =>
              entry.canDelete &&
              entry.name
                .toLocaleLowerCase()
                .includes(query.trim().toLocaleLowerCase()) &&
              (filter === "all" ||
                (filter === "hidden") ===
                  value.catalog.hidden.includes(entry.id)),
          )
          .map((entry) => entry.id);
        const visible =
          view === "owned" && job.action === "move"
            ? owned
            : view === "trash" && job.action !== "move"
              ? value.trash.entries
                  .filter((entry) =>
                    ["trashed", "deleting"].includes(entry.state),
                  )
                  .map((entry) => entry.trashId)
              : [];
        const remaining = ["conflict", "stale_context"].includes(job.code)
          ? []
          : retry.filter((id) => visible.includes(id));
        setSelected(remaining);
        setSelecting(remaining.length > 0);
        requestAnimationFrame(() => feedback.current?.focus());
      })
      .catch((failure) => setError(errorText(failure)));
  }, [batch.job?.jobId, batch.job?.state]);
  const canEdit =
    view === "owned" && !query.trim() && filter === "all" && !selecting;
  const move = (from: number, to: number) => {
    const order = rows.map((entry) => entry.id);
    const [id] = order.splice(from, 1);
    order.splice(Math.max(0, Math.min(to, order.length)), 0, id);
    return save({ sort: "custom", order }, "펫 순서를 저장했어요.");
  };
  const trashPet = (entry: PetCatalogEntry) => {
    if (entry.id === catalog?.petId) {
      setReplacement("");
      setConfirmation({ kind: "move", entry });
    } else
      void run(
        "pet.trash.move",
        { id: entry.id },
        `${entry.name}을(를) 휴지통으로 옮겼어요.`,
      );
  };
  const closeMenu = (element: HTMLElement) => {
    const details = element.closest("details");
    if (details) {
      details.open = false;
      details.querySelector("summary")?.focus();
    }
  };
  const resetOrderEditing = () => {
    setEditing(false);
    setDragId(null);
    setDropAt(null);
  };
  return (
    <>
      <Modal
        title={view === "trash" ? "펫 휴지통" : "펫 관리"}
        close={() => {
          if (!lock.current) close();
        }}
        error={
          error || batch.error ? (
            <>
              <span>{error || batch.error}</span>
              <button
                className="button compact"
                disabled={saving || loading}
                onClick={() => {
                  setError("");
                  batch.clearError();
                  void batch.refresh();
                  load().catch((failure) => setError(errorText(failure)));
                }}
              >
                다시 불러오기
              </button>
            </>
          ) : undefined
        }
        footer={
          <>
            {batch.job?.state === "running" ? (
              <div className="batch-footer">
                <span role="status">
                  {batch.job.processed} / {batch.job.total}개 처리 · 성공{" "}
                  {batch.job.succeeded} · 실패 {batch.job.failed}
                </span>
                <button
                  className="button"
                  disabled={batch.cancelling}
                  onClick={() => void batch.cancel()}
                >
                  남은 작업 중단
                </button>
              </div>
            ) : selecting ? (
              <div className="batch-footer">
                <strong>{selected.length}개 선택</strong>
                <button
                  className="text-button"
                  disabled={busy || !selected.length}
                  onClick={() => setSelected([])}
                >
                  선택 해제
                </button>
                <div className="batch-actions">
                  {view === "owned" ? (
                    <button
                      className="button primary"
                      disabled={busy || !selected.length}
                      onClick={() => confirmBatch("move")}
                    >
                      선택한 펫 이동
                    </button>
                  ) : (
                    <>
                      <button
                        className="button"
                        disabled={busy || !canRestore}
                        title={
                          !canRestore && selected.length
                            ? "삭제 중이던 항목은 영구 삭제 재시도만 가능해요."
                            : undefined
                        }
                        onClick={() => void startBatch("restore", selected)}
                      >
                        선택한 펫 복원
                      </button>
                      <button
                        className="button danger"
                        disabled={busy || !selected.length}
                        onClick={() => confirmBatch("delete")}
                      >
                        선택한 펫 영구 삭제
                      </button>
                    </>
                  )}
                  <button
                    className="button"
                    disabled={busy}
                    onClick={() => {
                      setSelecting(false);
                      setSelected([]);
                    }}
                  >
                    선택 완료
                  </button>
                </div>
              </div>
            ) : (
              <span className="manager-save-hint">
                변경 사항은 바로 저장됩니다.
              </span>
            )}
            <button
              className="button"
              disabled={saving || batch.starting}
              onClick={close}
            >
              닫기
            </button>
          </>
        }
      >
        <div className="pet-manager" aria-busy={busy}>
          <div className="batch-select-tools">
            <button
              className="button compact"
              disabled={busy || !selectable.length}
              aria-pressed={selecting}
              onClick={() => {
                resetOrderEditing();
                setSelecting(!selecting);
                clearSelection(false);
              }}
            >
              {selecting ? "선택 취소" : "선택"}
            </button>
            {selecting && (
              <label>
                <input
                  ref={selectAll}
                  type="checkbox"
                  aria-label="현재 화면 전체 선택"
                  checked={
                    selectable.length > 0 &&
                    selected.length === selectable.length
                  }
                  disabled={busy || !selectable.length}
                  onChange={(event) =>
                    setSelected(event.target.checked ? [...selectable] : [])
                  }
                />
                현재 화면 전체 선택
              </label>
            )}
          </div>
          <div className="manager-toolbar">
            {view === "owned" ? (
              <>
                <button
                  className="button primary"
                  disabled={busy || !catalog || selecting}
                  onClick={() => setImporting(true)}
                >
                  <Plus size={16} />펫 추가
                </button>
                <button
                  className="button"
                  disabled={navigationBusy}
                  onClick={() => {
                    resetOrderEditing();
                    setSelecting(false);
                    clearSelection(false);
                    setView("trash");
                  }}
                >
                  <Trash2 size={16} />
                  휴지통 {trash ? `(${trash.total})` : ""}
                </button>
              </>
            ) : (
              <>
                <button
                  className="button"
                  disabled={navigationBusy}
                  onClick={() => {
                    setView("owned");
                    setSelecting(false);
                    clearSelection(false);
                  }}
                >
                  <ArrowLeft size={16} />펫 목록
                </button>
                <button
                  className="button manager-danger"
                  disabled={busy || !trash?.total || selecting}
                  onClick={() => setConfirmation({ kind: "empty" })}
                >
                  휴지통 비우기
                </button>
              </>
            )}
          </div>
          <div className="manager-feedback" ref={feedback} tabIndex={-1}>
            <span role="status">
              {loading ? "목록을 불러오는 중…" : saving ? "저장 중…" : notice}
            </span>
            {undo && (
              <button
                className="text-button"
                disabled={busy}
                onClick={() =>
                  void run(
                    "pet.trash.restore",
                    { trashId: undo.trashId },
                    `${undo.name}을(를) 복원했어요.`,
                  )
                }
              >
                <RotateCcw size={14} />
                실행 취소
              </button>
            )}
          </div>
          {batchUndo.length > 0 && (
            <button
              className="text-button batch-undo"
              disabled={busy}
              onClick={() => void startBatch("restore", batchUndo)}
            >
              실행 취소 ({batchUndo.length}개)
            </button>
          )}
          {batch.job &&
            batch.job.state !== "running" &&
            batch.job.results.some(
              (row) => row.status === "failed" || row.status === "notStarted",
            ) && (
              <details className="batch-results">
                <summary>실패·미처리 항목 확인</summary>
                <ul>
                  {batch.job.results
                    .filter(
                      (row) =>
                        row.status === "failed" || row.status === "notStarted",
                    )
                    .map((row) => (
                      <li key={row.id}>
                        <strong>{row.name}</strong> ·{" "}
                        {row.status === "failed" ? "실패" : "미처리"} ·{" "}
                        {row.message}
                      </li>
                    ))}
                </ul>
              </details>
            )}
          {trash?.issues.length ? (
            <p className="error-banner" role="alert">
              확인이 필요한 휴지통 항목이 있어 파일을 보존했어요.{" "}
              {trash.issues[0]}
            </p>
          ) : null}
          {!catalog || !trash ? (
            <p role="status">펫 목록을 불러오는 중…</p>
          ) : view === "owned" ? (
            <>
              <label className="manager-search">
                <Search size={16} />
                <input
                  aria-label="펫 이름 검색"
                  placeholder="펫 이름 검색"
                  value={query}
                  disabled={busy}
                  onChange={(event) => {
                    clearSelection();
                    setQuery(event.target.value);
                    resetOrderEditing();
                  }}
                />
              </label>
              <div
                className="manager-filters"
                role="group"
                aria-label="펫 표시 필터"
              >
                {(
                  [
                    ["all", "전체"],
                    ["shown", "표시 중"],
                    ["hidden", "숨김"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    className={`button compact${filter === value ? " selected" : ""}`}
                    aria-pressed={filter === value}
                    disabled={busy}
                    onClick={() => {
                      clearSelection();
                      setFilter(value);
                      resetOrderEditing();
                    }}
                  >
                    {label} {counts[value]}
                  </button>
                ))}
              </div>
              {!selecting && (
                <div className="manager-order-tools">
                  <label>
                    정렬 방식{" "}
                    <select
                      aria-label="정렬 방식"
                      value={catalog.sort}
                      disabled={busy || selecting}
                      onChange={(event) => {
                        resetOrderEditing();
                        void save({
                          sort: event.target.value as "name" | "custom",
                        });
                      }}
                    >
                      <option value="name">이름순</option>
                      <option value="custom">직접 정렬</option>
                    </select>
                  </label>
                  <button
                    className="button compact"
                    aria-pressed={editing}
                    disabled={busy || !canEdit || rows.length < 2}
                    onClick={() => setEditing(!editing)}
                  >
                    {editing ? "순서 편집 마치기" : "순서 편집"}
                  </button>
                </div>
              )}
              <p className="manager-help">
                {selecting
                  ? "현재 화면에서 선택한 펫만 처리합니다. 검색·필터를 바꾸면 선택이 해제돼요."
                  : editing
                    ? "손잡이를 끌거나 위·아래 버튼으로 순서를 바꾸세요. 이동하면 직접 정렬로 저장됩니다."
                    : canEdit
                      ? "표시한 펫은 선택 창과 트레이 메뉴에 나타납니다."
                      : "순서를 바꾸려면 검색을 지우고 전체 목록을 선택하세요."}
              </p>
              {!shown.length ? (
                <div className="manager-empty">
                  <strong>검색 조건에 맞는 펫이 없어요.</strong>
                  <button
                    className="button"
                    onClick={() => {
                      clearSelection();
                      setQuery("");
                      setFilter("all");
                    }}
                  >
                    검색·필터 초기화
                  </button>
                </div>
              ) : (
                shown.map((entry, index) => {
                  const current = entry.id === catalog.petId;
                  const endDrag = () => {
                    setDragId(null);
                    setDropAt(null);
                  };
                  return (
                    <div
                      key={entry.id}
                      className={`catalog-row manager-row${dragId === entry.id ? " dragging" : ""}${dragId && dropAt === index ? " drop-before" : dragId && dropAt === index + 1 && index === rows.length - 1 ? " drop-after" : ""}`}
                      data-pet-id={entry.id}
                      onDragOver={
                        editing && !busy
                          ? (event) => {
                              event.preventDefault();
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
                        editing && !busy
                          ? (event) => {
                              event.preventDefault();
                              const from = rows.findIndex(
                                (row) => row.id === dragId,
                              );
                              if (from >= 0 && dropAt !== null)
                                void move(
                                  from,
                                  dropAt > from ? dropAt - 1 : dropAt,
                                );
                              endDrag();
                            }
                          : undefined
                      }
                    >
                      {editing && (
                        <span
                          className="drag-handle"
                          draggable={!busy}
                          aria-hidden="true"
                          title="끌어서 순서 바꾸기"
                          onDragStart={(event) => {
                            event.dataTransfer.effectAllowed = "move";
                            event.dataTransfer.setData("text/plain", entry.id);
                            setDragId(entry.id);
                          }}
                          onDragEnd={endDrag}
                        >
                          <GripVertical size={18} />
                        </span>
                      )}
                      {selecting && (
                        <input
                          type="checkbox"
                          aria-label={`${entry.name} (${entry.id}) 선택`}
                          title={
                            entry.canDelete ? undefined : entry.deletionReason
                          }
                          checked={selected.includes(entry.id)}
                          disabled={busy || !entry.canDelete}
                          onChange={() => toggleSelected(entry.id)}
                        />
                      )}
                      <img src={entry.thumbnail || undefined} alt="" />
                      <div className="manager-pet-info">
                        <div className="manager-pet-name">
                          <strong>{entry.name}</strong>
                          {current && (
                            <span className="current-badge">사용 중</span>
                          )}
                        </div>
                        <small>
                          {entry.description ? `${entry.description} · ` : ""}
                          {entry.source === "user"
                            ? "추가한 펫"
                            : entry.source === "bundled"
                              ? "기본 제공 펫"
                              : "외부 경로의 펫"}
                        </small>
                        {catalog.entries.some(
                          (other) =>
                            other.id !== entry.id &&
                            other.name === entry.name &&
                            (!entry.description ||
                              other.description === entry.description),
                        ) && (
                          <small
                            className="manager-package-id"
                            title={entry.id}
                          >
                            ID: {entry.id}
                          </small>
                        )}
                        {current && (!selecting || entry.canDelete) && (
                          <small>
                            {selecting
                              ? "함께 이동하면 대체 펫을 선택합니다."
                              : "다른 펫으로 바꾸면 숨길 수 있어요."}
                          </small>
                        )}
                        {selecting && !entry.canDelete && (
                          <small>{entry.deletionReason}</small>
                        )}
                      </div>
                      {!selecting &&
                        (editing ? (
                          <div className="manager-move-buttons">
                            <button
                              className="icon-button"
                              aria-label={`${entry.name} 위로`}
                              title="위로"
                              disabled={busy || index === 0}
                              onClick={() => void move(index, index - 1)}
                            >
                              <ArrowUp size={16} />
                            </button>
                            <button
                              className="icon-button"
                              aria-label={`${entry.name} 아래로`}
                              title="아래로"
                              disabled={busy || index === rows.length - 1}
                              onClick={() => void move(index, index + 1)}
                            >
                              <ArrowDown size={16} />
                            </button>
                          </div>
                        ) : (
                          <label className="manager-visibility">
                            <span>목록에 표시</span>
                            <Switch
                              label={`${entry.name} 목록에 표시`}
                              value={!hidden.includes(entry.id)}
                              disabled={busy || current}
                              change={(visible) =>
                                void save({
                                  hidden: visible
                                    ? hidden.filter((id) => id !== entry.id)
                                    : [...hidden, entry.id],
                                })
                              }
                            />
                          </label>
                        ))}
                      {!selecting && (
                        <details
                          className="manager-menu"
                          onKeyDown={(event) => {
                            if (event.key === "Escape") {
                              event.preventDefault();
                              event.stopPropagation();
                              event.currentTarget.open = false;
                              event.currentTarget
                                .querySelector("summary")
                                ?.focus();
                            }
                          }}
                        >
                          <summary
                            className="icon-button"
                            aria-label={`${entry.name} 더보기`}
                          >
                            <MoreHorizontal size={19} />
                          </summary>
                          <div className="manager-menu-items">
                            <button
                              disabled={busy || current}
                              onClick={(event) => {
                                closeMenu(event.currentTarget);
                                void run(
                                  "pet.select",
                                  { id: entry.id },
                                  `${entry.name}을(를) 사용하고 있어요.`,
                                );
                              }}
                            >
                              이 펫 사용하기
                            </button>
                            {editing && (
                              <>
                                <button
                                  disabled={busy || index === 0}
                                  onClick={(event) => {
                                    closeMenu(event.currentTarget);
                                    void move(index, 0);
                                  }}
                                >
                                  맨 위로
                                </button>
                                <button
                                  disabled={busy || index === rows.length - 1}
                                  onClick={(event) => {
                                    closeMenu(event.currentTarget);
                                    void move(index, rows.length - 1);
                                  }}
                                >
                                  맨 아래로
                                </button>
                              </>
                            )}
                            {entry.canDelete ? (
                              <button
                                className="manager-danger"
                                disabled={busy}
                                onClick={(event) => {
                                  closeMenu(event.currentTarget);
                                  trashPet(entry);
                                }}
                              >
                                휴지통으로 이동
                              </button>
                            ) : (
                              <p>{entry.deletionReason}</p>
                            )}
                          </div>
                        </details>
                      )}
                    </div>
                  );
                })
              )}
            </>
          ) : (
            <>
              <p className="manager-help">
                앱 전용 휴지통입니다. Windows 휴지통과 별개이며 자동으로
                삭제하지 않습니다.
              </p>
              <p className="manager-trash-summary">
                {trash.total}개 · {size(trash.totalBytes)}
              </p>
              {!trash.entries.length ? (
                <div className="manager-empty">
                  <Trash2 size={28} />
                  <strong>휴지통이 비어 있어요.</strong>
                  <span>삭제한 펫을 여기서 복원할 수 있어요.</span>
                </div>
              ) : (
                trash.entries.map((entry) => (
                  <div
                    className="catalog-row manager-row"
                    key={entry.trashId}
                    data-trash-id={entry.trashId}
                  >
                    {selecting && (
                      <input
                        type="checkbox"
                        aria-label={`${entry.name} (${entry.id}) 선택`}
                        checked={selected.includes(entry.trashId)}
                        disabled={
                          busy || !["trashed", "deleting"].includes(entry.state)
                        }
                        onChange={() => toggleSelected(entry.trashId)}
                      />
                    )}
                    <img src={entry.thumbnail || undefined} alt="" />
                    <div className="manager-pet-info">
                      <strong>{entry.name}</strong>
                      {trash.entries.some(
                        (other) =>
                          other.trashId !== entry.trashId &&
                          other.name === entry.name,
                      ) && (
                        <small className="manager-package-id">
                          ID: {entry.id}
                        </small>
                      )}
                      <small>
                        {new Date(entry.deletedAt).toLocaleString("ko-KR")} 삭제
                        · {size(entry.bytes)}
                      </small>
                      {entry.state !== "trashed" && (
                        <small>
                          이전 작업이 완료되지 않았어요.{" "}
                          {entry.state === "deleting"
                            ? "영구 삭제를 다시 시도하세요."
                            : "다시 불러오거나 앱을 재시작하세요."}
                        </small>
                      )}
                    </div>
                    {!selecting && (
                      <div className="manager-trash-actions">
                        <button
                          className="button compact"
                          disabled={busy || entry.state !== "trashed"}
                          onClick={() =>
                            void run(
                              "pet.trash.restore",
                              { trashId: entry.trashId },
                              `${entry.name}을(를) 복원했어요.`,
                            )
                          }
                        >
                          복원
                        </button>
                        <button
                          className="button compact manager-danger"
                          disabled={
                            busy ||
                            !["trashed", "deleting"].includes(entry.state)
                          }
                          onClick={() =>
                            setConfirmation({ kind: "delete", entry })
                          }
                        >
                          영구 삭제
                        </button>
                      </div>
                    )}
                  </div>
                ))
              )}
              {trash.total > 50 && (
                <div className="manager-pagination">
                  <button
                    className="button compact"
                    disabled={busy || !offset}
                    onClick={() => {
                      clearSelection();
                      setOffset(Math.max(0, offset - 50));
                    }}
                  >
                    이전
                  </button>
                  <span>
                    {Math.floor(offset / 50) + 1} /{" "}
                    {Math.ceil(trash.total / 50)}
                  </span>
                  <button
                    className="button compact"
                    disabled={busy || offset + 50 >= trash.total}
                    onClick={() => {
                      clearSelection();
                      setOffset(offset + 50);
                    }}
                  >
                    다음
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </Modal>
      {importing && (
        <PetImportDialog shell={shell} close={() => setImporting(false)} />
      )}
      {confirmation && (
        <Modal
          title={
            confirmation.kind === "batch"
              ? confirmation.action === "move"
                ? "선택한 펫 이동"
                : "선택한 펫 영구 삭제"
              : confirmation.kind === "move"
                ? "사용 중인 펫 이동"
                : confirmation.kind === "empty"
                  ? "휴지통 비우기"
                  : "펫 영구 삭제"
          }
          close={() => {
            if (!busy) setConfirmation(null);
          }}
          error={error || batch.error || undefined}
          footer={
            <>
              <button
                className="button"
                disabled={busy}
                onClick={() => setConfirmation(null)}
              >
                취소
              </button>
              <button
                className={
                  confirmation.kind === "move" ||
                  (confirmation.kind === "batch" &&
                    confirmation.action === "move")
                    ? "button primary"
                    : "button danger"
                }
                disabled={
                  busy ||
                  ((confirmation.kind === "move" ||
                    (confirmation.kind === "batch" &&
                      confirmation.action === "move" &&
                      confirmation.ids.includes(catalog?.petId ?? ""))) &&
                    !replacement)
                }
                onClick={() => {
                  if (confirmation.kind === "batch")
                    void startBatch(
                      confirmation.action,
                      confirmation.ids,
                      replacement,
                    );
                  else if (confirmation.kind === "move")
                    void run(
                      "pet.trash.move",
                      { id: confirmation.entry.id, replacementId: replacement },
                      "펫을 변경하고 휴지통으로 옮겼어요.",
                    );
                  else if (confirmation.kind === "delete")
                    void run(
                      "pet.trash.delete",
                      { trashId: confirmation.entry.trashId },
                      "펫을 영구 삭제했어요.",
                    );
                  else
                    void run(
                      "pet.trash.empty",
                      {},
                      "휴지통 비우기를 완료했어요.",
                    );
                }}
              >
                {confirmation.kind === "batch"
                  ? confirmation.action === "move"
                    ? "휴지통으로 이동"
                    : "영구 삭제"
                  : confirmation.kind === "move"
                    ? "변경 후 휴지통으로 이동"
                    : confirmation.kind === "empty"
                      ? "모두 영구 삭제"
                      : "영구 삭제"}
              </button>
            </>
          }
        >
          {confirmation.kind === "batch" ? (
            <>
              <p>
                {confirmation.ids.length}개 펫을{" "}
                {confirmation.action === "move"
                  ? "휴지통으로 옮깁니다. 나중에 복원할 수 있어요."
                  : `영구 삭제합니다 (${size(confirmation.bytes)}). 파일과 개별 설정은 복구할 수 없어요.`}
              </p>
              <ul className="batch-targets">
                {confirmation.names.map((name, index) => (
                  <li key={confirmation.ids[index]}>{name}</li>
                ))}
              </ul>
            </>
          ) : confirmation.kind === "move" ? (
            <p>
              <strong>{confirmation.entry.name}</strong>은(는) 현재 사용
              중이에요. 대신 사용할 펫을 선택하세요.
            </p>
          ) : (
            <p>
              <strong>
                {confirmation.kind === "delete"
                  ? confirmation.entry.name
                  : `${trash?.total ?? 0}개 펫 (${size(trash?.totalBytes ?? 0)})`}
              </strong>
              의 파일과 개별 설정을 영구 삭제합니다. 삭제 후에는 복원할 수
              없어요.
            </p>
          )}
          {(confirmation.kind === "move" ||
            (confirmation.kind === "batch" &&
              confirmation.action === "move" &&
              confirmation.ids.includes(catalog?.petId ?? ""))) && (
            <label className="manager-replacement">
              대신 사용할 펫
              <select
                aria-label="대신 사용할 펫"
                value={replacement}
                disabled={busy}
                onChange={(event) => setReplacement(event.target.value)}
              >
                <option value="">펫 선택</option>
                {rows
                  .filter((entry) =>
                    confirmation.kind === "batch"
                      ? !confirmation.ids.includes(entry.id)
                      : confirmation.kind === "move" &&
                        entry.id !== confirmation.entry.id,
                  )
                  .map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.name}
                      {hidden.includes(entry.id) ? " (숨김 해제)" : ""}
                    </option>
                  ))}
              </select>
            </label>
          )}
        </Modal>
      )}
    </>
  );
}
