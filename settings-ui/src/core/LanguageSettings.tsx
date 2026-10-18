import { useEffect, useRef, useState } from "react";
import { Copy, FolderOpen, RefreshCw, RotateCw } from "lucide-react";
import { Section } from "../components";
import type { Shell, LanguagePackInfo } from "../types";
import { t } from "../../localization.cjs";

export function LanguageSettings({ shell }: { shell: Shell }) {
  const [packs, setPacks] = useState<LanguagePackInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState("");
  const [restarting, setRestarting] = useState(false);
  const sequence = useRef(0);
  const load = async (refresh = false) => {
    const request = ++sequence.current;
    setBusy(true);
    try {
      const rows = await window.settings!.request(
        refresh ? "language.refresh" : "language.list",
      );
      if (request === sequence.current) {
        setPacks(rows);
        if (refresh) await shell.refresh();
      }
    } catch (error) {
      if (request === sequence.current) shell.reportError(error);
    } finally {
      if (request === sequence.current) setBusy(false);
    }
  };
  // A mutating command: sent once per click, never retried automatically.
  const copy = async () => {
    const request = ++sequence.current;
    setBusy(true);
    try {
      const result = await shell.command("language.copy");
      if (request === sequence.current) {
        setPacks(result.packs);
        setCopied(result.id);
      }
    } catch (error) {
      if (request === sequence.current) {
        shell.reportError(error);
        void load(true);
      }
    } finally {
      if (request === sequence.current) setBusy(false);
    }
  };
  const selectLanguage = async (value: string) => {
    const request = ++sequence.current;
    setCopied("");
    setBusy(true);
    try {
      await shell.command("settings.set", { key: "languagePack", value });
    } catch (error) {
      if (request === sequence.current) shell.reportError(error);
    } finally {
      if (request === sequence.current) setBusy(false);
    }
  };
  const restart = async () => {
    setRestarting(true);
    try {
      await shell.command("app.restart");
    } catch (error) {
      setRestarting(false);
      shell.reportError(error);
    }
  };
  useEffect(() => {
    void load();
    return () => {
      ++sequence.current;
    };
  }, []);
  const state = shell.snapshot.language;
  const controlsBusy = busy || shell.busy || restarting;
  const updateBusy = ["downloading", "preparing", "installing"].includes(
    shell.snapshot.update.state,
  );
  const selected = packs.find((pack) => pack.id === state.selected);
  const fallbackName = (pack: LanguagePackInfo) =>
    packs.find((row) => row.id === pack.fallback)?.name || pack.fallback;
  return (
    <Section title={t("language.title")}>
      <div className="setting-row">
        <div>
          <h3>{t("language.selection")}</h3>
          <p>{t("language.restart")}</p>
        </div>
        <select
          aria-label={t("language.selection")}
          value={state.selected}
          disabled={controlsBusy}
          onChange={(event) => void selectLanguage(event.target.value)}
        >
          {!selected && (
            <option value={state.selected} disabled>
              {state.selected}
            </option>
          )}
          {packs.map((pack, index) => (
            <option
              key={pack.id + ":" + index}
              value={pack.id}
              disabled={!pack.selectable}
            >
              {pack.name} · {pack.locale || "?"}
              {pack.error ? " · " + t("language.invalid") : ""}
            </option>
          ))}
        </select>
      </div>
      {/* One left edge for the pack details, notices and buttons. */}
      <div className="language-details">
        {selected && (
          <p className="footnote">
            {selected.author} · {selected.version} ·{" "}
            {t("language.coverage", {
              done: selected.translated,
              total: selected.total,
              review: selected.outdated,
            })}
            {selected.fallbackCount > 0 && (
              <>
                <br />
                {t("language.fallback", {
                  count: selected.fallbackCount,
                  name: fallbackName(selected),
                })}
              </>
            )}
          </p>
        )}
        {selected && selected.problemCount > 0 && (
          <details className="language-problems">
            <summary>
              {t("language.problems", { count: selected.problemCount })}
            </summary>
            <ul>
              {selected.problems.map((problem, index) => (
                <li key={problem.key + ":" + index}>
                  <code>{problem.key}</code> ·{" "}
                  {t("language.problem." + problem.code)}
                </li>
              ))}
              {selected.problemCount > selected.problems.length && (
                <li>
                  {t("bubble.more_items", {
                    count: selected.problemCount - selected.problems.length,
                  })}
                </li>
              )}
            </ul>
          </details>
        )}
        {copied && copied === state.selected && (
          <p role="status" className="footnote">
            {t("language.copy_done")}
          </p>
        )}
        {state.recovered && (
          <p role="status" className="language-notice">
            {t("language.recovered")}
          </p>
        )}
        {packs
          .filter((pack) => pack.error)
          .map((pack, index) => (
            <p key={index} className="footnote">
              {pack.name} · {t("language.error." + pack.error)}
            </p>
          ))}
        <div className="button-row">
          <button
            className="button"
            disabled={restarting}
            onClick={() =>
              window.settings!.openLanguagePackFolder().catch(shell.reportError)
            }
          >
            <FolderOpen size={14} />
            {t("language.folder")}
          </button>
          <button
            className="button"
            disabled={controlsBusy}
            onClick={() => void load(true)}
          >
            <RefreshCw size={14} />
            {t("language.refresh")}
          </button>
          <button
            className="button"
            disabled={controlsBusy || !selected?.selectable}
            onClick={() => void copy()}
          >
            <Copy size={14} />
            {t("language.copy")}
          </button>
          {state.restartRequired && (
            <button
              className="button primary language-restart"
              disabled={controlsBusy || updateBusy || !selected?.selectable}
              onClick={() => void restart()}
            >
              <RotateCw size={14} />
              {t(
                restarting ? "language.restarting" : "language.restart_button",
              )}
            </button>
          )}
        </div>
      </div>
    </Section>
  );
}
