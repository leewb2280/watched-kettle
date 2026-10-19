import { LocalizedText } from "./LocalizedText";
import { t } from "../localization.cjs";
import { Folder, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Modal, TabList } from "./components";
import { errorText } from "./errors";
import type { Shell } from "./types";
import { PetImportPreview } from "./PetImportPreview";

import type {
  PetRegistration,
  PetPreparation as Preparation,
  PetImportJob,
  InstalledPet,
} from "./types";

type Registration = Pick<
  PetRegistration,
  "id" | "name" | "alreadyExists" | "restoreRequired" | "trashId"
>;

function InstalledRow({
  row,
  busy,
  choose,
}: {
  row: InstalledPet;
  busy: boolean;
  choose: () => void;
}) {
  const button = useRef<HTMLButtonElement>(null);
  const [image, setImage] = useState("");
  useEffect(() => {
    let active = true;
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      if (!row.error)
        window
          .settings!.request("pet.import.installed.thumbnail", { id: row.id })
          .then((value) => {
            if (active) setImage(value.image);
          })
          .catch(() => {});
    });
    if (button.current) observer.observe(button.current);
    return () => {
      active = false;
      observer.disconnect();
    };
  }, [row.id, row.error]);
  return (
    <button
      ref={button}
      className="button import-installed-row"
      disabled={busy || !!row.error}
      onClick={choose}
    >
      {image && <img src={image} alt="" width={48} height={52} />}
      <span data-user-text>{row.name}</span>
      <small data-user-text>{row.description}</small>
      {row.error && <small>{row.error}</small>}
    </button>
  );
}

export function PetImportDialog({
  shell,
  close,
}: {
  shell: Shell;
  close: () => void;
}) {
  const [prepared, setPrepared] = useState<Preparation | null>(null);
  const [registered, setRegistered] = useState<Registration | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("file");
  const [command, setCommand] = useState("");
  const [installed, setInstalled] = useState<InstalledPet[]>([]);
  const [search, setSearch] = useState("");
  const [progress, setProgress] = useState<PetImportJob | null>(null);
  const job = useRef("");
  const generation = useRef(0);
  const token = useRef("");
  const mounted = useRef(false);
  const cancel = (value: string) => {
    if (job.current) {
      window
        .settings!.request("pet.import.stop", { jobId: job.current })
        .catch(() => {});
      job.current = "";
    }
    if (value)
      window
        .settings!.request("pet.import.cancel", { token: value })
        .catch(() => {});
  };
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current++;
      cancel(token.current);
    };
  }, []);

  useEffect(() => {
    if (!shell.visible) {
      generation.current++;
      cancel(token.current);
      setBusy(false);
      setPrepared(null);
    }
  }, [shell.visible]);
  const acceptJob = async (initial: PetImportJob, current: number) => {
    job.current = initial.jobId;
    let result = initial;
    while (mounted.current && generation.current === current) {
      setProgress(result);
      if (result.state === "error") throw new Error(result.error);
      if (result.state === "cancelled") return;
      if (result.state === "ready" && result.prepared) {
        token.current = result.prepared.token;
        setPrepared(result.prepared);
        setName(result.prepared.name);
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 300));
      if (!mounted.current || generation.current !== current) return;
      result = await window.settings!.request("pet.import.status", {
        jobId: initial.jobId,
      });
    }
    window
      .settings!.request("pet.import.stop", { jobId: initial.jobId })
      .catch(() => {});
  };
  const choose = async (
    kind: "pet" | "pet-folder" | "command" | "installed" = "pet",
    id = "",
  ) => {
    const current = ++generation.current;
    setBusy(true);
    setError("");
    setPrepared(null);
    setRegistered(null);
    cancel(token.current);
    token.current = "";
    try {
      const result =
        kind === "command"
          ? await window.settings!.request("pet.import.start", { command })
          : kind === "installed"
            ? await window.settings!.request("pet.import.installed.start", {
                id,
              })
            : await window.settings!.file(kind);
      if (!mounted.current || generation.current !== current) {
        if ("jobId" in result)
          window
            .settings!.request("pet.import.stop", { jobId: result.jobId })
            .catch(() => {});
        return;
      }
      if (!("cancelled" in result)) {
        await acceptJob(result, current);
      }
    } catch (failure) {
      if (mounted.current && generation.current === current)
        setError(errorText(failure));
    } finally {
      if (mounted.current && generation.current === current) setBusy(false);
    }
  };
  const refreshInstalled = async () => {
    setError("");
    try {
      setInstalled(await window.settings!.request("pet.import.installed"));
    } catch (failure) {
      if (mounted.current) setError(errorText(failure));
    }
  };
  const add = async () => {
    if (!prepared) return;
    setBusy(true);
    setError("");
    try {
      const result = await shell.command(
        "pet.import.commit",
        { token: prepared.token, name: name.trim() },
        { inline: true },
      );
      setRegistered(result);
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };
  const restore = async () => {
    if (!registered?.trashId) return;
    setBusy(true);
    setError("");
    try {
      const result = await shell.command(
        "pet.trash.restore",
        { trashId: registered.trashId! },
        { inline: true },
      );
      setRegistered({ id: result.id, name: result.name, alreadyExists: false });
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };
  const use = async () => {
    if (!registered) return;
    setBusy(true);
    setError("");
    try {
      // A duplicate may be hidden. Reveal it only when the user chooses use.
      const catalog = await window.settings!.request("pet.catalog");
      if (catalog.hidden.includes(registered.id))
        await shell.command(
          "pet.catalog.save",
          {
            sort: catalog.sort,
            order: catalog.order,
            hidden: catalog.hidden.filter((id: string) => id !== registered.id),
          },
          { inline: true },
        );
      await shell.command(
        "pet.select",
        { id: registered.id },
        { inline: true },
      );
      close();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={t("message.1126")}
      close={close}
      error={error || undefined}
      footer={
        <>
          <button className="button" onClick={close}>
            {registered ? t("message.0970") : t("message.0650")}
          </button>
          {registered ? (
            <button
              className="button primary"
              disabled={busy}
              onClick={registered.restoreRequired ? restore : use}
            >
              {registered.restoreRequired
                ? t("message.1152")
                : t("message.1153")}
            </button>
          ) : (
            <button
              className="button primary"
              disabled={busy || !prepared || !name.trim()}
              onClick={add}
            >
              <Plus size={15} />
              {t("message.1154")}
            </button>
          )}
        </>
      }
    >
      <p className="footnote">{t("message.1155")}</p>
      {!registered && (
        <>
          <TabList
            id="pet-import"
            label={t("pet.import.input")}
            tabs={[
              ["file", t("pet.import.file_tab")],
              ["command", t("pet.import.command_tab")],
              ["installed", t("pet.import.installed_tab")],
            ]}
            value={tab}
            select={(id) => {
              setTab(id);
              if (id === "installed") void refreshInstalled();
            }}
            className="import-tabs"
            tabClassName="button"
            disabled={busy}
          />
          <div
            role="tabpanel"
            id="pet-import-panel"
            aria-labelledby={`pet-import-tab-${tab}`}
          >
            {tab === "command" && (
              <div className="import-source-form">
                <label>
                  {t("pet.import.command_tab")}
                  <input
                    data-user-text
                    value={command}
                    maxLength={512}
                    disabled={busy}
                    onChange={(event) => setCommand(event.target.value)}
                  />
                </label>
                <p className="footnote">{t("pet.import.command_help")}</p>
                <button
                  className="button"
                  disabled={busy || !command.trim()}
                  onClick={() => void choose("command")}
                >
                  {t("pet.import.fetch")}
                </button>
              </div>
            )}
            {tab === "installed" && (
              <div className="import-source-form">
                <label>
                  {t("pet.import.search")}
                  <input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                </label>
                <button
                  className="button"
                  disabled={busy}
                  onClick={() => void refreshInstalled()}
                >
                  {t("pet.import.refresh")}
                </button>
                <div className="import-installed-list">
                  {installed
                    .filter((row) =>
                      `${row.name} ${row.description}`
                        .toLowerCase()
                        .includes(search.toLowerCase()),
                    )
                    .map((row) => (
                      <InstalledRow
                        key={row.id}
                        row={row}
                        busy={busy}
                        choose={() => void choose("installed", row.id)}
                      />
                    ))}
                  {!installed.length && <p>{t("pet.import.empty")}</p>}
                </div>
              </div>
            )}
            {tab === "file" && (
              <div className="import-file-actions">
                <button
                  className="button"
                  disabled={busy}
                  onClick={() => void choose()}
                >
                  <Folder size={15} />
                  {prepared ? t("message.1156") : t("message.1157")}
                </button>
                <button
                  className="button"
                  disabled={busy}
                  onClick={() => void choose("pet-folder")}
                >
                  {t("pet.import.folder")}
                </button>
              </div>
            )}
          </div>
        </>
      )}
      {prepared && (
        <div className="pet-import-preview">
          <PetImportPreview
            key={prepared.token}
            prepared={prepared}
            reduceMotion={shell.snapshot.appearance.reduceMotion}
          />
          {prepared.source && <p data-user-text>{prepared.source}</p>}
          {prepared.description && <p data-user-text>{prepared.description}</p>}
          {!!prepared.warnings?.length && (
            <p role="status">
              {t("pet.import.omitted_fields", {
                count: prepared.warnings.length,
              })}{" "}
              {prepared.warnings.map((field, index) => (
                <span key={field}>
                  {index > 0 && ", "}
                  <code data-user-text>{field}</code>
                </span>
              ))}
            </p>
          )}
          {prepared.omittedThemeReferences && (
            <p role="status">{t("pet.import.omitted_theme")}</p>
          )}
          {registered ? (
            <p role="status">
              <LocalizedText
                id={
                  registered.restoreRequired
                    ? "pet.import.trashed"
                    : registered.alreadyExists
                      ? "pet.import.exists"
                      : "pet.import.added"
                }
                values={{
                  name: <strong data-user-text>{registered.name}</strong>,
                }}
              />
            </p>
          ) : (
            <label className="pet-import-name">
              {t("message.1162")}
              <input
                type="text"
                data-user-text
                value={name}
                maxLength={100}
                disabled={busy}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
          )}
          <small>
            V{prepared.spriteVersion} {t("message.1163")}
          </small>
        </div>
      )}
      {busy && (
        <div role="status">
          <p>{t("status.processing")}</p>
          {progress && (
            <progress
              max={progress.total || undefined}
              value={progress.total ? progress.received : undefined}
            />
          )}
        </div>
      )}
    </Modal>
  );
}
