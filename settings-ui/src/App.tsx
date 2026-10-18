import { t } from "../localization.cjs";
import { AssistantPages } from "@assistant";
import {
  ChartNoAxesCombined,
  Check,
  ChevronRight,
  CircleHelp,
  Gauge,
  House,
  Info,
  Layers,
  MessageCircle,
  PawPrint,
  PlugZap,
  Power,
  Settings2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Empty, Modal } from "./components";
import { CorePages } from "./CorePages";
import { errorText } from "./errors";
import type {
  Args,
  CommandCall,
  CommandOptions,
  Page,
  RendererCommand,
  Route,
  SettingsSnapshot,
  Shell,
} from "./types";

const labels: Record<Page, string> = {
  home: t("message.0590"),
  pet: t("message.0591"),
  bubble: t("message.0592"),
  widget: t("message.0494"),
  usage: t("message.0204"),
  activity: t("message.0593"),
  integration: t("message.0594"),
  app: t("message.0595"),
};
export function App() {
  const [snapshot, setSnapshot] = useState<SettingsSnapshot | null>(null);
  const current = useRef<SettingsSnapshot | null>(null);
  const [page, setPage] = useState<Page>("pet");
  const [route, setRoute] = useState<Route | null>(null);
  const [visible, setVisible] = useState(true);
  const [eventVersion, setEventVersion] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(0);
  const [status, setStatus] = useState("");
  const [help, setHelp] = useState(false);
  const [toast, setToast] = useState("");
  const queue = useRef(Promise.resolve());
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const refreshSequence = useRef(0);
  const notify = useCallback((text: string) => {
    clearTimeout(toastTimer.current);
    setToast(text);
    toastTimer.current = setTimeout(() => setToast(""), 4000);
  }, []);
  const accept = (value: SettingsSnapshot) => {
    if (current.current && value.epoch < current.current.epoch) return;
    current.current = value;
    setSnapshot(value);
  };
  const refresh = useCallback(async () => {
    if (!window.settings) return;
    const seq = ++refreshSequence.current;
    const value = await window.settings.request("settings.snapshot");
    if (seq === refreshSequence.current) accept(value);
  }, []);
  const reportError = useCallback((e: unknown) => setError(errorText(e)), []);
  const command = useCallback(
    (
      method: RendererCommand,
      args: Args<RendererCommand> = {},
      options: CommandOptions = {},
    ): Promise<unknown> =>
      new Promise((resolve, reject) => {
        const origin = snapshot;
        queue.current = queue.current.then(async () => {
          if (!window.settings || !current.current) {
            reject(new Error(t("message.0596")));
            return;
          }
          setBusy((count) => count + 1);
          setError("");
          if (!options.quiet) setStatus("processing");
          try {
            const context = current.current;
            if (
              !origin ||
              origin.epoch !== context.epoch ||
              origin.pet.pet_id !== context.pet.pet_id
            )
              throw new Error(t("message.0597"));
            const result = await window.settings.request(method, {
              petId: context.pet.pet_id,
              revision: context.revision,
              epoch: context.epoch,
              ...args,
            });
            if ("snapshot" in result) {
              ++refreshSequence.current;
              accept(result.snapshot);
            } else if (method !== "app.restart") await refresh();
            setEventVersion((count) => count + 1);
            if (!options.quiet)
              setStatus(
                "saved" in result && result.saved ? "saved" : "processed",
              );
            resolve(result);
          } catch (e) {
            if (!options.inline) setError(errorText(e));
            setStatus("attention");
            try {
              await refresh();
            } catch {}
            reject(e);
          } finally {
            setBusy((count) => count - 1);
          }
        });
      }),
    [refresh, snapshot?.epoch, snapshot?.pet.pet_id],
  ) as CommandCall;
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (
        !event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        document.querySelector("dialog[open]")
      )
        return;
      if (event.key === "1" || event.key === "2") {
        event.preventDefault();
        setPage(event.key === "1" ? "pet" : "bubble");
      }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);
  useEffect(() => {
    if (!window.settings) {
      setError(t("message.0598"));
      return;
    }
    const off = window.settings.onEvent(({ event, data }) => {
      if (event === "navigate") {
        setRoute(data);
        setPage(data.page);
      }
      if (event === "visibility") {
        setVisible(data);
        if (data) refresh().catch((e) => setError(errorText(e)));
      }
      if (event === "invalidate") {
        if (data.topics.includes("account")) {
          setRoute(null);
          setSnapshot((value) =>
            value ? { ...value, epoch: data.epoch } : null,
          );
          if (current.current)
            current.current = { ...current.current, epoch: data.epoch };
        }
        setEventVersion((count) => count + 1);
        refresh().catch((e) => setError(errorText(e)));
      }
      if (event === "appearance") {
        document.documentElement.dataset.theme = data.effectiveTheme;
        document.documentElement.dataset.material = data.effectiveMaterial;
        document.documentElement.dataset.motion = data.reduceMotion
          ? "reduce"
          : "normal";
        document.documentElement.style.setProperty(
          "--frame-opacity",
          String(
            (data.effectiveTheme === "dark"
              ? data.darkOpacity
              : data.lightOpacity) / 100,
          ),
        );
      }
    });
    window.settings
      .ready()
      .then((state) => {
        if (state.route) {
          setPage(state.route.page);
          setRoute(state.route);
        }
        return refresh();
      })
      .catch((e) => setError(errorText(e)));
    return () => {
      off();
      clearTimeout(toastTimer.current);
    };
  }, [refresh]);
  useEffect(() => {
    if (!snapshot || !window.settings) return;
    window.settings
      .request("window.subscribe", {
        topics: visible
          ? [
              "settings",
              ...((
                {
                  home: ["usage", "activity"],
                  usage: ["usage"],
                  widget: ["usage"],
                  activity: ["activity"],
                } as Record<string, ("usage" | "activity")[]>
              )[page] || []),
            ]
          : [],
      })
      .catch((e) => setError(errorText(e)));
  }, [page, visible, snapshot?.edition]);
  const assistant = __ASSISTANT__ && snapshot?.edition === "pet-assistant";
  const shell: Shell | null = snapshot
    ? {
        snapshot,
        command,
        refresh,
        navigate: setPage,
        notify,
        reportError,
        visible,
        eventVersion,
        busy: busy > 0,
        route,
      }
    : null;
  const navButton = (id: Page, Icon: typeof PawPrint) => (
    <button
      key={id}
      aria-label={labels[id]}
      className={`nav-item ${page === id ? "active" : ""}`}
      aria-current={page === id ? "page" : undefined}
      onClick={() => setPage(id)}
    >
      <Icon />
      <span>{labels[id]}</span>
    </button>
  );
  return (
    <>
      <header className="titlebar">
        <div className="app-mark">
          <PawPrint size={17} />
          <strong>Watched Kettle</strong>
        </div>
        <span className="version-label">{snapshot?.version}</span>
      </header>
      <div className="shell">
        <aside className="sidebar">
          <nav aria-label={t("message.0599")}>
            {assistant && (
              <>
                {navButton("home", House)}
                <div className="nav-label separated">{t("message.0251")}</div>
                {navButton("usage", ChartNoAxesCombined)}
                {navButton("activity", Layers)}
                {navButton("integration", PlugZap)}
              </>
            )}
            <div className={`nav-label ${assistant ? "separated" : ""}`}>
              {t("message.0600")}
            </div>
            {navButton("pet", PawPrint)}
            {navButton("bubble", MessageCircle)}
            {assistant && navButton("widget", Gauge)}
          </nav>
          <div className="sidebar-bottom">
            <button
              className={`nav-item ${page === "app" ? "active" : ""}`}
              onClick={() => setPage("app")}
            >
              <Settings2 />
              <span>{t("message.0595")}</span>
            </button>
            <button
              className="nav-item quit"
              onClick={() => {
                if (confirm(t("message.0601")))
                  command("app.quit").catch(() => {});
              }}
            >
              <Power />
              <span>{t("message.0602")}</span>
            </button>
            <div className="sidebar-profile">
              <span className="profile-avatar">
                <PawPrint size={16} />
              </span>
              <div>
                <strong>
                  {snapshot?.pet.display_name || t("message.0603")}
                </strong>
                <span>{assistant ? t("message.0604") : t("message.0605")}</span>
              </div>
            </div>
          </div>
        </aside>
        <main id="main">
          <div className="page-topline">
            <div className="breadcrumb">
              {t("message.0225")}
              <ChevronRight size={13} />
              <span>{labels[page]}</span>
            </div>
            <div className="topline-actions">
              <span
                className={`save-state ${
                  !busy && status === "attention" ? "error" : ""
                }`}
                role="status"
              >
                {busy ? (
                  <span className="small-dot" />
                ) : status === "attention" ? (
                  <Info size={12} />
                ) : (
                  <Check size={12} />
                )}
                {status && t("status." + status)}
              </span>
              <button
                className="icon-button"
                aria-label={t("message.0606")}
                onClick={() => setHelp(true)}
              >
                <CircleHelp size={17} />
              </button>
            </div>
          </div>
          {error && (
            <div className="error-banner" role="alert">
              <Info size={17} />
              <span>{error}</span>
              <button
                className="text-button"
                onClick={() =>
                  refresh()
                    .then(() => setError(""))
                    .catch((e) => setError(errorText(e)))
                }
              >
                {t("message.0607")}
              </button>
              <button
                className="icon-button"
                aria-label={t("message.0608")}
                onClick={() => setError("")}
              >
                <X size={15} />
              </button>
            </div>
          )}
          {shell ? (
            <>
              <CorePages shell={shell} page={page} />
              {assistant && (
                <AssistantPages
                  key={snapshot.epoch}
                  shell={shell}
                  page={page}
                />
              )}
            </>
          ) : (
            <Empty>
              <PawPrint size={32} />
              <h2>{t("message.0609")}</h2>
              <p>{t("message.0610")}</p>
            </Empty>
          )}
        </main>
      </div>
      {toast && (
        <div className="toast" role="status">
          <Check size={15} />
          {toast}
        </div>
      )}
      {help && (
        <Modal title={t("message.0606")} close={() => setHelp(false)}>
          <p>{t("message.0611")}</p>
          <p>{t("message.0612")}</p>
          <p>{t("message.0613")}</p>
        </Modal>
      )}
    </>
  );
}
