import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChartNoAxesCombined,
  Check,
  ChevronRight,
  Gauge,
  House,
  CircleHelp,
  Info,
  Layers,
  MessageCircle,
  PawPrint,
  PlugZap,
  Power,
  Settings2,
  X,
} from "lucide-react";
import type {
  CommandOptions,
  Page,
  Route,
  SettingsSnapshot,
  Values,
  Shell,
} from "./types";
import { CorePages } from "./CorePages";
import { AssistantPages } from "@assistant";
import { Empty, Modal } from "./components";
import { errorText } from "./errors";

const labels: Record<Page, string> = {
  home: "홈",
  pet: "펫",
  bubble: "말풍선",
  widget: "위젯",
  usage: "사용량",
  activity: "활동 기록",
  integration: "연결·진단",
  app: "앱 설정",
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
      method: string,
      args: Values = {},
      options: CommandOptions = {},
    ): Promise<any> =>
      new Promise((resolve, reject) => {
        const origin = snapshot;
        queue.current = queue.current.then(async () => {
          if (!window.settings || !current.current) {
            reject(new Error("설정 연결을 기다려 주세요."));
            return;
          }
          setBusy((count) => count + 1);
          setError("");
          if (!options.quiet) setStatus("처리 중…");
          try {
            const context = current.current;
            if (
              !origin ||
              origin.epoch !== context.epoch ||
              origin.pet.pet_id !== context.pet.pet_id
            )
              throw new Error(
                "계정 또는 펫이 변경됐습니다. 현재 화면에서 다시 변경해 주세요.",
              );
            const result = await window.settings.request(method, {
              petId: context.pet.pet_id,
              revision: context.revision,
              epoch: context.epoch,
              ...args,
            });
            if (result?.snapshot) {
              ++refreshSequence.current;
              accept(result.snapshot);
            } else await refresh();
            setEventVersion((count) => count + 1);
            if (!options.quiet)
              setStatus(result?.saved ? "저장됨" : "요청 처리됨");
            resolve(result);
          } catch (e) {
            if (!options.inline) setError(errorText(e));
            setStatus("확인 필요");
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
  );
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
      setError(
        "설정창은 펫 앱의 트레이에서 열어주세요. 브라우저에서는 실제 설정에 연결할 수 없습니다.",
      );
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
                } as Record<string, string[]>
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
          <nav aria-label="설정 탐색">
            {assistant && (
              <>
                {navButton("home", House)}
                <div className="nav-label separated">비서</div>
                {navButton("usage", ChartNoAxesCombined)}
                {navButton("activity", Layers)}
                {navButton("integration", PlugZap)}
              </>
            )}
            <div className={`nav-label ${assistant ? "separated" : ""}`}>
              꾸미기
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
              <span>앱 설정</span>
            </button>
            <button
              className="nav-item quit"
              onClick={() => {
                if (confirm("펫과 비서, 설정창을 모두 종료할까요?"))
                  command("app.quit").catch(() => {});
              }}
            >
              <Power />
              <span>펫 앱 종료</span>
            </button>
            <div className="sidebar-profile">
              <span className="profile-avatar">
                <PawPrint size={16} />
              </span>
              <div>
                <strong>{snapshot?.pet.display_name || "연결 중"}</strong>
                <span>{assistant ? "펫 + 비서" : "펫만"}</span>
              </div>
            </div>
          </div>
        </aside>
        <main id="main">
          <div className="page-topline">
            <div className="breadcrumb">
              설정
              <ChevronRight size={13} />
              <span>{labels[page]}</span>
            </div>
            <div className="topline-actions">
              <span
                className={`save-state ${
                  !busy && status === "확인 필요" ? "error" : ""
                }`}
                role="status"
              >
                {busy ? (
                  <span className="small-dot" />
                ) : status === "확인 필요" ? (
                  <Info size={12} />
                ) : (
                  <Check size={12} />
                )}
                {status}
              </span>
              <button
                className="icon-button"
                aria-label="도움말"
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
                다시 확인
              </button>
              <button
                className="icon-button"
                aria-label="오류 안내 닫기"
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
              <h2>설정에 연결하는 중입니다.</h2>
              <p>펫의 현재 설정을 확인하고 있습니다.</p>
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
        <Modal title="도움말" close={() => setHelp(false)}>
          <p>
            일반 설정과 펫 관리는 즉시 적용·저장됩니다. 말풍선 꾸미기는 적용
            버튼으로 저장해 주세요.
          </p>
          <p>
            X는 설정창만 숨깁니다. 트레이에서 다시 열 수 있으며, 펫 앱 종료는
            모든 기능을 종료합니다.
          </p>
          <p>
            저장 오류가 표시되면 다시 확인해 주세요. 사용량과 활동 정보는 설치한
            구성과 연결 상태에 따라 표시됩니다.
          </p>
        </Modal>
      )}
    </>
  );
}
