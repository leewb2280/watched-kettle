import { LocalizedText } from "./LocalizedText";
import { t } from "../localization.cjs";
import { ArrowLeft, Check, Folder, Plus, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Modal, TabList } from "./components";
import { errorText } from "./errors";
import type {
  Shell,
  PetRegistration,
  PetPreparation as Preparation,
  PetImportJob,
  InstalledPet,
} from "./types";
import { PetImportPreview } from "./PetImportPreview";

type Registration = Pick<
  PetRegistration,
  "id" | "name" | "alreadyExists" | "restoreRequired" | "trashId"
>;
type InputKind = "pet" | "pet-folder" | "command" | "installed";
const originKeys: Record<InputKind, string> = {
  pet: "pet.import.from_file",
  "pet-folder": "pet.import.from_folder",
  command: "pet.import.from_command",
  installed: "pet.import.from_installed",
};

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
      <span className="import-installed-image" aria-hidden="true">
        {image && <img src={image} alt="" width={48} height={52} />}
      </span>
      <span className="import-installed-copy">
        <strong data-user-text>{row.name}</strong>
        {row.description && <small data-user-text>{row.description}</small>}
        {row.error && (
          <small className="import-installed-error">{row.error}</small>
        )}
      </span>
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
  const [inputKind, setInputKind] = useState<InputKind>("pet");
  const [command, setCommand] = useState("");
  const [installed, setInstalled] = useState<InstalledPet[]>([]);
  const [installedBusy, setInstalledBusy] = useState(false);
  const [installedError, setInstalledError] = useState("");
  const [search, setSearch] = useState("");
  const [progress, setProgress] = useState<PetImportJob | null>(null);
  const job = useRef("");
  const generation = useRef(0);
  const installedGeneration = useRef(0);
  const token = useRef("");
  const mounted = useRef(false);
  const fileButton = useRef<HTMLButtonElement>(null);
  const commandInput = useRef<HTMLInputElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const errorMessage = useRef<HTMLDivElement>(null);
  const step = registered ? "result" : prepared ? "confirm" : "source";
  const current = (value: number) =>
    mounted.current && generation.current === value;
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
    token.current = "";
  };
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current++;
      installedGeneration.current++;
      cancel(token.current);
    };
  }, []);
  useEffect(() => {
    if (!shell.visible) {
      generation.current++;
      installedGeneration.current++;
      cancel(token.current);
      setBusy(false);
      setProgress(null);
      setPrepared(null);
      setRegistered(null);
      setName("");
      setError("");
    }
  }, [shell.visible]);
  useEffect(() => {
    if (!shell.visible) return;
    const frame = requestAnimationFrame(() => {
      if (step === "confirm") nameInput.current?.focus();
      else if (step === "result") resultHeading.current?.focus();
      else if (tab === "command") commandInput.current?.focus();
      else if (tab === "installed") searchInput.current?.focus();
      else fileButton.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
    // TabList keeps its roving keyboard focus; move focus only between steps.
  }, [step, shell.visible]);
  useEffect(() => {
    if (error) errorMessage.current?.focus();
  }, [error]);

  const refreshInstalled = useCallback(async () => {
    const sequence = ++installedGeneration.current;
    setInstalledBusy(true);
    setInstalledError("");
    try {
      const rows = await window.settings!.request("pet.import.installed");
      if (mounted.current && sequence === installedGeneration.current)
        setInstalled(rows);
    } catch (failure) {
      if (mounted.current && sequence === installedGeneration.current)
        setInstalledError(errorText(failure));
    } finally {
      if (mounted.current && sequence === installedGeneration.current)
        setInstalledBusy(false);
    }
  }, []);
  useEffect(() => {
    if (step !== "source" || tab !== "installed" || !shell.visible) return;
    void refreshInstalled();
    return () => {
      installedGeneration.current++;
    };
  }, [step, tab, shell.visible, refreshInstalled]);

  const acceptJob = async (initial: PetImportJob, sequence: number) => {
    job.current = initial.jobId;
    let result = initial;
    while (current(sequence)) {
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
      if (!current(sequence)) return;
      result = await window.settings!.request("pet.import.status", {
        jobId: initial.jobId,
      });
    }
  };
  const choose = async (kind: InputKind = "pet", id = "") => {
    const sequence = ++generation.current;
    installedGeneration.current++;
    setBusy(true);
    setError("");
    setProgress(null);
    setPrepared(null);
    setRegistered(null);
    setName("");
    setInputKind(kind);
    cancel(token.current);
    try {
      const result =
        kind === "command"
          ? await window.settings!.request("pet.import.start", { command })
          : kind === "installed"
            ? await window.settings!.request("pet.import.installed.start", {
                id,
              })
            : await window.settings!.file(kind);
      if (!current(sequence)) {
        if ("jobId" in result)
          window
            .settings!.request("pet.import.stop", { jobId: result.jobId })
            .catch(() => {});
        return;
      }
      if (!("cancelled" in result)) await acceptJob(result, sequence);
    } catch (failure) {
      if (current(sequence)) setError(errorText(failure));
    } finally {
      if (current(sequence)) {
        setBusy(false);
        setProgress(null);
      }
    }
  };
  const back = () => {
    generation.current++;
    cancel(token.current);
    setPrepared(null);
    setName("");
    setError("");
    setProgress(null);
  };
  const add = async () => {
    if (!prepared || busy) return;
    const sequence = generation.current;
    setBusy(true);
    setError("");
    try {
      const result = await shell.command(
        "pet.import.commit",
        { token: prepared.token, name: name.trim() },
        { inline: true },
      );
      if (current(sequence)) setRegistered(result);
    } catch (failure) {
      if (current(sequence)) setError(errorText(failure));
    } finally {
      if (current(sequence)) setBusy(false);
    }
  };
  const restore = async () => {
    if (!registered?.trashId || busy) return;
    const sequence = generation.current;
    setBusy(true);
    setError("");
    try {
      const result = await shell.command(
        "pet.trash.restore",
        { trashId: registered.trashId },
        { inline: true },
      );
      if (current(sequence))
        setRegistered({
          id: result.id,
          name: result.name,
          alreadyExists: false,
        });
    } catch (failure) {
      if (current(sequence)) setError(errorText(failure));
    } finally {
      if (current(sequence)) setBusy(false);
    }
  };
  const use = async () => {
    if (!registered || busy) return;
    const sequence = generation.current;
    setBusy(true);
    setError("");
    try {
      // A duplicate may be hidden. Reveal it only when the user chooses use.
      const catalog = await window.settings!.request("pet.catalog");
      if (!current(sequence)) return;
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
      if (!current(sequence)) return;
      await shell.command(
        "pet.select",
        { id: registered.id },
        { inline: true },
      );
      if (current(sequence)) close();
    } catch (failure) {
      if (current(sequence)) setError(errorText(failure));
    } finally {
      if (current(sequence)) setBusy(false);
    }
  };
  const filtered = installed.filter((row) =>
    `${row.name} ${row.description}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  return (
    <Modal
      title={t("message.1126")}
      className="pet-import-modal"
      close={close}
      error={
        error ? (
          <div ref={errorMessage} tabIndex={-1}>
            {error}
          </div>
        ) : undefined
      }
      footer={
        <>
          {step === "confirm" && (
            <button
              className="button import-back"
              disabled={busy}
              onClick={back}
            >
              <ArrowLeft size={15} aria-hidden="true" />
              {t("message.1156")}
            </button>
          )}
          <div className="import-footer-actions">
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
            ) : prepared ? (
              <button
                className="button primary"
                disabled={busy || !name.trim()}
                onClick={add}
              >
                <Plus size={15} aria-hidden="true" />
                {t("message.1154")}
              </button>
            ) : null}
          </div>
        </>
      }
    >
      <div className="pet-import-body" data-import-step={step}>
        {step === "source" && (
          <div className="import-source" aria-busy={busy}>
            <p className="import-intro">{t("message.1155")}</p>
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
                setError("");
              }}
              className="import-tabs"
              disabled={busy}
            />
            <div
              role="tabpanel"
              id="pet-import-panel"
              aria-labelledby={`pet-import-tab-${tab}`}
            >
              {tab === "file" && (
                <div className="import-file-panel">
                  <Folder size={28} aria-hidden="true" />
                  <h3>{t("pet.import.file_heading")}</h3>
                  <p className="footnote">{t("pet.import.file_help")}</p>
                  <div className="import-file-actions">
                    <button
                      ref={fileButton}
                      className="button primary"
                      disabled={busy}
                      onClick={() => void choose()}
                    >
                      {t("message.1157")}
                    </button>
                    <button
                      className="button"
                      disabled={busy}
                      onClick={() => void choose("pet-folder")}
                    >
                      {t("pet.import.folder")}
                    </button>
                  </div>
                </div>
              )}
              {tab === "command" && (
                <form
                  className="import-source-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!busy && command.trim()) void choose("command");
                  }}
                >
                  <label htmlFor="pet-import-command">
                    {t("pet.import.command_tab")}
                  </label>
                  <div className="import-inline">
                    <input
                      ref={commandInput}
                      id="pet-import-command"
                      data-user-text
                      value={command}
                      maxLength={512}
                      disabled={busy}
                      aria-describedby="pet-import-command-help"
                      onChange={(event) => setCommand(event.target.value)}
                    />
                    <button
                      className="button primary"
                      disabled={busy || !command.trim()}
                      type="submit"
                    >
                      {t("pet.import.fetch")}
                    </button>
                  </div>
                  <div id="pet-import-command-help" className="import-help">
                    <p>{t("pet.import.command_example")}</p>
                    <p>{t("pet.import.command_help")}</p>
                  </div>
                </form>
              )}
              {tab === "installed" && (
                <div className="import-source-form">
                  <label htmlFor="pet-import-search">
                    {t("pet.import.search")}
                  </label>
                  <div className="import-inline">
                    <input
                      ref={searchInput}
                      id="pet-import-search"
                      data-user-text
                      value={search}
                      disabled={busy}
                      onChange={(event) => setSearch(event.target.value)}
                    />
                    <button
                      className="button"
                      disabled={busy || installedBusy}
                      onClick={() => void refreshInstalled()}
                    >
                      <RefreshCw size={15} aria-hidden="true" />
                      {t("pet.import.refresh")}
                    </button>
                  </div>
                  <div
                    className="import-installed-list"
                    aria-busy={installedBusy}
                  >
                    {installedBusy ? (
                      <p role="status">{t("pet.import.loading_installed")}</p>
                    ) : installedError ? (
                      <p role="alert">{installedError}</p>
                    ) : !installed.length ? (
                      <p role="status">{t("pet.import.empty")}</p>
                    ) : !filtered.length ? (
                      <p role="status">{t("pet.import.no_search_results")}</p>
                    ) : (
                      filtered.map((row) => (
                        <InstalledRow
                          key={row.id}
                          row={row}
                          busy={busy}
                          choose={() => void choose("installed", row.id)}
                        />
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
        {prepared && !registered && (
          <div className="pet-import-preview">
            <PetImportPreview
              key={prepared.token}
              prepared={prepared}
              reduceMotion={shell.snapshot.appearance.reduceMotion}
            />
            <div className="import-pet-details">
              <h3>{t("pet.import.confirm_title")}</h3>
              <label className="pet-import-name">
                {t("message.1162")}
                <input
                  ref={nameInput}
                  type="text"
                  data-user-text
                  value={name}
                  maxLength={100}
                  disabled={busy}
                  onChange={(event) => setName(event.target.value)}
                />
              </label>
              {prepared.description && (
                <p data-user-text>{prepared.description}</p>
              )}
              <div className="import-pet-origin">
                <span>{t(originKeys[inputKind])}</span>
                {prepared.source && (
                  <span data-user-text>{prepared.source}</span>
                )}
              </div>
              {!!prepared.warnings?.length && (
                <p role="status" className="import-warning">
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
                <p role="status" className="import-warning">
                  {t("pet.import.omitted_theme")}
                </p>
              )}
              <p className="import-help">
                {t("pet.import.sprite_version", {
                  version: prepared.spriteVersion,
                })}
              </p>
              <p className="import-help">{t("message.1163")}</p>
            </div>
          </div>
        )}
        {prepared && registered && (
          <div className="import-result">
            <img
              src={prepared.thumbnail}
              alt={t("message.1158")}
              width={144}
              height={156}
            />
            <div className="import-result-copy">
              <h3 ref={resultHeading} tabIndex={-1}>
                {!registered.restoreRequired && (
                  <Check size={20} aria-hidden="true" />
                )}
                {registered.restoreRequired
                  ? t("pet.import.restore_title")
                  : registered.alreadyExists
                    ? t("pet.import.exists_title")
                    : t("pet.import.added_title")}
              </h3>
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
            </div>
          </div>
        )}
        {busy && (
          <div className="import-progress" role="status">
            <span>{t("status.processing")}</span>
            {progress && (
              <progress
                aria-label={t("status.processing")}
                max={progress.total || undefined}
                value={progress.total ? progress.received : undefined}
              />
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
