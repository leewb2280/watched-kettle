import { LocalizedText } from "./LocalizedText";
import { t, locale } from "../localization.cjs";
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
import { useEffect, useRef, useState } from "react";
import { Modal, Switch } from "./components";
import { errorText } from "./errors";
import { PetImportDialog } from "./PetImportDialog";
import type {
  Args,
  PetBatchAction,
  PetCatalog,
  PetCatalogEntry,
  PetTrashCatalog,
  PetTrashEntry,
  RendererCommand,
  Shell,
} from "./types";
import { usePetBatch } from "./usePetBatch";

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
        catalog: nextCatalog,
        trash: nextTrash,
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

  const run = async <
    M extends Extract<
      RendererCommand,
      | "pet.trash.move"
      | "pet.trash.restore"
      | "pet.trash.delete"
      | "pet.trash.empty"
      | "pet.catalog.save"
      | "pet.select"
    >,
  >(
    method: M,
    args: Args<M>,
    message: string,
  ) => {
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
        method === "pet.trash.move" && "trashId" in result && "name" in result
          ? { trashId: result.trashId!, name: result.name! }
          : null,
      );
      if ("failed" in result && result.failed?.length)
        setError(
          t("message.1164", {
            value0: result.deleted,
            value1: result.failed.length,
          }),
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
  const save = (change: Partial<PetCatalog>, message = t("message.1165")) => {
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
    if (announce && selecting) setNotice(t("message.1166"));
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
      t("message.1167", {
        value0: job.succeeded,
        value1: job.failed,
        value2: job.total - job.processed,
        value3: job.message ? ` · ${job.message}` : "",
      }),
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
    return save({ sort: "custom", order }, t("message.1168"));
  };
  const trashPet = (entry: PetCatalogEntry) => {
    if (entry.id === catalog?.petId) {
      setReplacement("");
      setConfirmation({ kind: "move", entry });
    } else
      void run(
        "pet.trash.move",
        { id: entry.id },
        t("message.1169", { value0: entry.name }),
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
        title={view === "trash" ? t("message.1170") : t("message.1128")}
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
                {t("message.1171")}
              </button>
            </>
          ) : undefined
        }
        footer={
          <>
            {batch.job?.state === "running" ? (
              <div className="batch-footer">
                <span role="status">
                  {t("pet.batch_progress", {
                    processed: batch.job.processed,
                    total: batch.job.total,
                    succeeded: batch.job.succeeded,
                    failed: batch.job.failed,
                  })}
                </span>
                <button
                  className="button"
                  disabled={batch.cancelling}
                  onClick={() => void batch.cancel()}
                >
                  {t("message.1174")}
                </button>
              </div>
            ) : selecting ? (
              <div className="batch-footer">
                <strong>{t("pet.selected", { count: selected.length })}</strong>
                <button
                  className="text-button"
                  disabled={busy || !selected.length}
                  onClick={() => setSelected([])}
                >
                  {t("message.1176")}
                </button>
                <div className="batch-actions">
                  {view === "owned" ? (
                    <button
                      className="button primary"
                      disabled={busy || !selected.length}
                      onClick={() => confirmBatch("move")}
                    >
                      {t("message.1177")}
                    </button>
                  ) : (
                    <>
                      <button
                        className="button"
                        disabled={busy || !canRestore}
                        title={
                          !canRestore && selected.length
                            ? t("message.1178")
                            : undefined
                        }
                        onClick={() => void startBatch("restore", selected)}
                      >
                        {t("message.1179")}
                      </button>
                      <button
                        className="button danger"
                        disabled={busy || !selected.length}
                        onClick={() => confirmBatch("delete")}
                      >
                        {t("message.1180")}
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
                    {t("message.1181")}
                  </button>
                </div>
              </div>
            ) : (
              <span className="manager-save-hint">{t("message.1182")}</span>
            )}
            <button
              className="button"
              disabled={saving || batch.starting}
              onClick={close}
            >
              {t("message.0970")}
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
              {selecting ? t("message.1183") : t("message.1184")}
            </button>
            {selecting && (
              <label>
                <input
                  ref={selectAll}
                  type="checkbox"
                  aria-label={t("message.1185")}
                  checked={
                    selectable.length > 0 &&
                    selected.length === selectable.length
                  }
                  disabled={busy || !selectable.length}
                  onChange={(event) =>
                    setSelected(event.target.checked ? [...selectable] : [])
                  }
                />
                {t("message.1185")}
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
                  <Plus size={16} />
                  {t("message.1186")}
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
                  {trash
                    ? t("pet.trash_count", { count: trash.total })
                    : t("pet.trash")}
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
                  <ArrowLeft size={16} />
                  {t("message.1188")}
                </button>
                <button
                  className="button manager-danger"
                  disabled={busy || !trash?.total || selecting}
                  onClick={() => setConfirmation({ kind: "empty" })}
                >
                  {t("message.1189")}
                </button>
              </>
            )}
          </div>
          <div className="manager-feedback" ref={feedback} tabIndex={-1}>
            <span role="status">
              {loading
                ? t("message.1190")
                : saving
                  ? t("message.1191")
                  : notice}
            </span>
            {undo && (
              <button
                className="text-button"
                disabled={busy}
                onClick={() =>
                  void run(
                    "pet.trash.restore",
                    { trashId: undo.trashId },
                    t("message.1192", { value0: undo.name }),
                  )
                }
              >
                <RotateCcw size={14} />
                {t("message.1193")}
              </button>
            )}
          </div>
          {batchUndo.length > 0 && (
            <button
              className="text-button batch-undo"
              disabled={busy}
              onClick={() => void startBatch("restore", batchUndo)}
            >
              {t("pet.undo_count", { count: batchUndo.length })}
            </button>
          )}
          {batch.job &&
            batch.job.state !== "running" &&
            batch.job.results.some(
              (row) => row.status === "failed" || row.status === "notStarted",
            ) && (
              <details className="batch-results">
                <summary>{t("message.1196")}</summary>
                <ul>
                  {batch.job.results
                    .filter(
                      (row) =>
                        row.status === "failed" || row.status === "notStarted",
                    )
                    .map((row) => (
                      <li key={row.id}>
                        <strong>{row.name}</strong> ·{" "}
                        {row.status === "failed"
                          ? t("message.0284")
                          : t("message.1197")}{" "}
                        · {row.message}
                      </li>
                    ))}
                </ul>
              </details>
            )}
          {trash?.issues.length ? (
            <p className="error-banner" role="alert">
              {t("message.1198")} {trash.issues[0]}
            </p>
          ) : null}
          {!catalog || !trash ? (
            <p role="status">{t("message.1199")}</p>
          ) : view === "owned" ? (
            <>
              <label className="manager-search">
                <Search size={16} />
                <input
                  aria-label={t("message.1200")}
                  placeholder={t("message.1200")}
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
                aria-label={t("message.1201")}
              >
                {(
                  [
                    ["all", t("message.1202")],
                    ["shown", t("message.1203")],
                    ["hidden", t("message.0795")],
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
                    {t("message.1204")}{" "}
                    <select
                      aria-label={t("message.1204")}
                      value={catalog.sort}
                      disabled={busy || selecting}
                      onChange={(event) => {
                        resetOrderEditing();
                        void save({
                          sort: event.target.value as "name" | "custom",
                        });
                      }}
                    >
                      <option value="name">{t("message.0708")}</option>
                      <option value="custom">{t("message.0709")}</option>
                    </select>
                  </label>
                  <button
                    className="button compact"
                    aria-pressed={editing}
                    disabled={busy || !canEdit || rows.length < 2}
                    onClick={() => setEditing(!editing)}
                  >
                    {editing ? t("message.1205") : t("message.1206")}
                  </button>
                </div>
              )}
              <p className="manager-help">
                {selecting
                  ? t("message.1207")
                  : editing
                    ? t("message.1208")
                    : canEdit
                      ? t("message.1209")
                      : t("message.1210")}
              </p>
              {!shown.length ? (
                <div className="manager-empty">
                  <strong>{t("message.1211")}</strong>
                  <button
                    className="button"
                    onClick={() => {
                      clearSelection();
                      setQuery("");
                      setFilter("all");
                    }}
                  >
                    {t("message.1212")}
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
                          title={t("message.1213")}
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
                          aria-label={t("message.1214", {
                            value0: entry.name,
                            value1: entry.id,
                          })}
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
                            <span className="current-badge">
                              {t("message.1215")}
                            </span>
                          )}
                        </div>
                        <small>
                          {entry.description ? `${entry.description} · ` : ""}
                          {entry.source === "user"
                            ? t("message.1216")
                            : entry.source === "bundled"
                              ? t("message.1217")
                              : t("message.1218")}
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
                            {selecting ? t("message.1219") : t("message.1220")}
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
                              aria-label={t("message.0712", {
                                value0: entry.name,
                              })}
                              title={t("message.1221")}
                              disabled={busy || index === 0}
                              onClick={() => void move(index, index - 1)}
                            >
                              <ArrowUp size={16} />
                            </button>
                            <button
                              className="icon-button"
                              aria-label={t("message.0713", {
                                value0: entry.name,
                              })}
                              title={t("message.1222")}
                              disabled={busy || index === rows.length - 1}
                              onClick={() => void move(index, index + 1)}
                            >
                              <ArrowDown size={16} />
                            </button>
                          </div>
                        ) : (
                          <label className="manager-visibility">
                            <span>{t("message.1223")}</span>
                            <Switch
                              label={t("message.1224", { value0: entry.name })}
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
                            aria-label={t("message.1225", {
                              value0: entry.name,
                            })}
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
                                  t("message.1226", { value0: entry.name }),
                                );
                              }}
                            >
                              {t("message.1227")}
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
                                  {t("message.1228")}
                                </button>
                                <button
                                  disabled={busy || index === rows.length - 1}
                                  onClick={(event) => {
                                    closeMenu(event.currentTarget);
                                    void move(index, rows.length - 1);
                                  }}
                                >
                                  {t("message.1229")}
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
                                {t("message.1230")}
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
              <p className="manager-help">{t("message.1231")}</p>
              <p className="manager-trash-summary">
                {t("pet.trash_summary", {
                  count: trash.total,
                  size: size(trash.totalBytes),
                })}
              </p>
              {!trash.entries.length ? (
                <div className="manager-empty">
                  <Trash2 size={28} />
                  <strong>{t("message.1233")}</strong>
                  <span>{t("message.1234")}</span>
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
                        aria-label={t("message.1214", {
                          value0: entry.name,
                          value1: entry.id,
                        })}
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
                        {t("pet.deleted", {
                          date: new Date(entry.deletedAt).toLocaleString(
                            locale(),
                          ),
                          size: size(entry.bytes),
                        })}
                      </small>
                      {entry.state !== "trashed" && (
                        <small>
                          {t("message.1236")}{" "}
                          {entry.state === "deleting"
                            ? t("message.1237")
                            : t("message.1238")}
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
                              t("message.1192", { value0: entry.name }),
                            )
                          }
                        >
                          {t("message.1239")}
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
                          {t("message.1240")}
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
                    {t("message.1241")}
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
                    {t("message.1242")}
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
                ? t("message.1177")
                : t("message.1180")
              : confirmation.kind === "move"
                ? t("message.1243")
                : confirmation.kind === "empty"
                  ? t("message.1189")
                  : t("message.1244")
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
                {t("message.0650")}
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
                      t("message.1245"),
                    );
                  else if (confirmation.kind === "delete")
                    void run(
                      "pet.trash.delete",
                      { trashId: confirmation.entry.trashId },
                      t("message.1246"),
                    );
                  else void run("pet.trash.empty", {}, t("message.1247"));
                }}
              >
                {confirmation.kind === "batch"
                  ? confirmation.action === "move"
                    ? t("message.1230")
                    : t("message.1240")
                  : confirmation.kind === "move"
                    ? t("message.1248")
                    : confirmation.kind === "empty"
                      ? t("message.1249")
                      : t("message.1240")}
              </button>
            </>
          }
        >
          {confirmation.kind === "batch" ? (
            <>
              <p>
                {t(
                  confirmation.action === "move"
                    ? "pet.batch_move_confirm"
                    : "pet.batch_delete_confirm",
                  {
                    count: confirmation.ids.length,
                    size: size(confirmation.bytes),
                  },
                )}
              </p>
              <ul className="batch-targets">
                {confirmation.names.map((name, index) => (
                  <li key={confirmation.ids[index]}>{name}</li>
                ))}
              </ul>
            </>
          ) : confirmation.kind === "move" ? (
            <p>
              <LocalizedText
                id="pet.replacement_needed"
                values={{ name: <strong>{confirmation.entry.name}</strong> }}
              />
            </p>
          ) : (
            <p>
              <LocalizedText
                id="pet.delete_confirm"
                values={{
                  name: (
                    <strong>
                      {confirmation.kind === "delete"
                        ? confirmation.entry.name
                        : t("message.1254", {
                            value0: trash?.total ?? 0,
                            value1: size(trash?.totalBytes ?? 0),
                          })}
                    </strong>
                  ),
                }}
              />
            </p>
          )}
          {(confirmation.kind === "move" ||
            (confirmation.kind === "batch" &&
              confirmation.action === "move" &&
              confirmation.ids.includes(catalog?.petId ?? ""))) && (
            <label className="manager-replacement">
              {t("message.1256")}
              <select
                aria-label={t("message.1256")}
                value={replacement}
                disabled={busy}
                onChange={(event) => setReplacement(event.target.value)}
              >
                <option value="">{t("message.1111")}</option>
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
                      {hidden.includes(entry.id) ? t("message.1257") : ""}
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
